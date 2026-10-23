"""Guarda o dado bruto coletado, para auditoria e para reprocessar sem baixar de novo.

Formato: <pasta>/<nome>.jsonl.gz (um registro JSON por linha) e <nome>.manifesto.json com a data
da coleta, a fonte, a descrição do que foi filtrado, o nº de linhas e o SHA-256 do arquivo.
Escrita atômica (arquivo temporário e renomeação): nunca fica meio arquivo com nome definitivo.
"""
import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def salvar_jsonl_gz(pasta, nome, registros, fonte, filtro=None, extra=None):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{nome}.jsonl.gz"
    temporario = pasta / f"{nome}.jsonl.gz.tmp"
    n = 0
    with gzip.open(temporario, "wt", encoding="utf-8", compresslevel=6) as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
    sha = hashlib.sha256(temporario.read_bytes()).hexdigest()
    os.replace(temporario, destino)
    manifesto = {
        "arquivo": destino.name,
        "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": fonte,
        "filtro_aplicado": filtro,
        "linhas": n,
        "sha256": sha,
    }
    if extra:
        manifesto.update(extra)
    (pasta / f"{nome}.manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino, n


def salvar_bytes_gz(pasta, nome, dados, fonte, filtro=None, extra=None, extensao="gml"):
    """Como salvar_jsonl_gz, mas para a resposta inteira da fonte (bytes, ex.: um GML): <nome>.<extensao>.gz."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{nome}.{extensao}.gz"
    temporario = pasta / f"{nome}.{extensao}.gz.tmp"
    with gzip.open(temporario, "wb", compresslevel=6) as f:
        f.write(dados)
    sha = hashlib.sha256(temporario.read_bytes()).hexdigest()
    os.replace(temporario, destino)
    manifesto = {
        "arquivo": destino.name,
        "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": fonte,
        "filtro_aplicado": filtro,
        "bytes_originais": len(dados),
        "sha256": sha,
    }
    if extra:
        manifesto.update(extra)
    (pasta / f"{nome}.manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino, len(dados)


def sha256_arquivo(caminho, bloco=1 << 20):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while True:
            b = f.read(bloco)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
