"""Áreas embargadas e desembargadas da SEMA-MT -> vetorial.sema_mt_areas_embargadas e vetorial.sema_mt_areas_desembargadas, como ESPELHOS VERSIONADOS.

Lê o catálogo GeoNetwork da SEMA-MT, acha o link de download (SHAPE-ZIP do WFS do Geoportal) de cada camada, com a `authkey` pública que a própria SEMA publica ali (lida a cada execução,
nunca fixada no código), baixa e reconcilia igual às outras fontes (regras em dwlib/espelho.py): polígono novo entra; alterado fecha a versão antiga e insere a nova; o que a camada deixou de
publicar tem a versão fechada (nada é apagado); o que sumiu e voltou idêntico tem a versão reaberta.

DADO PESSOAL (mesma decisão do IBAMA e do ICMBio): nome como a fonte publica; CPF de pessoa física NÃO é guardado, só o HMAC-SHA256 (dwlib/documento.py, mesma chave); CNPJ e texto livre como vêm.
Sem a chave do hash o pipeline para.

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl sema_mt/areas_embargadas/scripts/areas_embargadas.py [opções]

  OPÇÕES: --camadas embargadas,desembargadas (padrão: as duas) | --simular | --aceitar-queda | --verificar (só procura os links no catálogo e mostra quantas linhas cada tabela tem)
"""
import argparse
import re
import sys
import tempfile
import time
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from dwlib import db, documento, espelho, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # sema_mt/areas_embargadas
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]

TEXTOS = ["nome", "cpf_cnpj", "propriedad", "dano", "ano_desmat", "a_infrac", "t_embargo", "dat_lavrat", "n_processo", "coord_x", "coord_y", "fonte", "obs"]
CAMPOS = (["chave_linha", "objectid", "nome", "cpf_cnpj", "tipo_doc_embargado", "doc_valido", "cpf_embargado_hash"] + TEXTOS[2:8] + ["data_lavratura"] + TEXTOS[8:] + ["area_ha"])
COLS_STAGE = {"objectid": "bigint", "doc_valido": "boolean", "data_lavratura": "date", "area_ha": "numeric"}
COMPARAR = [c for c in CAMPOS if c not in ("chave_linha", "objectid")] + ["geom_anomala", "geom_origem_texto"]


def log(*a):
    print(*a, flush=True)


