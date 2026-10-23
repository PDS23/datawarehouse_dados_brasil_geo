-- TROCA: a tabela nova do SICAR (sicar_novo.sicar_imoveis, carregada do zero pelo WFS) passa a ser vetorial.sicar_imoveis.
-- A antiga (pacote GeoPackage) fica guardada como vetorial.sicar_imoveis_gpkg_antiga ate o usuario aprovar apaga-la.
-- Rodar como postgres, DEPOIS de carregar as 27 UFs, fechar (03) e validar, e com backup com etiqueta feito:
--   Get-Content sicar\imoveis\sql\03_troca_unica.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Uma transacao: tudo ou nada. So ASCII de proposito.
BEGIN;

-- 1) Tabelas derivadas que apontam para o id da tabela antiga (decidido com o usuario: recriar depois pela metodologia salva)
DROP TABLE resultados.desmatamento_imovel_controle;
DROP TABLE resultados.desmatamento_imovel;

-- 2) A antiga sai do caminho (nome, indices, chaves e sequencia), sem perder nada
ALTER TABLE vetorial.sicar_imoveis RENAME TO sicar_imoveis_gpkg_antiga;
ALTER TABLE vetorial.sicar_imoveis_gpkg_antiga RENAME CONSTRAINT sicar_imoveis_pkey TO sicar_imoveis_gpkg_antiga_pkey;
ALTER TABLE vetorial.sicar_imoveis_gpkg_antiga RENAME CONSTRAINT sicar_imoveis_id_fonte_fkey TO sicar_imoveis_gpkg_antiga_id_fonte_fkey;
ALTER TABLE vetorial.sicar_imoveis_gpkg_antiga RENAME CONSTRAINT sicar_imoveis_id_municipio_fkey TO sicar_imoveis_gpkg_antiga_id_municipio_fkey;
ALTER TABLE vetorial.sicar_imoveis_gpkg_antiga RENAME CONSTRAINT sicar_imoveis_id_estado_fkey TO sicar_imoveis_gpkg_antiga_id_estado_fkey;
ALTER INDEX vetorial.idx_sicar_imoveis_id_estado    RENAME TO idx_sicar_imoveis_gpkg_antiga_id_estado;
ALTER INDEX vetorial.idx_sicar_imoveis_atual        RENAME TO idx_sicar_imoveis_gpkg_antiga_atual;
ALTER INDEX vetorial.idx_sicar_imoveis_geom         RENAME TO idx_sicar_imoveis_gpkg_antiga_geom;
ALTER INDEX vetorial.idx_sicar_imoveis_id_municipio RENAME TO idx_sicar_imoveis_gpkg_antiga_id_municipio;
ALTER INDEX vetorial.idx_sicar_imoveis_cod_imovel   RENAME TO idx_sicar_imoveis_gpkg_antiga_cod_imovel;
ALTER SEQUENCE vetorial.sicar_imoveis_id_seq RENAME TO sicar_imoveis_gpkg_antiga_id_seq;
COMMENT ON TABLE vetorial.sicar_imoveis_gpkg_antiga IS
    'GUARDADA: carga antiga do SICAR (pacotes GeoPackage por estado, 27/09/2026, com o Acre reconciliado pelo WFS em 16/10). Substituida em 2026-10-20 pela carga unica do WFS do CAR. Pode ser apagada quando o usuario aprovar.';

