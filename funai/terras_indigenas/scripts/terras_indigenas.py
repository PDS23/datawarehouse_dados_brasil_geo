"""Terras indígenas da FUNAI (camada Funai:tis_poligonais, WFS aberto) -> vetorial.funai_terras_indigenas, como ESPELHO VERSIONADO.

Baixa a camada inteira (uma requisição, ~49 MB em GeoJSON, 665 terras) e reconcilia com o banco igual ao SICAR, ao PRODES e ao MapBiomas
Alerta (regras em dwlib/espelho.py): terra nova entra; alterada fecha a versão antiga e insere a nova; terra que o servidor deixou de
publicar tem a versão fechada (nada é apagado na coleta); terra que sumiu e voltou idêntica tem a versão reaberta.

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl funai/terras_indigenas/scripts/terras_indigenas.py [opções]

  OPÇÕES: --simular (reconcilia e relata, nada é gravado) | --sem-bruto (não guarda o GeoJSON em bruto/) | --aceitar-queda
          --destino SCHEMA.TABELA (padrão: o do config.yaml; a tabela precisa existir: sql/01_tabela.sql)

Particularidades do servidor da FUNAI (ver LEIAME_terras_indigenas.md):
  - GetFeature SEM `count` leva 403 de um filtro nginx: o pedido sempre leva count;
  - o servidor não envia o certificado intermediário: usamos a intermediária pública de dwlib/certs/ e a verificação continua ligada.
"""
import argparse
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import yaml

from dwlib import bruto, db, espelho, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # funai/terras_indigenas
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]
CAMPOS = ["terrai_codigo", "terrai_nome", "etnia_nome", "municipio_nome", "uf_sigla", "id_estado", "superficie_perimetro_ha", "fase_ti",
          "modalidade_ti", "reestudo_ti", "cr", "faixa_fronteira", "undadm_codigo", "undadm_nome", "undadm_sigla", "dominio_uniao",
          "data_atualizacao"]
DA_FONTE = [c for c in CAMPOS if c != "id_estado"]       # campos que vêm da fonte (id_estado é derivado)
COMPARAR = [c for c in CAMPOS if c != "terrai_codigo"] + ["geom_anomala", "geom_origem_texto"]


def log(*a):
    print(*a, flush=True)


def baixar(sessao):
    """GeoJSON da camada inteira + total anunciado (numberMatched)."""
    r = sessao.get(CFG["url_wfs"], params={"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": CFG["camada"],
                                           "outputFormat": "application/json", "srsName": f"EPSG:{SRID}", "count": CFG["count"]}, timeout=900)
    r.raise_for_status()
    j = r.json()
    anunciado = j.get("numberMatched")
    if anunciado is None:
        raise RuntimeError(f"resposta sem numberMatched (chaves: {sorted(j)})")
    return j["features"], int(anunciado)


