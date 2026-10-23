-- Indices secundarios e chaves estrangeiras do PRODES, DEPOIS da carga (carregar com eles e bem mais lento).
-- Rodar como postgres:
--   Get-Content prodes\desmatamento\sql\02_indices_chaves.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente (indices IF NOT EXISTS; chaves so se ainda nao existem). Opera na tabela de construcao prodes_novo.
SET maintenance_work_mem = '2GB';
SET max_parallel_maintenance_workers = 4;

CREATE INDEX IF NOT EXISTS idx_prodes_geom       ON prodes_novo.prodes_desmatamento USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_prodes_uuid       ON prodes_novo.prodes_desmatamento (uuid);
CREATE INDEX IF NOT EXISTS idx_prodes_bioma      ON prodes_novo.prodes_desmatamento (bioma);
CREATE INDEX IF NOT EXISTS idx_prodes_id_bioma   ON prodes_novo.prodes_desmatamento (id_bioma);
CREATE INDEX IF NOT EXISTS idx_prodes_id_estado  ON prodes_novo.prodes_desmatamento (id_estado);
CREATE INDEX IF NOT EXISTS idx_prodes_vigente_ano ON prodes_novo.prodes_desmatamento (year) WHERE vigente_ate IS NULL;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'prodes_novo_fk_fonte') THEN
    ALTER TABLE prodes_novo.prodes_desmatamento ADD CONSTRAINT prodes_novo_fk_fonte FOREIGN KEY (id_fonte) REFERENCES dim.fontes (id_fonte);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'prodes_novo_fk_bioma') THEN
    ALTER TABLE prodes_novo.prodes_desmatamento ADD CONSTRAINT prodes_novo_fk_bioma FOREIGN KEY (id_bioma) REFERENCES dim.biomas (id_bioma);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'prodes_novo_fk_estado') THEN
    ALTER TABLE prodes_novo.prodes_desmatamento ADD CONSTRAINT prodes_novo_fk_estado FOREIGN KEY (id_estado) REFERENCES dim.estados (id_estado);
  END IF;
END $$;
GRANT SELECT ON prodes_novo.prodes_desmatamento TO leitura, geoserver, analistas;
ANALYZE prodes_novo.prodes_desmatamento;
