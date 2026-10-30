"""Atualiza dim.estados / dim.municipios direto do IBGE, sem download manual.

Fontes (as duas públicas, sem login):
  1. SIDRA, tabela 6579 (apisidra.ibge.gov.br): lista oficial vigente de UFs e municípios com
     código e nome. É por ela que se descobre um município novo (ex.: 5101837 Boa Esperança do
     Norte/MT, que o IBGE reconheceu depois da malha que usávamos).
  2. Malhas territoriais (geoftp.ibge.gov.br): shapefile de municípios e de UFs do ano mais
     recente publicado, em SIRGAS 2000 (EPSG:4674). Só com --geometria (baixa ~250 MB).

O que faz, e o que NÃO faz:
  - ACRESCENTA municípios que existem no IBGE e faltam na dimensão (com geometria, se --geometria).
  - PREENCHE a geometria de quem está sem (geom IS NULL).
  - NUNCA altera nome nem geometria de município que já tem: diferenças só são relatadas.
  - NUNCA apaga. Territórios nossos que o IBGE não lista como município (as lagoas Mirim e dos
    Patos, 4300001 e 4300002, vêm da malha) são relatados, não removidos.

Uso (no contêiner etl, a partir de infra/):
  docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl \
      ibge/municipios/scripts/localidades.py [--geometria] [--simular] [--ano-malha 2025]
  --simular: faz tudo numa transação que é desfeita no fim (não grava nada; o download acontece).
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

from dwlib import bruto, db, sidra
from dwlib.catalogo import Carga

RAIZ = Path(__file__).resolve().parents[1]          # ibge/municipios
PASTA_BRUTO = RAIZ / "bruto"
GEOFTP = "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/"
FONTE = "IBGE"
SRID = 4674


def log(*a):
    print(*a, flush=True)


def territorios_sidra():
    """({cd_uf: nome}, {cd_mun: (nome, sigla_uf)}) da tabela 6579 (vigente)."""
    ufs = {int(r["D1C"]): r["D1N"] for r in sidra.valores("6579", "n3", ["9324"], ["last"])}
    municipios = {}
    for r in sidra.valores("6579", "n6", ["9324"], ["last"]):
        nome, _, uf = r["D1N"].rpartition(" - ")
        municipios[int(r["D1C"])] = (nome, uf)
    return ufs, municipios


def ano_malha_mais_recente():
    html = requests.get(GEOFTP, timeout=60).text
    return max(int(a) for a in set(re.findall(r"municipio_(\d{4})", html)))


def baixar(url, destino, forcar=False):
    """Baixa em streaming; reaproveita o arquivo se já existe com o mesmo tamanho. Grava manifesto."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    cab = requests.head(url, timeout=60, allow_redirects=True)
    cab.raise_for_status()
    tamanho = int(cab.headers["Content-Length"])
    if destino.exists() and destino.stat().st_size == tamanho and not forcar:
        log(f"  já existe e tem o mesmo tamanho ({tamanho / 1e6:.1f} MB): {destino.name}")
        return destino
    log(f"  baixando {destino.name} ({tamanho / 1e6:.1f} MB) de {url}")
    temp = destino.with_suffix(destino.suffix + ".tmp")
    feito, marca = 0, 0
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(temp, "wb") as f:
            for bloco in r.iter_content(1 << 20):
                f.write(bloco)
                feito += len(bloco)
                if feito - marca >= 50 << 20:
                    marca = feito
                    log(f"    {feito / 1e6:.0f}/{tamanho / 1e6:.0f} MB")
    if feito != tamanho:
        raise RuntimeError(f"download incompleto: {feito} de {tamanho} bytes")
    temp.replace(destino)
    import json
    (destino.parent / (destino.name + ".manifesto.json")).write_text(json.dumps({
        "arquivo": destino.name, "url": url, "baixado_em": datetime.now().isoformat(timespec="seconds"),
        "bytes": tamanho, "sha256": bruto.sha256_arquivo(destino),
        "last_modified_servidor": cab.headers.get("Last-Modified")}, indent=2), encoding="utf-8")
    return destino


def ler_malha(zip_path):
    """{codigo: dict(campos..., wkb=bytes)} de um shapefile zipado do IBGE (via pyogrio, sem shapely)."""
    from pyogrio import read_info
    from pyogrio.raw import read
    info = read_info(f"zip://{zip_path}")
    crs = str(info.get("crs"))
    log(f"  {zip_path.name}: {info['features']} feições, campos {list(info['fields'])[:8]}..., CRS {crs}")
    if "4674" not in crs and "SIRGAS" not in crs.upper():
        raise RuntimeError(f"CRS inesperado na malha: {crs} (esperado EPSG:4674)")
    meta, _fids, geometria, dados = read(f"zip://{zip_path}")
    campos = [c.upper() for c in meta["fields"]]
    linhas = {}
    for i, wkb in enumerate(geometria):
        reg = {campos[j]: dados[j][i] for j in range(len(campos))}
        reg["wkb"] = bytes(wkb) if wkb is not None else None
        linhas[reg.get("CD_MUN") or reg.get("CD_UF")] = reg
    return linhas


