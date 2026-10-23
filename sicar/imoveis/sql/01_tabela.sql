-- SICAR reconstruido do zero a partir do WFS do CAR: tabela nova, catalogo de coletas e mapa de colunas.
-- Rodar como postgres:
--   Get-Content sicar\imoveis\sql\01_tabela.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. So ASCII de proposito.
--
-- A tabela nasce no schema de CONSTRUCAO sicar_novo (a vetorial.sicar_imoveis atual, vinda do pacote GeoPackage, segue
-- intacta). Depois de carregar e validar, 03_troca_unica.sql move a nova para vetorial e guarda a antiga renomeada.
-- Indices secundarios e chaves estrangeiras so depois da carga (02_indices_chaves.sql): carregar com eles e bem mais lento.
--
-- Regras (decididas com o usuario em 2026-10-20): uma fonte so (WFS do CAR), todas as colunas dele, cancelados inclusive,
-- nomes das colunas = os nossos de sempre (mapa em catalogo.mapa_colunas), historico por versao (vigente_desde/ate).

CREATE SCHEMA IF NOT EXISTS sicar_novo;

CREATE TABLE IF NOT EXISTS sicar_novo.sicar_imoveis (
    id               bigserial PRIMARY KEY,
    fid_wfs          text        NOT NULL,                 -- id da feicao no WFS (sicar_imoveis_<uf>.<n>)
    cod_imovel       text        NOT NULL,                 -- WFS: cod_imovel
    cod_estado       text        NOT NULL,                 -- WFS: uf
    id_estado        smallint    NOT NULL,                 -- derivado de uf (dim.estados)
    municipio        text,                                 -- WFS: municipio
    id_municipio     integer,                              -- WFS: cod_municipio_ibge (NULL se nao existir em dim.municipios)
    des_condic       text,                                 -- WFS: condicao
    ind_status       text,                                 -- WFS: status_imovel (AT ativo, PE pendente, SU suspenso, CA cancelado)
    num_area         numeric,                              -- WFS: area (ha)
    dat_criacao      timestamptz,                          -- WFS: dat_criacao
    dat_atualizacao  timestamptz,                          -- WFS: data_atualizacao
    mod_fiscal       numeric,                              -- WFS: m_fiscal
    ind_tipo         text,                                 -- WFS: tipo_imovel (IRU rural, AST assentamento, PCT povos e comunidades)
    geom             geometry(MultiPolygon, 4674),         -- WFS: geometria (EPSG:4326 rotulado, gravado como 4674 sem transformar)
    geom_anomala     boolean     NOT NULL DEFAULT false,   -- true = coordenadas fora do Brasil ou sem geometria na origem
    geom_origem_texto text,                                -- EWKT como o WFS entregou, SO quando geom_anomala (geom fica NULL)
    id_fonte         smallint    NOT NULL,
    importado_em     date        NOT NULL DEFAULT current_date,
    vigente_desde    date        NOT NULL DEFAULT current_date,
    vigente_ate      date,
    coletado_em      timestamptz NOT NULL DEFAULT now(),
    reaberto_em      date                                  -- data em que a versao foi reaberta (imovel voltou identico ao WFS); ver 04_reabertura.sql
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sicar_imoveis_vigente ON sicar_novo.sicar_imoveis (cod_imovel) WHERE vigente_ate IS NULL;

COMMENT ON TABLE sicar_novo.sicar_imoveis IS
    'Imoveis do SICAR (CAR), carregados do zero e atualizados SO pelo WFS publico do CAR (geoserver.car.gov.br), cancelados inclusive. Historico por versao: vigente = vigente_ate IS NULL. Ver sicar/imoveis/LEIAME_sicar_imoveis.md.';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.fid_wfs IS 'Origem: id da feicao no WFS (sicar_imoveis_<uf>.<numero>).';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.cod_imovel IS 'Origem: WFS cod_imovel. Chave estavel entre versoes; use para juntar.';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.cod_estado IS 'Origem: WFS uf.';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.id_municipio IS 'Origem: WFS cod_municipio_ibge (codigo IBGE de 7 digitos); NULL se o codigo nao existir em dim.municipios.';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.des_condic IS 'Origem: WFS condicao (situacao de analise do cadastro).';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.ind_status IS 'Origem: WFS status_imovel. AT ativo, PE pendente, SU suspenso, CA cancelado.';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.num_area IS 'Origem: WFS area (hectares, declarada no cadastro).';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.dat_criacao IS 'Origem: WFS dat_criacao (com hora).';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.dat_atualizacao IS 'Origem: WFS data_atualizacao (com hora). Nem toda mudanca de status atualiza esta data.';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.mod_fiscal IS 'Origem: WFS m_fiscal (modulos fiscais).';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.ind_tipo IS 'Origem: WFS tipo_imovel. IRU rural, AST assentamento, PCT povos e comunidades tradicionais.';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.geom IS 'Origem: geometria do WFS (geo_area_imovel). NULL quando geom_anomala (o original esta em geom_origem_texto).';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.geom_anomala IS 'true = o WFS entregou coordenadas fora do Brasil (x -75..-28, y -35..6) ou nenhuma geometria; mantido o texto original em geom_origem_texto.';
COMMENT ON COLUMN sicar_novo.sicar_imoveis.coletado_em IS 'Momento (UTC) da coleta no WFS em que esta versao entrou.';

-- Registro de cada coleta: de onde veio e quando (por dataset e recorte, ex.: UF)
CREATE TABLE IF NOT EXISTS catalogo.coletas (
    id              bigserial PRIMARY KEY,
    dataset         text        NOT NULL,                 -- ex.: vetorial.sicar_imoveis
    recorte         text        NOT NULL,                 -- ex.: AC
    fonte           text        NOT NULL,                 -- ex.: WFS do CAR (geoserver.car.gov.br)
    url             text,
    metodo          text,                                 -- ex.: reconciliacao por fatias de municipio, 4 agentes
    coletado_em     timestamptz NOT NULL DEFAULT now(),
    total_anunciado bigint,                               -- numberMatched do servidor
    linhas_lidas    bigint,
    novos           bigint,
    versoes_novas   bigint,
    fechados        bigint,
    inalterados     bigint,
    id_carga        bigint,                               -- catalogo.cargas.id
    observacao      text
);
CREATE INDEX IF NOT EXISTS idx_coletas_dataset_recorte ON catalogo.coletas (dataset, recorte, coletado_em DESC);
COMMENT ON TABLE catalogo.coletas IS 'Cada coleta de dados de uma fonte (dataset x recorte): origem, metodo, quando e quanto. A ultima de cada recorte esta em catalogo.v_ultima_coleta.';
CREATE OR REPLACE VIEW catalogo.v_ultima_coleta AS
SELECT DISTINCT ON (dataset, recorte) dataset, recorte, fonte, metodo, coletado_em, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, inalterados, id_carga, observacao
FROM catalogo.coletas ORDER BY dataset, recorte, coletado_em DESC;

-- Feicoes descartadas quando o WFS entrega o MESMO cod_imovel em duas feicoes (retificacao em andamento: a feicao nova
-- convive com a velha ate o CAR remove-la). Regra (decidida com o usuario em 2026-10-20, conferida contra 5 demonstrativos
-- do SICAR): fica a de maior data_atualizacao (nula = a menor); empate: o maior identificador da feicao.
CREATE TABLE IF NOT EXISTS catalogo.coletas_duplicados (
    id                bigserial PRIMARY KEY,
    dataset           text        NOT NULL,
    recorte           text        NOT NULL,
    cod_imovel        text        NOT NULL,
    fid_mantido       text        NOT NULL,
    fid_descartado    text        NOT NULL,
    status_mantido    text, status_descartado    text,
    condicao_mantida  text, condicao_descartada  text,
    dat_criacao_mantida timestamptz, dat_criacao_descartada timestamptz,
    dat_atualizacao_mantida timestamptz, dat_atualizacao_descartada timestamptz,
    regra             text        NOT NULL,
    id_carga          bigint,
    coletado_em       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_coletas_duplicados_cod ON catalogo.coletas_duplicados (cod_imovel);
COMMENT ON TABLE catalogo.coletas_duplicados IS 'cod_imovel repetido no WFS do CAR: a feicao mantida e a descartada de cada coleta, com a regra aplicada.';
GRANT SELECT, INSERT ON catalogo.coletas_duplicados TO etl;
GRANT USAGE ON SEQUENCE catalogo.coletas_duplicados_id_seq TO etl;
GRANT SELECT ON catalogo.coletas_duplicados TO leitura, analistas;

-- Mapa de colunas: de onde vem cada coluna da nossa tabela (nome na fonte x nome nosso)
CREATE TABLE IF NOT EXISTS catalogo.mapa_colunas (
    tabela      text NOT NULL,
    coluna      text NOT NULL,
    origem      text NOT NULL,           -- campo na fonte, ou 'derivado' / 'controle'
    fonte       text NOT NULL,
    observacao  text,
    PRIMARY KEY (tabela, coluna)
);
COMMENT ON TABLE catalogo.mapa_colunas IS 'Rastreabilidade: nome do campo na fonte x nome da coluna no banco.';
INSERT INTO catalogo.mapa_colunas (tabela, coluna, origem, fonte, observacao) VALUES
    ('vetorial.sicar_imoveis', 'fid_wfs',         'id da feicao',        'WFS do CAR', 'sicar_imoveis_<uf>.<n>'),
    ('vetorial.sicar_imoveis', 'cod_imovel',      'cod_imovel',          'WFS do CAR', NULL),
    ('vetorial.sicar_imoveis', 'cod_estado',      'uf',                  'WFS do CAR', NULL),
    ('vetorial.sicar_imoveis', 'id_estado',       'derivado de uf',      'dim.estados', NULL),
    ('vetorial.sicar_imoveis', 'municipio',       'municipio',           'WFS do CAR', NULL),
    ('vetorial.sicar_imoveis', 'id_municipio',    'cod_municipio_ibge',  'WFS do CAR', 'NULL se o codigo nao existir em dim.municipios'),
    ('vetorial.sicar_imoveis', 'des_condic',      'condicao',            'WFS do CAR', NULL),
    ('vetorial.sicar_imoveis', 'ind_status',      'status_imovel',       'WFS do CAR', 'AT, PE, SU, CA'),
    ('vetorial.sicar_imoveis', 'num_area',        'area',                'WFS do CAR', 'hectares'),
    ('vetorial.sicar_imoveis', 'dat_criacao',     'dat_criacao',         'WFS do CAR', 'com hora'),
    ('vetorial.sicar_imoveis', 'dat_atualizacao', 'data_atualizacao',    'WFS do CAR', 'com hora'),
    ('vetorial.sicar_imoveis', 'mod_fiscal',      'm_fiscal',            'WFS do CAR', NULL),
    ('vetorial.sicar_imoveis', 'ind_tipo',        'tipo_imovel',         'WFS do CAR', 'IRU, AST, PCT'),
    ('vetorial.sicar_imoveis', 'geom',            'geo_area_imovel',     'WFS do CAR', 'EPSG:4326 rotulado, gravado como 4674 sem transformar; NULL se geom_anomala'),
    ('vetorial.sicar_imoveis', 'geom_anomala',    'controle',            'pipeline',   'coordenadas fora do Brasil ou sem geometria'),
    ('vetorial.sicar_imoveis', 'geom_origem_texto','geo_area_imovel',    'WFS do CAR', 'EWKT original, so quando geom_anomala'),
    ('vetorial.sicar_imoveis', 'vigente_desde',   'controle',            'pipeline',   'historico por versao'),
    ('vetorial.sicar_imoveis', 'vigente_ate',     'controle',            'pipeline',   'NULL = versao vigente'),
    ('vetorial.sicar_imoveis', 'coletado_em',     'controle',            'pipeline',   'momento da coleta')
ON CONFLICT (tabela, coluna) DO UPDATE SET origem = EXCLUDED.origem, fonte = EXCLUDED.fonte, observacao = EXCLUDED.observacao;
-- Descartadas de proposito (existiam no pacote antigo e NAO existem no WFS): nom_tema (constante) e num_retific.
INSERT INTO catalogo.mapa_colunas (tabela, coluna, origem, fonte, observacao) VALUES
    ('vetorial.sicar_imoveis', '(descartada) num_retific', 'inexistente no WFS', 'pacote GeoPackage antigo', 'numero de retificacoes: 3,12 milhoes de imoveis tinham valor > 0; nao ha como obter pelo WFS'),
    ('vetorial.sicar_imoveis', '(descartada) nom_tema',    'inexistente no WFS', 'pacote GeoPackage antigo', 'constante "Area do imovel"')
ON CONFLICT (tabela, coluna) DO NOTHING;

-- O ETL escreve na tabela nova e nos registros de coleta (DML; nao cria nem apaga)
GRANT USAGE ON SCHEMA sicar_novo TO etl;
GRANT SELECT, INSERT, UPDATE ON sicar_novo.sicar_imoveis TO etl;
GRANT USAGE ON SEQUENCE sicar_novo.sicar_imoveis_id_seq TO etl;
GRANT SELECT, INSERT ON catalogo.coletas TO etl;
GRANT USAGE ON SEQUENCE catalogo.coletas_id_seq TO etl;
GRANT SELECT ON catalogo.mapa_colunas, catalogo.v_ultima_coleta TO leitura, analistas;
GRANT SELECT ON catalogo.coletas TO leitura, analistas;

SELECT 'sicar_novo.sicar_imoveis' AS item, count(*)::text AS valor FROM sicar_novo.sicar_imoveis
UNION ALL SELECT 'catalogo.coletas', count(*)::text FROM catalogo.coletas
UNION ALL SELECT 'catalogo.mapa_colunas', count(*)::text FROM catalogo.mapa_colunas;
