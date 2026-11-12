"""Territorios quilombolas oficialmente delimitados (IBGE, WFS aberto) -> vetorial.ibge_territorios_quilombolas, como ESPELHO VERSIONADO.

Le o GetCapabilities do workspace CGMAT do servidor de mapas do IBGE, escolhe a camada `qg_AAAA_620_territorioquilombola__vNN` MAIS RECENTE (ano e versao
estao no nome), baixa a camada inteira (uma requisicao, ~500 poligonos) e reconcilia com o banco igual a FUNAI e as demais fontes vivas (regras em
dwlib/espelho.py): territorio novo entra; alterado fecha a versao antiga e insere a nova; o que o servidor deixou de publicar tem a versao fechada
(nada e apagado na coleta); o que sumiu e voltou identico tem a versao reaberta.

Uso (a partir da raiz do repositorio):
  .\\infra\\scripts\\dw.ps1 etl ibge/territorios_quilombolas/scripts/territorios_quilombolas.py [opcoes]

  OPCOES: --verificar (so diz qual camada o IBGE publica hoje x a que o banco tem) | --simular (reconcilia e relata, nada e gravado) |
          --sem-bruto (nao guarda o GeoJSON em bruto/) | --aceitar-queda | --destino SCHEMA.TABELA (padrao: o do config.yaml)
"""
import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import yaml

from dwlib import bruto, db, espelho, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # ibge/territorios_quilombolas
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]
CAMPOS = ["cd_recorte", "cd_tq", "nm_tq", "status", "quadro", "cd_uf", "sg_uf", "id_estado", "camada_origem"]
DA_FONTE = ["cd_recorte", "cd_tq", "nm_tq", "status", "quadro", "cd_uf", "sg_uf"]
COMPARAR = [c for c in CAMPOS if c != "cd_recorte"] + ["geom_anomala", "geom_origem_texto"]


def log(*a):
    print(*a, flush=True)


def camada_mais_recente(sessao):
    """(nome da camada, ano, versao) da camada quilombola mais recente publicada no workspace CGMAT."""
    r = sessao.get(CFG["url_wfs"], params={"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"}, timeout=300)
    r.raise_for_status()
    achadas = []
    for el in ET.fromstring(r.content).iter():
        if el.tag.endswith("}Name") and el.text:
            m = re.fullmatch(CFG["padrao_camada"], el.text.strip())
            if m:
                achadas.append((int(m.group(1)), int(m.group(2)), el.text.strip()))
    if not achadas:
        raise RuntimeError(f"nenhuma camada casa com {CFG['padrao_camada']} no GetCapabilities de {CFG['url_wfs']}")
    ano, versao, nome = max(achadas)
    return nome, ano, versao


