#!/usr/bin/env python3
"""
Baixa folhas do TOPODATA (INPE, via API STAC do BDC) recortadas por uma
bounding box, em vez do Brasil inteiro. Util para baixar so um estado/regiao
sem precisar do dataset completo (que pode passar de 40-50GB por produto).

Uso:
    python baixar_topodata_regiao.py

Edite as constantes abaixo antes de rodar: PRODUTO, OUTDIR e a bbox
(MINLON/MAXLON/MINLAT/MAXLAT). A selecao de folhas e feita por interseccao
de bounding box (retangulo), nao pelo contorno exato do estado - pode trazer
uma folha ou outra alem da fronteira exata, o que geralmente e desejavel
(evita buraco na borda) e pode ser recortado depois no QGIS se precisar do
limite exato.
"""

import json
import os
import time
import urllib.request

BASE = "https://data.inpe.br/bdc/stac/v1/collections/topodata-1/items"

PRODUTO = "ZN"
OUTDIR = os.path.join(os.path.dirname(__file__), "..", "bruto", "rs_sc", "altitude_zn")

# bbox combinado Rio Grande do Sul + Santa Catarina (com folga), graus WGS84
MINLON, MAXLON = -58.0, -48.0
MINLAT, MAXLAT = -34.0, -25.5


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


def intersects(bbox):
    blon0, blat0, blon1, blat1 = bbox
    return not (blon1 < MINLON or blon0 > MAXLON or blat1 < MINLAT or blat0 > MAXLAT)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    items = [f for f in iter_items() if intersects(f["bbox"])]
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
                print(f"[{i}/{total}] OK: {tile_id}{PRODUTO}")
                break
            except Exception as e:
                if tentativa == 2:
                    print(f"[{i}/{total}] FALHOU: {tile_id} ({e})")
                    fail += 1
                    falhas.append(tile_id)
                else:
                    time.sleep(2)

    print("\n=== RESUMO ===")
    print(f"produto: {PRODUTO}")
    print(f"total de folhas na bbox: {total}")
    print(f"baixadas agora: {ok}")
    print(f"ja existiam: {skip}")
    print(f"falharam: {fail}")
    if falhas:
        print("folhas com falha:", falhas)


if __name__ == "__main__":
    main()
