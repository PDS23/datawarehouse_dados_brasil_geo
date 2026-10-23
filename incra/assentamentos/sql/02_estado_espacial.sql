-- Migracao (executada em 2026-10-15) para bancos que criaram a tabela com o 01_esquema.sql antigo, em que
-- id_estado vinha da camada do INCRA. A camada DF e a jurisdicao do DF (204 de 208 poligonos em GO e MG) e a
-- de PE traz projetos da BA; o estado correto vem da posicao do poligono.
-- Rodar como postgres:
--   Get-Content incra\assentamentos\sql\02_estado_espacial.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. So ASCII de proposito. Em banco novo (01 ja com as duas colunas), so recalcula id_estado.

ALTER TABLE vetorial.incra_assentamentos ADD COLUMN IF NOT EXISTS id_estado_camada smallint REFERENCES dim.estados (id_estado);
UPDATE vetorial.incra_assentamentos SET id_estado_camada = id_estado WHERE id_estado_camada IS NULL;
ALTER TABLE vetorial.incra_assentamentos ALTER COLUMN id_estado_camada SET NOT NULL;
ALTER TABLE vetorial.incra_assentamentos ALTER COLUMN id_estado DROP NOT NULL;
COMMENT ON COLUMN vetorial.incra_assentamentos.id_estado_camada IS 'Camada do INCRA de origem. A camada DF e a jurisdicao do DF: 204 de 208 poligonos estao em GO e MG; a de PE traz projetos na BA. Para filtrar por estado use id_estado.';

UPDATE vetorial.incra_assentamentos a
SET id_estado = coalesce((SELECT e.id_estado FROM dim.estados e WHERE ST_Intersects(e.geom, ST_PointOnSurface(a.geom)) ORDER BY e.id_estado LIMIT 1),
                         a.id_estado_camada);

SELECT c.sigla_uf AS camada, e.sigla_uf AS estado_real, count(*) AS poligonos
FROM vetorial.incra_assentamentos a
JOIN dim.estados c ON c.id_estado = a.id_estado_camada
JOIN dim.estados e ON e.id_estado = a.id_estado
WHERE a.id_estado <> a.id_estado_camada
GROUP BY 1, 2 ORDER BY 3 DESC;
