-- Base da automacao de coleta (ETL): papel "etl", registro de cargas e permissoes.
-- (Executado em 2026-10-14.) Rodar como postgres (socket local):
--   Get-Content infra\postgres\etl_base.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- A SENHA do papel NAO fica aqui: infra\scripts\criar_papel_etl.ps1 gera uma senha aleatoria,
-- grava em infra\.env (ETL_PASSWORD) e aplica no banco, sem imprimi-la.
--
-- Principio: o ETL so faz DML (INSERT/UPDATE) nas tabelas que alimenta. Nao cria objetos,
-- nao apaga, nao tem acesso ao socket de administracao. A DDL de cada pipeline e rodada pelo
-- administrador (postgres), a partir de SQL versionado no repositorio.
-- Idempotente. So ASCII de proposito.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl') THEN
        CREATE ROLE etl LOGIN CONNECTION LIMIT 5;
    END IF;
END $$;
ALTER ROLE etl SET statement_timeout = '30min';
ALTER ROLE etl SET idle_in_transaction_session_timeout = '15min';

GRANT CONNECT ON DATABASE data_warehouse TO etl;
GRANT USAGE ON SCHEMA dim, tabular, catalogo, vetorial, resultados TO etl;
GRANT SELECT ON ALL TABLES IN SCHEMA dim, tabular, catalogo TO etl;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA dim, tabular, catalogo
    GRANT SELECT ON TABLES TO etl;

-- Registro de cada execucao de um pipeline (quem, quando, com que parametros, quantas linhas)
CREATE TABLE IF NOT EXISTS catalogo.cargas (
    id                bigserial PRIMARY KEY,
    pipeline          text NOT NULL,
    dataset           text,
    iniciada_em       timestamptz NOT NULL DEFAULT now(),
    finalizada_em     timestamptz,
    status            text NOT NULL DEFAULT 'rodando' CHECK (status IN ('rodando', 'ok', 'falhou')),
    parametros        jsonb,
    linhas_lidas      bigint,
    linhas_inseridas  bigint,
    linhas_atualizadas bigint,
    linhas_rejeitadas bigint,
    mensagem          text
);
COMMENT ON TABLE catalogo.cargas IS 'Uma linha por execucao de pipeline de coleta automatizada (scripts_comuns/dwlib).';
GRANT SELECT, INSERT, UPDATE ON catalogo.cargas TO etl;
GRANT USAGE ON SEQUENCE catalogo.cargas_id_seq TO etl;

-- Catalogo de datasets: o ETL registra o que alimenta
GRANT INSERT, UPDATE ON catalogo.datasets TO etl;
GRANT USAGE ON SEQUENCE catalogo.datasets_id_seq TO etl;

-- Dimensoes territoriais: o pipeline de localidades acrescenta territorios que o IBGE criou
GRANT INSERT, UPDATE ON dim.estados, dim.municipios TO etl;

SELECT 'papel etl' AS item, count(*)::text AS valor FROM pg_roles WHERE rolname = 'etl'
UNION ALL SELECT 'catalogo.cargas', count(*)::text FROM catalogo.cargas;
