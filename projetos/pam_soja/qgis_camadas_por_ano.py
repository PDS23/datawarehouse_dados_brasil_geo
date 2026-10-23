"""QGIS: cria uma camada de consulta por ano com o PAM da soja (uma linha por município).
Como usar: QGIS > Plugins > Console Python > Mostrar editor > abrir este arquivo > Executar.
Preencha HOST, PORT, USUARIO e SENHA abaixo (ou use uma configuração de autenticação do QGIS: AUTHCFG).
"""
from qgis.core import QgsDataSourceUri, QgsVectorLayer, QgsProject

HOST, PORT, BANCO = '127.0.0.1', '5432', 'data_warehouse'   # ajuste o HOST (endereço do servidor)
USUARIO, SENHA = 'COLOQUE_AQUI', 'COLOQUE_AQUI'
AUTHCFG = ''                                                # opcional: id da configuração de autenticação
ANOS = range(2015, 2026)                                    # 2015 a 2025

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

grupo = QgsProject.instance().layerTreeRoot().addGroup('PAM Soja por ano')
for ano in ANOS:
    uri = QgsDataSourceUri()
    if AUTHCFG:
        uri.setConnection(HOST, PORT, BANCO, '', '', QgsDataSourceUri.SslPrefer, AUTHCFG)
    else:
        uri.setConnection(HOST, PORT, BANCO, USUARIO, SENHA)
    # (esquema, consulta entre parênteses, coluna de geometria, filtro, coluna de id único)
    uri.setDataSource('', '(' + SQL.format(ano=ano) + ')', 'geom', '', 'id')
    uri.setSrid('4674')
    camada = QgsVectorLayer(uri.uri(False), f'soja_pam_{ano}', 'postgres')
    if not camada.isValid():
        print(f'{ano}: camada inválida, confira conexão e senha')
        continue
    QgsProject.instance().addMapLayer(camada, False)
    grupo.addLayer(camada)
    print(f'{ano}: ok ({camada.featureCount()} municípios)')
