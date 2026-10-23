-- Versionamento da malha territorial (geometria de dim.municipios e dim.estados).
-- Rodar como postgres:
--   Get-Content ibge\municipios\sql\01_malha_versionada.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. So ASCII de proposito.
--
-- ano_malha: ano da malha do IBGE de onde veio a geometria atual (NULL = malha anterior a este controle, ano nao registrado).
-- dim.malha_anterior: geometria substituida quando uma malha nova entra (nada se perde; da para voltar).

ALTER TABLE dim.municipios ADD COLUMN IF NOT EXISTS ano_malha smallint;
ALTER TABLE dim.estados    ADD COLUMN IF NOT EXISTS ano_malha smallint;
COMMENT ON COLUMN dim.municipios.ano_malha IS 'Ano da malha municipal do IBGE da geometria atual. NULL = malha antiga sem ano registrado (a malha 2025 entrou em 5101837 em 14/10/2026).';
COMMENT ON COLUMN dim.estados.ano_malha IS 'Ano da malha de UFs do IBGE da geometria atual. NULL = malha antiga sem ano registrado.';

CREATE TABLE IF NOT EXISTS dim.malha_anterior (
    id            bigserial PRIMARY KEY,
    tipo          text     NOT NULL CHECK (tipo IN ('municipio', 'estado')),
    id_territorio integer  NOT NULL,                       -- id_municipio ou id_estado
    ano_malha     smallint,                                -- ano da geometria arquivada (NULL = nao registrado)
    area_km2      numeric,
    geom          geometry(MultiPolygon, 4674),
    arquivado_em  date     NOT NULL DEFAULT current_date,
    motivo        text                                     -- ex.: 'substituida pela malha 2025 (Hausdorff 0.0123 graus)'
);
CREATE INDEX IF NOT EXISTS idx_malha_anterior_terr ON dim.malha_anterior (tipo, id_territorio);
COMMENT ON TABLE dim.malha_anterior IS 'Geometrias de dim.municipios/dim.estados substituidas por uma malha nova do IBGE. Para voltar: copiar geom de volta pelo id_territorio.';

-- O ETL atualiza a dimensao e arquiva a geometria antiga (so INSERT; nao apaga o arquivo)
GRANT SELECT, INSERT ON dim.malha_anterior TO etl;
GRANT USAGE ON SEQUENCE dim.malha_anterior_id_seq TO etl;
GRANT SELECT ON dim.malha_anterior TO leitura, analistas;

SELECT 'municipios sem ano_malha' AS item, count(*)::text AS valor FROM dim.municipios WHERE ano_malha IS NULL
UNION ALL SELECT 'estados sem ano_malha', count(*)::text FROM dim.estados WHERE ano_malha IS NULL
UNION ALL SELECT 'dim.malha_anterior', count(*)::text FROM dim.malha_anterior;
