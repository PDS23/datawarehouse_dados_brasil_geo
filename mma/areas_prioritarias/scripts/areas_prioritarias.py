"""Áreas Prioritárias para a Conservação da Biodiversidade (MMA) -> vetorial.mma_areas_prioritarias, como ESPELHO VERSIONADO.

Lê o pacote do CKAN do MMA, baixa os 7 shapefiles em zip (um por bioma/região; esquemas diferentes) e reconcilia igual às outras fontes (regras em dwlib/espelho.py): área nova entra; alterada
fecha a versão antiga e insere a nova; a que a edição nova não traz tem a versão fechada (nada é apagado). É uma edição estática (a 2ª atualização, de 2022): rodar de novo não muda nada,
mas uma edição nova do MMA seria detectada. As colunas comuns são harmonizadas (config.yaml); todos os campos de cada shapefile ficam em atributos_originais (jsonb).

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl mma/areas_prioritarias/scripts/areas_prioritarias.py [opções]

  OPÇÕES: --simular | --aceitar-queda | --destino SCHEMA.TABELA (padrão: o do config.yaml; a tabela precisa existir: sql/01_tabela.sql)
"""
import argparse
import json
import math
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

RAIZ = Path(__file__).resolve().parents[1]               # mma/areas_prioritarias
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]

CAMPOS = ["camada_origem", "cod_area", "nome_area", "importancia_biologica", "prioridade_acao", "acao_principal_codigo", "acao_principal", "acoes_complementares", "estados",
          "area_ha", "atributos_originais", "edicao"]
COLS_STAGE = {"area_ha": "numeric", "atributos_originais": "jsonb"}
COMPARAR = [c for c in CAMPOS if c not in ("camada_origem", "cod_area", "edicao")] + ["geom_anomala", "geom_origem_texto"]


def log(*a):
    print(*a, flush=True)


