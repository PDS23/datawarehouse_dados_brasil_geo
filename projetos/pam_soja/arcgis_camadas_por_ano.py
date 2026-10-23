"""ArcGIS Pro: cria uma camada de consulta por ano com o PAM da soja (uma linha por município).
Como usar: no ArcGIS Pro, abrir o mapa que vai receber as camadas > aba Análise > Python > Janela Python
e colar/executar este código, ou rodar como script no Notebook do Pro.
Pré-requisito: um arquivo de conexão .sde (ou .sde de conexão direta) com o banco data_warehouse
(Banco de dados > Nova conexão de banco de dados > PostgreSQL). Ajuste CONEXAO abaixo.
"""
import arcpy

CONEXAO = r'C:\caminho\para\data_warehouse.sde'
ANOS = range(2015, 2026)   # 2015 a 2025

SQL = """
SELECT p.id,
       m.id_municipio, m.nome_municipio, m.sigla_uf, p.ano,
       p.area_plantada_ha, p.area_colhida_ha,
       p.quantidade_produzida AS producao_t,
       p.rendimento_medio AS rendimento_kg_ha,
       p.valor_producao_mil_reais, p.unidade_valor,
       m.geom
FROM tabular.ibge_pam p
JOIN dim.cultura c ON c.id_cultura = p.id_cultura
JOIN dim.municipios m ON m.id_municipio = p.id_municipio
WHERE c.nome ILIKE 'Soja%' AND p.ano = {ano}
"""

mapa = arcpy.mp.ArcGISProject('CURRENT').activeMap
for ano in ANOS:
    nome = f'soja_pam_{ano}'
    arcpy.management.MakeQueryLayer(
        input_database=CONEXAO,
        out_layer_name=nome,
        query=SQL.format(ano=ano),
        oid_fields='id',
        shape_type='POLYGON',
        srid='4674',
    )
    print(f'{ano}: ok')
# MakeQueryLayer adiciona a camada ao mapa ativo quando rodado na janela Python do Pro.
# Para salvar cada uma em arquivo .lyrx: arcpy.management.SaveToLayerFile(nome, rf'C:\pasta\{nome}.lyrx')
