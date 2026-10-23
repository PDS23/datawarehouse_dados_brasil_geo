#!/usr/bin/env python3
"""
Baixa folhas do TOPODATA (INPE) via API STAC do BDC (Brazil Data Cube).

Substitui o antigo baixar_topodata.py, que apontava para
dsr.inpe.br/topodata (domínio fora do ar). Não precisa de lista manual de
folhas: pagina a coleção inteira sozinho (556 folhas cobrindo o Brasil).

Uso:
    python baixar_topodata_stac.py

Edite as constantes PRODUTO e OUTDIR abaixo antes de rodar.

Produtos (chave do asset no STAC):
    ZN  altitude
    SN  declividade continua (graus)          ~49,9 GB Brasil inteiro
    SA  declividade em classes - Marques 1971 ~1,04 GB
    SB  declividade em classes - Lepsch 1991  ~1,70 GB
    SC  declividade em classes - Embrapa 1999 ~1,36 GB
    ON  orientacao de vertente (aspect)
    OC  orientacao em octantes
    HN/H3/H5  curvatura horizontal (continua/3cl/5cl)
    VN/V3/V5  curvatura vertical (continua/3cl/5cl)
    FT  forma de terreno
    DD  divisores e talvegues
    RS  relevo sombreado (hillshade)
"""

import json
import os
import time
import urllib.request

BASE = "https://data.inpe.br/bdc/stac/v1/collections/topodata-1/items"

PRODUTO = "ZN"
OUTDIR = os.path.join(os.path.dirname(__file__), "..", "bruto", "brasil", "altitude_zn")
# baixa Brasil inteiro (556 folhas) - troque PRODUTO e o ultimo trecho do
# OUTDIR (ex. "declividade_sn") antes de rodar


def iter_items():
    url = BASE + "?limit=100"
    while url:
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.load(r)
        for feat in d["features"]:
            yield feat
        url = None
        for l in d.get("links", []):
            if l["rel"] == "next":
                url = l["href"]


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    items = list(iter_items())
    total = len(items)
    ok = skip = fail = 0
    falhas = []

    for i, feat in enumerate(items, 1):
        tile_id = feat["id"]
        asset = feat["assets"].get(PRODUTO)
        if not asset:
            print(f"[{i}/{total}] {tile_id}: sem asset {PRODUTO}")
            fail += 1
            falhas.append(tile_id)
            continue

        href = asset["href"]
        dest = os.path.join(OUTDIR, f"{tile_id}{PRODUTO}.tif")
        tamanho_esperado = asset.get("bdc:size")

        if os.path.exists(dest) and tamanho_esperado and os.path.getsize(dest) == tamanho_esperado:
            skip += 1
            continue

        for tentativa in range(3):
            try:
                urllib.request.urlretrieve(href, dest)
                ok += 1
                break
            except Exception as e:
                if tentativa == 2:
                    print(f"[{i}/{total}] FALHOU: {tile_id} ({e})")
                    fail += 1
                    falhas.append(tile_id)
                else:
                    time.sleep(2)

        if i % 50 == 0 or i == total:
            print(f"[{i}/{total}] baixadas={ok} puladas={skip} falhas={fail}")

    print("\n=== RESUMO ===")
    print(f"produto: {PRODUTO}")
    print(f"total de folhas: {total}")
    print(f"baixadas agora: {ok}")
    print(f"ja existiam: {skip}")
    print(f"falharam: {fail}")
    if falhas:
        print("folhas com falha:", falhas)


if __name__ == "__main__":
    main()