# Metrica da mudanca: area da DIFERENCA SIMETRICA entre a geometria antiga e a nova, em fracao da area antiga.
# (O Hausdorff foi testado e e quadratico: passou de 9 min so no 1o passo; a diferenca simetrica e linear.)
TOL_IGUAL = 1e-6        # fracao da area: abaixo disso a geometria e a mesma (ruido de digitalizacao)
TOL_GRANDE = 1e-3       # fracao da area (0,1%): acima disso a mudanca e relevante


def atualizar_malha(conn, tipo, malha, ano, fonte, simular, carga):
    """Compara a malha do IBGE com a geometria da dimensao e, se nao for --simular, SUBSTITUI as que mudaram.

    A geometria antiga NAO e arquivada: a tabela dim.malha_anterior foi retirada em 2026-10-30 (decisao do usuario; copia em D:\backups\data_warehouse\malha_anterior_2026-10-30.dump).
    Faca um backup do banco antes de aplicar. Geometria nova invalida nao entra.
    Retorna um resumo (dict) para o relatorio."""
    tabela, col_id = ("municipios", "id_municipio") if tipo == "municipio" else ("estados", "id_estado")
    minimo = 5500 if tipo == "municipio" else 27
    if len(malha) < minimo:
        raise RuntimeError(f"malha com {len(malha)} feicoes (esperado >= {minimo}): nao atualizo a dimensao")
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _cmp")
        cur.execute("DROP TABLE IF EXISTS _malha")
        cur.execute("CREATE TEMP TABLE _malha (cod integer PRIMARY KEY, area_km2 numeric, wkb bytea)")
        with cur.copy("COPY _malha (cod, area_km2, wkb) FROM STDIN") as copia:
            for cod, reg in malha.items():
                if reg.get("wkb") is not None:
                    copia.write_row((int(cod), float(reg["AREA_KM2"]) if reg.get("AREA_KM2") is not None else None, reg["wkb"]))
        cur.execute(f"""CREATE TEMP TABLE _cmp AS
            SELECT d.{col_id} AS id, d.ano_malha AS ano_antigo, d.area_km2 AS area_antiga, m.area_km2 AS area_nova,
                   d.geom AS g_ant, ST_Multi(ST_SetSRID(ST_GeomFromWKB(m.wkb), {SRID})) AS g_nov
            FROM dim.{tabela} d JOIN _malha m ON m.cod = d.{col_id}""")
        cur.execute("ALTER TABLE _cmp ADD COLUMN valida boolean, ADD COLUMN dif_rel double precision, ADD COLUMN classe text")
        cur.execute("UPDATE _cmp SET valida = ST_IsValid(g_nov)")
        # barato primeiro: igual depois de arredondar a 1e-7 grau; so os demais pagam a diferenca simetrica
        cur.execute("UPDATE _cmp SET dif_rel = 0 WHERE ST_Equals(ST_SnapToGrid(g_ant, 1e-7), ST_SnapToGrid(g_nov, 1e-7))")
        cur.execute("SELECT count(*) FROM _cmp WHERE dif_rel IS NULL AND valida")
        log(f"  {tipo}: {cur.fetchone()[0]} diferem do arredondamento a 1e-7 grau; medindo a diferenca simetrica so nesses")
        cur.execute("UPDATE _cmp SET dif_rel = ST_Area(ST_SymDifference(g_ant, g_nov)) / NULLIF(ST_Area(g_ant), 0) WHERE dif_rel IS NULL AND valida")
        cur.execute(f"UPDATE _cmp SET classe = CASE WHEN NOT valida THEN 'invalida' WHEN dif_rel <= {TOL_IGUAL} THEN 'igual' "
                    f"WHEN dif_rel <= {TOL_GRANDE} THEN 'pequena' ELSE 'grande' END")
        cur.execute("SELECT classe, count(*) FROM _cmp GROUP BY 1 ORDER BY 2 DESC")
        resumo = dict(cur.fetchall())
        cur.execute(f"""SELECT c.id, d.{'nome_municipio' if tipo == 'municipio' else 'nome_uf'}, c.classe, round((c.dif_rel * 100)::numeric, 4),
                          round(c.area_antiga::numeric, 1), round(c.area_nova::numeric, 1)
                        FROM _cmp c JOIN dim.{tabela} d ON d.{col_id} = c.id WHERE c.classe IN ('grande', 'invalida')
                        ORDER BY c.dif_rel DESC NULLS FIRST LIMIT 12""")
        maiores = cur.fetchall()
        cur.execute(f"SELECT count(*) FROM dim.{tabela} d WHERE NOT EXISTS (SELECT 1 FROM _malha m WHERE m.cod = d.{col_id})")
        fora_da_malha = cur.fetchone()[0]
        log(f"  {tipo}: {sum(resumo.values())} comparados | {resumo} | na dimensao e fora da malha: {fora_da_malha}")
        for linha in maiores:
            log(f"    maior mudanca: id {linha[0]} {linha[1]} [{linha[2]}] diferenca {linha[3]}% da area, area {linha[4]} -> {linha[5]} km2")
        if resumo.get("invalida"):
            carga.avisos.append(f"{resumo['invalida']} geometria(s) nova(s) invalida(s) de {tipo} NAO aplicadas")

        # --- aplicacao: troca so o que mudou (pequena/grande); igual so ganha o ano da malha ---
        cur.execute(f"""UPDATE dim.{tabela} d SET geom = c.g_nov, area_km2 = c.area_nova, ano_malha = %s, id_fonte = %s, importado_em = current_date
                        FROM _cmp c WHERE c.id = d.{col_id} AND c.classe IN ('pequena', 'grande')""", (ano, fonte))
        trocadas = cur.rowcount
        cur.execute(f"UPDATE dim.{tabela} d SET ano_malha = %s FROM _cmp c WHERE c.id = d.{col_id} AND c.classe = 'igual' AND d.ano_malha IS DISTINCT FROM %s", (ano, ano))
        carimbadas = cur.rowcount
        carga.atualizadas += trocadas
        log(f"  {tipo}: {trocadas} geometria(s) substituida(s), "
            f"{carimbadas} identica(s) so com ano_malha={ano}" + (" [SIMULACAO: sera desfeito]" if simular else ""))
        return {"resumo": resumo, "trocadas": trocadas}


