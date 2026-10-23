-- INCRA - Projetos de assentamento (poligonos), WFS publico do Acervo Fundiario.
-- Rodar como postgres:
--   Get-Content incra\assentamentos\sql\01_esquema.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. So ASCII de proposito. Pre-requisito: infra/postgres/etl_base.sql.

-- Fonte nova (dim.fontes): o INCRA ainda nao existia.
INSERT INTO dim.fontes (nome, sigla, url, descricao)
SELECT 'INCRA', 'INCRA', 'https://acervofundiario.incra.gov.br/',
       'Instituto Nacional de Colonizacao e Reforma Agraria (Acervo Fundiario, WFS publico i3Geo)'
WHERE NOT EXISTS (SELECT 1 FROM dim.fontes WHERE nome = 'INCRA');

-- Uma linha por POLIGONO publicado pelo INCRA. Um projeto (cd_sipra) pode ter varios poligonos (22 codigos
-- se repetem em 2026-10): area_declarada_ha vale para o projeto inteiro e se repete em cada poligono, entao
-- NAO se soma por linha; area_calc_ha e do poligono.
CREATE TABLE IF NOT EXISTS vetorial.incra_assentamentos (
    id                 bigserial PRIMARY KEY,
    gid_incra          integer  NOT NULL UNIQUE,     -- gid do servidor do INCRA (unico por poligono; o INCRA nao garante estabilidade)
    cd_sipra           text     NOT NULL,            -- codigo do projeto no SIPRA (UF + numero; 'MF...' em PE)
    nome_projeto       text,
    municipio          text,                         -- como o INCRA escreve (MAIUSCULAS, sem UF); pode haver varios municipios no projeto
    id_estado_camada   smallint NOT NULL REFERENCES dim.estados (id_estado),  -- UF da CAMADA do INCRA de onde veio (e a jurisdicao da superintendencia, nao a UF do poligono)
    id_estado          smallint REFERENCES dim.estados (id_estado),           -- UF onde o poligono esta (ponto na superficie dentro de dim.estados); calculado apos a carga
    area_declarada_ha  numeric,                      -- area do projeto (repete em cada poligono dele)
    area_calc_ha       numeric,                      -- area calculada do poligono (nula em alguns)
    capacidade_familias integer,
    num_familias       integer,                      -- familias assentadas
    fase               smallint,                     -- codigo da fase do projeto no SIPRA (3 a 7, 10); o servidor nao traz a descricao
    data_criacao       date,
    forma_obtencao     text,
    data_obtencao      date,
    geom               geometry(MultiPolygon, 4674) NOT NULL,
    id_fonte           smallint NOT NULL REFERENCES dim.fontes (id_fonte),
    importado_em       date NOT NULL DEFAULT current_date,   -- ultima vez que a linha MUDOU
    visto_em           date NOT NULL DEFAULT current_date    -- ultima coleta em que o poligono ainda existia no INCRA
);
CREATE INDEX IF NOT EXISTS idx_incra_assent_geom   ON vetorial.incra_assentamentos USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_incra_assent_sipra  ON vetorial.incra_assentamentos (cd_sipra);
CREATE INDEX IF NOT EXISTS idx_incra_assent_estado ON vetorial.incra_assentamentos (id_estado);
COMMENT ON TABLE vetorial.incra_assentamentos IS
    'Poligonos de projetos de assentamento do INCRA (WFS publico do Acervo Fundiario, uma camada por UF). Coordenadas rotuladas WGS84 pela fonte e gravadas como SIRGAS 2000 (4674) sem transformar (diferenca abaixo de 1 m). Uso comercial vedado pela fonte. Ver incra/assentamentos/LEIAME_assentamentos.md.';
COMMENT ON COLUMN vetorial.incra_assentamentos.id_estado_camada IS 'Camada do INCRA de origem. A camada DF e a jurisdicao do DF: 204 de 208 poligonos estao em GO e MG; a de PE traz projetos na BA. Para filtrar por estado use id_estado.';
COMMENT ON COLUMN vetorial.incra_assentamentos.area_declarada_ha IS 'Area do projeto, repetida em cada poligono do mesmo cd_sipra: nao somar por linha.';
COMMENT ON COLUMN vetorial.incra_assentamentos.visto_em IS 'Ultima coleta em que o poligono ainda apareceu no servidor; menor que a data da ultima coleta da UF = sumiu do INCRA (nunca apagamos).';

-- O ETL so grava nesta tabela (DML); nao cria nem apaga
GRANT SELECT, INSERT, UPDATE ON vetorial.incra_assentamentos TO etl;
GRANT USAGE ON SEQUENCE vetorial.incra_assentamentos_id_seq TO etl;

SELECT 'dim.fontes INCRA' AS item, id_fonte::text AS valor FROM dim.fontes WHERE nome = 'INCRA'
UNION ALL SELECT 'vetorial.incra_assentamentos', count(*)::text FROM vetorial.incra_assentamentos
UNION ALL SELECT 'leitura pode ler', has_table_privilege('leitura', 'vetorial.incra_assentamentos', 'SELECT')::text
UNION ALL SELECT 'geoserver pode ler', has_table_privilege('geoserver', 'vetorial.incra_assentamentos', 'SELECT')::text;
