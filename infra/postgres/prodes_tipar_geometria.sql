-- Tipa a geometria do PRODES: de geometry (sem tipo) para geometry(MultiPolygon, 4674).
-- Antes: 6.880.431 linhas, todas MULTIPOLYGON em 4674 (conferido em 2026-10-16). Reescreve a tabela (11 GB) e
-- recria o indice espacial; a view dependente e recriada igual (mesma definicao e mesmas permissoes).
-- Rodar como postgres:
--   Get-Content infra\postgres\prodes_tipar_geometria.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente: se a coluna ja estiver tipada, o ALTER nao muda nada de relevante.
BEGIN;
DROP VIEW vetorial.v_prodes_municipio;
ALTER TABLE vetorial.prodes_desmatamento ALTER COLUMN geom TYPE geometry(MultiPolygon, 4674) USING geom::geometry(MultiPolygon, 4674);
CREATE VIEW vetorial.v_prodes_municipio AS
 SELECT b.id AS id_ponte,
    b.id_municipio,
    p.id AS id_prodes,
    p.year,
    p.main_class,
    p.class_name,
    p.area_km,
    p.image_date,
    p.id_bioma,
    p.id_estado,
    p.geom
   FROM resultados.prodes_municipio b
     JOIN vetorial.prodes_desmatamento p ON p.id = b.id_prodes;
GRANT SELECT ON vetorial.v_prodes_municipio TO leitura, geoserver, analistas;
COMMIT;
ANALYZE vetorial.prodes_desmatamento;
SELECT f_table_name, type, srid FROM geometry_columns WHERE f_table_schema = 'vetorial' AND f_table_name IN ('prodes_desmatamento', 'v_prodes_municipio') ORDER BY 1;
