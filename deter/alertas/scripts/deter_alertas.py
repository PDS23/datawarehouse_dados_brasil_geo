"""DETER (alertas de desmatamento do INPE, Amazônia e Cerrado) -> vetorial.deter_alertas, como ESPELHO VERSIONADO.

Baixa as duas camadas do servidor de mapas do TerraBrasilis (WFS aberto, sem login) em SHAPE-ZIP, fatiadas por mês de publicação
(publish_month), várias fatias ao mesmo tempo, e reconcilia com o banco igual ao SICAR, ao PRODES, ao MapBiomas Alerta e à FUNAI
(regras em dwlib/espelho.py): alerta novo entra; alterado fecha a versão antiga e insere a nova; alerta que o servidor deixou de
publicar tem a versão fechada (nada é apagado na coleta); alerta que sumiu e voltou idêntico tem a versão reaberta.

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl deter/alertas/scripts/deter_alertas.py [opções]

  OPÇÕES: --biomas amazonia,cerrado (padrão: os dois) | --a-partir 2024-01 (só os meses de publicação desde aí; teste)
          --paralelo N (padrão 4, máx. 6) | --sem-bruto (não guarda as fatias em bruto/) | --simular | --aceitar-queda
          --destino SCHEMA.TABELA (padrão: o do config.yaml; a tabela precisa existir: sql/01_tabela.sql)

Regras (ver config.yaml e LEIAME_deter_alertas.md):
  - chave = (id_bioma, gid, chave_linha): o gid NÃO é único (repete entre os biomas, entre os municípios que um polígono cruza e é reutilizado por alertas
    diferentes); chave_linha = município|view_date|classname|areamunkm, a menor combinação que distingue todas as linhas;
  - o SHAPE-ZIP traz a precisão completa (o GeoJSON do servidor corta as coordenadas em 4 casas), com nomes de campo truncados em 10 letras;
  - a camada muda ao vivo (o DETER é diário): baixou menos que (1 - tolerância) do anunciado, ou sumiram mais que max_queda dos vigentes: não grava;
  - geometria ausente ou fora da caixa do Brasil: o alerta ENTRA com geom NULL, geom_anomala e o texto original.
"""
import argparse
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import yaml

from dwlib import db, espelho, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # deter/alertas
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]
# campos da fonte (a Amazônia não tem created_date nem areatotalkm; o Cerrado não tem mun_geocod: ficam NULL)
DA_FONTE = ["gid", "classname", "quadrant", "path_row", "view_date", "created_date", "sensor", "satellite", "areatotalkm", "areauckm", "uc",
            "areamunkm", "municipality", "mun_geocod", "uf", "publish_month"]
CAMPOS = ["id_bioma"] + DA_FONTE + ["chave_linha", "id_estado", "id_municipio"]
CHAVE = ["id_bioma", "gid", "chave_linha"]
COMPARAR = [c for c in CAMPOS if c not in CHAVE] + ["geom_anomala", "geom_origem_texto"]
DATAS = {"view_date", "created_date", "publish_month"}
REAIS = {"areatotalkm", "areauckm", "areamunkm"}
CAMPO_SHP = {"municipali": "municipality", "publish_mo": "publish_month", "created_da": "created_date", "areatotalk": "areatotalkm"}


def log(*a):
    print(*a, flush=True)


def pedido(camada, extra):
    p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": camada}
    p.update(extra)
    return p


def total(sessao, camada, filtro):
    r = sessao.get(CFG["url_wfs"], params=pedido(camada, {"resultType": "hits", "cql_filter": filtro}), timeout=300)
    r.raise_for_status()
    m = re.search(r'numberMatched="(\d+)"', r.text)
    if not m:
        raise RuntimeError(f"resposta sem numberMatched: {r.text[:200]}")
    return int(m.group(1))


