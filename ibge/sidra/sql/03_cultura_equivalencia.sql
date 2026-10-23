-- Cultura canonica e equivalencia entre classificacoes do SIDRA (PAM c782 x Censo Agropecuario c227): para juntar PAM, Censo e LSPA.
-- Rodar como postgres, DEPOIS de 01_camada_generica.sql, de dim.cultura (PAM) e de dim.sidra_categoria da c227 estarem preenchidas
-- (o pipeline do SIDRA cadastra as categorias na primeira execucao, inclusive com --listar):
--   .\infra\scripts\dw.ps1 psql -Arquivo ibge\sidra\sql\03_cultura_equivalencia.sql
-- Idempotente. Decisao de 2026-10-23: o id da cultura canonica das culturas que a PAM ja tem e o proprio codigo da PAM (c782), para nao trocar
-- os ids das 238 mil linhas de tabular.ibge_pam nem quebrar consultas que usam esses ids; culturas SEM equivalente na PAM (so o Censo traz) recebem
-- ids a partir de 900001 (sequencia dim.cultura_id_extra_seq). id_cultura e portanto um id NOSSO, que coincide com o codigo c782 onde a PAM existe.

-- ---------------------------------------------------------------- tabela de equivalencia
CREATE TABLE IF NOT EXISTS dim.cultura_equivalencia (
    id_categoria integer PRIMARY KEY REFERENCES dim.sidra_categoria (id_categoria),   -- categoria de uma classificacao do SIDRA
    id_cultura   integer NOT NULL REFERENCES dim.cultura (id_cultura)                 -- cultura canonica
);
CREATE INDEX IF NOT EXISTS ix_cultura_equivalencia_cultura ON dim.cultura_equivalencia (id_cultura);
COMMENT ON TABLE dim.cultura_equivalencia IS
    'Liga cada categoria de produto do SIDRA (PAM c782, Censo c227...) a uma cultura canonica de dim.cultura. Varias categorias podem apontar para a mesma cultura (ex.: uva de mesa e de vinho).';
COMMENT ON TABLE dim.cultura IS
    'Culturas canonicas. Onde a PAM tem a cultura, id_cultura = codigo SIDRA c782 (soja 40124); culturas so do Censo recebem ids a partir de 900001. dim.cultura_equivalencia liga as categorias do SIDRA a ela.';
CREATE SEQUENCE IF NOT EXISTS dim.cultura_id_extra_seq START 900001;

-- ---------------------------------------------------------------- PAM (c782) como classificacao do SIDRA
INSERT INTO dim.sidra_classificacao (id_classificacao, nome)
VALUES (782, 'Produto das lavouras temporárias e permanentes')
ON CONFLICT (id_classificacao) DO NOTHING;

INSERT INTO dim.sidra_categoria (id_classificacao, codigo_sidra, nome, ordem)
SELECT 782, c.id_cultura, c.nome, row_number() OVER (ORDER BY c.id_cultura)
FROM dim.cultura c WHERE c.id_cultura < 900000
ON CONFLICT (id_classificacao, codigo_sidra) DO NOTHING;

-- cada categoria da PAM aponta para a propria cultura
INSERT INTO dim.cultura_equivalencia (id_categoria, id_cultura)
SELECT g.id_categoria, c.id_cultura
FROM dim.sidra_categoria g JOIN dim.cultura c ON c.id_cultura = g.codigo_sidra
WHERE g.id_classificacao = 782 AND c.id_cultura < 900000
ON CONFLICT (id_categoria) DO NOTHING;

-- ---------------------------------------------------------------- Censo (c227): culturas que o Censo traz e a PAM nao
-- (mudas e "Outros produtos" nao sao culturas: ficam sem equivalencia)
INSERT INTO dim.cultura (id_cultura, nome, slug, nota_ibge, id_fonte)
SELECT nextval('dim.cultura_id_extra_seq'), t.nome,
       trim(both '_' from regexp_replace(lower(translate(t.nome, 'áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÉÊÍÓÔÕÚÇ', 'aaaaaeeeeiiiiooooouuuucnAAAAEEIOOOUC')), '[^a-z0-9]+', '_', 'g')),
       false, (SELECT id_fonte FROM dim.fontes WHERE nome = 'IBGE')
