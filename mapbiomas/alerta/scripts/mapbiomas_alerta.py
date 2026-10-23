"""MapBiomas Alerta (alertas de desmatamento validados) -> vetorial.mapbiomas_alerta, como ESPELHO VERSIONADO.

Baixa a camada publica `dashboard-alert-shapefile` do servidor de mapas do MapBiomas Alerta (WFS aberto, sem login), em fatias por
faixa de codigo do alerta, varias ao mesmo tempo, e reconcilia com o banco igual ao SICAR e ao PRODES: alerta novo entra; alterado
fecha a versao antiga e insere a nova; alerta que o servidor deixou de publicar tem a versao fechada (nada e apagado); alerta que
sumiu e voltou IDENTICO tem a versao reaberta. Reexecutar sem mudanca na fonte nao grava nada.

Uso (no conteiner etl, a partir de infra/):
  docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl mapbiomas/alerta/scripts/mapbiomas_alerta.py [opcoes]

  OPCOES: --codigos 200000-230000 (so esta faixa de alert_code; para testes) | --paralelo N (padrao 4, max 6)
          --so-baixar (so guarda as fatias em bruto/, sem tocar no banco) | --sem-bruto (nao guarda as fatias)
          --simular (reconcilia e relata, nada e gravado) | --aceitar-queda | --destino SCHEMA.TABELA

Regras (ver config.yaml e LEIAME_mapbiomas_alerta.md):
  - chave = alert_code; status_name pode ser `cancelled`: o alerta entra mesmo assim (filtre na analise);
  - geometria ausente ou com a caixa fora do Brasil: o alerta ENTRA com geom NULL, geom_anomala e o texto original;
  - a camada muda ao vivo: baixou menos que (1 - tolerancia) do anunciado, ou mais de max_queda dos vigentes sumiram: nao grava.
"""
import argparse
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from dwlib import db, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # mapbiomas/alerta
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]
CAMPOS = ["alert_code", "area_ha", "sources", "biomes", "states", "cities", "detected_at", "year_detected_at", "published_at",
          "image_after_at", "image_before_at", "deforestation_driver", "status_name", "lat", "lng", "crossed_special_territories",
          "crossed_rural_properties_total"]
DATAS = {"detected_at", "published_at", "image_after_at", "image_before_at"}
COMPARAR = [c for c in CAMPOS if c != "alert_code"] + ["geom_anomala", "geom_origem_texto"]


def log(*a):
    print(*a, flush=True)


def pedido(extra):
    p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": CFG["camada"]}
    p.update(extra)
    return p


def total(sessao, filtro):
    r = sessao.get(CFG["url_wfs"], params=pedido({"resultType": "hits", "cql_filter": filtro}), timeout=300)
    r.raise_for_status()
    m = re.search(r'numberMatched="(\d+)"', r.text)
    if not m:
        raise RuntimeError(f"resposta sem numberMatched: {r.text[:200]}")
    return int(m.group(1))


def extremos(sessao):
    """Menor e maior alert_code publicados."""
    saida = []
    for ordem in ("A", "D"):
        r = sessao.get(CFG["url_wfs"], params=pedido({"outputFormat": "application/json", "count": 1, "sortBy": f"alert_code {ordem}",
                                                      "propertyName": "alert_code"}), timeout=300)
        r.raise_for_status()
        saida.append(r.json()["features"][0]["properties"]["alert_code"])
    return saida[0], saida[1]


# O SHAPE-ZIP do servidor traz a precisao COMPLETA das coordenadas (GeoJSON e GML cortam em 4 casas, ~5 m), mas com os nomes de campo
# truncados em 10 letras. srsName=EPSG:4674 (forma curta) devolve longitude/latitude; a forma urn:...:4674 inverte os eixos.
CAMPO_SHP = {"detected_a": "detected_at", "year_detec": "year_detected_at", "published_": "published_at", "image_afte": "image_after_at",
             "image_befo": "image_before_at", "deforestat": "deforestation_driver", "status_nam": "status_name",
             "crossed_sp": "crossed_special_territories", "crossed_ru": "crossed_rural_properties_total"}