-- 3) A nova assume o lugar e o nome
ALTER TABLE sicar_novo.sicar_imoveis SET SCHEMA vetorial;
ALTER INDEX vetorial.idx_sicar_imoveis_geom_wfs       RENAME TO idx_sicar_imoveis_geom;
ALTER INDEX vetorial.idx_sicar_imoveis_cod_wfs        RENAME TO idx_sicar_imoveis_cod_imovel;
ALTER INDEX vetorial.idx_sicar_imoveis_uf_vigente_wfs RENAME TO idx_sicar_imoveis_uf_vigente;
ALTER INDEX vetorial.idx_sicar_imoveis_munic_wfs      RENAME TO idx_sicar_imoveis_id_municipio;
ALTER INDEX vetorial.idx_sicar_imoveis_estado_wfs     RENAME TO idx_sicar_imoveis_id_estado;
ALTER INDEX vetorial.idx_sicar_imoveis_status_wfs     RENAME TO idx_sicar_imoveis_status_vigente;
ALTER TABLE vetorial.sicar_imoveis RENAME CONSTRAINT fk_sicar_imoveis_estado_wfs    TO sicar_imoveis_id_estado_fkey;
ALTER TABLE vetorial.sicar_imoveis RENAME CONSTRAINT fk_sicar_imoveis_municipio_wfs TO sicar_imoveis_id_municipio_fkey;
ALTER TABLE vetorial.sicar_imoveis RENAME CONSTRAINT fk_sicar_imoveis_fonte_wfs     TO sicar_imoveis_id_fonte_fkey;
GRANT SELECT ON vetorial.sicar_imoveis TO leitura, geoserver, analistas;
DROP SCHEMA sicar_novo;                 -- schema de construcao, agora vazio (RESTRICT: falha se sobrar algo)

-- 4) Registros do catalogo passam a apontar para o nome definitivo
UPDATE catalogo.coletas            SET dataset = 'vetorial.sicar_imoveis' WHERE dataset = 'sicar_novo.sicar_imoveis';
UPDATE catalogo.coletas_duplicados SET dataset = 'vetorial.sicar_imoveis' WHERE dataset = 'sicar_novo.sicar_imoveis';
UPDATE catalogo.cargas             SET dataset = 'vetorial.sicar_imoveis' WHERE dataset = 'sicar_novo.sicar_imoveis';

-- os 2 imoveis de geometria corrompida: o id_registro passa a ser o id da tabela nova (o cod_imovel ja estava guardado)
UPDATE catalogo.anomalias_geometria a
SET id_registro = s.id,
    observacao = coalesce(a.observacao || ' | ', '') || 'Migrado para a carga do WFS (2026-10-20): geom NULL, geom_anomala = true; texto original em geom_origem_texto.'
FROM vetorial.sicar_imoveis s WHERE s.cod_imovel = a.cod_imovel AND a.tabela = 'vetorial.sicar_imoveis' AND s.vigente_ate IS NULL;

UPDATE catalogo.datasets
SET nome = 'SICAR - Imoveis rurais (WFS do CAR)', ano_referencia = 2026, data_importacao = current_date,
    observacoes = 'Carga unica pelo WFS publico do CAR (geoserver.car.gov.br), 27 UFs, cancelados inclusive (ind_status CA). Historico por versao (vigente_ate IS NULL = atual). Colunas com nomes proprios; origem de cada uma em catalogo.mapa_colunas; fonte e data por UF em catalogo.v_ultima_coleta. Geometria fora do Brasil fica NULL (geom_anomala) com o texto original em geom_origem_texto. Cod_imovel repetido no WFS (retificacao em andamento): fica a feicao de maior data_atualizacao; as descartadas em catalogo.coletas_duplicados. Atualizar por sicar/imoveis/scripts/atualizar_imoveis_sicar.py.'
WHERE schema_tabela = 'vetorial.sicar_imoveis';

COMMIT;
ANALYZE vetorial.sicar_imoveis;

SELECT 'vetorial.sicar_imoveis (nova)' AS tabela, count(*)::text AS linhas FROM vetorial.sicar_imoveis
UNION ALL SELECT 'vetorial.sicar_imoveis_gpkg_antiga (guardada)', count(*)::text FROM vetorial.sicar_imoveis_gpkg_antiga
UNION ALL SELECT 'schema sicar_novo existe?', (EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'sicar_novo'))::text
UNION ALL SELECT 'geoserver le a nova', has_table_privilege('geoserver', 'vetorial.sicar_imoveis', 'SELECT')::text
UNION ALL SELECT 'etl escreve na nova', (has_table_privilege('etl', 'vetorial.sicar_imoveis', 'INSERT') AND has_table_privilege('etl', 'vetorial.sicar_imoveis', 'UPDATE'))::text;
