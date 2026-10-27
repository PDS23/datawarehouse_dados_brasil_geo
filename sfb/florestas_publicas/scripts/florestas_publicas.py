"""Cadastro Nacional de Florestas Públicas (CNFP, Serviço Florestal Brasileiro) -> vetorial.sfb_florestas_publicas, como ESPELHO VERSIONADO.

Lê o CKAN do SFB, escolhe a edição mais recente (um recurso "AAAA - Cadastro Nacional de Florestas Públicas" por ano), baixa o shapefile ZIP do item público
do portal ArcGIS do SFB e reconcilia igual às outras fontes (regras em dwlib/espelho.py): registro novo entra; alterado fecha a versão antiga e insere a nova;
registro que a edição nova não traz tem a versão fechada (nada é apagado); o que sumiu e voltou idêntico tem a versão reaberta.

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl sfb/florestas_publicas/scripts/florestas_publicas.py [opções]

  OPÇÕES: --verificar (só consulta o CKAN: qual é a edição mais recente e qual o banco tem; não baixa nem grava)
          --edicao AAAA (padrão: a mais recente do CKAN) | --simular | --aceitar-queda | --guardar-bruto
          --destino SCHEMA.TABELA (padrão: o do config.yaml; a tabela precisa existir: sql/01_tabela.sql)

O shapefile não tem id: a chave é a identidade do registro (campos de `chave_campos`, no config.yaml), com ordinal só para registros idênticos.
"""
import argparse
import hashlib
import re
import shutil
import sys
import tempfile
import time
import zipfile
from decimal import Decimal
from pathlib import Path

import yaml

from dwlib import db, espelho, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # sfb/florestas_publicas
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]

TEXTOS = ["nome", "categoria", "protecao", "tipo", "governo", "comunitari", "classe", "orgao", "sobreposic", "atolegal", "anocriacao", "estagio", "codigo",
          "observacao", "uf", "bioma", "municipio", "geocodigo"]
CAMPOS = ["chave_linha"] + TEXTOS[:11] + ["ano_criacao"] + TEXTOS[11:15] + ["id_estado"] + TEXTOS[15:] + ["area_ha", "edicao"]
COLS_STAGE = {"ano_criacao": "smallint", "id_estado": "smallint", "area_ha": "numeric"}
COMPARAR = [c for c in CAMPOS if c not in ("chave_linha", "edicao")] + ["geom_anomala", "geom_origem_texto"]


def log(*a):
    print(*a, flush=True)


def vazio(v):
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() in ("", "nan", "None")


def texto(v):
    return None if vazio(v) else str(v).strip()


def edicoes_ckan():
    """{ano: id do item ArcGIS} dos recursos de shapefile do CNFP no CKAN do SFB."""
    r = http.sessao().get(CFG["url_ckan_pacote"], timeout=60)
    r.raise_for_status()
    achadas = {}
    for x in r.json()["result"]["resources"]:
        m, i = re.search(CFG["padrao_recurso"], x.get("name") or ""), re.search(CFG["padrao_item"], x.get("url") or "")
        if m and i:
            achadas[m.group(1)] = i.group(1)
    if not achadas:
        raise RuntimeError("nenhum recurso 'AAAA - Cadastro Nacional de Florestas Publicas' com item do portal no CKAN (o SFB mudou a publicacao?): NADA gravado")
    return achadas


def baixar(item, destino):
    """Baixa o shapefile ZIP do item público do portal ArcGIS. Retorna (bytes, sha256)."""
    r = http.sessao().get(CFG["url_download"].format(item=item), stream=True, timeout=(30, 600))
    r.raise_for_status()
    esperado = int(r.headers.get("content-length", 0))
    h, n = hashlib.sha256(), 0
    with open(destino, "wb") as f:
        for bloco in r.iter_content(1 << 20):
            f.write(bloco)
            h.update(bloco)
            n += len(bloco)
    if esperado and n != esperado:
        raise RuntimeError(f"download truncado: {n} de {esperado} bytes: NADA gravado")
    if n < CFG["tamanho_minimo_bytes"]:
        raise RuntimeError(f"arquivo com {n} bytes (esperado mais de {CFG['tamanho_minimo_bytes']}): o SFB trocou o item? NADA gravado")
    return n, h.hexdigest()


