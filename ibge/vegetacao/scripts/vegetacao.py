"""Vegetação (BDiA, IBGE) -> vetorial.ibge_vegetacao, como ESPELHO VERSIONADO. A mecanica e comum aos 4 temas do BDiA (scripts_comuns/dwlib/bdia.py).

Uso (a partir da raiz do repositorio):
  .\\infra\\scripts\\dw.ps1 etl ibge/vegetacao/scripts/vegetacao.py [--verificar | --simular | --aceitar-queda | --edicao AAAA]
"""
import sys
from pathlib import Path

from dwlib import bdia

if __name__ == "__main__":
    sys.exit(bdia.executar(Path(__file__).resolve().parents[1]))
