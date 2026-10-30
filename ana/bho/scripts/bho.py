"""Base Hidrográfica Ottocodificada 1:250.000 (BHO250, ANA) -> 4 tabelas vetorial.ana_bho_*, como ESPELHOS VERSIONADOS.

Lê o registro da BHO250 no catálogo de metadados da ANA (GeoNetwork do SNIRH), descobre a versão pelo nome do arquivo da base completa (bho_250k_v_AA_BB.gpkg), baixa o GeoPackage de cada camada
(links diretos, sem login), lê em lotes e reconcilia igual às outras fontes (regras em dwlib/espelho.py): feição nova entra; alterada fecha a versão antiga e insere a nova; a que a versão nova não
traz tem a versão fechada (nada é apagado); a que sumiu e voltou idêntica tem a versão reaberta.

Camadas: trechos_drenagem (1,6 milhão de linhas), cursos_dagua (807 mil), linha_costa (25) e bacias_otto (níveis 1 a 6 numa tabela só). NÃO carrega as áreas de contribuição (1,6 milhão de
polígonos, 3,7 GB) nem os pontos de drenagem: sob demanda (ver config.yaml).

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl ana/bho/scripts/bho.py [--camadas trechos_drenagem,cursos_dagua,linha_costa,bacias_otto] [--verificar | --simular | --aceitar-queda]
"""
import argparse
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

RAIZ = Path(__file__).resolve().parents[1]               # ana/bho
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]
SQLT = {"integer": "integer", "double": "double precision", "text": "text"}


def log(*a):
    print(*a, flush=True)


