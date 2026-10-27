"""Unidades de conservação do CNUC (Ministério do Meio Ambiente) -> vetorial.mma_unidades_conservacao, como ESPELHO VERSIONADO.

CARGA MANUAL AUTORIZADA (2026-10-27): o shapefile do CNUC mais recente só existe em links do SharePoint do MMA (com token, instáveis), que não se baixam
por script; o CKAN do MMA só tem o shapefile até 2025_08. O usuário baixa o zip (ex.: cnuc_2026_07.zip) e o coloca em bruto/; este script lê dali,
registra a edição (do nome do zip) e o SHA-256, e reconcilia igual às outras fontes (regras em dwlib/espelho.py): UC nova entra; alterada fecha a versão
antiga e insere a nova; UC que a edição nova não traz tem a versão fechada (nada é apagado); UC que sumiu e voltou idêntica tem a versão reaberta.

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl mma/unidades_conservacao/scripts/unidades_conservacao.py [opções]

  OPÇÕES: --verificar (só consulta o CKAN do MMA: avisa se o shapefile passou a ter link direto e qual edição o banco tem; não grava)
          --arquivo bruto/cnuc_AAAA_MM.zip (padrão: a edição mais recente em bruto/) | --simular | --aceitar-queda
          --destino SCHEMA.TABELA (padrão: o do config.yaml; a tabela precisa existir: sql/01_tabela.sql)

O zip traz dois shapefiles com UCs DIFERENTES: polígonos (3.406 na edição 2026_07) e pontos esquemáticos das UCs sem polígono (170). A chave é cd_cnuc.
"""
import argparse
import hashlib
import re
import struct
import sys
import time
import zipfile
from decimal import Decimal
from pathlib import Path

import yaml

from dwlib import db, espelho, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # mma/unidades_conservacao
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]

# colunas do banco (na ordem da tabela) que vêm dos shapefiles: coluna -> nome do campo no shapefile
NUMERICAS = ["ha_total", "ha_ato", "amazonia", "caatinga", "cerrado", "matlantica", "pampa", "pantanal", "marinho"]
TEXTOS_POL = ["docleg_id", "uc_id", "wdpa_pid", "nome_uc", "cria_ano", "cria_ato", "outro_ato", "pl_manejo", "co_gestor", "quali_pol", "ppgr", "esfera", "uf",
              "municipio", "org_gestor", "grupo", "categoria", "cat_iucn", "situacao", "limite"]
CAMPO_PONTO = {"nome_uc": "nome_uc", "nome_abrev": "NomeAbrev", "cria_ano": "cria_ano", "cria_ato": "cria_ato", "quali_pol": "quali_pol", "ppgr_rev": "ppgr_rev",
               "esfera": "esfera", "org_gestor": "org_gestor", "grupo": "grupo", "categoria": "categoria", "sitiopatri": "sitiopatri", "ramsar": "ramsar",
               "mosaico": "mosaico", "biosfera": "biosfera"}
CAMPOS = (["cd_cnuc", "camada_origem", "docleg_id", "uc_id", "wdpa_pid", "nome_uc", "nome_abrev", "cria_ano", "ano_criacao", "cria_ato", "outro_ato", "pl_manejo",
           "co_gestor", "quali_pol", "ppgr", "ppgr_rev", "ha_total", "ha_ato", "esfera", "uf", "municipio", "org_gestor", "grupo", "categoria", "cat_iucn"]
          + NUMERICAS[2:] + ["situacao", "limite", "sitiopatri", "ramsar", "mosaico", "biosfera", "siscosmar", "longitude_ponto", "latitude_ponto", "edicao"])
COLS_STAGE = {"ano_criacao": "smallint", "siscosmar": "integer", "longitude_ponto": "double precision", "latitude_ponto": "double precision",
              **{c: "numeric" for c in NUMERICAS}}
