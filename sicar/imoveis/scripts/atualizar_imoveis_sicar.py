"""SICAR (imoveis rurais) -> vetorial.sicar_imoveis, SO pelo WFS publico do CAR (sem CAPTCHA). Carga inicial e atualizacao
sao o MESMO caminho: reconciliar uma UF inteira com o que o WFS entrega agora.

Como baixa: o WFS e lento para paginar a UF inteira (BA: 12 a 55 s por pagina), entao a UF e FATIADA por municipio
(CQL cod_municipio_ibge=...), cada fatia paginada de 1.000 em 1.000 (0,4 a 0,8 s por pagina), com varios AGENTES
(threads) pedindo ao mesmo tempo (--paralelo, padrao 4, maximo 6). Um filtro de "tudo que sobrou" (POST) pega o que
nao cair em nenhum municipio da dimensao. Confere o total contra o anunciado pelo servidor (resultType=hits).

Como grava (uma transacao por UF), comparando com as versoes VIGENTES (vigente_ate IS NULL):
  - NOVOS: cod_imovel que nao esta vigente entra (vigente_desde = hoje);
  - ALTERADOS: algum campo da fonte ou a geometria mudou -> fecha a versao antiga (vigente_ate = hoje) e insere a nova;
  - AUSENTES: vigente no banco e ausente do WFS -> versao fechada (o banco e espelho do WFS; nada e apagado).
    Trava: se passar de max_queda da UF, aborta e pede conferencia (--aceitar-queda libera);
  - INALTERADOS: nada e feito.
Guarda TODAS as colunas do WFS (nomes nossos; mapa em catalogo.mapa_colunas), cancelados (CA) inclusive. Geometria com
vertice fora do Brasil ou ausente vira ANOMALA: geom NULL e o texto original em geom_origem_texto.
Cada UF coletada vira uma linha em catalogo.coletas (fonte, metodo, quando, quanto).

SOB DEMANDA: --ufs e obrigatorio. Comece com --simular (baixa e compara, desfaz no fim).

Uso (no conteiner etl, a partir de infra/):
  docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl sicar/imoveis/scripts/atualizar_imoveis_sicar.py --ufs AC --simular
  OPCOES: --tabela <schema.tabela> (padrao vetorial.sicar_imoveis; na construcao: sicar_novo.sicar_imoveis)
          --paralelo N | --aceitar-queda | --simular
"""
import argparse
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from dwlib import db, http, wfs
from dwlib.catalogo import Carga
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # sicar/imoveis
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID, CAIXA = CFG["srid_gravado"], CFG["caixa_brasil"]
UFS = "AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split()
_local = threading.local()


def log(*a):
    print(*a, flush=True)


def sessao():
    if getattr(_local, "s", None) is None:
        _local.s = http.sessao(tls_legado=CFG["tls_legado"])
    return _local.s


def pedir(params, saida_json=False):
    """GET (ou POST se o filtro for longo) com repeticao propria alem da da sessao. Devolve a resposta."""
    longo = len(params.get("CQL_FILTER", "")) > 1200
    ultimo = None
    for tentativa in range(1, 5):
        try:
            r = sessao().post(CFG["url_wfs"], data=params, timeout=600) if longo else sessao().get(CFG["url_wfs"], params=params, timeout=600)
            r.raise_for_status()
            return r
        except Exception as e:                           # rede, 5xx, timeout
            ultimo = e
            time.sleep(3 * tentativa)
    raise RuntimeError(f"WFS falhou apos 4 tentativas: {ultimo}")


