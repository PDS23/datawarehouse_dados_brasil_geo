"""Teste de regressão da automação do PAM: compara tabular.ibge_pam com a coleta MANUAL de erva-mate do RS
(projetos/mate_rs/mate_rs_2023_2025_ibge_pam.csv, baixada à mão do SIDRA).

Para cada município do CSV e cada ano (2023-2025) compara:
  area_destinada_colheita_ha_AAAA   com  area_plantada_ha        (variável 8331)
  quantidade_produzida_t_AAAA       com  quantidade_produzida    (variável 214)
Município sem linha em tabular.ibge_pam vale 0 (a carga só grava quando há valor > 0).
Sai com código 1 se houver qualquer diferença.

  docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl ibge/PAM/scripts/validar_mate_rs.py
"""
import csv
import sys
from pathlib import Path

from dwlib import db

CSV = Path(__file__).resolve().parent / "mate_rs_2023_2025_ibge_pam.csv"
CULTURA = 40147  # Erva-mate (folha verde), SIDRA c782
ANOS = (2023, 2024, 2025)

with open(CSV, encoding="latin-1", newline="") as f:
    manual = {int(l["Codigo"]): l for l in csv.DictReader(f, delimiter=";")}
print(f"CSV manual: {len(manual)} municípios do RS")

conn = db.conectar()
with conn.cursor() as cur:
    cur.execute("SELECT id_municipio, ano, area_plantada_ha, quantidade_produzida FROM tabular.ibge_pam "
                "WHERE id_cultura = %s AND ano = ANY(%s) AND id_municipio BETWEEN 4300000 AND 4399999", (CULTURA, list(ANOS)))
    banco = {(m, a): (area, qtd) for m, a, area, qtd in cur.fetchall()}
print(f"banco: {len(banco)} linhas (município x ano) do RS com erva-mate")

dif, comparados = [], 0
for cod, linha in manual.items():
    for ano in ANOS:
        esp_area = float(linha[f"area_destinada_colheita_ha_{ano}"] or 0)
        esp_qtd = float(linha[f"quantidade_produzida_t_{ano}"] or 0)
        area, qtd = banco.get((cod, ano), (0, 0))
        area, qtd = float(area or 0), float(qtd or 0)
        comparados += 1
        if abs(area - esp_area) > 0.5 or abs(qtd - esp_qtd) > 0.5:
            dif.append((cod, ano, esp_area, area, esp_qtd, qtd))
extras = [(m, a) for (m, a) in banco if m not in manual]
print(f"comparações: {comparados}; diferenças: {len(dif)}; linhas do banco fora do CSV: {len(extras)}")
for d in dif[:15]:
    print(f"  município {d[0]} ano {d[1]}: área csv {d[2]} x banco {d[3]} | qtd csv {d[4]} x banco {d[5]}")
for m, a in extras[:10]:
    print(f"  só no banco: município {m} ano {a} -> {banco[(m, a)]}")
sys.exit(1 if dif else 0)
