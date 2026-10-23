-- Reabertura de versao: imovel que sumiu do WFS e volta IDENTICO a ultima versao fechada tem essa versao reaberta
-- (vigente_ate volta a NULL, mesmo id), em vez de ganhar uma versao nova. reaberto_em registra quando.
-- Rodar como postgres (operacao so de metadados: coluna nova sem valor padrao, instantanea):
--   Get-Content sicar\imoveis\sql\04_reabertura.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. Decidido com o usuario em 2026-10-21 (vale tambem para o PRODES).
ALTER TABLE vetorial.sicar_imoveis ADD COLUMN IF NOT EXISTS reaberto_em date;
COMMENT ON COLUMN vetorial.sicar_imoveis.reaberto_em IS 'Data em que o imovel voltou ao WFS identico a esta versao e ela foi reaberta (vigente_ate voltou a NULL). NULL = nunca reaberta.';
ALTER TABLE catalogo.coletas ADD COLUMN IF NOT EXISTS reabertos bigint;
COMMENT ON COLUMN catalogo.coletas.reabertos IS 'Versoes reabertas na coleta (feicao retirada pela fonte e republicada identica).';
INSERT INTO catalogo.mapa_colunas (tabela, coluna, origem, fonte, observacao) VALUES
    ('vetorial.sicar_imoveis', 'reaberto_em', 'controle', 'pipeline', 'data da reabertura da versao; NULL = nunca reaberta')
ON CONFLICT (tabela, coluna) DO UPDATE SET origem = EXCLUDED.origem, fonte = EXCLUDED.fonte, observacao = EXCLUDED.observacao;
SELECT count(*) AS reabertas FROM vetorial.sicar_imoveis WHERE reaberto_em IS NOT NULL;
