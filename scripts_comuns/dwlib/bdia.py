"""Carga de uma camada do BDiA (Banco de Informações Ambientais do IBGE: geologia, geomorfologia, pedologia, vegetação) como ESPELHO VERSIONADO.

Cada fonte (ibge/geologia, ibge/geomorfologia, ibge/pedologia, ibge/vegetacao) tem o seu config.yaml, o seu SQL e um script de 3 linhas que chama `executar()`. A mecânica é a mesma:
  1. descobre a edição mais recente (pastas `versao_AAAA/`) na listagem do diretório do IBGE (servidor de arquivos geoftp);
  2. baixa o zip da camada (`*_area.zip`, 350 a 500 MB), confere o tamanho e descompacta numa área temporária;
  3. lê o shapefile em lotes (nunca tudo na memória), grava num _stage e reconcilia com a tabela (dwlib/espelho.py): feição nova entra; alterada fecha a versão antiga e insere a nova;
     a que a edição nova não traz tem a versão fechada (nada é apagado); a que sumiu e voltou idêntica tem a versão reaberta.
A chave é o `id1` do shapefile. Se o IBGE renumerar o `id1` numa edição nova, o espelho mostra a edição inteira como troca (feições antigas fechadas, novas abertas): a trava de queda de 10% impede
que isso entre sem `--aceitar-queda`.

Opções comuns: --simular | --aceitar-queda | --edicao AAAA (padrão: a mais recente) | --verificar (só lista as edições do IBGE e a que o banco tem) | --destino SCHEMA.TABELA
"""
import argparse
import hashlib
import re
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


def log(*a):
    print(*a, flush=True)