def ler_registros(shp, edicao):
    """Lê o shapefile em lotes. Retorna lista de (registro, wkb_hex)."""
    from pyogrio.raw import read
    registros, lote, pos = [], CFG["lote_leitura"], 0
    while True:
        meta, _, geoms, campos = read(str(shp), skip_features=pos, max_features=lote)
        if pos == 0:
            col0 = [str(c) for c in meta["fields"]]
            faltam = [c for c in CFG["campos_esperados"] if c not in col0]
            if faltam:
                raise RuntimeError(f"shapefile sem os campos {faltam} (o SFB mudou o esquema?): NADA gravado")
        nomes = [str(c) for c in meta["fields"]]
        col = {c: campos[i] for i, c in enumerate(nomes)}
        n = len(geoms)
        if n == 0:
            break
        for i in range(n):
            reg = {c: None for c in CAMPOS}
            reg["edicao"] = edicao
            for c in TEXTOS:
                reg[c] = texto(col[c][i])
            reg["area_ha"] = None if vazio(col["area_ha"][i]) else Decimal(repr(float(col["area_ha"][i])))
            registros.append((reg, bytes(geoms[i]).hex() if geoms[i] is not None else None))
        pos += n
        if n < lote:
            break
    return registros


def montar_chaves(registros):
    """chave_linha = identidade do registro; ordinal (#2, #3...) só nos idênticos, na ordem de (area, estagio, municipio, bioma)."""
    grupos = {}
    for reg, wkb in registros:
        base = "|".join(reg[c] or "" for c in CFG["chave_campos"])
        grupos.setdefault(base, []).append(reg)
    repetidas = 0
    for base, regs in grupos.items():
        regs.sort(key=lambda r: (r["area_ha"] if r["area_ha"] is not None else Decimal(-1), r["estagio"] or "", r["municipio"] or "", r["bioma"] or ""))
        for k, reg in enumerate(regs):
            reg["chave_linha"] = base if k == 0 else f"{base}#{k + 1}"
        repetidas += len(regs) - 1
    return repetidas


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="CNFP (SFB, direto da fonte) -> espelho versionado de vetorial.sfb_florestas_publicas")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--edicao", help="ano da edicao (padrao: a mais recente do CKAN)")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--guardar-bruto", action="store_true", help="guarda o zip em bruto/ (por padrao nao guarda: e baixado de novo a cada carga)")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    conn = db.conectar()
    edicoes = edicoes_ckan()
    edicao = args.edicao or max(edicoes)
    if edicao not in edicoes:
        raise SystemExit(f"edicao {edicao} nao existe no CKAN (tem: {', '.join(sorted(edicoes))})")
    if args.verificar:
        cur = conn.cursor()
        cur.execute("SELECT to_regclass(%s)", (T,))
        ed_banco = None
        if cur.fetchone()[0]:
            cur.execute(f"SELECT max(edicao), count(*) FILTER (WHERE vigente_ate IS NULL) FROM {T}")
            ed_banco, n = cur.fetchone()
            log(f"banco: edicao mais recente carregada = {ed_banco}, {n} registros vigentes")
        log(f"CKAN: edicoes {', '.join(sorted(edicoes))}; a mais recente e {max(edicoes)} (item {edicoes[max(edicoes)]})")
        log("RESULTADO: " + ("HA EDICAO NOVA para carregar." if ed_banco is None or max(edicoes) > ed_banco else "o banco ja tem a edicao mais recente."))
        return 0

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / f"CNFP_{edicao}.zip"
        n_bytes, hash_zip = baixar(edicoes[edicao], zip_path)
        log(f"== CNFP {edicao}: {n_bytes / 1e6:.1f} MB baixados (item {edicoes[edicao]}, sha256 {hash_zip[:16]}...) em {time.time() - t0:.0f} s")
        if args.guardar_bruto:
            bruto = RAIZ / "bruto"
            bruto.mkdir(exist_ok=True)
            shutil.copy2(zip_path, bruto / zip_path.name)
        with zipfile.ZipFile(zip_path) as z:
            shps = [n for n in z.namelist() if n.lower().endswith(".shp")]
            if len(shps) != 1:
                raise RuntimeError(f"o zip deveria ter 1 shapefile, achei {shps}: NADA gravado")
            z.extractall(Path(tmp) / "shp")
        registros = ler_registros(Path(tmp) / "shp" / shps[0], edicao)
    if len(registros) < CFG["linhas_minimas"]:
        raise RuntimeError(f"so {len(registros)} registros no shapefile (esperado mais de {CFG['linhas_minimas']}): NADA gravado")
    for reg, _ in registros:
        m = re.search(r"(\d{4})", reg["anocriacao"] or "")
        reg["ano_criacao"] = int(m.group(1)) if m else None
    repetidas = montar_chaves(registros)
    log(f"  {len(registros):,} poligonos lidos; {repetidas} com chave identica a outro (ganham ordinal)".replace(",", "."))

    fonte = db.id_fonte(conn, CFG["fonte"])
    with Carga(conn, "sfb_florestas_publicas", dataset=T, parametros={**vars(args), "edicao": edicao, "sha256": hash_zip}, simular=args.simular) as carga:
        cur = conn.cursor()
        cols = ", ".join(f"{c} {COLS_STAGE.get(c, 'text')}" for c in CAMPOS)
        cur.execute(f"CREATE TEMP TABLE _stage ({cols}, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) ON COMMIT DROP")
        with cur.copy(f"COPY _stage ({', '.join(CAMPOS)}, geom) FROM STDIN") as copia:
            for reg, geom in registros:
                copia.write_row([reg[c] for c in CAMPOS] + [geom])
        carga.lidas += len(registros)
        cx = CFG["caixa_brasil"]
        caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
        cur.execute(f"UPDATE _stage SET geom = ST_Force2D(ST_SetSRID(geom, {SRID})) WHERE geom IS NOT NULL")
        cur.execute("SELECT count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)), count(*) FILTER (WHERE geom IS NULL) FROM _stage")
        invalidas, sem_geom = cur.fetchone()
        cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = ST_AsEWKT(geom), geom = NULL WHERE geom IS NOT NULL AND NOT (geom @ {caixa})")
        anomalas = cur.rowcount
        if anomalas:
            carga.avisos.append(f"{anomalas} poligono(s) fora da caixa do Brasil (geom NULL e texto original)")
        if invalidas:
            carga.avisos.append(f"{invalidas} poligono(s) invalido(s) pelo PostGIS (gravados como vieram)")
        cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {SRID}) USING ST_Multi(geom)")
        cur.execute("UPDATE _stage s SET id_estado = e.id_estado FROM dim.estados e WHERE e.sigla_uf = upper(trim(s.uf))")
        cur.execute("SELECT count(*) FILTER (WHERE id_estado IS NULL) FROM _stage")
        sem_uf = cur.fetchone()[0]
        if sem_uf:
            carga.avisos.append(f"{sem_uf} registro(s) sem id_estado (uf fora de dim.estados)")
        cur.execute("CREATE UNIQUE INDEX ON _stage (chave_linha)")
        cur.execute("ANALYZE _stage")
        log(f"  poligonos invalidos: {invalidas} | sem geometria: {sem_geom} | fora do Brasil: {anomalas} | sem id_estado: {sem_uf}")
        stats = espelho.reconciliar(conn, T, ["chave_linha"], COMPARAR, CAMPOS, fonte=fonte, id_carga=carga.id, max_queda=CFG["max_queda"],
                                    aceitar_queda=args.aceitar_queda, simular=args.simular, log=log)
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
            return 0
        cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                    "inalterados, id_carga, observacao, reabertos, edicao) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, "todas", "SFB (CNFP)", CFG["url_download"].format(item=edicoes[edicao]), "CKAN do SFB -> shapefile ZIP do item publico do portal ArcGIS",
                     len(registros), len(registros), stats["novos"], stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                     f"sha256 {hash_zip}; {invalidas} poligonos invalidos; {anomalas} fora do Brasil; {repetidas} chaves repetidas (ordinal)", stats["reabertos"], edicao))
        registrar_dataset(conn, "SFB - Cadastro Nacional de Florestas Publicas (CNFP)", T, fonte, ano_referencia=int(edicao), licenca=CFG["licenca"], tipo="vetor",
                          observacoes=f"Edicao CNFP {edicao}, direto do portal do SFB. Ver sfb/florestas_publicas/LEIAME_florestas_publicas.md.")
        conn.commit()
        carga.inseridas += stats["inseridos"]
        carga.atualizadas += stats["ausentes"]
        log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']:,} versoes inseridas, {stats['reabertos']:,} reabertas, "
            f"{stats['ausentes']:,} fechadas por ausencia)".replace(",", "."))
        return 0


if __name__ == "__main__":
    sys.exit(main())