def texto(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    v = str(v).strip()
    return None if v in ("", "None", "nan") else v


def inteiro(v):
    return None if v is None or (isinstance(v, float) and v != v) else int(v)


def duplo(v):
    return None if v is None or (isinstance(v, float) and v != v) else float(v)


def versao_catalogo(sessao):
    """Versão da BHO (ex.: '02_03') pelo nome do arquivo da base completa no registro do catálogo."""
    r = sessao.get(CFG["url_busca"], params={"_content_type": "json", "uuid": CFG["uuid_registro"], "fast": "index", "resultType": "details"},
                   headers={"Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    m = re.search(CFG["padrao_versao"], r.text)
    if not m:
        raise RuntimeError("nao achei o arquivo da base completa (bho_250k_v_AA_BB.gpkg) no registro do catalogo da ANA (a ANA mudou a publicacao?): NADA gravado")
    return m.group(1)


def baixar(sessao, url, destino, minimo):
    r = sessao.get(url, stream=True, timeout=(30, 900))
    r.raise_for_status()
    esperado = int(r.headers.get("content-length", 0))
    n = 0
    with open(destino, "wb") as f:
        for bloco in r.iter_content(1 << 20):
            f.write(bloco)
            n += len(bloco)
    if esperado and n != esperado:
        raise RuntimeError(f"download truncado: {n} de {esperado} bytes: NADA gravado")
    if n < minimo:
        raise RuntimeError(f"arquivo com {n} bytes (esperado mais de {minimo}): a ANA trocou o arquivo? NADA gravado")
    return n


def ler_camada(gpkg, cfg_c):
    """Gera (linha_de_valores, wkb) de todas as feições, em lotes. As 6 camadas de bacias viram uma só."""
    from pyogrio import list_layers
    from pyogrio.raw import read
    campos = list(cfg_c["colunas"])
    layers = [cfg_c["layer"]] if cfg_c["layer"] else sorted(n for n, _ in list_layers(str(gpkg)) if "ach_otto_nivel" in n)
    if not layers:
        raise RuntimeError("camada nao encontrada no GeoPackage: NADA gravado")
    lote = CFG["lote_leitura"]
    for layer in layers:
        pos = 0
        while True:
            meta, _, geoms, vals = read(str(gpkg), layer=layer, skip_features=pos, max_features=lote)
            nomes = [str(c).lower() for c in meta["fields"]]
            faltam = [c for c in campos if c not in nomes]
            if faltam:
                raise RuntimeError(f"{layer}: faltam os campos {faltam} (a ANA mudou o esquema?): NADA gravado")
            col = {c: vals[i] for i, c in enumerate(nomes)}
            n = len(geoms)
            if n == 0:
                break
            for i in range(n):
                linha = []
                for c in campos:
                    t = cfg_c["colunas"][c]
                    v = col[c][i]
                    linha.append(inteiro(v) if t == "integer" else duplo(v) if t == "double" else texto(v))
                yield linha, (bytes(geoms[i]).hex() if geoms[i] is not None else None)
            pos += n
            if n < lote:
                break


def carregar(conn, sessao, nome, cfg_c, edicao, args):
    T = cfg_c["destino"]
    campos = list(cfg_c["colunas"])
    todos = campos + ["edicao"]
    campos_stage = ["chave_linha"] + todos                       # o espelho reconcilia por chave_linha
    chave = cfg_c["chave"]
    comparar = list(campos) + ["geom_anomala", "geom_origem_texto"]
    t0 = time.time()
    url = CFG["url_arquivos"] + cfg_c["arquivo"]
    with tempfile.TemporaryDirectory() as tmp:
        gpkg = Path(tmp) / cfg_c["arquivo"]
        n_bytes = baixar(sessao, url, gpkg, cfg_c["tamanho_minimo_bytes"])
        log(f"== ANA BHO {nome} (versao {edicao}): {n_bytes / 1e6:.0f} MB baixados em {time.time() - t0:.0f} s")
        with Carga(conn, T.split(".")[1], dataset=T, parametros={**vars(args), "edicao": edicao, "camada": nome}, simular=args.simular) as carga:
            cur = conn.cursor()
            ddl = ", ".join(f"{c} {SQLT[cfg_c['colunas'][c]]}" for c in campos)
            cur.execute(f"CREATE TEMP TABLE _stage (chave_linha text, {ddl}, edicao text, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) ON COMMIT DROP")
            vistos, n = {}, 0
            idx_chave = [campos.index(c) for c in cfg_c["chave_campos"]]
            with cur.copy(f"COPY _stage (chave_linha, {', '.join(todos)}, geom) FROM STDIN") as copia:
                for linha, wkb in ler_camada(gpkg, cfg_c):
                    base = "|".join(str(linha[i]) for i in idx_chave)
                    if any(linha[i] is None for i in idx_chave):
                        raise RuntimeError(f"campo da chave vazio ({base}): NADA gravado")
                    vistos[base] = vistos.get(base, 0) + 1
                    copia.write_row([base if vistos[base] == 1 else f"{base}#{vistos[base]}"] + linha + [edicao, wkb])
                    n += 1
            repetidas = sum(v - 1 for v in vistos.values() if v > 1)
            vistos.clear()
            if repetidas:
                carga.avisos.append(f"{repetidas} feicao(oes) com chave repetida na fonte (ganham ordinal)")
            carga.lidas += n
            if n < cfg_c["linhas_minimas"]:
                raise RuntimeError(f"so {n} feicoes (esperado mais de {cfg_c['linhas_minimas']}): NADA gravado")
            cx = CFG["caixa_brasil"]
            caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
            cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(geom, {SRID}) WHERE geom IS NOT NULL")
            cur.execute("SELECT count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)), count(*) FILTER (WHERE geom IS NULL) FROM _stage")
            invalidas, sem_geom = cur.fetchone()
            cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = ST_AsEWKT(geom), geom = NULL WHERE geom IS NOT NULL AND NOT (geom @ {caixa})")
            anomalas = cur.rowcount
            if anomalas:
                carga.avisos.append(f"{anomalas} feicao(oes) fora da caixa do Brasil (geom NULL e texto original)")
            if invalidas:
                carga.avisos.append(f"{invalidas} geometria(s) invalida(s) pelo PostGIS (gravadas como vieram)")
            cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry({cfg_c['geometria']}, {SRID}) USING ST_Multi(geom)")
            cur.execute("CREATE UNIQUE INDEX ON _stage (chave_linha)")
            cur.execute("ANALYZE _stage")
            log(f"  {n:,} feicoes lidas | chaves repetidas (ordinal): {repetidas} | invalidas: {invalidas} | sem geometria: {sem_geom} | fora do Brasil: {anomalas}".replace(",", "."))
            fonte = db.id_fonte(conn, CFG["fonte"])
            stats = espelho.reconciliar(conn, T, chave, comparar, campos_stage, fonte=fonte, id_carga=carga.id, max_queda=CFG["max_queda"],
                                        aceitar_queda=args.aceitar_queda, simular=args.simular, log=log)
            if args.simular:
                conn.rollback()
                log("SIMULACAO: nada foi gravado.")
                return
            cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                        "inalterados, id_carga, observacao, reabertos, edicao) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (T, nome, "ANA (BHO250)", url, "GeoPackage da ANA (links do catalogo de metadados), lido em lotes", n, n, stats["novos"], stats["alterados"],
                         stats["ausentes"], stats["inalterados"], carga.id, f"{invalidas} invalidas; {anomalas} fora do Brasil", stats["reabertos"], edicao))
            registrar_dataset(conn, f"ANA - BHO 1:250.000, {nome}", T, fonte, ano_referencia=2023, licenca=CFG["licenca"], tipo="vetor",
                              observacoes=f"Base Hidrografica Ottocodificada 1:250.000, versao {edicao} (dez/2023). Ver ana/bho/LEIAME_bho.md.")
            conn.commit()
            carga.inseridas += stats["inseridos"]
            carga.atualizadas += stats["ausentes"]
            log(f"== {nome}: fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']:,} versoes inseridas, {stats['reabertos']:,} reabertas, "
                f"{stats['ausentes']:,} fechadas por ausencia)".replace(",", "."))


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="ANA, BHO 1:250.000 (GeoPackage) -> espelhos versionados de vetorial.ana_bho_*")
    ap.add_argument("--camadas", default=",".join(CFG["camadas"]), help="padrao: todas")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    args = ap.parse_args()
    escolhidas = [c.strip() for c in args.camadas.split(",") if c.strip()]
    if any(c not in CFG["camadas"] for c in escolhidas):
        raise SystemExit(f"camadas validas: {', '.join(CFG['camadas'])}")
    sessao = http.sessao()
    edicao = versao_catalogo(sessao)
    conn = db.conectar()
    if args.verificar:
        for nome in escolhidas:
            T = CFG["camadas"][nome]["destino"]
            cur = conn.cursor()
            cur.execute("SELECT to_regclass(%s)", (T,))
            ed_banco, n = None, None
            if cur.fetchone()[0]:
                cur.execute(f"SELECT max(edicao), count(*) FILTER (WHERE vigente_ate IS NULL) FROM {T}")
                ed_banco, n = cur.fetchone()
            log(f"{nome}: banco {ed_banco} ({n} vigentes); catalogo da ANA {edicao}")
        return 0
    for nome in escolhidas:
        carregar(conn, sessao, nome, CFG["camadas"][nome], edicao, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
