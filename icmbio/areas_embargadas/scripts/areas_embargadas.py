"""Áreas embargadas do ICMBio -> vetorial.icmbio_areas_embargadas, como ESPELHO VERSIONADO.

Lê a camada pública "embargos_icmbio" do FeatureServer do ArcGIS Online do ICMBio (paginada de 2.000 em 2.000 por OBJECTID, geometria em GeoJSON, SIRGAS 2000) e reconcilia igual
às outras fontes (regras em dwlib/espelho.py): polígono novo entra; alterado fecha a versão antiga e insere a nova; o que a camada deixou de publicar tem a versão fechada
(nada é apagado); o que sumiu e voltou idêntico tem a versão reaberta.

DADO PESSOAL (mesma decisão do IBAMA): o nome do autuado entra como a fonte publica; CPF de pessoa física NÃO é guardado, só o HMAC-SHA256 (dwlib/documento.py, mesma chave do IBAMA);
CNPJ e texto livre entram como vêm. Se não houver a chave, o pipeline para (não cria chave nova: dois hashes com chaves diferentes não casariam).

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl icmbio/areas_embargadas/scripts/areas_embargadas.py [opções]

  OPÇÕES: --verificar (só consulta a camada: total e data da última edição na origem x o que o banco tem; não baixa nem grava)
          --simular | --aceitar-queda | --destino SCHEMA.TABELA (padrão: o do config.yaml; a tabela precisa existir: sql/01_tabela.sql)

A camada não tem id único (um embargo tem vários polígonos): a chave é a identidade do registro, com ordinal só para polígonos idênticos nos campos da chave.
"""
import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import yaml

from dwlib import db, documento, espelho, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # icmbio/areas_embargadas
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]

TEXTOS = ["numero_emb", "serie", "origem", "numero_ai", "cpf_cnpj", "autuado", "desc_infra", "desc_sanc", "artigo_1", "artigo_2", "tipo_infra", "nome_uc", "cnuc",
          "municipio", "uf", "data", "ano", "obs", "julgamento", "area", "processo", "ngi", "ct", "gr", "gr_nome"]
CAMPOS = (["chave_linha", "objectid", "vw_num_emb"] + TEXTOS[:5] + ["tipo_doc_autuado", "doc_valido", "cpf_autuado_hash"] + TEXTOS[5:15] + ["id_estado"]
          + TEXTOS[15:17] + ["data_embargo", "area_informada_ha"] + TEXTOS[17:20] + TEXTOS[20:])
COLS_STAGE = {"objectid": "bigint", "vw_num_emb": "numeric", "doc_valido": "boolean", "id_estado": "smallint", "data_embargo": "date", "area_informada_ha": "numeric"}
NAO_COMPARAR = {"chave_linha", "objectid", "vw_num_emb"}
COMPARAR = [c for c in CAMPOS if c not in NAO_COMPARAR] + ["geom_anomala", "geom_origem_texto"]
AREA = re.compile(r"^\s*([\d.,]+)\s*(ha|hectares?|m²|m2)\s*$", re.I)


def log(*a):
    print(*a, flush=True)


def texto(v):
    """A fonte usa ' ' (espaço) e 'None' no lugar de vazio."""
    if v is None:
        return None
    v = str(v).strip()
    return None if v in ("", "None", "nan") else v


