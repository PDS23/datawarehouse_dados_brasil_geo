"""PRODES (desmatamento anual por bioma, INPE/TerraBrasilis) -> vetorial.prodes_desmatamento, como ESPELHO VERSIONADO.

Descobre a edicao mais recente de cada bioma no catalogo do TerraBrasilis, baixa os GeoPackages (varios ao mesmo tempo,
retomavel) e reconcilia cada bioma com o banco, igual ao SICAR: feicao nova entra; feicao alterada fecha a versao antiga e
insere a nova; feicao que o INPE retirou tem a versao fechada (nada e apagado: vigente = vigente_ate IS NULL). Bioma cuja
edicao ja foi carregada e pulado. Os biomas sao carregados em processos paralelos, cada um com a sua conexao.

Uso (no conteiner etl, a partir de infra/):
  docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl prodes/desmatamento/scripts/prodes_desmatamento.py [opcoes]

  OPCOES: --biomas pantanal,pampa (padrao: os 6) | --paralelo N (padrao 3, max 4) | --versao AAAAMMDD (padrao: a mais recente)
          --verificar (compara a fonte com o banco e com o bruto/, sem baixar nem gravar) | --so-baixar | --sem-baixar
          --forcar (reconcilia mesmo se a edicao ja foi carregada) | --aceitar-queda | --simular (nada e gravado)
          --destino SCHEMA.TABELA (padrao: o do config.yaml; a tabela precisa existir: sql/01_tabela.sql)

Regras (ver config.yaml e LEIAME_prodes_desmatamento.md):
  - chave = (bioma, uuid): o mesmo uuid pode estar nos arquivos de dois biomas (poligonos de divisa) e fica nos dois;
    uuid repetido entre camadas do mesmo bioma: vale a primeira camada do config (aviso);
  - geometria ausente ou com a caixa fora do Brasil: a feicao ENTRA com geom NULL, geom_anomala e o EWKT original em texto;
  - `state` entra como o INPE entrega (texto inteiro); id_estado vem dele (sigla ou nome do estado);
  - mais de max_queda das feicoes vigentes ausentes na edicao: o bioma NAO e gravado (--aceitar-queda libera).
"""
import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import yaml
from psycopg import sql

from dwlib import db, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # prodes/desmatamento
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
BRUTO = RAIZ / "bruto"
CHUNK = 8 * 1024 * 1024
INTEIROS = {"julian_day", "scene_id", "year"}
COLUNAS_FONTE = ["state", "path_row", "main_class", "class_name", "def_cloud", "julian_day", "image_date", "year",
                 "area_km", "scene_id", "source", "satellite", "sensor", "uuid"]
# colunas da fonte que, se mudarem, geram uma versao nova (alem da geometria)
COMPARAR = [c for c in COLUNAS_FONTE if c != "uuid"] + ["camada_origem", "geom_anomala", "geom_origem_texto"]


def log(*a):
    print(*a, flush=True)


def sem_acento(txt):
    return "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn").upper().strip()


# ---------------------------------------------------------------- catalogo e download

def catalogo_links(sessao):
    """Todos os links de download publicados no TerraBrasilis (a pagina de downloads e montada a partir deste JSON)."""
    r = sessao.get(CFG["url_base"] + CFG["url_catalogo"], timeout=60)
    r.raise_for_status()
    return [item["link"] for item in r.json() if item.get("link")]


def resolver(links, bioma, cfg_b, versao=None):
    """(versao, link) do GeoPackage do bioma no catalogo: a mais recente, ou a `versao` pedida (AAAAMMDD)."""
    padrao = re.compile(re.escape(f"/download/dataset/{cfg_b['dataset']}/vector/") + cfg_b["padrao"] + "$")
    achados = {m.group(1): link for link in links if (m := padrao.search(link))}
    if not achados:
        raise RuntimeError(f"{bioma}: nenhum arquivo no catalogo casa com {cfg_b['padrao']} (o INPE mudou a publicacao?)")
    if versao:
        if versao not in achados:
            raise RuntimeError(f"{bioma}: versao {versao} nao esta no catalogo; disponiveis: {sorted(achados)}")
        return versao, achados[versao]
    v = max(achados)
    return v, achados[v]