def extremos(sessao, camada):
    """Menor e maior publish_month publicados (ignorando os nulos, que o servidor ordena de forma diferente em A e D)."""
    saida = []
    for ordem in ("A", "D"):
        r = sessao.get(CFG["url_wfs"], params=pedido(camada, {"outputFormat": "application/json", "count": 1, "sortBy": f"publish_month {ordem}",
                                                            "propertyName": "publish_month", "cql_filter": "publish_month IS NOT NULL"}), timeout=300)
        r.raise_for_status()
        saida.append(date.fromisoformat(r.json()["features"][0]["properties"]["publish_month"][:10]))
    return saida[0], saida[1]


def fatias_do_bioma(menor, maior, a_partir):
    """Filtros CQL por mês de publicação (rótulo, filtro). A primeira fatia fica sem piso e a última sem teto (alerta novo durante a coleta
    não se perde); os alertas sem mês entram numa fatia própria. Com a_partir ("AAAA-MM") só os meses desde aí (teste)."""
    inicio = date(menor.year, menor.month, 1)
    if a_partir:
        inicio = max(inicio, date(int(a_partir[:4]), int(a_partir[5:]), 1))
    meses, m = [], inicio
    while m <= maior:
        meses.append(m)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    fatias = []
    for i, m in enumerate(meses):
        prox = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        cond = []
        if i > 0 or a_partir:
            cond.append(f"publish_month >= '{m}'")
        if i < len(meses) - 1:
            cond.append(f"publish_month < '{prox}'")
        fatias.append((m.strftime("%Y-%m"), " AND ".join(cond) or "publish_month IS NOT NULL"))
    if not a_partir:
        fatias.append(("sem_mes", "publish_month IS NULL"))
    return fatias


def valor(campo, v):
    if hasattr(v, "item"):
        v = v.item()
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return None
    if campo in DATAS:
        if isinstance(v, datetime):
            return v.date()
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    if campo in REAIS:
        return float(v)
    return str(v)