def texto(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    v = str(v).strip()
    return None if v in ("", "None", "nan") else v


def inteiro(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    return int(v)


def numero(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    return Decimal(repr(float(v)))


def edicoes(sessao, url_base):
    r = sessao.get(url_base, timeout=60)
    r.raise_for_status()
    achadas = sorted(set(re.findall(r'href="versao_(\d{4})/"', r.text)))
    if not achadas:
        raise RuntimeError(f"nenhuma pasta versao_AAAA em {url_base} (o IBGE mudou a organizacao?): NADA gravado")
    return achadas


def baixar(sessao, url, destino, minimo):
    r = sessao.get(url, stream=True, timeout=(30, 600))
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
    if n < minimo or not zipfile.is_zipfile(destino):
        raise RuntimeError(f"arquivo com {n} bytes ou que nao e zip (esperado mais de {minimo}): NADA gravado")
    return n, h.hexdigest()


def executar(raiz, argv=None):
    """raiz = pasta da fonte (ex.: ibge/geologia); le raiz/config.yaml."""
    tratar_sigterm()
    cfg = yaml.safe_load((Path(raiz) / "config.yaml").read_text(encoding="utf-8"))
    srid = cfg["srid_gravado"]
    colunas = cfg["colunas"]                                      # coluna do banco (= campo do shapefile em minusculas) -> tipo
    campos = list(colunas)
    comparar = [c for c in campos if c != cfg["chave"]] + ["geom_anomala", "geom_origem_texto"]
    cols_stage = {c: {"integer": "integer", "bigint": "bigint", "numeric": "numeric"}.get(t, "text") for c, t in colunas.items()}

    ap = argparse.ArgumentParser(description=f"IBGE, {cfg['titulo']} (BDiA) -> espelho versionado de {cfg['destino_padrao']}")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--edicao", help="ano da edicao (padrao: a mais recente do IBGE)")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=cfg["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    conn = db.conectar()
    sessao = http.sessao()
    vers = edicoes(sessao, cfg["url_base"])
    edicao = args.edicao or vers[-1]
    if edicao not in vers:
        raise SystemExit(f"edicao {edicao} nao existe no IBGE (tem: {', '.join(vers)})")
    if args.verificar:
        cur = conn.cursor()
        cur.execute("SELECT to_regclass(%s)", (T,))
        ed_banco = None
        if cur.fetchone()[0]:
            cur.execute(f"SELECT max(edicao), count(*) FILTER (WHERE vigente_ate IS NULL) FROM {T}")
            ed_banco, n = cur.fetchone()
            log(f"banco: edicao {ed_banco}, {n} feicoes vigentes")
        log(f"IBGE: edicoes {', '.join(vers)}; a mais recente e {vers[-1]}")
        log("RESULTADO: " + ("HA EDICAO NOVA para carregar." if ed_banco is None or vers[-1] > ed_banco else "o banco ja tem a edicao mais recente."))
        return 0

    t0 = time.time()
    url = cfg["url_base"] + f"versao_{edicao}/" + cfg["arquivo"]
    fonte = db.id_fonte(conn, cfg["fonte"])
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / cfg["arquivo"]
        n_bytes, hash_zip = baixar(sessao, url, zip_path, cfg["tamanho_minimo_bytes"])
        log(f"== IBGE {cfg['titulo']} {edicao}: {n_bytes / 1e6:.0f} MB baixados em {time.time() - t0:.0f} s (sha256 {hash_zip[:16]}...)")
        with zipfile.ZipFile(zip_path) as z:
            shps = [n for n in z.namelist() if n.lower().endswith(".shp")]
            if len(shps) != 1:
                raise RuntimeError(f"o zip deveria ter 1 shapefile, achei {shps}: NADA gravado")
            z.extractall(Path(tmp) / "shp")
        zip_path.unlink()
        shp = Path(tmp) / "shp" / shps[0]
        from pyogrio import read_info
        from pyogrio.raw import read
        info = read_info(str(shp))
        faltam = [c for c in campos if c not in [str(x).lower() for x in info["fields"]]]
        if faltam:
            raise RuntimeError(f"shapefile sem os campos {faltam} (o IBGE mudou o esquema?): NADA gravado")
        total = info["features"]
        if total < cfg["linhas_minimas"]:
            raise RuntimeError(f"so {total} feicoes (esperado mais de {cfg['linhas_minimas']}): NADA gravado")

        with Carga(conn, cfg["destino_padrao"].split(".")[1], dataset=T, parametros={**vars(args), "edicao": edicao, "sha256": hash_zip}, simular=args.simular) as carga:
            cur = conn.cursor()
            ddl = ", ".join(f"{c} {cols_stage[c]}" for c in campos)
            cur.execute(f"CREATE TEMP TABLE _stage ({ddl}, edicao text, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) ON COMMIT DROP")
            todos = campos + ["edicao"]
            lote, pos, vistos = cfg["lote_leitura"], 0, set()
            with cur.copy(f"COPY _stage ({', '.join(todos)}, geom) FROM STDIN") as copia:
                while pos < total:
                    meta, _, geoms, valores = read(str(shp), skip_features=pos, max_features=lote)
                    nomes = [str(c).lower() for c in meta["fields"]]
                    col = {c: valores[i] for i, c in enumerate(nomes)}
                    for i in range(len(geoms)):
                        linha = []
                        for c in campos:
                            v = col[c][i]
                            t = colunas[c]
                            linha.append(inteiro(v) if t in ("integer", "bigint") else numero(v) if t == "numeric" else texto(v))
                        chave = linha[campos.index(cfg["chave"])]
                        if chave is None or chave in vistos:
                            raise RuntimeError(f"chave {cfg['chave']} vazia ou repetida ({chave}): NADA gravado")
                        vistos.add(chave)
                        copia.write_row(linha + [str(edicao), bytes(geoms[i]).hex() if geoms[i] is not None else None])
                    pos += len(geoms)
                    if not len(geoms):
                        break
            carga.lidas += pos
            if pos != total:
                raise RuntimeError(f"leu {pos} de {total} feicoes: NADA gravado")
            cx = cfg["caixa_brasil"]
            caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {srid})"
            cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(geom, {srid}) WHERE geom IS NOT NULL")
            cur.execute("SELECT count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)), count(*) FILTER (WHERE geom IS NULL) FROM _stage")
            invalidas, sem_geom = cur.fetchone()
            cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = ST_AsEWKT(geom), geom = NULL WHERE geom IS NOT NULL AND NOT (geom @ {caixa})")
            anomalas = cur.rowcount
            if anomalas:
                carga.avisos.append(f"{anomalas} feicao(oes) fora da caixa do Brasil (geom NULL e texto original)")
            if invalidas:
                carga.avisos.append(f"{invalidas} poligono(s) invalido(s) pelo PostGIS (gravados como vieram)")
            cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {srid}) USING ST_Multi(geom)")
            cur.execute(f"CREATE UNIQUE INDEX ON _stage ({cfg['chave']})")
            cur.execute("ANALYZE _stage")
            log(f"  {pos:,} feicoes lidas | poligonos invalidos: {invalidas} | sem geometria: {sem_geom} | fora do Brasil: {anomalas}".replace(",", "."))
            stats = espelho.reconciliar(conn, T, [cfg["chave"]], comparar, todos, fonte=fonte, id_carga=carga.id, max_queda=cfg["max_queda"],
                                        aceitar_queda=args.aceitar_queda, simular=args.simular, log=log)
            if args.simular:
                conn.rollback()
                log("SIMULACAO: nada foi gravado.")
                return 0
            cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                        "inalterados, id_carga, observacao, reabertos, edicao) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (T, "todas", f"IBGE ({cfg['titulo']})", url, "listagem do geoftp do IBGE -> zip do shapefile da edicao mais recente", total, pos, stats["novos"],
                         stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                         f"sha256 {hash_zip}; {invalidas} poligonos invalidos; {anomalas} fora do Brasil", stats["reabertos"], str(edicao)))
            registrar_dataset(conn, f"IBGE - {cfg['titulo']} (BDiA, 1:250.000)", T, fonte, ano_referencia=int(edicao), licenca=cfg["licenca"], tipo="vetor",
                              observacoes=f"Edicao {edicao} do BDiA, escala 1:250.000. Ver {cfg['pasta']}/LEIAME_{cfg['pasta'].split('/')[-1]}.md.")
            conn.commit()
            carga.inseridas += stats["inseridos"]
            carga.atualizadas += stats["ausentes"]
            log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']:,} versoes inseridas, {stats['reabertos']:,} reabertas, "
                f"{stats['ausentes']:,} fechadas por ausencia)".replace(",", "."))
    return 0


if __name__ == "__main__":
    sys.exit("modulo: use ibge/<tema>/scripts/<tema>.py")