def baixar_fatia(ini, fim, guardar):
    """Alertas com ini <= alert_code < fim, em SHAPE-ZIP (thread propria, sessao propria).
    Retorna (ini, fim, anunciado, [linhas]); cada linha = valores de CAMPOS + geometria (WKB em hexadecimal)."""
    from pyogrio.raw import read
    sessao = http.sessao()
    filtro = f"alert_code >= {ini} AND alert_code < {fim}"
    n = total(sessao, filtro)
    if n == 0:
        return ini, fim, 0, []
    r = sessao.get(CFG["url_wfs"], params=pedido({"outputFormat": "SHAPE-ZIP", "srsName": "EPSG:4674", "cql_filter": filtro}), timeout=900)
    r.raise_for_status()
    pasta = (RAIZ / "bruto" / "wfs") if guardar else Path(tempfile.mkdtemp())
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"alertas_{ini}_{fim}.zip"
    arq.write_bytes(r.content)
    try:
        meta, _, geoms, campos = read(f"zip://{arq}")
    finally:
        if not guardar:
            arq.unlink(missing_ok=True)
            pasta.rmdir()
    idx = {CAMPO_SHP.get(str(c), str(c)): i for i, c in enumerate(meta["fields"])}
    faltam = [c for c in CAMPOS if c not in idx]
    if faltam:
        raise RuntimeError(f"campos esperados ausentes no SHAPE-ZIP: {faltam} (o servidor mudou o esquema?)")
    linhas = []
    for i in range(len(geoms)):
        linhas.append([valor(c, campos[idx[c]][i]) for c in CAMPOS] + [bytes(geoms[i]).hex() if geoms[i] is not None else None])
    return ini, fim, n, linhas