def texto(v):
    """A fonte grava 'None' e espaços no lugar de vazio."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    v = str(v).strip()
    return None if v in ("", "None", "nan") else v


def links_do_catalogo(sessao):
    """{type_name: url do SHAPE-ZIP} lido do catálogo (a url traz a authkey publicada pela SEMA)."""
    r = sessao.get(CFG["url_catalogo"], params={"_content_type": "json", "any": CFG["busca_catalogo"], "fast": "index", "resultType": "details", "to": 50},
                   headers={"Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    md = r.json().get("metadata") or []
    md = md if isinstance(md, list) else [md]
    achados = {}
    for m in md:
        links = m.get("link") or []
        for l in (links if isinstance(links, list) else [links]):
            url = str(l).split("|")[2] if str(l).count("|") >= 2 else ""
            q = {k.lower(): v for k, v in parse_qs(urlparse(url).query).items()}
            if q.get("typename") and "shape-zip" in [x.lower() for x in q.get("outputformat", [])] and "authkey" in q:
                achados[q["typename"][0]] = url
    return achados


def baixar(sessao, url, destino):
    r = sessao.get(url, stream=True, timeout=(30, 600))
    r.raise_for_status()
    n = 0
    with open(destino, "wb") as f:
        for bloco in r.iter_content(1 << 20):
            f.write(bloco)
            n += len(bloco)
    if not zipfile.is_zipfile(destino):
        raise RuntimeError("o download nao e um zip (a authkey mudou ou o servico respondeu erro?): NADA gravado")
    return n


def ler_shapefile(zip_path, pasta):
    from pyogrio.raw import read
    with zipfile.ZipFile(zip_path) as z:
        shps = [n for n in z.namelist() if n.lower().endswith(".shp")]
        if len(shps) != 1:
            raise RuntimeError(f"o zip deveria ter 1 shapefile, achei {shps}: NADA gravado")
        z.extractall(pasta)
    meta, _, geoms, campos = read(str(Path(pasta) / shps[0]))
    nomes = [str(c) for c in meta["fields"]]
    faltam = [c for c in CFG["campos_esperados"] if c not in nomes]
    if faltam:
        raise RuntimeError(f"shapefile sem os campos {faltam} (a SEMA mudou o esquema?): NADA gravado")
    return geoms, {c: campos[i] for i, c in enumerate(nomes)}


def data_br(v):
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", v or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None                                          # ex.: 00/07/2017


def montar_registros(geoms, col, chave):
    registros, cpfs, cnpjs, outros, invalidos = [], 0, 0, 0, 0
    for i in range(len(geoms)):
        reg = {c: None for c in CAMPOS}
        oid = col["OBJECTID"][i]
        reg["objectid"] = None if oid is None or oid != oid else int(oid)
        for c in TEXTOS:
            reg[c] = texto(col[c.upper()][i])
        a = col["AREA_HA"][i]
        reg["area_ha"] = None if a is None or a != a else Decimal(repr(float(a)))
        tipo, digitos, valido = documento.classificar(reg["cpf_cnpj"])
        reg["tipo_doc_embargado"], reg["doc_valido"] = tipo, valido
        if tipo == "CPF":
            reg["cpf_embargado_hash"], reg["cpf_cnpj"] = documento.hash_cpf(digitos, chave), None      # CPF de pessoa fisica NAO e guardado
            cpfs += 1
        elif tipo == "CNPJ":
            reg["cpf_cnpj"] = digitos
            cnpjs += 1
        elif tipo == "OUTRO":
            outros += 1
        invalidos += valido is False
        reg["data_lavratura"] = data_br(reg["dat_lavrat"])
        registros.append((reg, bytes(geoms[i]).hex() if geoms[i] is not None else None))
    grupos = {}
    for reg, _ in registros:
        base = "|".join([reg["t_embargo"] or "", reg["n_processo"] or "", reg["a_infrac"] or "", reg["cpf_embargado_hash"] or reg["cpf_cnpj"] or "", reg["propriedad"] or "",
                         reg["dat_lavrat"] or "", reg["ano_desmat"] or ""])
        grupos.setdefault(base, []).append(reg)
    repetidas = 0
    for base, regs in grupos.items():
        regs.sort(key=lambda r: (r["area_ha"] if r["area_ha"] is not None else Decimal(-1), r["objectid"] or 0))
        for k, reg in enumerate(regs):
            reg["chave_linha"] = base if k == 0 else f"{base}#{k + 1}"
        repetidas += len(regs) - 1
    return registros, cpfs, cnpjs, outros, invalidos, repetidas


def carregar(conn, nome, cfg_c, url, args, chave, sessao):
    T, t0 = cfg_c["destino"], time.time()
    with tempfile.TemporaryDirectory() as tmp:
        z = Path(tmp) / f"{nome}.zip"
        n_bytes = baixar(sessao, url, z)
        geoms, col = ler_shapefile(z, Path(tmp) / "shp")
    total = len(geoms)
    log(f"== SEMA-MT, {nome}: {total:,} poligonos ({n_bytes / 1e6:.1f} MB) em {time.time() - t0:.0f} s".replace(",", "."))
    if total < cfg_c["linhas_minimas"]:
        raise RuntimeError(f"so {total} poligonos (esperado mais de {cfg_c['linhas_minimas']}): NADA gravado")
    registros, cpfs, cnpjs, outros, invalidos, repetidas = montar_registros(geoms, col, chave)
    log(f"  CPF (so hash): {cpfs:,} | CNPJ: {cnpjs:,} | texto/outro: {outros} | documentos com digito verificador errado: {invalidos} | chaves repetidas (ordinal): {repetidas}".replace(",", "."))
    fonte = db.id_fonte(conn, CFG["fonte"])
    with Carga(conn, T.split(".")[1], dataset=T, parametros={**vars(args), "camada": nome}, simular=args.simular) as carga:
        cur = conn.cursor()
        cols = ", ".join(f"{c} {COLS_STAGE.get(c, 'text')}" for c in CAMPOS)
        cur.execute(f"CREATE TEMP TABLE _stage ({cols}, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) ON COMMIT DROP")
        with cur.copy(f"COPY _stage ({', '.join(CAMPOS)}, geom) FROM STDIN") as copia:
            for reg, g in registros:
                copia.write_row([reg[c] for c in CAMPOS] + [g])
        carga.lidas += len(registros)
        cx = CFG["caixa_mt"]
        caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
        cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(geom, {SRID}) WHERE geom IS NOT NULL")
        cur.execute("SELECT count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)), count(*) FILTER (WHERE geom IS NULL) FROM _stage")
        inval, sem_geom = cur.fetchone()
        cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = ST_AsEWKT(geom), geom = NULL WHERE geom IS NOT NULL AND NOT (geom @ {caixa})")
        anomalas = cur.rowcount
        if anomalas:
            carga.avisos.append(f"{anomalas} poligono(s) fora de Mato Grosso (geom NULL e texto original)")
        if inval:
            carga.avisos.append(f"{inval} poligono(s) invalido(s) pelo PostGIS (gravados como vieram)")
        cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {SRID}) USING ST_Multi(geom)")
        cur.execute("CREATE UNIQUE INDEX ON _stage (chave_linha)")
        cur.execute("ANALYZE _stage")
        log(f"  poligonos invalidos: {inval} | sem geometria: {sem_geom} | fora de Mato Grosso: {anomalas}")
        stats = espelho.reconciliar(conn, T, ["chave_linha"], COMPARAR, CAMPOS, fonte=fonte, id_carga=carga.id, max_queda=CFG["max_queda"],
                                    aceitar_queda=args.aceitar_queda, simular=args.simular, log=log)
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
            return
        cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                    "inalterados, id_carga, observacao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, nome, "SEMA-MT (areas embargadas)", CFG["url_pagina"], "catalogo GeoNetwork -> link SHAPE-ZIP do WFS do Geoportal (authkey publica lida do catalogo)",
                     total, total, stats["novos"], stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                     f"CPF so como hash; {inval} poligonos invalidos; {anomalas} fora de MT; {repetidas} chaves repetidas (ordinal)", stats["reabertos"]))
        registrar_dataset(conn, f"SEMA-MT - Areas {nome}", T, fonte, ano_referencia=date.today().year, licenca=CFG["licenca"], tipo="vetor",
                          observacoes="WFS do Geoportal da SEMA-MT. CPF so como HMAC (mesma chave do IBAMA). Ver sema_mt/areas_embargadas/LEIAME_areas_embargadas.md.")
        conn.commit()
        carga.inseridas += stats["inseridos"]
        carga.atualizadas += stats["ausentes"]
        log(f"== {nome}: fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']:,} versoes inseridas, {stats['reabertos']:,} reabertas, "
            f"{stats['ausentes']:,} fechadas por ausencia)".replace(",", "."))


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="SEMA-MT, areas embargadas e desembargadas (WFS do Geoportal) -> espelhos versionados")
    ap.add_argument("--camadas", default=",".join(CFG["camadas"]), help="embargadas,desembargadas (padrao: as duas)")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    args = ap.parse_args()
    escolhidas = [c.strip() for c in args.camadas.split(",") if c.strip()]
    if any(c not in CFG["camadas"] for c in escolhidas):
        raise SystemExit(f"camadas validas: {', '.join(CFG['camadas'])}")
    conn = db.conectar()
    sessao = http.sessao()
    links = links_do_catalogo(sessao)
    for nome in escolhidas:
        if CFG["camadas"][nome]["type_name"] not in links:
            raise RuntimeError(f"o catalogo da SEMA nao traz mais o link de {CFG['camadas'][nome]['type_name']} (ou a authkey sumiu do link): NADA gravado")
    if args.verificar:
        for nome in escolhidas:
            cur = conn.cursor()
            cur.execute("SELECT to_regclass(%s)", (CFG["camadas"][nome]["destino"],))
            n = None
            if cur.fetchone()[0]:
                cur.execute(f"SELECT count(*) FILTER (WHERE vigente_ate IS NULL) FROM {CFG['camadas'][nome]['destino']}")
                n = cur.fetchone()[0]
            log(f"{nome}: link encontrado no catalogo; banco tem {n} poligonos vigentes")
        return 0
    chave = documento.chave()
    if chave is None:
        raise RuntimeError("sem a chave do HMAC do CPF (DW_CHAVE_HASH_CPF ou ibama/embargos/segredo/chave_hash_cpf.key): NADA gravado")
    for nome in escolhidas:
        carregar(conn, nome, CFG["camadas"][nome], links[CFG["camadas"][nome]["type_name"]], args, chave, sessao)
    return 0


if __name__ == "__main__":
    sys.exit(main())
