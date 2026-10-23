-- Visao tipada do Censo Agropecuario 2017 (SIDRA 6956) sobre a camada generica: mesmas colunas da tabela
-- tabular.ibge_censoagro2017_estab_lavoura_perm (menos o `id`, que nao faz sentido numa visao), so valores vigentes.
-- Substituiu a tabela de mesmo nome em 2026-10-23 (ver ibge/sidra/HISTORICO.md). Rodar como postgres:
--   .\infra\scripts\dw.ps1 psql -Arquivo ibge\sidra\sql\02_visao_censo_lavoura_permanente.sql
-- Idempotente. So ASCII de proposito.
--
-- id_produto e id_grupo_area devolvem o CODIGO SIDRA (4961 = laranja), como a tabela antiga; os ids da camada estao em dim.sidra_categoria.
-- Zero ('-') nao tem linha na camada: dentro de uma linha existente a coluna que faltou vale 0, como na tabela antiga.
-- Sigilo (X): valor NULL e coluna *_sigilo = true.
-- id_cultura (ultima coluna): cultura canonica (dim.cultura) via dim.cultura_equivalencia, para juntar com a PAM; NULL nas categorias que nao sao
-- cultura (mudas, outros produtos). Rodar DEPOIS de 03_cultura_equivalencia.sql.
CREATE OR REPLACE VIEW tabular.ibge_censoagro2017_estab_lavoura_perm AS
SELECT v.id_municipio,
       c1.codigo_sidra AS id_produto,
       c2.codigo_sidra AS id_grupo_area,
       CASE WHEN bool_or(v.id_situacao = 2) FILTER (WHERE v.id_variavel = 9504) THEN NULL
            ELSE COALESCE(sum(v.valor) FILTER (WHERE v.id_variavel = 9504), 0)::integer END AS estab_50_pes_mais,
       COALESCE(bool_or(v.id_situacao = 2) FILTER (WHERE v.id_variavel = 9504), false) AS estab_50_pes_mais_sigilo,
       CASE WHEN bool_or(v.id_situacao = 2) FILTER (WHERE v.id_variavel = 10081) THEN NULL
            ELSE COALESCE(sum(v.valor) FILTER (WHERE v.id_variavel = 10081), 0)::integer END AS estab_menos_50_pes,
       COALESCE(bool_or(v.id_situacao = 2) FILTER (WHERE v.id_variavel = 10081), false) AS estab_menos_50_pes_sigilo,
       t.id_fonte,
       min(v.vigente_desde) AS importado_em,
       e.id_cultura
FROM tabular.sidra_valor v
JOIN dim.sidra_tabela t ON t.id_tabela = v.id_tabela
JOIN dim.sidra_categoria c1 ON c1.id_categoria = v.id_cat1
JOIN dim.sidra_categoria c2 ON c2.id_categoria = v.id_cat2
LEFT JOIN dim.cultura_equivalencia e ON e.id_categoria = c1.id_categoria
WHERE v.id_tabela = 6956 AND v.vigente_ate IS NULL AND v.periodo = 2017 AND v.nivel = 6
GROUP BY v.id_municipio, c1.codigo_sidra, c2.codigo_sidra, t.id_fonte, e.id_cultura;
COMMENT ON VIEW tabular.ibge_censoagro2017_estab_lavoura_perm IS
    'Censo Agropecuario 2017 (SIDRA 6956) sobre tabular.sidra_valor: estabelecimentos com lavoura permanente por municipio, produto (codigo SIDRA c227) e grupo de area (c220). Tipologia Total.';
GRANT SELECT ON tabular.ibge_censoagro2017_estab_lavoura_perm TO etl;
