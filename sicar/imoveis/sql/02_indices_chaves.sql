-- Fecha a tabela nova do SICAR depois da carga: indices secundarios, chaves estrangeiras, permissoes e ANALYZE.
-- Rodar como postgres, DEPOIS de carregar as UFs (carregar com estes indices ativos e bem mais lento):
--   Get-Content sicar\imoveis\sql\02_indices_chaves.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. So ASCII de proposito.
CREATE INDEX IF NOT EXISTS idx_sicar_imoveis_geom_wfs       ON sicar_novo.sicar_imoveis USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_sicar_imoveis_cod_wfs        ON sicar_novo.sicar_imoveis (cod_imovel);
CREATE INDEX IF NOT EXISTS idx_sicar_imoveis_uf_vigente_wfs ON sicar_novo.sicar_imoveis (cod_estado) WHERE vigente_ate IS NULL;
CREATE INDEX IF NOT EXISTS idx_sicar_imoveis_munic_wfs      ON sicar_novo.sicar_imoveis (id_municipio);
CREATE INDEX IF NOT EXISTS idx_sicar_imoveis_estado_wfs     ON sicar_novo.sicar_imoveis (id_estado);
CREATE INDEX IF NOT EXISTS idx_sicar_imoveis_status_wfs     ON sicar_novo.sicar_imoveis (ind_status) WHERE vigente_ate IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sicar_imoveis_estado_wfs') THEN
        ALTER TABLE sicar_novo.sicar_imoveis ADD CONSTRAINT fk_sicar_imoveis_estado_wfs FOREIGN KEY (id_estado) REFERENCES dim.estados (id_estado);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sicar_imoveis_municipio_wfs') THEN
        ALTER TABLE sicar_novo.sicar_imoveis ADD CONSTRAINT fk_sicar_imoveis_municipio_wfs FOREIGN KEY (id_municipio) REFERENCES dim.municipios (id_municipio);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sicar_imoveis_fonte_wfs') THEN
        ALTER TABLE sicar_novo.sicar_imoveis ADD CONSTRAINT fk_sicar_imoveis_fonte_wfs FOREIGN KEY (id_fonte) REFERENCES dim.fontes (id_fonte);
    END IF;
END $$;

GRANT USAGE ON SCHEMA sicar_novo TO leitura, geoserver, analistas;
GRANT SELECT ON sicar_novo.sicar_imoveis TO leitura, geoserver, analistas;
ANALYZE sicar_novo.sicar_imoveis;

SELECT count(*) AS linhas, count(*) FILTER (WHERE vigente_ate IS NULL) AS vigentes,
       pg_size_pretty(pg_total_relation_size('sicar_novo.sicar_imoveis')) AS tamanho
FROM sicar_novo.sicar_imoveis;