def area_ha(txt):
    """Hectares, só quando o texto é um número seguido de ha/hectare(s)/m²; senão None (não adivinhamos a unidade)."""
    m = AREA.match(txt or "")
    if not m:
        return None
    n = m.group(1)
    n = n.replace(".", "").replace(",", ".") if "," in n else (n.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", n) else n)
    try:
        v = Decimal(n)
    except Exception:
        return None
    return v / 10000 if m.group(2).lower() in ("m²", "m2") else v


def info_camada(sessao):
    r = sessao.get(CFG["url_camada"], params={"f": "json"}, timeout=60)
    r.raise_for_status()
    d = r.json()
    c = sessao.get(CFG["url_camada"] + "/query", params={"where": "1=1", "returnCountOnly": "true", "f": "json"}, timeout=60)
    c.raise_for_status()
    editado = (d.get("editingInfo") or {}).get("dataLastEditDate")
    return d, c.json()["count"], (datetime.fromtimestamp(editado / 1000, timezone.utc).date() if editado else None)


def baixar(sessao, total):
    """Todas as feições (atributos + geometria GeoJSON), paginadas por OBJECTID. Confere o total."""
    feicoes, off = [], 0
    while True:
        r = sessao.get(CFG["url_camada"] + "/query", params={"where": "1=1", "outFields": "*", "outSR": SRID, "orderByFields": "OBJECTID", "resultOffset": off,
                                                             "resultRecordCount": CFG["pagina"], "f": "geojson"}, timeout=(30, 300))
        r.raise_for_status()
        fs = r.json().get("features", [])
        if not fs:
            break
        feicoes += fs
        off += len(fs)
        if len(fs) < CFG["pagina"]:
            break
    if len(feicoes) != total:
        raise RuntimeError(f"baixou {len(feicoes)} feicoes, a camada anuncia {total}: NADA gravado")
    return feicoes


def montar_chaves(registros):
    """chave_linha = identidade do polígono; ordinal (#2, #3...) só nos idênticos, na ordem de (área da forma, obs, area, julgamento)."""
    grupos = {}
    for reg, _, ordem in registros:
        base = "|".join([reg["numero_emb"] or "", reg["serie"] or "", reg["numero_ai"] or "", reg["cpf_autuado_hash"] or reg["cpf_cnpj"] or "", reg["nome_uc"] or "",
                         reg["municipio"] or "", reg["uf"] or "", reg["data"] or "", reg["processo"] or ""])
        grupos.setdefault(base, []).append((reg, ordem))
    repetidas = 0
    for base, regs in grupos.items():
        regs.sort(key=lambda x: x[1])
        for k, (reg, _) in enumerate(regs):
            reg["chave_linha"] = base if k == 0 else f"{base}#{k + 1}"
        repetidas += len(regs) - 1
    return repetidas


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="ICMBio, areas embargadas (camada publica do ArcGIS Online) -> espelho versionado de vetorial.icmbio_areas_embargadas")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    conn = db.conectar()
    sessao = http.sessao()
    d, total, editado = info_camada(sessao)
    faltam = [c for c in CFG["campos_esperados"] if c not in {f["name"] for f in d["fields"]}]
    if faltam:
        raise RuntimeError(f"camada sem os campos {faltam} (o ICMBio mudou o esquema?): NADA gravado")
    if args.verificar:
        cur = conn.cursor()
        cur.execute("SELECT to_regclass(%s)", (T,))
        n = None
        if cur.fetchone()[0]:
            cur.execute(f"SELECT count(*) FILTER (WHERE vigente_ate IS NULL), max(coletado_em)::date FROM {T}")
            n, ultima = cur.fetchone()
            log(f"banco: {n} poligonos vigentes, ultima coleta {ultima}")
        log(f"origem: {total} poligonos, ultima edicao da camada em {editado}")
        return 0
    if total < CFG["linhas_minimas"]:
        raise RuntimeError(f"a camada anuncia so {total} poligonos (esperado mais de {CFG['linhas_minimas']}): NADA gravado")
    chave = documento.chave()
    if chave is None:
        raise RuntimeError("sem a chave do HMAC do CPF (DW_CHAVE_HASH_CPF ou ibama/embargos/segredo/chave_hash_cpf.key): NADA gravado")

    t0 = time.time()
    feicoes = baixar(sessao, total)
    log(f"== ICMBio, areas embargadas: {len(feicoes):,} poligonos baixados em {time.time() - t0:.0f} s (camada editada em {editado})".replace(",", "."))
    registros = []                                                # (reg, geojson_texto_ou_None, ordem)
    n_cpf = n_cnpj = n_outro = n_invalidos = 0
    for f in feicoes:
        p = f["properties"]
        reg = {c: None for c in CAMPOS}
        reg["objectid"] = int(p["OBJECTID"])
        reg["vw_num_emb"] = None if p.get("vw_num_emb") is None else Decimal(repr(p["vw_num_emb"]))
        for c in TEXTOS:
            reg[c] = texto(p.get(c))
        tipo, digitos, valido = documento.classificar(reg["cpf_cnpj"])
        reg["tipo_doc_autuado"], reg["doc_valido"] = tipo, valido
        if tipo == "CPF":
            reg["cpf_autuado_hash"] = documento.hash_cpf(digitos, chave)
            reg["cpf_cnpj"] = None                               # CPF de pessoa fisica NAO e guardado
            n_cpf += 1
        elif tipo == "CNPJ":
            reg["cpf_cnpj"] = digitos
            n_cnpj += 1
        elif tipo == "OUTRO":
            n_outro += 1
        n_invalidos += valido is False
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", reg["data"] or "")
        reg["data_embargo"] = date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
        reg["area_informada_ha"] = area_ha(reg["area"])
        g = f.get("geometry")
        ordem = (float(p.get("Shape__Area") or 0), reg["obs"] or "", reg["area"] or "", reg["julgamento"] or "", reg["objectid"])
        registros.append((reg, json.dumps(g) if g else None, ordem))
    repetidas = montar_chaves([(r, g, o) for r, g, o in registros])
    log(f"  CPF (so hash): {n_cpf:,} | CNPJ: {n_cnpj:,} | texto/outro: {n_outro} | documentos com digito verificador errado: {n_invalidos} | chaves repetidas (ordinal): {repetidas}".replace(",", "."))

    fonte = db.id_fonte(conn, CFG["fonte"])
    with Carga(conn, "icmbio_areas_embargadas", dataset=T, parametros={**vars(args), "camada_editada_em": str(editado)}, simular=args.simular) as carga:
        cur = conn.cursor()
        cols = ", ".join(f"{c} {COLS_STAGE.get(c, 'text')}" for c in CAMPOS)
        cur.execute(f"CREATE TEMP TABLE _stage ({cols}, geom_geojson text, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) ON COMMIT DROP")
        with cur.copy(f"COPY _stage ({', '.join(CAMPOS)}, geom_geojson) FROM STDIN") as copia:
            for reg, g, _ in registros:
                copia.write_row([reg[c] for c in CAMPOS] + [g])
        carga.lidas += len(registros)
        cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(ST_GeomFromGeoJSON(geom_geojson), {SRID}) WHERE geom_geojson IS NOT NULL")
        cur.execute("SELECT count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)), count(*) FILTER (WHERE geom IS NULL) FROM _stage")
        invalidas, sem_geom = cur.fetchone()
        cx = CFG["caixa_brasil"]
        caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
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
            carga.avisos.append(f"{sem_uf} registro(s) sem id_estado (uf vazia ou fora de dim.estados)")
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
                    "inalterados, id_carga, observacao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, "todas", "ICMBio (areas embargadas)", CFG["url_camada"], "camada publica do ArcGIS Online (FeatureServer, paginada por OBJECTID, GeoJSON)",
                     total, len(registros), stats["novos"], stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                     f"camada editada em {editado}; CPF so como hash; {invalidas} poligonos invalidos; {anomalas} fora do Brasil; {repetidas} chaves repetidas (ordinal)", stats["reabertos"]))
        registrar_dataset(conn, "ICMBio - Areas embargadas", T, fonte, ano_referencia=(editado.year if editado else None), licenca=CFG["licenca"], tipo="vetor",
                          observacoes="Camada publica do ArcGIS Online do ICMBio. CPF so como HMAC (mesma chave do IBAMA). Ver icmbio/areas_embargadas/LEIAME_areas_embargadas.md.")
        conn.commit()
        carga.inseridas += stats["inseridos"]
        carga.atualizadas += stats["ausentes"]
        log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']:,} versoes inseridas, {stats['reabertos']:,} reabertas, "
            f"{stats['ausentes']:,} fechadas por ausencia)".replace(",", "."))
        return 0


if __name__ == "__main__":
    sys.exit(main())