def baixar(sessao, camada):
    r = sessao.get(CFG["url_wfs"], params={"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": camada,
                                           "outputFormat": "application/json", "srsName": f"EPSG:{SRID}", "count": CFG["count"]}, timeout=900)
    r.raise_for_status()
    j = r.json()
    anunciado = j.get("numberMatched")
    if anunciado is None:
        raise RuntimeError(f"resposta sem numberMatched (chaves: {sorted(j)})")
    return j["features"], int(anunciado)


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="Territorios quilombolas do IBGE (WFS aberto) -> espelho versionado de vetorial.ibge_territorios_quilombolas")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--sem-bruto", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    t0 = time.time()

    sessao = http.sessao()
    camada, ano, versao = camada_mais_recente(sessao)
    log(f"== IBGE: camada mais recente publicada: {camada} (ano {ano}, versao {versao})")
    conn = db.conectar()
    if args.verificar:
        with conn.cursor() as cur:
            cur.execute(f"SELECT camada_origem, count(*) FROM {T} WHERE vigente_ate IS NULL GROUP BY 1")
            log(f"   no banco (vigentes): {cur.fetchall() or 'nada'}")
        return 0

    features, anunciado = baixar(sessao, camada)
    log(f"== IBGE: {len(features)} territorios baixados ({anunciado} anunciados) em {time.time() - t0:.0f} s")
    if len(features) != anunciado:
        raise RuntimeError(f"coleta incompleta: {len(features)} baixados de {anunciado} anunciados: NADA gravado")
    if len(features) < CFG["territorios_minimos"]:
        raise RuntimeError(f"so {len(features)} territorios (minimo {CFG['territorios_minimos']}): camada errada ou truncada, NADA gravado")

    fonte = db.id_fonte(conn, CFG["fonte"])
    with Carga(conn, "ibge_territorios_quilombolas", dataset=T, parametros=vars(args), simular=args.simular) as carga:
        cur = conn.cursor()
        cur.execute("CREATE TEMP TABLE _stage (cd_recorte text, cd_tq text, nm_tq text, status text, quadro text, cd_uf text, sg_uf text, "
                    "id_estado smallint, camada_origem text, geom_json text, geom geometry, geom_anomala boolean DEFAULT false, "
                    "geom_origem_texto text) ON COMMIT DROP")
        with cur.copy(f"COPY _stage ({', '.join(DA_FONTE)}, geom_json) FROM STDIN") as copia:
            for f in features:
                p = f["properties"]
                copia.write_row([(p.get(c) if p.get(c) not in ("",) else None) for c in DA_FONTE] +
                                [json.dumps(f["geometry"]) if f.get("geometry") else None])
        carga.lidas += len(features)
        cur.execute("UPDATE _stage SET camada_origem = %s", (camada,))

        cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(ST_GeomFromGeoJSON(geom_json), {SRID}) WHERE geom_json IS NOT NULL")
        cx = CFG["caixa_brasil"]
        caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
        cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = CASE WHEN geom IS NULL THEN NULL ELSE ST_AsEWKT(geom) END, "
                    f"geom = NULL WHERE geom IS NULL OR NOT (geom @ {caixa})")
        anomalas = cur.rowcount
        if anomalas:
            carga.avisos.append(f"{anomalas} territorio(s) com geometria anomala (fora do Brasil ou ausente), gravados com geom NULL e o texto original")
        cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {SRID}) USING ST_Multi(ST_Force2D(geom))")   # a camada do IBGE traz Z
        cur.execute("UPDATE _stage s SET id_estado = e.id_estado FROM dim.estados e WHERE e.sigla_uf = trim(s.sg_uf)")
        cur.execute("SELECT count(*) FILTER (WHERE id_estado IS NULL), count(*) FILTER (WHERE cd_recorte IS NULL) FROM _stage")
        sem_uf, sem_chave = cur.fetchone()
        if sem_chave:
            raise RuntimeError(f"{sem_chave} territorio(s) sem cd_recorte (chave): NADA gravado")
        cur.execute("DELETE FROM _stage s USING (SELECT ctid AS c, row_number() OVER (PARTITION BY cd_recorte ORDER BY ctid) AS rn FROM _stage) r "
                    "WHERE s.ctid = r.c AND r.rn > 1")
        if cur.rowcount:
            carga.avisos.append(f"{cur.rowcount} cd_recorte repetido(s) na coleta (vale o primeiro)")
        cur.execute("CREATE UNIQUE INDEX ON _stage (cd_recorte)")
        log(f"  geometrias anomalas: {anomalas} | territorios sem id_estado: {sem_uf}")

        stats = espelho.reconciliar(conn, T, ["cd_recorte"], COMPARAR, CAMPOS, fonte=fonte, id_carga=carga.id,
                                    max_queda=CFG["max_queda"], aceitar_queda=args.aceitar_queda, simular=args.simular, log=log)
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
            return 0
        cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                    "inalterados, id_carga, observacao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, "todos", "IBGE (servidor de mapas, WFS aberto)", CFG["url_wfs"], f"camada inteira {camada} em GeoJSON", anunciado,
                     stats["lidos"], stats["novos"], stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                     f"{anomalas} geometrias anomalas", stats["reabertos"]))
        registrar_dataset(conn, "IBGE - Territorios quilombolas oficialmente delimitados", T, fonte, ano_referencia=ano, licenca=CFG["licenca"], tipo="vetor",
                          observacoes=f"Camada {camada} do servidor de mapas do IBGE (WFS aberto). Espelho versionado. Nao e a base do INCRA. "
                                      "Ver ibge/territorios_quilombolas/LEIAME_territorios_quilombolas.md.")
        conn.commit()
        carga.inseridas += stats["inseridos"]
        carga.atualizadas += stats["ausentes"]
        if not args.sem_bruto:
            destino, n = bruto.salvar_jsonl_gz(RAIZ / "bruto" / "wfs", "territorios_quilombolas", features,
                                               fonte=f"{CFG['url_wfs']}?typeNames={camada}&outputFormat=application/json&count={CFG['count']}",
                                               filtro="camada inteira, uma feicao GeoJSON por linha", extra={"anunciado": anunciado, "camada": camada})
            log(f"  bruto {destino.name}: {n} feicoes")
        log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']} versoes inseridas, {stats['reabertos']} reabertas, "
            f"{stats['ausentes']} fechadas por ausencia)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