FROM (SELECT g.nome FROM dim.sidra_categoria g
      WHERE g.id_classificacao = 227
        AND g.codigo_sidra IN (111645, 4926, 4927, 4928, 40626, 111649, 4940, 4946, 4951, 4955, 4956, 4957, 4960, 111650, 4962, 4964, 4971, 4972,
                               40627, 111651, 111653, 111652)
        AND NOT EXISTS (SELECT 1 FROM dim.cultura_equivalencia e WHERE e.id_categoria = g.id_categoria)
      ORDER BY g.nome) t
ON CONFLICT (slug) DO NOTHING;

-- categorias do Censo com equivalente na PAM: (codigo c227, codigo c782). Revisar aqui se o IBGE mudar os nomes.
WITH mapa(c227, c782) AS (VALUES
    (4921, 40129), (4996, 45982), (4922, 83399), (111644, 40270), (111646, 40130), (4929, 40131), (4930, 40136), (4932, 40137), (4931, 40468),
    (4933, 40138), (111647, 40140), (111648, 40141), (4936, 40143), (4937, 40330), (4939, 40142), (4943, 40144), (4945, 40145), (4997, 83400),
    (4947, 40146), (4948, 40147), (4949, 40148), (4952, 40149), (4953, 83401), (4954, 40150), (4961, 40151), (4963, 40152), (4966, 40260),
    (4967, 40261), (4968, 40262), (4969, 40263), (4973, 40265), (4976, 40266), (4977, 40267), (4978, 40268), (4979, 40269), (4982, 40271),
    (4984, 40273), (4985, 40274), (4986, 40274))
INSERT INTO dim.cultura_equivalencia (id_categoria, id_cultura)
SELECT g.id_categoria, m.c782
FROM mapa m JOIN dim.sidra_categoria g ON g.id_classificacao = 227 AND g.codigo_sidra = m.c227
WHERE EXISTS (SELECT 1 FROM dim.cultura c WHERE c.id_cultura = m.c782)
ON CONFLICT (id_categoria) DO NOTHING;

-- a fonte escreve 'kiwi' em minusculas
UPDATE dim.cultura SET nome = 'Kiwi' WHERE id_cultura >= 900000 AND nome = 'kiwi';

-- as culturas novas (so do Censo) recebem a propria categoria do Censo, pelo nome
INSERT INTO dim.cultura_equivalencia (id_categoria, id_cultura)
SELECT g.id_categoria, c.id_cultura
FROM dim.sidra_categoria g JOIN dim.cultura c ON c.id_cultura >= 900000 AND lower(c.nome) = lower(g.nome)
WHERE g.id_classificacao = 227
ON CONFLICT (id_categoria) DO NOTHING;

-- ---------------------------------------------------------------- permissoes (o etl so faz DML)
GRANT SELECT, INSERT, UPDATE ON dim.cultura_equivalencia TO etl;
GRANT USAGE ON SEQUENCE dim.cultura_id_extra_seq TO etl;
GRANT MAINTAIN ON dim.cultura_equivalencia TO etl;

SELECT 'dim.cultura' AS tabela, count(*)::text AS linhas FROM dim.cultura
UNION ALL SELECT '  so do Censo (id >= 900001)', count(*)::text FROM dim.cultura WHERE id_cultura >= 900000
UNION ALL SELECT 'dim.cultura_equivalencia', count(*)::text FROM dim.cultura_equivalencia
UNION ALL SELECT '  categorias do Censo (c227) com cultura', count(*)::text FROM dim.cultura_equivalencia e JOIN dim.sidra_categoria g USING (id_categoria) WHERE g.id_classificacao = 227
UNION ALL SELECT '  categorias do Censo (c227) sem cultura', count(*)::text FROM dim.sidra_categoria g WHERE g.id_classificacao = 227
    AND NOT EXISTS (SELECT 1 FROM dim.cultura_equivalencia e WHERE e.id_categoria = g.id_categoria);
