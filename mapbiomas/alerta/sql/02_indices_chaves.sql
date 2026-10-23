-- Indices secundarios e chaves estrangeiras do MapBiomas Alerta, DEPOIS da primeira carga. Idempotente.
-- Rodar como postgres:
--   Get-Content mapbiomas\alerta\sql\02_indices_chaves.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
SET maintenance_work_mem = '1GB';
CREATE INDEX IF NOT EXISTS idx_mapbiomas_alerta_geom    ON vetorial.mapbiomas_alerta USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_mapbiomas_alerta_codigo  ON vetorial.mapbiomas_alerta (alert_code);
CREATE INDEX IF NOT EXISTS idx_mapbiomas_alerta_ano     ON vetorial.mapbiomas_alerta (year_detected_at) WHERE vigente_ate IS NULL;
CREATE INDEX IF NOT EXISTS idx_mapbiomas_alerta_detec   ON vetorial.mapbiomas_alerta (detected_at) WHERE vigente_ate IS NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'mapbiomas_alerta_fk_fonte') THEN
    ALTER TABLE vetorial.mapbiomas_alerta ADD CONSTRAINT mapbiomas_alerta_fk_fonte FOREIGN KEY (id_fonte) REFERENCES dim.fontes (id_fonte);
  END IF;
END $$;
ANALYZE vetorial.mapbiomas_alerta;