def valor(campo, v):
    if v is None or v == "":
        return None
    if campo == "data_atualizacao":
        return datetime.strptime(v, "%d/%m/%Y").date()
    if campo == "dominio_uniao":
        return {"t": True, "f": False}.get(str(v).lower())
    if campo in ("terrai_codigo", "undadm_codigo"):
        return int(v)
    if campo == "superficie_perimetro_ha":
        return float(v)
    return v


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="Terras indígenas da FUNAI (WFS aberto) -> espelho versionado de vetorial.funai_terras_indigenas")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--sem-bruto", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    t0 = time.time()

    sessao = http.sessao(ca_extra=CFG["ca_extra"])
    features, anunciado = baixar(sessao)
    log(f"== FUNAI: {len(features)} terras indigenas baixadas ({anunciado} anunciadas) em {time.time() - t0:.0f} s")
    if len(features) != anunciado:
        raise RuntimeError(f"coleta incompleta: {len(features)} baixadas de {anunciado} anunciadas: NADA gravado")

    conn = db.conectar()
    fonte = db.id_fonte(conn, CFG["fonte"])
    with Carga(conn, "funai_terras_indigenas", dataset=T, parametros=vars(args), simular=args.simular) as carga:
        cur = conn.cursor()
        cur.execute("CREATE TEMP TABLE _stage (terrai_codigo integer, terrai_nome text, etnia_nome text, municipio_nome text, uf_sigla text, "
                    "id_estado smallint, superficie_perimetro_ha numeric, fase_ti text, modalidade_ti text, reestudo_ti text, cr text, "
                    "faixa_fronteira text, undadm_codigo bigint, undadm_nome text, undadm_sigla text, dominio_uniao boolean, "
                    "data_atualizacao date, geom_json text, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) "
                    "ON COMMIT DROP")
        with cur.copy(f"COPY _stage ({', '.join(DA_FONTE)}, geom_json) FROM STDIN") as copia:
            for f in features:
                p = f["properties"]
                copia.write_row([valor(c, p.get(c)) for c in DA_FONTE] + [json.dumps(f["geometry"]) if f.get("geometry") else None])
        carga.lidas += len(features)

        cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(ST_GeomFromGeoJSON(geom_json), {SRID}) WHERE geom_json IS NOT NULL")
        cx = CFG["caixa_brasil"]
        caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
        cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = CASE WHEN geom IS NULL THEN NULL ELSE ST_AsEWKT(geom) END, "
                    f"geom = NULL WHERE geom IS NULL OR NOT (geom @ {caixa})")
        anomalas = cur.rowcount
        if anomalas:
            carga.avisos.append(f"{anomalas} terra(s) com geometria anomala (fora do Brasil ou ausente), gravadas com geom NULL e o texto original")
        cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {SRID}) USING ST_Multi(geom)")
        # id_estado so quando a fonte lista UMA UF que existe em dim.estados (a fonte pode listar varias, ex.: "MT, PA")
        cur.execute("UPDATE _stage s SET id_estado = e.id_estado FROM dim.estados e WHERE e.sigla_uf = trim(s.uf_sigla)")
        cur.execute("SELECT count(*) FILTER (WHERE id_estado IS NULL), count(*) FILTER (WHERE uf_sigla ~ '[^A-Za-z ]') FROM _stage")
        sem_uf, multi_uf = cur.fetchone()
        cur.execute("DELETE FROM _stage s USING (SELECT ctid AS c, row_number() OVER (PARTITION BY terrai_codigo ORDER BY ctid) AS rn FROM _stage) r "
                    "WHERE s.ctid = r.c AND r.rn > 1")
        if cur.rowcount:
            carga.avisos.append(f"{cur.rowcount} terrai_codigo repetido(s) na coleta (vale o primeiro)")
        cur.execute("CREATE UNIQUE INDEX ON _stage (terrai_codigo)")
        log(f"  geometrias anomalas: {anomalas} | terras sem id_estado (UF composta ou desconhecida): {sem_uf} (com separador: {multi_uf})")

        stats = espelho.reconciliar(conn, T, ["terrai_codigo"], COMPARAR, CAMPOS, fonte=fonte, id_carga=carga.id,
                                    max_queda=CFG["max_queda"], aceitar_queda=args.aceitar_queda, simular=args.simular, log=log)
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
            return 0
        cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                    "inalterados, id_carga, observacao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, "todas", "FUNAI (servidor de mapas, WFS aberto)", CFG["url_wfs"], "camada inteira em GeoJSON (count=10000)", anunciado,
                     stats["lidos"], stats["novos"], stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                     f"{anomalas} geometrias anomalas", stats["reabertos"]))
        registrar_dataset(conn, "FUNAI - Terras indigenas (poligonais)", T, fonte, ano_referencia=date.today().year, licenca=CFG["licenca"], tipo="vetor",
                          observacoes="Camada Funai:tis_poligonais do servidor de mapas da FUNAI (WFS aberto). Espelho versionado. "
                                      "Ver funai/terras_indigenas/LEIAME_terras_indigenas.md.")
        conn.commit()
        carga.inseridas += stats["inseridos"]
        carga.atualizadas += stats["ausentes"]
        if not args.sem_bruto:
            destino, n = bruto.salvar_jsonl_gz(RAIZ / "bruto" / "wfs", "tis_poligonais", features,
                                               fonte=f"{CFG['url_wfs']}?typeNames={CFG['camada']}&outputFormat=application/json&count={CFG['count']}",
                                               filtro="camada inteira, uma feicao GeoJSON por linha", extra={"anunciado": anunciado})
            log(f"  bruto {destino.name}: {n} feicoes")
        log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']} versoes inseridas, {stats['reabertos']} reabertas, "
            f"{stats['ausentes']} fechadas por ausencia)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