def valor(campo, v):
    if hasattr(v, "item"):
        v = v.item()
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return None
    if campo in DATAS:
        if isinstance(v, datetime):
            return v.date()
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    if campo in ("lat", "lng"):
        return float(v)
    if campo in ("alert_code", "year_detected_at", "crossed_rural_properties_total"):
        return int(v)
    return v


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="MapBiomas Alerta (WFS aberto) -> espelho versionado de vetorial.mapbiomas_alerta")
    ap.add_argument("--codigos", help="faixa de alert_code, ex.: 200000-230000 (padrao: todos)")
    ap.add_argument("--paralelo", type=int, default=CFG["paralelo_padrao"])
    ap.add_argument("--so-baixar", action="store_true")
    ap.add_argument("--sem-bruto", action="store_true")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    if not 1 <= args.paralelo <= CFG["paralelo_maximo"]:
        raise SystemExit(f"--paralelo deve ficar entre 1 e {CFG['paralelo_maximo']}")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    sessao = http.sessao()
    t0 = time.time()

    menor, maior = extremos(sessao)
    if args.codigos:
        a, _, b = args.codigos.partition("-")
        faixa = (max(int(a), menor), min(int(b), maior + 1))
    else:
        faixa = (menor, 10 ** 9)                      # a ultima fatia nao tem teto: alerta novo durante a coleta nao se perde
    filtro_total = f"alert_code >= {faixa[0]} AND alert_code < {faixa[1]}"
    anunciado = total(sessao, filtro_total)
    largura = CFG["fatia_codigos"]
    limites = list(range(faixa[0], min(faixa[1], maior + 1), largura)) + [faixa[1]]
    fatias = [(limites[i], limites[i + 1] if i + 2 < len(limites) else faixa[1]) for i in range(len(limites) - 1)]
    log(f"== MapBiomas Alerta: {anunciado:,} alertas anunciados (codigos {faixa[0]} a {maior}); {len(fatias)} fatias, {args.paralelo} ao mesmo tempo".replace(",", "."))

    conn = fonte = None
    if not args.so_baixar:
        conn = db.conectar()
        fonte = db.id_fonte(conn, CFG["fonte"])
    carga = Carga(conn, "mapbiomas_alerta", dataset=T, parametros=vars(args), simular=args.simular or args.so_baixar) if conn else None
    if carga:
        carga.__enter__()
    try:
        if conn:
            cur = conn.cursor()
            cur.execute("SET statement_timeout = 0")
            cur.execute("CREATE TEMP TABLE _stage (alert_code integer, area_ha numeric, sources text, biomes text, states text, cities text, "
                        "detected_at date, year_detected_at smallint, published_at date, image_after_at date, image_before_at date, "
                        "deforestation_driver text, status_name text, lat double precision, lng double precision, "
                        "crossed_special_territories text, crossed_rural_properties_total integer, geom geometry)")
            copia_ctx = cur.copy("COPY _stage FROM STDIN")
            copia = copia_ctx.__enter__()
        lidos, feitas = 0, 0
        with ThreadPoolExecutor(max_workers=args.paralelo) as pool:
            futuros = [pool.submit(baixar_fatia, ini, fim, not args.sem_bruto) for ini, fim in fatias]
            for f in as_completed(futuros):
                ini, fim, n, linhas = f.result()                  # propaga o erro da fatia: aborta
                feitas += 1
                if not linhas:
                    continue
                lidos += len(linhas)
                if conn:
                    for ln in linhas:
                        copia.write_row(ln)
                if feitas % max(1, len(fatias) // 10) == 0 or feitas == len(fatias):
                    log(f"  {feitas}/{len(fatias)} fatias, {lidos:,} alertas ({time.time() - t0:.0f} s)".replace(",", "."))
        log(f"  baixados {lidos:,} alertas em {time.time() - t0:.0f} s".replace(",", "."))
        if args.so_baixar:
            log(f"== so-baixar: fatias guardadas em {RAIZ / 'bruto' / 'wfs'}; o banco nao foi tocado")
            return 0
        if lidos < anunciado * (1 - CFG["tolerancia_coleta"]):
            raise RuntimeError(f"coleta incompleta: {lidos} baixados de {anunciado} anunciados: NADA gravado")
        copia_ctx.__exit__(None, None, None)
        carga.lidas += lidos

        cx = CFG["caixa_brasil"]
        caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
        cur.execute("ALTER TABLE _stage ADD COLUMN geom_anomala boolean DEFAULT false, ADD COLUMN geom_origem_texto text")
        cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(geom, {SRID}) WHERE geom IS NOT NULL")
        cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = CASE WHEN geom IS NULL THEN NULL ELSE ST_AsEWKT(geom) END, "
                    f"geom = NULL WHERE geom IS NULL OR NOT (geom @ {caixa})")
        anomalas = cur.rowcount
        cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {SRID}) USING ST_Multi(geom)")
        if anomalas:
            carga.avisos.append(f"{anomalas} alerta(s) com geometria anomala (fora do Brasil ou ausente), gravados com geom NULL e o texto original")
        cur.execute("DELETE FROM _stage s USING (SELECT ctid AS c, row_number() OVER (PARTITION BY alert_code ORDER BY ctid) AS rn FROM _stage) r "
                    "WHERE s.ctid = r.c AND r.rn > 1")
        if cur.rowcount:
            carga.avisos.append(f"{cur.rowcount} alert_code repetido(s) na coleta (vale o primeiro)")
        cur.execute("CREATE UNIQUE INDEX ON _stage (alert_code)")
        cur.execute("ANALYZE _stage")
        cur.execute("SELECT count(*) FROM _stage")
        n = cur.fetchone()[0]
        faixa_sql = f"alert_code >= {faixa[0]} AND alert_code < {faixa[1]}"

        comp = " OR ".join(f"c.{c} IS DISTINCT FROM s.{c}" for c in COMPARAR)
        geom_dif = "((c.geom IS NULL) <> (s.geom IS NULL)) OR (c.geom IS NOT NULL AND s.geom IS NOT NULL AND NOT ST_OrderingEquals(c.geom, s.geom))"
        cur.execute(f"CREATE TEMP TABLE _alt AS SELECT c.id AS id_antigo FROM _stage s JOIN {T} c ON c.alert_code = s.alert_code AND c.vigente_ate IS NULL "
                    f"WHERE {comp} OR {geom_dif}")
        cur.execute(f"CREATE TEMP TABLE _aus AS SELECT c.id AS id_antigo FROM {T} c WHERE c.vigente_ate IS NULL AND c.{faixa_sql} "
                    f"AND NOT EXISTS (SELECT 1 FROM _stage s WHERE s.alert_code = c.alert_code)")
        cur.execute(f"SELECT count(*) FROM {T} c WHERE c.vigente_ate IS NULL AND c.{faixa_sql}")
        vigentes_antes = cur.fetchone()[0]
        cur.execute("SELECT (SELECT count(*) FROM _alt), (SELECT count(*) FROM _aus)")
        n_alt, n_aus = cur.fetchone()
        cur.execute(f"SELECT count(*) FROM _stage s WHERE NOT EXISTS (SELECT 1 FROM {T} c WHERE c.alert_code = s.alert_code AND c.vigente_ate IS NULL)")
        n_novos = cur.fetchone()[0]
        idem = " AND ".join(f"NOT (c.{c} IS DISTINCT FROM s.{c})" for c in COMPARAR)
        idem += " AND ((c.geom IS NULL) = (s.geom IS NULL)) AND (c.geom IS NULL OR ST_OrderingEquals(c.geom, s.geom))"
        cur.execute(f"""CREATE TEMP TABLE _reab AS
            WITH ult AS (SELECT DISTINCT ON (c.alert_code) c.* FROM {T} c WHERE c.vigente_ate IS NOT NULL
                         AND c.alert_code IN (SELECT alert_code FROM _stage) ORDER BY c.alert_code, c.vigente_ate DESC, c.id DESC)
            SELECT c.id AS id_antigo FROM _stage s JOIN ult c ON c.alert_code = s.alert_code
            WHERE NOT EXISTS (SELECT 1 FROM {T} v WHERE v.alert_code = s.alert_code AND v.vigente_ate IS NULL) AND {idem}""")
        cur.execute("SELECT count(*) FROM _reab")
        n_reab = cur.fetchone()[0]
        inalterados = n - n_novos - n_alt
        n_cancelados = 0
        cur.execute("SELECT count(*) FROM _stage WHERE status_name = 'cancelled'")
        n_cancelados = cur.fetchone()[0]
        log(f"  vigentes no banco {vigentes_antes:,} | NOVOS {n_novos - n_reab:,} | REABERTOS {n_reab:,} | ALTERADOS {n_alt:,} | "
            f"AUSENTES da fonte {n_aus:,} | inalterados {inalterados:,} | cancelados na fonte {n_cancelados:,} | geometrias anomalas {anomalas}".replace(",", "."))
        if vigentes_antes and n_aus > vigentes_antes * CFG["max_queda"] and not args.aceitar_queda:
            raise RuntimeError(f"{n_aus} ausentes = mais de {CFG['max_queda']:.0%} dos vigentes: NAO gravado (confira; --aceitar-queda libera)")
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
            return 0
        hoje, agora = date.today(), datetime.now(timezone.utc)
        cur.execute(f"UPDATE {T} SET vigente_ate = %s WHERE id IN (SELECT id_antigo FROM _alt UNION SELECT id_antigo FROM _aus)", (hoje,))
        cur.execute(f"UPDATE {T} SET vigente_ate = NULL, reaberto_em = %s WHERE id IN (SELECT id_antigo FROM _reab)", (hoje,))
        cols = ", ".join(CAMPOS)
        cur.execute(f"""INSERT INTO {T} ({cols}, geom, geom_anomala, geom_origem_texto, id_fonte, importado_em, vigente_desde, coletado_em)
                        SELECT {", ".join('s.' + c for c in CAMPOS)}, s.geom, s.geom_anomala, s.geom_origem_texto, %s, %s, %s, %s
                        FROM _stage s WHERE NOT EXISTS (SELECT 1 FROM {T} c WHERE c.alert_code = s.alert_code AND c.vigente_ate IS NULL)""",
                    (fonte, hoje, hoje, agora))
        inseridos = cur.rowcount
        if inseridos != n_novos - n_reab + n_alt:
            raise RuntimeError(f"inseridos {inseridos} != novos {n_novos - n_reab} + alterados {n_alt}: transacao desfeita")
        cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                    "inalterados, id_carga, observacao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, "todos" if not args.codigos else args.codigos, "MapBiomas Alerta (servidor de mapas, WFS aberto)", CFG["url_wfs"],
                     f"reconciliacao por {len(fatias)} faixas de alert_code, {args.paralelo} ao mesmo tempo", anunciado, lidos, n_novos - n_reab,
                     n_alt, n_aus, inalterados, carga.id, f"{n_cancelados} cancelados; {anomalas} geometrias anomalas", n_reab))
        conn.commit()
        carga.inseridas += inseridos
        carga.atualizadas += n_aus
        if not args.codigos:
            cur.execute(f"SELECT max(year_detected_at) FROM {T} WHERE vigente_ate IS NULL")
            registrar_dataset(conn, "MapBiomas Alerta - Alertas de desmatamento validados", T, fonte, ano_referencia=cur.fetchone()[0],
                              licenca=CFG["licenca"], tipo="vetor",
                              observacoes="Camada dashboard-alert-shapefile do servidor de mapas do MapBiomas Alerta (WFS aberto). Espelho versionado; inclui "
                                          "alertas cancelados (status_name). Ver mapbiomas/alerta/LEIAME_mapbiomas_alerta.md.")
            conn.commit()
        log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({inseridos:,} versoes inseridas, {n_reab:,} reabertas, {n_aus:,} fechadas por ausencia)".replace(",", "."))
        return 0
    finally:
        if carga:
            exc = sys.exc_info()
            carga.__exit__(exc[0], exc[1], exc[2])
        if conn:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
