-- Ano da malha territorial (geometria de dim.municipios e dim.estados).
-- Rodar como postgres:
--   Get-Content ibge\municipios\sql\01_malha_versionada.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. So ASCII de proposito.
--
-- ano_malha: ano da malha do IBGE de onde veio a geometria atual (NULL = malha anterior a este controle, ano nao registrado).
-- (A tabela dim.malha_anterior, que arquivava a geometria substituida, foi RETIRADA em 2026-10-30 por decisao do usuario; antes de trocar uma malha, faca backup do banco.)

ALTER TABLE dim.municipios ADD COLUMN IF NOT EXISTS ano_malha smallint;
ALTER TABLE dim.estados    ADD COLUMN IF NOT EXISTS ano_malha smallint;
COMMENT ON COLUMN dim.municipios.ano_malha IS 'Ano da malha municipal do IBGE da geometria atual. NULL = malha antiga sem ano registrado (a malha 2025 entrou em 5101837 em 14/10/2026).';
COMMENT ON COLUMN dim.estados.ano_malha IS 'Ano da malha de UFs do IBGE da geometria atual. NULL = malha antiga sem ano registrado.';

SELECT 'municipios sem ano_malha' AS item, count(*)::text AS valor FROM dim.municipios WHERE ano_malha IS NULL
UNION ALL SELECT 'estados sem ano_malha', count(*)::text FROM dim.estados WHERE ano_malha IS NULL;
