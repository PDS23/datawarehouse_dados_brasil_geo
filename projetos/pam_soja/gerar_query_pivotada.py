"""Gera o SQL (query layer do ArcGIS) com o PAM da soja pivotado: uma linha por município,
5 variáveis x N anos em colunas, sufixo _{ano} no nome.
Uso: python gerar_query_pivotada.py 2015 2025 > pam_soja_2015_2025.sql
"""
import sys

ini, fim = int(sys.argv[1]), int(sys.argv[2])
VARS = [  # (coluna no banco, prefixo do alias, condição extra)
    ('area_plantada_ha', 'area_plantada_ha', ''),
    ('area_colhida_ha', 'area_colhida_ha', ''),
    ('quantidade_produzida', 'producao_t', ''),
    ('rendimento_medio', 'rendimento_kg_ha', ''),
    ('valor_producao_mil_reais', 'valor_producao_mil_reais', " AND p.unidade_valor = 'mil reais'"),
]
cols = []
for ano in range(ini, fim + 1):
    for col, alias, extra in VARS:
        cols.append(f"       MAX(p.{col}) FILTER (WHERE p.ano = {ano}{extra}) AS {alias}_{ano}")
sub =',\n'.join(cols)
names = [f"{a}_{ano}" for ano in range(ini, fim + 1) for _, a, _ in VARS]
outer = ',\n'.join(f"       s.{n}" for n in names)
print(f"""SELECT m.id_municipio,
       m.nome_municipio,
       m.sigla_uf,
{outer},
       m.geom
FROM dim.municipios m
JOIN (
  SELECT p.id_municipio,
{sub.replace('       MAX', '         MAX')}
  FROM tabular.ibge_pam p
  JOIN dim.cultura c ON c.id_cultura = p.id_cultura
  WHERE c.nome ILIKE 'Soja%'
    AND p.ano BETWEEN {ini} AND {fim}
  GROUP BY p.id_municipio
) s ON s.id_municipio = m.id_municipio""")