def base(uf):
    return {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": CFG["camada_por_uf"].format(uf=uf.lower())}


def hits(uf, cql=None):
    p = {**base(uf), "resultType": "hits"}
    if cql:
        p["CQL_FILTER"] = cql
    return int(re.search(r'numberMatched="(\d+)"', pedir(p).text).group(1))


def fora_do_brasil(coords):
    """True se algum vertice (lon, lat) sair da caixa do Brasil."""
    pilha = [coords]
    while pilha:
        c = pilha.pop()
        if isinstance(c[0], (int, float)):
            x, y = c[0], c[1]
            if not (CAIXA["lon_min"] <= x <= CAIXA["lon_max"] and CAIXA["lat_min"] <= y <= CAIXA["lat_max"]):
                return True
        else:
            pilha.extend(c)
    return False


def linha(f):
    """Feicao GeoJSON -> tupla na ordem das colunas da tabela temporaria _stage (ver coletar_uf)."""
    p, g = f["properties"], f.get("geometry")
    ewkt = anomala = texto = None
    if g is None:
        anomala, texto = True, None
    else:
        ewkt = wfs.ewkt_de_geojson(g, SRID)
        if fora_do_brasil(g["coordinates"]):
            anomala, texto, ewkt = True, ewkt, None      # guarda o original, nao o usa como geometria
        else:
            anomala = False
    return (f["id"], p["cod_imovel"], p.get("status_imovel"), p.get("dat_criacao"), p.get("data_atualizacao"), p.get("area"),
            p.get("condicao"), p.get("uf"), p.get("municipio"), p.get("cod_municipio_ibge"), p.get("m_fiscal"),
            p.get("tipo_imovel"), ewkt, anomala, texto)


def pagina(uf, cql, inicio):
    p = {**base(uf), "outputFormat": "application/json", "count": CFG["por_pagina"], "startIndex": inicio}
    if cql:
        p["CQL_FILTER"] = cql
    return [linha(f) for f in pedir(p).json()["features"]]


def fatiar(uf, municipios, pool, anunciado):
    """[(cql, n)] com n > 0: uma fatia por municipio + o resto (o que nao cair em nenhum municipio da dimensao)."""
    contagens = list(pool.map(lambda m: (m, hits(uf, f"cod_municipio_ibge={m}")), municipios))
    fatias = [(f"cod_municipio_ibge={m}", n) for m, n in contagens if n > 0]
    soma = sum(n for _, n in fatias)
    resto = anunciado - soma
    if resto > max(5, int(anunciado * CFG["tolerancia_coleta"] / 2)):
        lista = ",".join(str(m) for m, _ in contagens)
        cql = f"NOT (cod_municipio_ibge IN ({lista}))"
        n = hits(uf, cql)
        if n > 0:
            log(f"  {uf}: {n} imoveis fora dos municipios da dimensao (fatia 'resto')")
            fatias.append((cql, n))
    grandes = [(c, n) for c, n in fatias if n > CFG["limite_fatia"]]
    if grandes:
        log(f"  AVISO: fatia(s) acima de {CFG['limite_fatia']}: {grandes[:3]} (paginacao funda pode ser lenta)")
    return fatias


def coletar_uf(conn, uf, paralelo, municipios):
    """Baixa a UF para a tabela temporaria _stage. Devolve (anunciado, lidos, fatias)."""
    anunciado = hits(uf)
    log(f"== {uf}: {anunciado:,} imoveis anunciados pelo WFS".replace(",", "."))
    t0 = time.time()
    with ThreadPoolExecutor(paralelo) as pool:
        fatias = fatiar(uf, municipios, pool, anunciado)
        tarefas = [(cql, ini) for cql, n in fatias for ini in range(0, n, CFG["por_pagina"])]
        esperado = sum(n for _, n in fatias)
        log(f"  {len(fatias)} fatias, {len(tarefas)} paginas, {paralelo} agentes ({time.time() - t0:.0f} s para medir as fatias)")
        lidos, feitas = 0, 0
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS _stage")
            cur.execute("CREATE TEMP TABLE _stage (fid_wfs text, cod_imovel text, ind_status text, dat_criacao timestamptz, "
                        "dat_atualizacao timestamptz, num_area numeric, des_condic text, cod_estado text, municipio text, "
                        "cod_municipio_ibge integer, mod_fiscal numeric, ind_tipo text, geom geometry(MultiPolygon, %s), "
                        "geom_anomala boolean, geom_origem_texto text)" % SRID)
            with cur.copy("COPY _stage FROM STDIN") as copia:
                pendentes, futuros = iter(tarefas), set()
                try:
                    while True:
                        while len(futuros) < paralelo * 2:
                            t = next(pendentes, None)
                            if t is None:
                                break
                            futuros.add(pool.submit(pagina, uf, *t))
                        if not futuros:
                            break
                        prontos, futuros = wait(futuros, return_when=FIRST_COMPLETED)
                        for f in prontos:
                            for ln in f.result():        # propaga o erro da pagina: aborta a UF
                                copia.write_row(ln)
                                lidos += 1
                            feitas += 1
                            if feitas % max(1, len(tarefas) // 10) == 0:
                                log(f"  {feitas}/{len(tarefas)} paginas, {lidos:,} imoveis ({time.time() - t0:.0f} s)".replace(",", "."))
                except BaseException:
                    for f in futuros:
                        f.cancel()
                    raise
    log(f"  baixados {lidos:,} imoveis em {time.time() - t0:.0f} s ({lidos / max(1, time.time() - t0):.0f}/s)".replace(",", "."))
    return anunciado, lidos, esperado, len(fatias)


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="SICAR (WFS publico do CAR) -> tabela de imoveis, por UF")
    ap.add_argument("--ufs", required=True, help="siglas separadas por virgula (obrigatorio: nunca roda o Brasil por padrao)")
    ap.add_argument("--tabela", default="vetorial.sicar_imoveis", help="schema.tabela de destino")
    ap.add_argument("--paralelo", type=int, default=CFG["paralelo_padrao"])
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--simular", action="store_true")
    args = ap.parse_args()
    ufs = [u.strip().upper() for u in args.ufs.split(",")]
    if [u for u in ufs if u not in UFS]:
        raise SystemExit(f"UFs desconhecidas: {[u for u in ufs if u not in UFS]}")
    if not re.fullmatch(r"[a-z_]+\.[a-z_]+", args.tabela):
        raise SystemExit("--tabela deve ser schema.tabela em minusculas")
    if not 1 <= args.paralelo <= CFG["paralelo_maximo"]:
        raise SystemExit(f"--paralelo deve ficar entre 1 e {CFG['paralelo_maximo']}")
    T = args.tabela

    conn = db.conectar()
    fonte = db.id_fonte(conn, CFG["fonte"])
    with conn.cursor() as cur:
        cur.execute("SELECT sigla_uf, id_estado FROM dim.estados")
        id_estado = dict(cur.fetchall())
    hoje, agora = date.today(), datetime.now(timezone.utc)
    with Carga(conn, "sicar_wfs", dataset=T, parametros=vars(args), simular=args.simular) as carga:
        t_total = time.time()
        for uf in ufs:
            with conn.cursor() as cur:
                cur.execute("SELECT id_municipio FROM dim.municipios WHERE id_estado = %s ORDER BY 1", (id_estado[uf],))
                municipios = [r[0] for r in cur.fetchall()]
            anunciado, lidos, esperado, n_fatias = coletar_uf(conn, uf, args.paralelo, municipios)
            carga.lidas += lidos
            if lidos < anunciado * (1 - CFG["tolerancia_coleta"]) or lidos < esperado * (1 - CFG["tolerancia_coleta"]):
                raise RuntimeError(f"{uf}: coleta incompleta ({lidos} lidos, {anunciado} anunciados, {esperado} nas fatias): UF NAO gravada")
            with conn.cursor() as cur:
                cur.execute("SELECT count(*), count(DISTINCT cod_imovel), count(*) FILTER (WHERE geom_anomala), "
                            "count(*) FILTER (WHERE cod_estado <> %s), count(*) FILTER (WHERE cod_municipio_ibge IS NOT NULL AND NOT EXISTS "
                            "(SELECT 1 FROM dim.municipios m WHERE m.id_municipio = cod_municipio_ibge)) FROM _stage", (uf,))
                n, distintos, anomalas, uf_outra, mun_fora = cur.fetchone()
                n_dup = n - distintos
                if n_dup:
                    # O CAR entrega o mesmo cod_imovel em 2 feicoes enquanto uma retificacao esta em andamento. Fica a de maior
                    # data_atualizacao (nula = a menor), empate pelo maior identificador; a descartada e registrada.
                    cur.execute("ALTER TABLE _stage ADD COLUMN fid_num bigint")
                    cur.execute("UPDATE _stage SET fid_num = substring(fid_wfs from '[0-9]+$')::bigint")
                    cur.execute("""CREATE TEMP TABLE _rank ON COMMIT DROP AS
                        SELECT fid_wfs, cod_imovel, ind_status, des_condic, dat_criacao, dat_atualizacao,
                               row_number() OVER (PARTITION BY cod_imovel ORDER BY dat_atualizacao DESC NULLS LAST, fid_num DESC) AS rn,
                               count(*) OVER (PARTITION BY cod_imovel) AS qtd
                        FROM _stage""")
                    cur.execute("""INSERT INTO catalogo.coletas_duplicados (dataset, recorte, cod_imovel, fid_mantido, fid_descartado,
                                     status_mantido, status_descartado, condicao_mantida, condicao_descartada, dat_criacao_mantida,
                                     dat_criacao_descartada, dat_atualizacao_mantida, dat_atualizacao_descartada, regra, id_carga)
                                   SELECT %s, %s, d.cod_imovel, k.fid_wfs, d.fid_wfs, k.ind_status, d.ind_status, k.des_condic, d.des_condic,
                                          k.dat_criacao, d.dat_criacao, k.dat_atualizacao, d.dat_atualizacao,
                                          'maior data_atualizacao (nula = menor); empate: maior identificador', %s
                                   FROM _rank d JOIN _rank k ON k.cod_imovel = d.cod_imovel AND k.rn = 1
                                   WHERE d.rn > 1""", (T, uf, carga.id))
                    cur.execute("DELETE FROM _stage s USING _rank r WHERE r.fid_wfs = s.fid_wfs AND r.rn > 1")
                    log(f"  {uf}: {n_dup} cod_imovel repetido(s) no WFS (retificacao em andamento): mantida a feicao de maior data_atualizacao, "
                        f"descartadas registradas em catalogo.coletas_duplicados")
                    carga.avisos.append(f"{uf}: {n_dup} feicao(oes) descartada(s) por cod_imovel repetido no WFS (ver catalogo.coletas_duplicados)")
                    cur.execute("SELECT count(*) FROM _stage")
                    n = cur.fetchone()[0]
                if uf_outra:
                    carga.avisos.append(f"{uf}: {uf_outra} imoveis com 'uf' diferente da camada")
                if mun_fora:
                    carga.avisos.append(f"{uf}: {mun_fora} imoveis com cod_municipio_ibge fora de dim.municipios (id_municipio NULL)")
                cur.execute("CREATE INDEX ON _stage (cod_imovel)")
                cur.execute("ALTER TABLE _stage ADD COLUMN id_municipio integer, ADD COLUMN id_estado smallint")
                cur.execute("UPDATE _stage s SET id_municipio = m.id_municipio FROM dim.municipios m WHERE m.id_municipio = s.cod_municipio_ibge")
                cur.execute("UPDATE _stage s SET id_estado = e.id_estado FROM dim.estados e WHERE e.sigla_uf = s.cod_estado")
                cur.execute("ANALYZE _stage")

                # ---- diferencas contra as versoes vigentes ----
                cur.execute(f"""CREATE TEMP TABLE _alt ON COMMIT DROP AS
                    SELECT c.id AS id_antigo, s.cod_imovel
                    FROM _stage s JOIN {T} c ON c.cod_imovel = s.cod_imovel AND c.vigente_ate IS NULL
                    WHERE c.ind_status IS DISTINCT FROM s.ind_status OR c.dat_criacao IS DISTINCT FROM s.dat_criacao
                       OR c.dat_atualizacao IS DISTINCT FROM s.dat_atualizacao OR c.num_area IS DISTINCT FROM s.num_area
                       OR c.des_condic IS DISTINCT FROM s.des_condic OR c.cod_estado IS DISTINCT FROM s.cod_estado
                       OR c.municipio IS DISTINCT FROM s.municipio OR c.id_municipio IS DISTINCT FROM s.id_municipio
                       OR c.mod_fiscal IS DISTINCT FROM s.mod_fiscal OR c.ind_tipo IS DISTINCT FROM s.ind_tipo
                       OR c.geom_anomala IS DISTINCT FROM s.geom_anomala OR c.geom_origem_texto IS DISTINCT FROM s.geom_origem_texto
                       OR ((c.geom IS NULL) <> (s.geom IS NULL))
                       OR (c.geom IS NOT NULL AND s.geom IS NOT NULL AND NOT ST_OrderingEquals(c.geom, s.geom))""")
                cur.execute(f"CREATE TEMP TABLE _aus ON COMMIT DROP AS SELECT c.id AS id_antigo FROM {T} c WHERE c.cod_estado = %s "
                            f"AND c.vigente_ate IS NULL AND NOT EXISTS (SELECT 1 FROM _stage s WHERE s.cod_imovel = c.cod_imovel)", (uf,))
                cur.execute(f"SELECT count(*) FROM {T} WHERE cod_estado = %s AND vigente_ate IS NULL", (uf,))
                vigentes_antes = cur.fetchone()[0]
                cur.execute("SELECT (SELECT count(*) FROM _alt), (SELECT count(*) FROM _aus)")
                n_alt, n_aus = cur.fetchone()
                cur.execute(f"SELECT count(*) FROM _stage s WHERE NOT EXISTS (SELECT 1 FROM {T} c WHERE c.cod_imovel = s.cod_imovel AND c.vigente_ate IS NULL)")
                n_novos = cur.fetchone()[0]
                # imovel que sumiu do WFS e voltou IDENTICO a ultima versao fechada: reabre a versao (mesmo id), nao cria outra
                cur.execute(f"""CREATE TEMP TABLE _reab ON COMMIT DROP AS
                    WITH ult AS (SELECT DISTINCT ON (c.cod_imovel) c.* FROM {T} c WHERE c.cod_estado = %s AND c.vigente_ate IS NOT NULL
                                 AND c.cod_imovel IN (SELECT cod_imovel FROM _stage) ORDER BY c.cod_imovel, c.vigente_ate DESC, c.id DESC)
                    SELECT c.id AS id_antigo FROM _stage s JOIN ult c ON c.cod_imovel = s.cod_imovel
                    WHERE NOT EXISTS (SELECT 1 FROM {T} v WHERE v.cod_imovel = s.cod_imovel AND v.vigente_ate IS NULL)
                      AND NOT (c.ind_status IS DISTINCT FROM s.ind_status OR c.dat_criacao IS DISTINCT FROM s.dat_criacao
                       OR c.dat_atualizacao IS DISTINCT FROM s.dat_atualizacao OR c.num_area IS DISTINCT FROM s.num_area
                       OR c.des_condic IS DISTINCT FROM s.des_condic OR c.cod_estado IS DISTINCT FROM s.cod_estado
                       OR c.municipio IS DISTINCT FROM s.municipio OR c.id_municipio IS DISTINCT FROM s.id_municipio
                       OR c.mod_fiscal IS DISTINCT FROM s.mod_fiscal OR c.ind_tipo IS DISTINCT FROM s.ind_tipo
                       OR c.geom_anomala IS DISTINCT FROM s.geom_anomala OR c.geom_origem_texto IS DISTINCT FROM s.geom_origem_texto
                       OR ((c.geom IS NULL) <> (s.geom IS NULL))
                       OR (c.geom IS NOT NULL AND s.geom IS NOT NULL AND NOT ST_OrderingEquals(c.geom, s.geom)))""", (uf,))
                cur.execute("SELECT count(*) FROM _reab")
                n_reab = cur.fetchone()[0]
                inalterados = n - n_novos - n_alt                # n = feicoes unicas apos tratar os repetidos
                log(f"  {uf}: vigentes no banco {vigentes_antes:,} | NOVOS {n_novos - n_reab:,} | REABERTOS {n_reab:,} | ALTERADOS {n_alt:,} | "
                    f"AUSENTES do WFS {n_aus:,} | inalterados {inalterados:,} | geometrias anomalas {anomalas}".replace(",", "."))
                if vigentes_antes and n_aus > vigentes_antes * CFG["max_queda"] and not args.aceitar_queda:
                    raise RuntimeError(f"{uf}: {n_aus} ausentes = mais de {CFG['max_queda']:.0%} da UF: UF NAO gravada (confira; --aceitar-queda libera)")
                if anomalas:
                    carga.avisos.append(f"{uf}: {anomalas} geometria(s) anomala(s) (fora do Brasil ou ausentes na origem), guardadas como texto")

                if args.simular:
                    conn.rollback()
                    log(f"  {uf}: SIMULACAO, nada gravado.")
                    continue
                # ---- gravacao (uma transacao por UF) ----
                cur.execute(f"UPDATE {T} SET vigente_ate = %s WHERE id IN (SELECT id_antigo FROM _alt UNION SELECT id_antigo FROM _aus)", (hoje,))
                cur.execute(f"UPDATE {T} SET vigente_ate = NULL, reaberto_em = %s WHERE id IN (SELECT id_antigo FROM _reab)", (hoje,))
                cur.execute(f"""INSERT INTO {T} (fid_wfs, cod_imovel, cod_estado, id_estado, municipio, id_municipio, des_condic, ind_status, num_area,
                                dat_criacao, dat_atualizacao, mod_fiscal, ind_tipo, geom, geom_anomala, geom_origem_texto, id_fonte,
                                importado_em, vigente_desde, coletado_em)
                               SELECT s.fid_wfs, s.cod_imovel, s.cod_estado, s.id_estado, s.municipio, s.id_municipio, s.des_condic, s.ind_status, s.num_area,
                                s.dat_criacao, s.dat_atualizacao, s.mod_fiscal, s.ind_tipo, s.geom, s.geom_anomala, s.geom_origem_texto, %s, %s, %s, %s
                               FROM _stage s WHERE NOT EXISTS (SELECT 1 FROM {T} c WHERE c.cod_imovel = s.cod_imovel AND c.vigente_ate IS NULL)""",
                            (fonte, hoje, hoje, agora))
                inseridos = cur.rowcount
                if inseridos != n_novos - n_reab + n_alt:
                    raise RuntimeError(f"{uf}: inseridas {inseridos} != novas {n_novos - n_reab} + alteradas {n_alt}: UF NAO gravada")
                cur.execute("""INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas,
                               fechados, inalterados, id_carga, observacao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (T, uf, CFG["fonte_descricao"], CFG["url_wfs"],
                             f"reconciliacao da UF por {n_fatias} fatias de municipio, {args.paralelo} agentes", anunciado, lidos,
                             n_novos - n_reab, n_alt, n_aus, inalterados, carga.id, f"{anomalas} geometria(s) anomala(s)" if anomalas else None, n_reab))
                conn.commit()
                carga.inseridas += inseridos
                carga.atualizadas += n_alt
                log(f"  {uf}: GRAVADO ({inseridos:,} linhas inseridas, {n_reab:,} versoes reabertas, {n_alt:,} versoes fechadas por mudanca, "
                    f"{n_aus:,} por ausencia)".replace(",", "."))
        log(f"== fim: {carga.lidas:,} imoveis lidos em {(time.time() - t_total) / 60:.1f} min".replace(",", "."))
        if args.simular:
            conn.rollback()
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