COMPARAR = [c for c in CAMPOS if c not in ("cd_cnuc", "edicao")] + ["geom_anomala", "geom_origem_texto"]


def log(*a):
    print(*a, flush=True)


def vazio(v):
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() in ("", "nan", "None")


def texto(v):
    return None if vazio(v) else str(v).strip()


def numero(v):
    return None if vazio(v) else Decimal(str(v).strip().replace(",", "."))


def ler_shapefile(zip_path, nome):
    from pyogrio.raw import read
    meta, _, geoms, campos = read(f"/vsizip/{zip_path}/{nome}")
    campos_fonte = [str(c) for c in meta["fields"]]
    return meta, geoms, {c: campos[i] for i, c in enumerate(campos_fonte)}


def escolher_arquivo(args):
    if args.arquivo:
        p = Path(args.arquivo)
        p = p if p.is_absolute() else (RAIZ.parents[1] / p)
    else:
        achados = sorted(RAIZ.joinpath("bruto").glob("cnuc_*.zip"), key=lambda f: re.search(CFG["padrao_arquivo"], f.name).groups() if re.search(CFG["padrao_arquivo"], f.name) else ("",))
        if not achados:
            raise SystemExit("nenhum bruto/cnuc_AAAA_MM.zip: baixe o zip do CNUC (ver LEIAME_unidades_conservacao.md) e coloque em bruto/")
        p = achados[-1]
    m = re.fullmatch(CFG["padrao_arquivo"], p.name)
    if not m or not p.exists():
        raise SystemExit(f"arquivo invalido ou inexistente: {p} (esperado: cnuc_AAAA_MM.zip)")
    return p, f"{m.group(1)}_{m.group(2)}"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def verificar(conn):
    """Consulta o CKAN do MMA: o shapefile do CNUC ja tem link direto (fora do SharePoint)? E qual edicao o banco tem?"""
    r = http.sessao().get(CFG["url_ckan_pacote"], timeout=60)
    r.raise_for_status()
    recursos = r.json()["result"]["resources"]
    log(f"== CKAN do MMA ({CFG['url_pagina']}): {len(recursos)} recursos")
    diretos = {}                                                  # edicao (AAAA_MM) -> nome, so dos shapefiles com link direto
    for x in recursos:
        fmt, url, nome = (x.get("format") or "").upper(), x.get("url") or "", x.get("name") or ""
        if "ZIP" in fmt or "SHP" in fmt or url.lower().endswith(".zip"):
            sp = "sharepoint" in url.lower()
            ed = re.search(r"(\d{4})_(\d{2})", nome + " " + url)
            log(f"  {nome} | {fmt} | {x.get('last_modified') or x.get('created')} | {'SHAREPOINT (manual)' if sp else 'LINK DIRETO'}")
            if not sp and ed:
                diretos[f"{ed.group(1)}_{ed.group(2)}"] = nome
    ed_banco = None
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (CFG["destino_padrao"],))
    if cur.fetchone()[0]:
        cur.execute(f"SELECT max(edicao), count(*) FILTER (WHERE vigente_ate IS NULL) FROM {CFG['destino_padrao']}")
        ed_banco, n = cur.fetchone()
        log(f"  banco: edicao mais recente carregada = {ed_banco}, {n} UCs vigentes")
    ultima_direta = max(diretos) if diretos else None
    if ultima_direta and (ed_banco is None or ultima_direta > ed_banco):
        log(f"  RESULTADO: HA EDICAO NOVA COM LINK DIRETO ({ultima_direta}, mais nova que a do banco): a coleta pode ser automatizada.")
    else:
        log(f"  RESULTADO: a edicao mais recente com link direto e {ultima_direta}; o banco tem {ed_banco}. A edicao nova continua manual (SharePoint).")


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="CNUC (zip baixado pelo usuario em bruto/) -> espelho versionado de vetorial.mma_unidades_conservacao")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--arquivo")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    conn = db.conectar()
    if args.verificar:
        verificar(conn)
        return 0
    t0 = time.time()
    zip_path, edicao = escolher_arquivo(args)
    hash_zip = sha256(zip_path)
    log(f"== CNUC {edicao}: {zip_path.name} ({zip_path.stat().st_size / 1e6:.1f} MB, sha256 {hash_zip[:16]}...)")
    with zipfile.ZipFile(zip_path) as z:
        shps = [n for n in z.namelist() if n.lower().endswith(".shp")]
    pontos = [n for n in shps if n.lower().endswith("_pontos.shp")]
    polis = [n for n in shps if n not in pontos]
    if len(polis) != 1 or len(pontos) != 1:
        raise RuntimeError(f"o zip deveria ter 1 shapefile de poligonos e 1 de pontos, achei {shps}: NADA gravado")

    registros = []                                                # (reg, wkb_poligono_ou_None)
    meta_p, geoms_p, col_p = ler_shapefile(zip_path, polis[0])
    faltam = [c for c in CFG["campos_poligonos_esperados"] if c not in col_p]
    if faltam:
        raise RuntimeError(f"shapefile de poligonos sem os campos {faltam} (o MMA mudou o esquema?): NADA gravado")
    for i in range(len(geoms_p)):
        reg = {c: None for c in CAMPOS}
        reg.update(camada_origem="poligonos", edicao=edicao, cd_cnuc=texto(col_p["cd_cnuc"][i]))
        for c in TEXTOS_POL:
            reg[c] = texto(col_p[c][i])
        for c in NUMERICAS:
            reg[c] = numero(col_p[c][i])
        registros.append((reg, bytes(geoms_p[i]).hex() if geoms_p[i] is not None else None))
    meta_t, geoms_t, col_t = ler_shapefile(zip_path, pontos[0])
    faltam = [c for c in CFG["campos_pontos_esperados"] if c not in col_t]
    if faltam:
        raise RuntimeError(f"shapefile de pontos sem os campos {faltam} (o MMA mudou o esquema?): NADA gravado")
    for i in range(len(geoms_t)):
        reg = {c: None for c in CAMPOS}
        reg.update(camada_origem="pontos", edicao=edicao, cd_cnuc=texto(col_t["cd_cnuc"][i]))
        for c, f in CAMPO_PONTO.items():
            reg[c] = texto(col_t[f][i])
        reg["siscosmar"] = None if vazio(col_t["SisCosMar"][i]) else int(col_t["SisCosMar"][i])
        g = geoms_t[i]
        if g is not None:
            wkb = bytes(g)
            e = "<" if wkb[0] == 1 else ">"
            if struct.unpack_from(e + "I", wkb, 1)[0] != 1:
                raise RuntimeError(f"{reg['cd_cnuc']}: geometria do shapefile de pontos nao e Point: NADA gravado")
            reg["longitude_ponto"], reg["latitude_ponto"] = struct.unpack_from(e + "dd", wkb, 5)
        registros.append((reg, None))
    for reg, _ in registros:
        m = re.search(r"(\d{4})$", reg["cria_ano"] or "")
        reg["ano_criacao"] = int(m.group(1)) if m else None
    cds = [r["cd_cnuc"] for r, _ in registros]
    if any(c is None for c in cds):
        raise RuntimeError("UC sem cd_cnuc: NADA gravado")
    if len(registros) < CFG["linhas_minimas"]:
        raise RuntimeError(f"so {len(registros)} UCs no zip (esperado mais de {CFG['linhas_minimas']}): NADA gravado")
    log(f"  {len(polis)} + {len(pontos)} shapefiles: {len(geoms_p):,} poligonos e {len(geoms_t):,} pontos ({len(set(cds)):,} cd_cnuc distintos)".replace(",", "."))

    fonte = db.id_fonte(conn, CFG["fonte"])
    with Carga(conn, "mma_unidades_conservacao", dataset=T, parametros={**vars(args), "edicao": edicao, "sha256": hash_zip}, simular=args.simular) as carga:
        cur = conn.cursor()
        cols = ", ".join(f"{c} {COLS_STAGE.get(c, 'text')}" for c in CAMPOS)
        cur.execute(f"CREATE TEMP TABLE _stage ({cols}, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) ON COMMIT DROP")
        with cur.copy(f"COPY _stage ({', '.join(CAMPOS)}, geom) FROM STDIN") as copia:
            for reg, geom in registros:
                copia.write_row([reg[c] for c in CAMPOS] + [geom])
        carga.lidas += len(registros)
        cx = CFG["caixa_brasil"]
        caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
        cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(geom, {SRID}) WHERE geom IS NOT NULL")
        cur.execute("SELECT count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)) FROM _stage")
        invalidas = cur.fetchone()[0]
        cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = ST_AsEWKT(geom), geom = NULL WHERE geom IS NOT NULL AND NOT (geom @ {caixa})")
        anomalas = cur.rowcount
        cur.execute(f"UPDATE _stage SET geom_anomala = true WHERE camada_origem = 'pontos' AND longitude_ponto IS NOT NULL AND "
                    f"NOT (ST_SetSRID(ST_MakePoint(longitude_ponto, latitude_ponto), {SRID}) @ {caixa})")
        anomalas += cur.rowcount
        if anomalas:
            carga.avisos.append(f"{anomalas} UC(s) com geometria fora da caixa do Brasil (poligono: geom NULL e texto original; ponto: marcado)")
        if invalidas:
            carga.avisos.append(f"{invalidas} poligono(s) invalido(s) pelo PostGIS (gravados como vieram)")
        cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {SRID}) USING ST_Multi(geom)")
        cur.execute("DELETE FROM _stage s USING (SELECT ctid AS c, row_number() OVER (PARTITION BY cd_cnuc ORDER BY ctid) AS rn FROM _stage) r WHERE s.ctid = r.c AND r.rn > 1")
        if cur.rowcount:
            carga.avisos.append(f"{cur.rowcount} cd_cnuc repetido(s) entre os shapefiles (vale o primeiro)")
        cur.execute("CREATE UNIQUE INDEX ON _stage (cd_cnuc)")
        cur.execute("ANALYZE _stage")
        log(f"  poligonos invalidos: {invalidas} | geometrias fora do Brasil: {anomalas}")
        stats = espelho.reconciliar(conn, T, ["cd_cnuc"], COMPARAR, CAMPOS, fonte=fonte, id_carga=carga.id, max_queda=CFG["max_queda"],
                                    aceitar_queda=args.aceitar_queda, simular=args.simular, log=log)
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
            return 0
        cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                    "inalterados, id_carga, observacao, reabertos, edicao) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, "todas", "MMA (CNUC)", CFG["url_pagina"], "zip baixado manualmente pelo usuario (autorizado) e colocado em bruto/", len(registros), len(registros),
                     stats["novos"], stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                     f"{zip_path.name} sha256 {hash_zip}; {anomalas} geometrias fora do Brasil; {invalidas} poligonos invalidos", stats["reabertos"], edicao))
        registrar_dataset(conn, "MMA - Unidades de conservacao (CNUC)", T, fonte, ano_referencia=int(edicao[:4]), licenca=CFG["licenca"], tipo="vetor",
                          observacoes=f"Edicao CNUC {edicao}, carga manual autorizada (shapefile so em SharePoint). Ver mma/unidades_conservacao/LEIAME_unidades_conservacao.md.")
        conn.commit()
        carga.inseridas += stats["inseridos"]
        carga.atualizadas += stats["ausentes"]
        log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']:,} versoes inseridas, {stats['reabertos']:,} reabertas, "
            f"{stats['ausentes']:,} fechadas por ausencia)".replace(",", "."))
        return 0


if __name__ == "__main__":
    sys.exit(main())
