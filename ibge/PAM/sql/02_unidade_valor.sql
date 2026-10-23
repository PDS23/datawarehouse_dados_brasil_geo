-- PAM: o valor da producao ate 1993 NAO esta em reais (executado em 2026-10-14).
-- A API rotula a variavel 215 como "Mil Reais" em todos os anos, mas a serie nacional quebra a cada
-- reforma monetaria (laranja: razao entre anos vizinhos de 0,00 em 1985, 4,03 em 1987, 16,50 em 1988,
-- 0,02 em 1989, 11,22 em 1992, 0,03 em 1993, 0,01 em 1994). So de 1994 em diante a serie e comparavel.
-- Acrescenta unidade_valor, como unidade_quantidade e unidade_rendimento.
-- Rodar como postgres:
--   Get-Content ibge\PAM\sql\02_unidade_valor.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente (em banco novo, depois do 01_esquema.sql, nao faz nada). So ASCII de proposito.

ALTER TABLE tabular.ibge_pam ADD COLUMN IF NOT EXISTS unidade_valor text NOT NULL DEFAULT 'mil reais';
COMMENT ON COLUMN tabular.ibge_pam.unidade_valor IS
    'Ate 1993 o valor esta na moeda nominal da epoca (cruzeiro, cruzado, cruzado novo, cruzeiro real): nao comparavel entre anos nem com reais. De 1994 em diante, mil reais (nominais, sem deflacionar).';
COMMENT ON COLUMN tabular.ibge_pam.valor_producao_mil_reais IS
    'v215. Mil reais nominais so de 1994 em diante; antes, ver unidade_valor.';

UPDATE tabular.ibge_pam
SET unidade_valor = 'moeda nominal da epoca (pre-Real; nao comparavel)'
WHERE ano <= 1993 AND unidade_valor = 'mil reais';

SELECT unidade_valor, min(ano) AS de, max(ano) AS ate, count(*) AS linhas FROM tabular.ibge_pam GROUP BY 1 ORDER BY 2;