def main():
    ap = argparse.ArgumentParser(description="Atualiza dim.estados e dim.municipios direto do IBGE.")
    ap.add_argument("--atualizar-geometria", action="store_true",
                    help="com --geometria: SUBSTITUI as geometrias de municipios e UFs que mudaram na malha nova (a antiga NAO e arquivada: faca backup antes)")
    ap.add_argument("--geometria", action="store_true", help="baixa as malhas do IBGE e preenche a geometria de quem está sem")
    ap.add_argument("--ano-malha", type=int, help="ano da malha (padrão: o mais recente publicado)")
    ap.add_argument("--forcar-download", action="store_true")
    ap.add_argument("--simular", action="store_true", help="não grava nada (transação desfeita)")
    args = ap.parse_args()
    if args.atualizar_geometria and not args.geometria:
        ap.error("--atualizar-geometria exige --geometria")

    conn = db.conectar()
    with Carga(conn, "ibge_localidades", dataset=None, parametros=vars(args), simular=args.simular) as carga:
        carga.analisar = ["dim.municipios", "dim.estados"]
        fonte = db.id_fonte(conn, FONTE)
        log("== 1) lista oficial do IBGE (SIDRA 6579)")
        ufs_ibge, mun_ibge = territorios_sidra()
        log(f"  IBGE: {len(ufs_ibge)} UFs, {len(mun_ibge)} municípios")
        with conn.cursor() as cur:
            cur.execute("SELECT id_estado FROM dim.estados")
            ufs_dim = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT id_municipio, nome_municipio, geom IS NULL FROM dim.municipios")
            mun_dim = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        log(f"  dimensão: {len(ufs_dim)} UFs, {len(mun_dim)} municípios ({sum(1 for v in mun_dim.values() if v[1])} sem geometria)")

        faltam_uf = sorted(set(ufs_ibge) - ufs_dim)
        if faltam_uf:
            raise RuntimeError(f"UFs do IBGE que faltam em dim.estados: {faltam_uf} (o pipeline não cria UF)")
        faltam = sorted(set(mun_ibge) - set(mun_dim))
        sobram = sorted(set(mun_dim) - set(mun_ibge))
        norm = sidra.normaliza
        nomes_dif = [(c, mun_dim[c][0], mun_ibge[c][0]) for c in sorted(set(mun_ibge) & set(mun_dim))
                     if norm(mun_dim[c][0]) != norm(mun_ibge[c][0])]
        log(f"  faltam na dimensão: {len(faltam)} -> {[(c, mun_ibge[c][0], mun_ibge[c][1]) for c in faltam]}")
        log(f"  na dimensão e fora da lista do IBGE: {len(sobram)} -> {[(c, mun_dim[c][0]) for c in sobram]}")
        log(f"  nomes diferentes (só relato): {len(nomes_dif)}" + (f" -> {nomes_dif[:8]}" if nomes_dif else ""))
        carga.lidas = len(mun_ibge)

        if faltam:
            hoje = datetime.now().date()
            linhas = [(c, mun_ibge[c][0], int(str(c)[:2]), mun_ibge[c][1], fonte, hoje) for c in faltam]
            ins, atu = db.upsert(conn, "dim", "municipios",
                                 ["id_municipio", "nome_municipio", "id_estado", "sigla_uf", "id_fonte", "importado_em"],
                                 linhas, chave=["id_municipio"],
                                 atualizar=["nome_municipio", "id_estado", "sigla_uf", "id_fonte", "importado_em"])
            carga.inseridas += ins
            log(f"  acrescentados: {ins} município(s) (geometria vazia até --geometria)")
            for c in faltam:
                mun_dim[c] = (mun_ibge[c][0], True)

        if args.geometria:
            log("== 2) malha territorial do IBGE (geoftp)")
            ano = args.ano_malha or ano_malha_mais_recente()
            base = f"{GEOFTP}municipio_{ano}/Brasil/"
            zip_mun = baixar(f"{base}BR_Municipios_{ano}.zip", PASTA_BRUTO / f"BR_Municipios_{ano}.zip", args.forcar_download)
            zip_uf = baixar(f"{base}BR_UF_{ano}.zip", PASTA_BRUTO / f"BR_UF_{ano}.zip", args.forcar_download)
            malha = ler_malha(zip_mun)
            malha_uf = ler_malha(zip_uf)
            log(f"  malha {ano}: {len(malha)} municípios, {len(malha_uf)} UFs")
            cods_malha = {int(c) for c in malha}
            log(f"  na malha e fora da dimensão: {sorted(cods_malha - set(mun_dim))}")
            log(f"  na dimensão e fora da malha: {sorted(set(mun_dim) - cods_malha)}")
            sem_geom = [c for c, (_, sem) in mun_dim.items() if sem]
            a_preencher = [c for c in sem_geom if str(c) in malha]
            sem_na_malha = [c for c in sem_geom if str(c) not in malha]
            if sem_na_malha:
                log(f"  AVISO: sem geometria na dimensão e ausentes da malha: {sem_na_malha}")
                carga.avisos.append(f"sem geometria e fora da malha: {sem_na_malha}")
            with conn.cursor() as cur:
                for c in a_preencher:
                    reg = malha[str(c)]
                    cur.execute(
                        "UPDATE dim.municipios SET geom = ST_Multi(ST_SetSRID(ST_GeomFromWKB(%s), %s)), "
                        "area_km2 = %s, id_fonte = %s, importado_em = current_date "
                        "WHERE id_municipio = %s AND geom IS NULL",
                        (reg["wkb"], SRID, float(reg["AREA_KM2"]) if reg.get("AREA_KM2") is not None else None, fonte, c))
                    carga.atualizadas += cur.rowcount
            log(f"  geometria preenchida em {len(a_preencher)} município(s): {a_preencher}")

            if args.atualizar_geometria:
                log(f"== 2b) substituir geometrias pela malha {ano} (o que mudou; a antiga NAO e arquivada: faca backup antes)")
                r_mun = atualizar_malha(conn, "municipio", malha, ano, fonte, args.simular, carga)
                r_uf = atualizar_malha(conn, "estado", malha_uf, ano, fonte, args.simular, carga)
                if r_mun["trocadas"] or r_uf["trocadas"]:
                    aviso = (f"geometrias trocadas pela malha {ano}: {r_mun['trocadas']} municipio(s), {r_uf['trocadas']} UF(s). "
                             "RECALCULAR o que depende delas: resultados.prodes_municipio (ponte PRODES) e "
                             "vetorial.sicar_imoveis.id_municipio/id_estado.")
                    log("  AVISO:", aviso)
                    carga.avisos.append(aviso)

        # conferência final (dentro da transação)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(*) FILTER (WHERE geom IS NULL), "
                        "count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)) FROM dim.municipios")
            total, sem_geom, invalidas = cur.fetchone()
            log(f"== conferência: {total} municípios; sem geometria: {sem_geom}; geometrias inválidas: {invalidas}")
            if faltam:
                cur.execute("SELECT id_municipio, nome_municipio, sigla_uf, geom IS NOT NULL AS tem_geom, round(area_km2::numeric, 2), "
                            "id_estado FROM dim.municipios WHERE id_municipio = ANY(%s) ORDER BY 1", (faltam,))
                for linha in cur.fetchall():
                    log("   novo:", linha)
        if args.simular:
            conn.rollback()
            log("SIMULAÇÃO: nada foi gravado.")
        else:
            conn.commit()
            log("OK: gravado.")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
