-- PAM (Producao Agricola Municipal, IBGE/SIDRA tabela 5457): dimensao de culturas e fato municipal.
-- (Executado em 2026-10-14.) Pre-requisito: infra/postgres/etl_base.sql.
-- Rodar como postgres:
--   Get-Content ibge\PAM\sql\01_esquema.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. So ASCII de proposito.
--
-- Convencoes do projeto (ARQUITETURA.md): dimensao antes do fato; chave = codigo oficial quando
-- existe (aqui, o codigo da classificacao c782 do SIDRA); id_fonte e importado_em em tudo.

CREATE TABLE IF NOT EXISTS dim.cultura (
    id_cultura   integer PRIMARY KEY,          -- codigo SIDRA, classificacao c782 (tabela 5457)
    nome         text NOT NULL,                -- como o IBGE escreve (sem o asterisco de nota)
    slug         text NOT NULL UNIQUE,         -- nome sem acento, minusculo, com '_'
    nota_ibge    boolean NOT NULL DEFAULT false, -- true se o nome vem com asterisco (nota de rodape do IBGE)
    id_fonte     smallint NOT NULL REFERENCES dim.fontes (id_fonte),
    importado_em date NOT NULL DEFAULT current_date
);
COMMENT ON TABLE dim.cultura IS 'Produtos da PAM (SIDRA 5457, c782). O codigo 0 (Total) nao entra: e soma dos demais.';

-- Largo: uma linha por municipio x cultura x ano, so quando ha algum valor > 0.
-- Ausencia de linha = o IBGE informou zero ('-') ou nao informou ('...') nas 5 variaveis.
CREATE TABLE IF NOT EXISTS tabular.ibge_pam (
    id                       bigserial PRIMARY KEY,
    id_municipio             integer  NOT NULL REFERENCES dim.municipios (id_municipio),
    id_cultura               integer  NOT NULL REFERENCES dim.cultura (id_cultura),
    ano                      smallint NOT NULL,
    area_plantada_ha         numeric,           -- v8331: area plantada ou destinada a colheita
    area_colhida_ha          numeric,           -- v216
    quantidade_produzida     numeric,           -- v214 (a UNIDADE esta em unidade_quantidade)
    unidade_quantidade       text NOT NULL,     -- 'toneladas', 'mil frutos', 'mil cachos' ou 'a confirmar (nota * do IBGE)'
    rendimento_medio         numeric,           -- v112 (a unidade esta em unidade_rendimento)
    unidade_rendimento       text NOT NULL,     -- 'kg/ha', 'frutos/ha', 'cachos/ha' ou 'a confirmar (nota * do IBGE)'
    valor_producao_mil_reais numeric,           -- v215 (so e mil reais de 1994 em diante; ver unidade_valor)
    unidade_valor            text NOT NULL DEFAULT 'mil reais',  -- ate 1993: 'moeda nominal da epoca (pre-Real; nao comparavel)'
    id_fonte                 smallint NOT NULL REFERENCES dim.fontes (id_fonte),
    importado_em             date NOT NULL DEFAULT current_date,
    UNIQUE (id_municipio, id_cultura, ano)
);
CREATE INDEX IF NOT EXISTS idx_ibge_pam_cultura_ano ON tabular.ibge_pam (id_cultura, ano);
CREATE INDEX IF NOT EXISTS idx_ibge_pam_municipio   ON tabular.ibge_pam (id_municipio);
COMMENT ON TABLE tabular.ibge_pam IS 'PAM/IBGE (SIDRA 5457), 1974 em diante. Valores como o IBGE devolve; a API rotula tudo como toneladas, por isso unidade_* registra a unidade real quando ela e conhecida.';
COMMENT ON COLUMN tabular.ibge_pam.unidade_quantidade IS 'Ate 2000 algumas frutas vem em mil frutos/mil cachos (a API diz toneladas). Ver ibge/PAM/config.yaml.';

-- O ETL so grava nestas tabelas (DML); nao cria nem apaga
GRANT INSERT, UPDATE ON dim.cultura, tabular.ibge_pam TO etl;
GRANT USAGE ON SEQUENCE tabular.ibge_pam_id_seq TO etl;

SELECT 'dim.cultura' AS tabela, count(*)::text AS linhas FROM dim.cultura
UNION ALL SELECT 'tabular.ibge_pam', count(*)::text FROM tabular.ibge_pam;