def baixar_fatia(bioma, camada, rotulo, filtro, guardar):
    """Alertas de uma fatia, em SHAPE-ZIP (thread própria, sessão própria). Retorna (bioma, rotulo, anunciado, [linhas]); cada linha =
    valores de DA_FONTE + geometria (WKB em hexadecimal)."""
    from pyogrio.raw import read
    sessao = http.sessao()
    n = total(sessao, camada, filtro)
    if n == 0:
        return bioma, rotulo, 0, []
    r = sessao.get(CFG["url_wfs"], params=pedido(camada, {"outputFormat": "SHAPE-ZIP", "srsName": f"EPSG:{SRID}", "cql_filter": filtro}), timeout=900)
    r.raise_for_status()
    pasta = (RAIZ / "bruto" / bioma) if guardar else Path(tempfile.mkdtemp())
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"deter_{rotulo}.zip"
    arq.write_bytes(r.content)
    try:
        meta, _, geoms, campos = read(f"zip://{arq}")
    finally:
        if not guardar:
            arq.unlink(missing_ok=True)
            pasta.rmdir()
    idx = {CAMPO_SHP.get(str(c), str(c)): i for i, c in enumerate(meta["fields"])}
    if "gid" not in idx or "classname" not in idx:
        raise RuntimeError(f"{bioma}/{rotulo}: campos gid/classname ausentes no SHAPE-ZIP ({sorted(idx)}): o servidor mudou o esquema?")
    linhas = []
    for i in range(len(geoms)):
        linhas.append([valor(c, campos[idx[c]][i]) if c in idx else None for c in DA_FONTE] + [bytes(geoms[i]).hex() if geoms[i] is not None else None])
    return bioma, rotulo, n, linhas


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="DETER (WFS aberto do TerraBrasilis) -> espelho versionado de vetorial.deter_alertas")
    ap.add_argument("--biomas", default=",".join(CFG["biomas"]))
    ap.add_argument("--a-partir", help="AAAA-MM: só os meses de publicação desde aí (teste; use com --simular ou numa tabela de teste)")
    ap.add_argument("--paralelo", type=int, default=CFG["paralelo_padrao"])
    ap.add_argument("--sem-bruto", action="store_true")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    biomas = [b.strip() for b in args.biomas.split(",") if b.strip()]
    desconhecidos = [b for b in biomas if b not in CFG["biomas"]]
    if desconhecidos:
        raise SystemExit(f"bioma(s) sem DETER publicado: {desconhecidos} (disponiveis: {list(CFG['biomas'])})")
    if not 1 <= args.paralelo <= CFG["paralelo_maximo"]:
        raise SystemExit(f"--paralelo deve ficar entre 1 e {CFG['paralelo_maximo']}")
    if args.a_partir and not re.fullmatch(r"\d{4}-\d{2}", args.a_partir):
        raise SystemExit("--a-partir deve ser AAAA-MM")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    t0 = time.time()
    sessao = http.sessao()

    # plano: fatias de cada bioma e o total anunciado
    plano, anunciado = [], {}
    for b in biomas:
        camada = CFG["biomas"][b]["camada"]
        menor, maior = extremos(sessao, camada)
        fatias = fatias_do_bioma(menor, maior, args.a_partir)
        anunciado[b] = sum(total(sessao, camada, f) for _, f in fatias)
        plano += [(b, camada, r, f) for r, f in fatias]
        log(f"== DETER {b}: {anunciado[b]:,} alertas anunciados (publish_month {menor} a {maior}); {len(fatias)} fatias".replace(",", "."))

    conn = db.conectar()
    fonte = db.id_fonte(conn, CFG["fonte"])
    with Carga(conn, "deter_alertas", dataset=T, parametros=vars(args), simular=args.simular) as carga:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = 0")
        cur.execute("CREATE TEMP TABLE _stage (id_bioma smallint, gid text, classname text, quadrant text, path_row text, view_date date, "
                    "created_date date, sensor text, satellite text, areatotalkm double precision, areauckm double precision, uc text, "
                    "areamunkm double precision, municipality text, mun_geocod text, uf text, publish_month date, chave_linha text, id_estado smallint, "
                    "id_municipio integer, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) ON COMMIT DROP")
        lidos = {b: 0 for b in biomas}
        feitas = 0
        with cur.copy(f"COPY _stage ({', '.join(['id_bioma'] + DA_FONTE)}, geom) FROM STDIN") as copia:
            with ThreadPoolExecutor(max_workers=args.paralelo) as pool:
                futuros = [pool.submit(baixar_fatia, b, camada, r, f, not args.sem_bruto) for b, camada, r, f in plano]
                for fut in as_completed(futuros):
                    b, r, n, linhas = fut.result()                  # propaga o erro da fatia: aborta
                    feitas += 1
                    if len(linhas) != n:
                        raise RuntimeError(f"{b}/{r}: {len(linhas)} lidas do SHAPE-ZIP de {n} anunciadas: NADA gravado")
                    lidos[b] += len(linhas)
                    for ln in linhas:
                        copia.write_row([CFG["biomas"][b]["id_bioma"]] + ln)
                    if feitas % max(1, len(plano) // 10) == 0 or feitas == len(plano):
                        log(f"  {feitas}/{len(plano)} fatias, {sum(lidos.values()):,} alertas ({time.time() - t0:.0f} s)".replace(",", "."))
        for b in biomas:
            if lidos[b] < anunciado[b] * (1 - CFG["tolerancia_coleta"]):
                raise RuntimeError(f"{b}: coleta incompleta: {lidos[b]} baixados de {anunciado[b]} anunciados: NADA gravado")
        carga.lidas += sum(lidos.values())

        cx = CFG["caixa_brasil"]
        caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
        cur.execute("UPDATE _stage SET chave_linha = concat_ws('|', coalesce(mun_geocod, upper(municipality), ''), view_date, classname, areamunkm)")
        cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(geom, {SRID}) WHERE geom IS NOT NULL")
        cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = CASE WHEN geom IS NULL THEN NULL ELSE ST_AsEWKT(geom) END, "
                    f"geom = NULL WHERE geom IS NULL OR NOT (geom @ {caixa})")
        anomalas = cur.rowcount
        if anomalas:
            carga.avisos.append(f"{anomalas} alerta(s) com geometria anomala (fora do Brasil ou ausente), gravados com geom NULL e o texto original")
        cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {SRID}) USING ST_Multi(geom)")
        cur.execute("UPDATE _stage s SET id_estado = e.id_estado FROM dim.estados e WHERE e.sigla_uf = upper(trim(s.uf))")
        cur.execute("UPDATE _stage s SET id_municipio = m.id_municipio FROM dim.municipios m WHERE s.mun_geocod ~ '^[0-9]{7}$' "
                    "AND m.id_municipio = s.mun_geocod::integer")
        cur.execute("SELECT id_bioma, count(*), count(*) FILTER (WHERE id_estado IS NULL), count(*) FILTER (WHERE id_municipio IS NULL) "
                    "FROM _stage GROUP BY 1 ORDER BY 1")
        for ib, n, sem_uf, sem_mun in cur.fetchall():
            log(f"  bioma {ib}: {n:,} alertas | sem id_estado {sem_uf} | sem id_municipio {sem_mun}".replace(",", "."))
        cur.execute("DELETE FROM _stage s USING (SELECT ctid AS c, row_number() OVER (PARTITION BY id_bioma, gid, chave_linha ORDER BY ctid) AS rn FROM _stage) r "
                    "WHERE s.ctid = r.c AND r.rn > 1")
        if cur.rowcount:
            carga.avisos.append(f"{cur.rowcount} (id_bioma, gid, chave_linha) repetido(s) na coleta (vale o primeiro)")
        cur.execute("CREATE UNIQUE INDEX ON _stage (id_bioma, gid, chave_linha)")
        cur.execute("ANALYZE _stage")

        escopo = "c.id_bioma IN (" + ", ".join(str(CFG["biomas"][b]["id_bioma"]) for b in biomas) + ")"
        if args.a_partir:
            escopo += f" AND c.publish_month >= '{args.a_partir}-01'"
        stats = espelho.reconciliar(conn, T, CHAVE, COMPARAR, CAMPOS, fonte=fonte, id_carga=carga.id, max_queda=CFG["max_queda"],
                                    aceitar_queda=args.aceitar_queda, simular=args.simular, escopo_sql=escopo, log=log)
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
            return 0
        recorte = ",".join(biomas) + (f" desde {args.a_partir}" if args.a_partir else "")
        cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                    "inalterados, id_carga, observacao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, recorte, "INPE/TerraBrasilis (DETER, WFS aberto)", CFG["url_wfs"],
                     f"SHAPE-ZIP em {len(plano)} fatias por mes de publicacao, {args.paralelo} ao mesmo tempo", sum(anunciado.values()), sum(lidos.values()),
                     stats["novos"], stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id, f"{anomalas} geometrias anomalas",
                     stats["reabertos"]))
        if not args.a_partir:
            cur.execute(f"SELECT max(view_date) FROM {T} WHERE vigente_ate IS NULL")
            ultimo = cur.fetchone()[0]
            registrar_dataset(conn, "DETER - Alertas de desmatamento (Amazonia e Cerrado)", T, fonte, ano_referencia=(ultimo.year if ultimo else None),
                              licenca=CFG["licenca"], tipo="vetor",
                              observacoes="Camadas deter-amz:deter_amz e deter-cerrado-nb:deter_cerrado do servidor de mapas do TerraBrasilis (WFS aberto). "
                                          "Espelho versionado. Ver deter/alertas/LEIAME_deter_alertas.md.")
        conn.commit()
        carga.inseridas += stats["inseridos"]
        carga.atualizadas += stats["ausentes"]
        log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']:,} versoes inseridas, {stats['reabertos']:,} reabertas, "
            f"{stats['ausentes']:,} fechadas por ausencia)".replace(",", "."))
        return 0


if __name__ == "__main__":
    sys.exit(main())