def manifesto_de(pasta):
    f = pasta / "manifesto.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def baixar(bioma, link, verificar=False):
    """Garante o GeoPackage do bioma em bruto/<bioma>/ (roda numa thread: sessao propria). Retorna o caminho."""
    sessao = http.sessao()
    url = CFG["url_base"] + link
    nome_zip = url.rsplit("/", 1)[1]
    pasta = BRUTO / bioma
    r = sessao.head(url, timeout=60, allow_redirects=True)
    r.raise_for_status()
    esperado = int(r.headers["Content-Length"])
    man = manifesto_de(pasta)
    gpkg = pasta / nome_zip.removesuffix(".zip")
    if man and man.get("arquivo_zip") == nome_zip and man.get("bytes_zip") == esperado and gpkg.exists():
        log(f"  [{bioma}] bruto ja confere com a fonte ({nome_zip})")
        return gpkg
    if verificar:
        log(f"  [{bioma}] NAO baixado ou diferente (fonte: {nome_zip}, {esperado / 1e6:.0f} MB)")
        return None
    pasta.mkdir(parents=True, exist_ok=True)
    zip_path = pasta / nome_zip
    parcial = pasta / (nome_zip + ".parte")
    baixado = parcial.stat().st_size if parcial.exists() else 0
    log(f"  [{bioma}] baixando {nome_zip} ({esperado / 1e6:.0f} MB; ja tinha {baixado / 1e6:.0f} MB)")
    t0, falhas = time.time(), 0
    while baixado < esperado:
        try:
            with sessao.get(url, headers={"Range": f"bytes={baixado}-"}, stream=True, timeout=(30, 120)) as resp:
                if resp.status_code not in (200, 206):
                    raise RuntimeError(f"{url}: HTTP {resp.status_code}")
                if resp.status_code == 200 and baixado:          # servidor ignorou o Range: recomeca do zero
                    baixado = 0
                    parcial.unlink(missing_ok=True)
                with open(parcial, "ab") as f:
                    for pedaco in resp.iter_content(CHUNK):
                        f.write(pedaco)
                        baixado += len(pedaco)
        except (requests.RequestException, OSError) as e:        # queda de conexao: retoma de onde parou
            falhas += 1
            if falhas > 8:
                raise
            log(f"  [{bioma}] conexao caiu em {baixado / 1e6:.0f} MB ({type(e).__name__}); retomando ({falhas}/8)")
            time.sleep(5 * falhas)
            baixado = parcial.stat().st_size if parcial.exists() else 0
    if parcial.stat().st_size != esperado:
        raise RuntimeError(f"{bioma}: tamanho final nao bate: {parcial.stat().st_size} != {esperado}")
    parcial.replace(zip_path)
    sha = hashlib.sha256()
    with open(zip_path, "rb") as f:
        while bloco := f.read(CHUNK):
            sha.update(bloco)
    with zipfile.ZipFile(zip_path) as z:
        gpkgs = [n for n in z.namelist() if n.lower().endswith(".gpkg")]
        if len(gpkgs) != 1:
            raise RuntimeError(f"esperava 1 .gpkg em {nome_zip}, achei {gpkgs}")
        z.extract(gpkgs[0], pasta)
    (pasta / "manifesto.json").write_text(json.dumps({
        "arquivo_zip": nome_zip, "arquivo_gpkg": gpkg.name, "fonte": url, "bytes_zip": esperado, "sha256_zip": sha.hexdigest(),
        "baixado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    zip_path.unlink()                                    # o GeoPackage extraido e o bruto; o sha256 do zip fica no manifesto
    log(f"  [{bioma}] baixado em {time.time() - t0:.0f} s")
    return gpkg


# ---------------------------------------------------------------- carga de um bioma (roda num processo proprio)

def valor(v):
    """Valor de pyogrio -> Python simples (NaN/None -> None, numpy -> nativo, datas -> date)."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, datetime):
        return v.date()
    return v


def carregar_bioma(p):
    """Le o GeoPackage, reconcilia com a tabela e grava (uma transacao). Retorna um dicionario com o resultado."""
    from pyogrio import read_info
    from pyogrio.raw import read
    bioma, gpkg, edicao, T = p["bioma"], p["gpkg"], p["edicao"], p["destino"]
    cfg_b = CFG["biomas"][bioma]
    srid, cx = CFG["srid_gravado"], CFG["caixa_brasil"]
    caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {srid})"
    t0 = time.time()
    avisos = []
    conn = db.conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
            cur.execute("SELECT id_estado, sigla_uf, nome_uf FROM dim.estados")
            estados = {}
            for ide, sigla, nome in cur.fetchall():
                estados[sem_acento(sigla)] = ide
                estados[sem_acento(nome)] = ide
            cur.execute("CREATE TEMP TABLE _stage (state text, path_row text, main_class text, class_name text, def_cloud double precision, "
                        "julian_day integer, image_date date, year integer, area_km double precision, scene_id integer, source text, "
                        "satellite text, sensor text, uuid text, camada_origem text, prio smallint, id_estado smallint, geom geometry, "
                        "geom_anomala boolean DEFAULT false, geom_origem_texto text)")
            lidas, sem_estado = 0, 0
            for prio, camada in enumerate(cfg_b["camadas"]):
                total = read_info(gpkg, layer=camada)["features"]
                for ini in range(0, total, CFG["por_lote"]):
                    meta, _, geoms, campos = read(gpkg, layer=camada, skip_features=ini, max_features=CFG["por_lote"])
                    idx = {str(n): i for i, n in enumerate(meta["fields"])}
                    faltam = [c for c in COLUNAS_FONTE if c not in idx]
                    if faltam:
                        raise RuntimeError(f"{bioma}/{camada}: colunas esperadas ausentes no GeoPackage: {faltam}")
                    with cur.copy("COPY _stage (state, path_row, main_class, class_name, def_cloud, julian_day, image_date, year, area_km, "
                                  "scene_id, source, satellite, sensor, uuid, camada_origem, prio, id_estado, geom) FROM STDIN") as cp:
                        for i in range(len(geoms)):
                            linha = [valor(campos[idx[c]][i]) for c in COLUNAS_FONTE]
                            for k, c in enumerate(COLUNAS_FONTE):   # a fonte as vezes entrega inteiros como decimal (205.0)
                                if c in INTEIROS and linha[k] is not None:
                                    linha[k] = int(linha[k])
                            ide = estados.get(sem_acento(linha[0])) if linha[0] else None
                            if ide is None:
                                sem_estado += 1
                            wkb = geoms[i]
                            cp.write_row(linha + [camada, prio, ide, bytes(wkb).hex() if wkb is not None else None])
                    lidas += len(geoms)
                    if (ini // CFG["por_lote"]) % 10 == 9:
                        log(f"  [{bioma}] {camada}: {min(ini + CFG['por_lote'], total):,}/{total:,}".replace(",", "."))
            log(f"  [{bioma}] lidas {lidas:,} feicoes em {time.time() - t0:.0f} s; conferindo".replace(",", "."))

            # geometria: SRID, anomalas (sem geometria ou caixa fora do Brasil) viram texto, o resto vira MultiPolygon
            cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(geom, {srid}) WHERE geom IS NOT NULL")
            cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = CASE WHEN geom IS NULL THEN NULL ELSE ST_AsEWKT(geom) END, "
                        f"geom = NULL WHERE geom IS NULL OR NOT (geom @ {caixa})")
            anomalas = cur.rowcount
            cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {srid}) USING ST_Multi(geom)")
            if anomalas:
                avisos.append(f"{bioma}: {anomalas} feicao(oes) com geometria anomala (fora do Brasil ou ausente), gravadas com geom NULL e o texto original")
            # uuid repetido entre camadas: vale a primeira camada
            cur.execute("DELETE FROM _stage s USING (SELECT ctid AS c, row_number() OVER (PARTITION BY uuid ORDER BY prio) AS rn FROM _stage) r "
                        "WHERE s.ctid = r.c AND r.rn > 1")
            repetidas = cur.rowcount
            if repetidas:
                avisos.append(f"{bioma}: {repetidas} feicao(oes) com uuid repetido entre camadas (vale a primeira camada)")
            if sem_estado:
                avisos.append(f"{bioma}: {sem_estado} feicao(oes) com state que nao casa com dim.estados (id_estado NULL)")
            cur.execute("CREATE UNIQUE INDEX ON _stage (uuid)")
            cur.execute("ANALYZE _stage")
            cur.execute("SELECT count(*) FROM _stage")
            n = cur.fetchone()[0]

            # diferencas contra as versoes vigentes do bioma
            comp = " OR ".join(f"c.{c} IS DISTINCT FROM s.{c}" for c in COMPARAR)
            cur.execute(f"""CREATE TEMP TABLE _alt AS SELECT c.id AS id_antigo FROM _stage s JOIN {T} c
                            ON c.uuid = s.uuid AND c.vigente_ate IS NULL AND c.bioma = %s
                            WHERE {comp} OR ((c.geom IS NULL) <> (s.geom IS NULL))
                               OR (c.geom IS NOT NULL AND s.geom IS NOT NULL AND NOT ST_OrderingEquals(c.geom, s.geom))""", (bioma,))
            cur.execute(f"CREATE TEMP TABLE _aus AS SELECT c.id AS id_antigo FROM {T} c WHERE c.bioma = %s AND c.vigente_ate IS NULL "
                        f"AND NOT EXISTS (SELECT 1 FROM _stage s WHERE s.uuid = c.uuid)", (bioma,))
            cur.execute(f"SELECT count(*) FROM {T} WHERE bioma = %s AND vigente_ate IS NULL", (bioma,))
            vigentes_antes = cur.fetchone()[0]
            cur.execute("SELECT (SELECT count(*) FROM _alt), (SELECT count(*) FROM _aus)")
            n_alt, n_aus = cur.fetchone()
            cur.execute(f"SELECT count(*) FROM _stage s WHERE NOT EXISTS (SELECT 1 FROM {T} c WHERE c.uuid = s.uuid AND c.vigente_ate IS NULL AND c.bioma = %s)", (bioma,))
            n_novos = cur.fetchone()[0]
            # feicao que o INPE retirou e republicou IDENTICA a ultima versao fechada: reabre a versao (mesmo id), nao cria outra
            idem = " AND ".join(f"NOT (c.{c} IS DISTINCT FROM s.{c})" for c in COMPARAR)
            idem += " AND ((c.geom IS NULL) = (s.geom IS NULL)) AND (c.geom IS NULL OR ST_OrderingEquals(c.geom, s.geom))"
            cur.execute(f"""CREATE TEMP TABLE _reab AS
                WITH ult AS (SELECT DISTINCT ON (c.uuid) c.* FROM {T} c WHERE c.bioma = %s AND c.vigente_ate IS NOT NULL
                             AND c.uuid IN (SELECT uuid FROM _stage) ORDER BY c.uuid, c.vigente_ate DESC, c.id DESC)
                SELECT c.id AS id_antigo FROM _stage s JOIN ult c ON c.uuid = s.uuid
                WHERE NOT EXISTS (SELECT 1 FROM {T} v WHERE v.uuid = s.uuid AND v.bioma = %s AND v.vigente_ate IS NULL) AND {idem}""",
                        (bioma, bioma))
            cur.execute("SELECT count(*) FROM _reab")
            n_reab = cur.fetchone()[0]
            inalterados = n - n_novos - n_alt
            log(f"  [{bioma}] vigentes no banco {vigentes_antes:,} | NOVOS {n_novos - n_reab:,} | REABERTOS {n_reab:,} | ALTERADOS {n_alt:,} | "
                f"AUSENTES da fonte {n_aus:,} | inalterados {inalterados:,}".replace(",", "."))
            if vigentes_antes and n_aus > vigentes_antes * CFG["max_queda"] and not p["aceitar_queda"]:
                raise RuntimeError(f"{bioma}: {n_aus} ausentes = mais de {CFG['max_queda']:.0%} do bioma: NAO gravado (confira; --aceitar-queda libera)")

            res = {"bioma": bioma, "edicao": edicao, "lidas": lidas, "validas": n, "novos": n_novos - n_reab, "alterados": n_alt, "ausentes": n_aus,
                   "reabertos": n_reab, "inalterados": inalterados, "vigentes_antes": vigentes_antes, "avisos": avisos, "pulado": False}
            if p["simular"]:
                conn.rollback()
                res["segundos"] = time.time() - t0
                return res
            hoje = date.today()
            cur.execute(f"UPDATE {T} SET vigente_ate = %s WHERE id IN (SELECT id_antigo FROM _alt UNION SELECT id_antigo FROM _aus)", (hoje,))
            cur.execute(f"UPDATE {T} SET vigente_ate = NULL, reaberto_em = %s WHERE id IN (SELECT id_antigo FROM _reab)", (hoje,))
            cur.execute(f"""INSERT INTO {T} (uuid, bioma, camada_origem, id_bioma, state, id_estado, path_row, main_class, class_name, def_cloud,
                                julian_day, image_date, year, area_km, scene_id, source, satellite, sensor, geom, geom_anomala, geom_origem_texto,
                                id_fonte, importado_em, vigente_desde, coletado_em, edicao)
                            SELECT s.uuid, %s, s.camada_origem, %s, s.state, s.id_estado, s.path_row, s.main_class, s.class_name, s.def_cloud,
                                s.julian_day, s.image_date, s.year, s.area_km, s.scene_id, s.source, s.satellite, s.sensor, s.geom, s.geom_anomala,
                                s.geom_origem_texto, %s, %s, %s, now(), %s
                            FROM _stage s WHERE NOT EXISTS (SELECT 1 FROM {T} c WHERE c.uuid = s.uuid AND c.bioma = %s AND c.vigente_ate IS NULL)""",
                        (bioma, cfg_b["id_bioma"], p["fonte"], hoje, hoje, edicao, bioma))
            inseridas = cur.rowcount
            if inseridas != n_novos - n_reab + n_alt:
                raise RuntimeError(f"{bioma}: inseridas {inseridas} != novas {n_novos - n_reab} + alteradas {n_alt}: transacao desfeita")
            cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, "
                        "fechados, inalterados, id_carga, observacao, edicao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (T, bioma, CFG["fonte"], p["url"], "reconciliacao por bioma (GeoPackage do INPE)", lidas, n, n_novos - n_reab, n_alt, n_aus,
                         inalterados, p["id_carga"], "; ".join(avisos) or None, edicao, n_reab))
        conn.commit()
        res["segundos"] = time.time() - t0
        return res
    finally:
        conn.close()


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="PRODES (INPE/TerraBrasilis) -> espelho versionado de vetorial.prodes_desmatamento")
    ap.add_argument("--biomas", help="chaves do config.yaml separadas por virgula (padrao: todos)")
    ap.add_argument("--paralelo", type=int, default=CFG["paralelo_padrao"])
    ap.add_argument("--versao", help="versao AAAAMMDD do arquivo (padrao: a mais recente do catalogo)")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--so-baixar", action="store_true")
    ap.add_argument("--sem-baixar", action="store_true")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    biomas = [b.strip() for b in args.biomas.split(",")] if args.biomas else list(CFG["biomas"])
    desconhecidos = [b for b in biomas if b not in CFG["biomas"]]
    if desconhecidos:
        raise SystemExit(f"biomas desconhecidos: {desconhecidos}; validos: {list(CFG['biomas'])}")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    if not 1 <= args.paralelo <= CFG["paralelo_maximo"]:
        raise SystemExit(f"--paralelo deve ficar entre 1 e {CFG['paralelo_maximo']}")
    T = args.destino

    sessao = http.sessao()
    links = catalogo_links(sessao)
    edicoes = {b: resolver(links, b, CFG["biomas"][b], args.versao) for b in biomas}

    conn = db.conectar()
    fonte = db.id_fonte(conn, CFG["fonte"])
    ultima = {}
    with conn.cursor() as cur:
        for b in biomas:
            cur.execute("SELECT edicao FROM catalogo.coletas WHERE dataset = %s AND recorte = %s AND edicao IS NOT NULL "
                        "ORDER BY coletado_em DESC LIMIT 1", (T, b))
            r = cur.fetchone()
            ultima[b] = r[0] if r else None
    conn.rollback()

    log(f"== fonte x banco ({T})")
    a_fazer = []
    for b in biomas:
        v, link = edicoes[b]
        estado = "ja carregada" if ultima[b] == v else ("NOVA" if ultima[b] else "nunca carregada")
        log(f"  {b:15s} fonte v{v} | banco {('v' + ultima[b]) if ultima[b] else '-':>10s} | {estado}")
        if ultima[b] != v or args.forcar:
            a_fazer.append(b)
    if args.verificar or not a_fazer:
        if not a_fazer:
            log("nada a fazer: todos os biomas pedidos estao na edicao mais recente (--forcar reconcilia mesmo assim)")
        if args.verificar:
            for b in biomas:
                baixar(b, edicoes[b][1], verificar=True)
        conn.close()
        return 0

    gpkgs, falhas_download = {}, {}
    if args.sem_baixar:
        for b in a_fazer:
            man = manifesto_de(BRUTO / b)
            if not man:
                raise SystemExit(f"{b}: sem bruto/ (rode sem --sem-baixar)")
            gpkgs[b] = BRUTO / b / man["arquivo_gpkg"]
    else:
        log(f"== download ({len(a_fazer)} bioma(s), {args.paralelo} ao mesmo tempo)")
        with ThreadPoolExecutor(max_workers=args.paralelo) as pool:
            futuros = {pool.submit(baixar, b, edicoes[b][1]): b for b in a_fazer}
            for f in as_completed(futuros):
                try:
                    gpkgs[futuros[f]] = f.result()
                except Exception as e:                           # um bioma que nao baixa nao derruba os outros
                    falhas_download[futuros[f]] = f"{type(e).__name__}: {e}"[:300]
                    log(f"  [{futuros[f]}] DOWNLOAD FALHOU: {falhas_download[futuros[f]]}")
        a_fazer = [b for b in a_fazer if b in gpkgs]
    if args.so_baixar:
        conn.close()
        return 3 if falhas_download else 0

    com_carga = Carga(conn, "prodes_desmatamento", dataset=T, parametros=vars(args), simular=args.simular)
    falhas = dict(falhas_download)
    with com_carga as carga:
        t0 = time.time()
        log(f"== carga em {T} ({len(a_fazer)} bioma(s), {args.paralelo} processos)")
        a_fazer.sort(key=lambda b: -gpkgs[b].stat().st_size)         # os maiores primeiro: equilibra os processos
        pedidos = [{"bioma": b, "gpkg": str(gpkgs[b]), "edicao": edicoes[b][0], "destino": T, "fonte": fonte,
                    "url": CFG["url_base"] + edicoes[b][1], "id_carga": carga.id, "simular": args.simular,
                    "aceitar_queda": args.aceitar_queda} for b in a_fazer]
        resultados = []
        with ProcessPoolExecutor(max_workers=args.paralelo) as pool:
            futuros = {pool.submit(carregar_bioma, p): p["bioma"] for p in pedidos}
            for f in as_completed(futuros):
                b = futuros[f]
                try:
                    r = f.result()
                except Exception as e:
                    falhas[b] = f"{type(e).__name__}: {e}"[:300]
                    log(f"  [{b}] FALHOU: {falhas[b]}")
                    continue
                resultados.append(r)
                carga.lidas += r["lidas"]
                carga.inseridas += r["novos"] + r["alterados"]
                carga.atualizadas += r["ausentes"]               # versoes fechadas por ausencia
                carga.avisos += r["avisos"]
                log(f"  [{b}] ok em {r['segundos']:.0f} s: {r['novos']} novos, {r['reabertos']} reabertos, {r['alterados']} versoes novas, {r['ausentes']} fechadas, "
                    f"{r['inalterados']} inalterados" + (" (SIMULACAO)" if args.simular else ""))
        for b, m in falhas.items():
            carga.avisos.append(f"{b} NAO carregado: {m}")
        if not args.simular and not falhas and args.destino == CFG["destino_padrao"]:
            with conn.cursor() as cur:
                cur.execute(f"SELECT max(year) FROM {T} WHERE vigente_ate IS NULL")
                ano = cur.fetchone()[0]
            registrar_dataset(conn, "PRODES - Desmatamento anual por bioma (INPE/TerraBrasilis)", T, fonte, ano_referencia=ano,
                              licenca=CFG["licenca"], tipo="vetor",
                              observacoes="Espelho versionado do INPE (yearly_deforestation por bioma; Amazonia tambem a nao-floresta). Vigente = vigente_ate IS NULL. "
                                          "Ver prodes/desmatamento/LEIAME_prodes_desmatamento.md.")
            conn.commit()
        log(f"== fim: {carga.lidas} lidas; {carga.inseridas} versoes inseridas; {carga.atualizadas} fechadas; {time.time() - t0:.0f} s"
            + (f"; FALHARAM: {', '.join(falhas)}" if falhas else ""))
    conn.close()
    return 3 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
