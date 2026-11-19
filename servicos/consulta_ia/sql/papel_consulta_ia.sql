-- Papel do servidor MCP de consulta (servicos/consulta_ia): SÓ LEITURA, sem dado pessoal. Idempotente.
--
-- Rodar como postgres:
--   .\infra\scripts\dw.ps1 psql -Arquivo servicos\consulta_ia\sql\papel_consulta_ia.sql
-- Depois:
--   .\infra\scripts\senha_papel_servico.ps1 -Papel consulta_ia -Variavel CONSULTA_IA_PASSWORD   # senha gerada, vai só para o .env
--   .\infra\scripts\dw.ps1 etl servicos/consulta_ia/scripts/gerar_permissoes.py                # escreve sql/permissoes_consulta_ia.sql
--   .\infra\scripts\dw.ps1 psql -Arquivo servicos\consulta_ia\sql\permissoes_consulta_ia.sql
--
-- Por que um papel próprio e não o "leitura": o "leitura" lê tudo, inclusive nome e CPF/CNPJ dos embargados. O que o consulta_ia lê vai
-- para o provedor de IA que o analista escolheu, então ele lê todas as colunas MENOS as pessoais (permissão por coluna, gerada a partir de
-- infra/diagrama/descricoes_colunas.yaml, seção colunas_pessoais). Lê TODAS as versões (vigentes e fechadas): o histórico é o produto.
--
-- Defesa em camadas: (1) privilégio: só SELECT, coluna a coluna, nenhum CREATE; (2) os limites abaixo; (3) o servidor (scripts/consulta.py)
-- embrulha cada SQL numa subconsulta somente leitura, com tempo e linhas limitados, e recusa consulta cara pelo EXPLAIN.
-- Os SET abaixo são o padrão da sessão; quem conecta pode mudá-los, por isso o servidor os reaplica a cada chamada (SET LOCAL).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'consulta_ia') THEN
        -- nasce SEM SENHA (não entra até rodar senha_papel_servico.ps1)
        CREATE ROLE consulta_ia LOGIN NOINHERIT NOCREATEDB NOCREATEROLE CONNECTION LIMIT 5;
    END IF;
END $$;

COMMENT ON ROLE consulta_ia IS 'Servidor MCP de consulta (servicos/consulta_ia): só leitura, sem colunas de dado pessoal. Permissões geradas por gerar_permissoes.py.';

ALTER ROLE consulta_ia SET default_transaction_read_only = on;
ALTER ROLE consulta_ia SET statement_timeout = '120s';
ALTER ROLE consulta_ia SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE consulta_ia SET temp_file_limit = '5GB';
ALTER ROLE consulta_ia SET search_path = public;          -- funções do PostGIS; tabelas sempre com o schema (vetorial.sicar_imoveis)

GRANT CONNECT ON DATABASE data_warehouse TO consulta_ia;
GRANT USAGE ON SCHEMA catalogo, dim, resultados, tabular, vetorial TO consulta_ia;

-- Conferência
SELECT r.rolname, r.rolcanlogin, r.rolinherit, r.rolconnlimit, r.rolconfig,
       has_schema_privilege('consulta_ia', 'vetorial', 'CREATE') AS cria_em_vetorial,
       has_schema_privilege('consulta_ia', 'analises', 'USAGE') AS le_analises
FROM pg_roles r WHERE r.rolname = 'consulta_ia';
