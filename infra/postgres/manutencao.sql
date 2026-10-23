-- Privilegio MAINTAIN (PostgreSQL 17+) ao papel etl: permite ANALYZE (e VACUUM, REINDEX) nas tabelas onde os pipelines gravam,
-- para atualizar as estatisticas do planejador ao fim de cada coleta, sem dar posse da tabela.
-- Rodar como postgres:
--   Get-Content infra\postgres\manutencao.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. Tabelas criadas depois entram pelo ALTER DEFAULT PRIVILEGES (valem para as criadas pelo papel postgres).
DO $$
DECLARE s text;
BEGIN
  FOREACH s IN ARRAY ARRAY['vetorial', 'catalogo', 'tabular', 'resultados', 'dim'] LOOP
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
      EXECUTE format('GRANT MAINTAIN ON ALL TABLES IN SCHEMA %I TO etl', s);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT MAINTAIN ON TABLES TO etl', s);
      RAISE NOTICE 'MAINTAIN concedido ao etl em %', s;
    END IF;
  END LOOP;
END $$;