def valor(v):
    """Valor do shapefile como JSON-serializável: NaN/None viram None; número inteiro vindo como float (12.0) vira inteiro."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def texto(v):
    v = valor(v)
    if v is None:
        return None
    v = str(v).strip()
    return None if v in ("", "None", "nan") else v


def baixar_pacote(sessao, tmp):
    r = sessao.get(CFG["url_ckan_pacote"], timeout=60)
    r.raise_for_status()
    urls = {}
    for x in r.json()["result"]["resources"]:
        nome = (x.get("url") or "").rsplit("/", 1)[-1]
        if nome in CFG["camadas"]:
            urls[nome] = x["url"]
    faltam = [n for n in CFG["camadas"] if n not in urls]
    if faltam:
        raise RuntimeError(f"o CKAN do MMA nao traz mais os arquivos {faltam} (o MMA mudou a publicacao?): NADA gravado")
    arquivos = {}
    for nome, url in urls.items():
        destino = Path(tmp) / nome
        with sessao.get(url, stream=True, timeout=(30, 300)) as resp:
            resp.raise_for_status()
            with open(destino, "wb") as f:
                for bloco in resp.iter_content(1 << 20):
                    f.write(bloco)
        if not zipfile.is_zipfile(destino):
            raise RuntimeError(f"{nome} nao e um zip: NADA gravado")
        arquivos[nome] = destino
    return arquivos


def ler_camada(zip_path, nome_zip, cfg_c):
    from pyogrio.raw import read
    with zipfile.ZipFile(zip_path) as z:
        shps = [n for n in z.namelist() if n.lower().endswith(".shp")]
    if len(shps) != 1:
        raise RuntimeError(f"{nome_zip}: esperava 1 shapefile, achei {shps}: NADA gravado")
    m = re.search(r"_(\d+)a_atualizacao", shps[0], re.I)
    edicao = f"{m.group(1)}a atualizacao" if m else shps[0]
    meta, _, geoms, campos = read(f"/vsizip/{zip_path}/{shps[0]}")
    nomes = [str(c) for c in meta["fields"]]
    col = {c: campos[i] for i, c in enumerate(nomes)}
    mapa = cfg_c["campos"]
    precisa = [v for v in ([mapa[k] for k in mapa if not isinstance(mapa[k], list)] + [x for k in mapa if isinstance(mapa[k], list) for x in mapa[k]]) if v not in col]
    if precisa:
        raise RuntimeError(f"{nome_zip}: faltam os campos {precisa} (o MMA mudou o esquema?): NADA gravado")
    registros = []
    for i in range(len(geoms)):
        reg = {c: None for c in CAMPOS}
        reg.update(camada_origem=cfg_c["camada_origem"], edicao=edicao)
        for coluna, campo in mapa.items():
            if coluna == "acoes_complementares":
                partes = [texto(col[c][i]) for c in campo]
                reg[coluna] = " | ".join(p for p in partes if p) or None
            elif coluna == "area_ha":
                v = valor(col[campo][i])
                reg[coluna] = None if v is None else Decimal(repr(float(v)))
            else:
                reg[coluna] = texto(col[campo][i])
        reg["atributos_originais"] = json.dumps({c: valor(col[c][i]) for c in nomes if c not in CFG["ignorar_campos"]}, ensure_ascii=False)
        if not reg["cod_area"]:
            raise RuntimeError(f"{nome_zip}: area sem codigo (linha {i}): NADA gravado")
        registros.append((reg, bytes(geoms[i]).hex() if geoms[i] is not None else None))
    return registros


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="MMA, areas prioritarias para a conservacao (CKAN) -> espelho versionado de vetorial.mma_areas_prioritarias")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    t0 = time.time()
    conn = db.conectar()
    sessao = http.sessao()
    registros = []
    with tempfile.TemporaryDirectory() as tmp:
        arquivos = baixar_pacote(sessao, tmp)
        for nome, cfg_c in CFG["camadas"].items():
            r = ler_camada(arquivos[nome], nome, cfg_c)
            log(f"  {cfg_c['camada_origem']}: {len(r)} areas ({r[0][0]['edicao']})")
            registros += r
    if len(registros) < CFG["linhas_minimas"]:
        raise RuntimeError(f"so {len(registros)} areas (esperado mais de {CFG['linhas_minimas']}): NADA gravado")
    chaves = [(r["camada_origem"], r["cod_area"]) for r, _ in registros]
    if len(set(chaves)) != len(chaves):
        raise RuntimeError("camada_origem + cod_area repetido: NADA gravado")
    log(f"== MMA, areas prioritarias: {len(registros):,} areas em {len(CFG['camadas'])} camadas".replace(",", "."))

    fonte = db.id_fonte(conn, CFG["fonte"])
    with Carga(conn, "mma_areas_prioritarias", dataset=T, parametros=vars(args), simular=args.simular) as carga:
        cur = conn.cursor()
        cols = ", ".join(f"{c} {COLS_STAGE.get(c, 'text')}" for c in CAMPOS)
        cur.execute(f"CREATE TEMP TABLE _stage ({cols}, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) ON COMMIT DROP")
        with cur.copy(f"COPY _stage ({', '.join(CAMPOS)}, geom) FROM STDIN") as copia:
            for reg, geom in registros:
                copia.write_row([reg[c] for c in CAMPOS] + [geom])
        carga.lidas += len(registros)
        cx = CFG["caixa_brasil"]
        caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
        cur.execute(f"UPDATE _stage SET geom = ST_Force2D(ST_SetSRID(geom, {SRID})) WHERE geom IS NOT NULL")
        cur.execute("SELECT count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)), count(*) FILTER (WHERE geom IS NULL) FROM _stage")
        invalidas, sem_geom = cur.fetchone()
        cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = ST_AsEWKT(geom), geom = NULL WHERE geom IS NOT NULL AND NOT (geom @ {caixa})")
        anomalas = cur.rowcount
        if anomalas:
            carga.avisos.append(f"{anomalas} area(s) fora da caixa do Brasil (geom NULL e texto original)")
        if invalidas:
            carga.avisos.append(f"{invalidas} poligono(s) invalido(s) pelo PostGIS (gravados como vieram)")
        cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {SRID}) USING ST_Multi(geom)")
        cur.execute("CREATE UNIQUE INDEX ON _stage (camada_origem, cod_area)")
        cur.execute("ANALYZE _stage")
        log(f"  poligonos invalidos: {invalidas} | sem geometria: {sem_geom} | fora do Brasil: {anomalas}")
        stats = espelho.reconciliar(conn, T, ["camada_origem", "cod_area"], COMPARAR, CAMPOS, fonte=fonte, id_carga=carga.id, max_queda=CFG["max_queda"],
                                    aceitar_queda=args.aceitar_queda, simular=args.simular, log=log)
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
            return 0
        edicoes = sorted({r["edicao"] for r, _ in registros})
        cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                    "inalterados, id_carga, observacao, reabertos, edicao) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, "todas", "MMA (areas prioritarias)", CFG["url_pagina"], "CKAN do MMA -> 7 shapefiles em zip (links diretos)", len(registros), len(registros),
                     stats["novos"], stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                     f"{invalidas} poligonos invalidos; {anomalas} fora do Brasil", stats["reabertos"], ", ".join(edicoes)))
        registrar_dataset(conn, "MMA - Areas prioritarias para a conservacao da biodiversidade", T, fonte, ano_referencia=2022, licenca=CFG["licenca"], tipo="vetor",
                          observacoes=f"Edicao {', '.join(edicoes)} (7 shapefiles, esquemas diferentes). Ver mma/areas_prioritarias/LEIAME_areas_prioritarias.md.")
        conn.commit()
        carga.inseridas += stats["inseridos"]
        carga.atualizadas += stats["ausentes"]
        log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']:,} versoes inseridas, {stats['reabertos']:,} reabertas, "
            f"{stats['ausentes']:,} fechadas por ausencia)".replace(",", "."))
        return 0


if __name__ == "__main__":
    sys.exit(main())
