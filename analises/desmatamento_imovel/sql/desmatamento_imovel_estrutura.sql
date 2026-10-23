-- Estrutura de resultados.desmatamento_imovel (desmatamento PRODES por imovel do SICAR).
-- Rodar como postgres (o script analises/desmatamento_imovel/scripts/desmatamento_imovel.ps1 ja faz isso sozinho, e e idempotente):
--   Get-Content analises\desmatamento_imovel\sql\desmatamento_imovel_estrutura.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- So ASCII de proposito.
--
-- Decisoes: o desmatamento acompanha o IMOVEL (cod_imovel, estavel entre versoes do SICAR); id_imovel_sicar guarda o id da versao
-- VIGENTE em que foi calculado. A tabela de controle diz quais versoes de imovel ja foram processadas (inclusive as sem
-- desmatamento algum) E COM QUAL EDICAO DO PRODES: (2026-10-21) o resultado depende das duas fontes, entao a versao do imovel
-- ou uma edicao nova do PRODES tornam o resultado desatualizado e ele e recalculado. As views v_*_vigente mostram so o que
-- ainda vale; as tabelas completas ficam para auditoria. Nenhuma coluna 'vigente' e copiada para o resultado (ela mesma
-- ficaria desatualizada): o status vem do cruzamento com a origem.

CREATE TABLE IF NOT EXISTS resultados.desmatamento_imovel (
    id                bigserial PRIMARY KEY,
    id_imovel_sicar   bigint   NOT NULL REFERENCES vetorial.sicar_imoveis (id),   -- versao do imovel usada no calculo
    cod_imovel        text     NOT NULL,
    ano               smallint NOT NULL,                                          -- ano PRODES
    id_bioma          smallint NOT NULL REFERENCES dim.biomas (id_bioma),
    area_desmatada_ha numeric(14, 2) NOT NULL,
    pct_area_imovel   numeric(8, 2),
    calculado_em      date     NOT NULL DEFAULT current_date
);
CREATE INDEX IF NOT EXISTS idx_desmatamento_imovel_cod ON resultados.desmatamento_imovel (cod_imovel);
CREATE INDEX IF NOT EXISTS idx_desmatamento_imovel_id  ON resultados.desmatamento_imovel (id_imovel_sicar);
COMMENT ON TABLE resultados.desmatamento_imovel IS
    'Desmatamento PRODES por imovel do SICAR, por ano e bioma. Metodo: ver analises/desmatamento_imovel/LEIAME_desmatamento_imovel.md. Ligue pelo cod_imovel (estavel); id_imovel_sicar e a versao do imovel em que foi calculado. Para ver so o que ainda vale use resultados.v_desmatamento_imovel_vigente.';
COMMENT ON COLUMN resultados.desmatamento_imovel.cod_imovel IS 'Codigo do imovel no CAR; estavel entre versoes do SICAR. Use este para juntar.';
COMMENT ON COLUMN resultados.desmatamento_imovel.id_imovel_sicar IS 'id da versao do imovel (vetorial.sicar_imoveis) usada no calculo.';
COMMENT ON COLUMN resultados.desmatamento_imovel.pct_area_imovel IS 'Area desmatada / num_area do imovel x 100, limitada a 999,99 (imoveis de area minuscula).';

CREATE TABLE IF NOT EXISTS resultados.desmatamento_imovel_controle (
    id_imovel_sicar bigint   PRIMARY KEY REFERENCES vetorial.sicar_imoveis (id),   -- versao do imovel processada
    cod_imovel      text     NOT NULL,
    cod_estado      text     NOT NULL,
    ano_prodes_max  smallint,                                                      -- ultimo ano PRODES existente no calculo
    edicoes_prodes  text     NOT NULL,                                             -- edicoes do PRODES usadas, ex.: amazonia=20261016,caatinga=20260805,...
    calculado_em    date     NOT NULL DEFAULT current_date
);
CREATE INDEX IF NOT EXISTS idx_desmat_controle_uf ON resultados.desmatamento_imovel_controle (cod_estado);
CREATE INDEX IF NOT EXISTS idx_desmat_controle_cod ON resultados.desmatamento_imovel_controle (cod_imovel);
COMMENT ON TABLE resultados.desmatamento_imovel_controle IS
    'Versoes de imovel ja processadas por analises/desmatamento_imovel/scripts/desmatamento_imovel.ps1 (inclusive as sem desmatamento) e com que edicao do PRODES. Versao vigente fora daqui, ou processada com edicao antiga do PRODES = pendente.';

-- Edicoes do PRODES hoje no banco (a mais recente carregada de cada bioma), no mesmo formato de edicoes_prodes
CREATE OR REPLACE VIEW catalogo.v_edicoes_prodes AS
SELECT coalesce(string_agg(recorte || '=' || edicao, ',' ORDER BY recorte), '') AS edicoes
FROM (SELECT DISTINCT ON (recorte) recorte, edicao FROM catalogo.coletas
      WHERE dataset = 'vetorial.prodes_desmatamento' AND edicao IS NOT NULL ORDER BY recorte, coletado_em DESC) t;
COMMENT ON VIEW catalogo.v_edicoes_prodes IS 'Edicao vigente do PRODES por bioma, numa linha so; compara com resultados.desmatamento_imovel_controle.edicoes_prodes.';

-- So o que ainda vale: versao do imovel vigente E calculada com as edicoes atuais do PRODES
CREATE OR REPLACE VIEW resultados.v_desmatamento_imovel_vigente AS
SELECT d.*
FROM resultados.desmatamento_imovel d
JOIN vetorial.sicar_imoveis s ON s.id = d.id_imovel_sicar AND s.vigente_ate IS NULL
JOIN resultados.desmatamento_imovel_controle c ON c.id_imovel_sicar = d.id_imovel_sicar
WHERE c.edicoes_prodes = (SELECT edicoes FROM catalogo.v_edicoes_prodes);
COMMENT ON VIEW resultados.v_desmatamento_imovel_vigente IS 'Desmatamento por imovel que ainda vale: versao do imovel vigente e calculada com as edicoes atuais do PRODES. Use esta no dia a dia.';

GRANT SELECT ON resultados.desmatamento_imovel, resultados.desmatamento_imovel_controle, resultados.v_desmatamento_imovel_vigente,
                catalogo.v_edicoes_prodes TO leitura, analistas;

SELECT 'linhas em desmatamento_imovel' AS item, count(*)::text AS valor FROM resultados.desmatamento_imovel
UNION ALL SELECT 'controle', count(*)::text FROM resultados.desmatamento_imovel_controle
UNION ALL SELECT 'edicoes atuais do PRODES', edicoes FROM catalogo.v_edicoes_prodes;
