-- Troca da tabela de PRODES: o espelho versionado (prodes_novo) assume vetorial.prodes_desmatamento; a da carga manual de
-- 2026-09 fica guardada como vetorial.prodes_desmatamento_carga_manual_antiga (NAO e apagada; apagar e decisao a parte).
-- Rodar como postgres, UMA vez, DEPOIS do backup e com a ponte nova ja construida e validada (refazer_ponte_municipio.ps1):
--   Get-Content prodes\desmatamento\sql\03_troca.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Em seguida: refazer_ponte_municipio.ps1 -Trocar -SufixoAntiga carga_manual_antiga  (troca a ponte e recria a view v_prodes_municipio
-- so com os vigentes), infra/postgres/retencao.sql (DELETE do etl na tabela movida) e publicar_geoserver.py --recriar v_prodes_municipio.
-- Uma transacao: ou troca tudo, ou nada. So ASCII de proposito.
BEGIN;

DO $$ BEGIN
  IF to_regclass('prodes_novo.prodes_desmatamento') IS NULL THEN RAISE EXCEPTION 'prodes_novo.prodes_desmatamento nao existe'; END IF;
  IF to_regclass('vetorial.prodes_desmatamento_carga_manual_antiga') IS NOT NULL THEN RAISE EXCEPTION 'a troca ja foi feita'; END IF;
  IF to_regclass('resultados.prodes_municipio_nova') IS NULL THEN RAISE EXCEPTION 'a ponte nova (resultados.prodes_municipio_nova) nao existe: construa antes'; END IF;
  IF (SELECT count(*) FROM prodes_novo.prodes_desmatamento WHERE vigente_ate IS NULL) = 0 THEN RAISE EXCEPTION 'prodes_novo sem versoes vigentes'; END IF;
END $$;

-- 1) a da carga manual sai do caminho (a view v_prodes_municipio depende dela: e recriada na troca da ponte)
DROP VIEW vetorial.v_prodes_municipio;
ALTER TABLE vetorial.prodes_desmatamento RENAME TO prodes_desmatamento_carga_manual_antiga;
ALTER TABLE vetorial.prodes_desmatamento_carga_manual_antiga RENAME CONSTRAINT prodes_desmatamento_pkey TO prodes_desmatamento_carga_manual_antiga_pkey;
ALTER INDEX vetorial.idx_prodes_bioma     RENAME TO idx_prodes_bioma_carga_manual_antiga;
ALTER INDEX vetorial.idx_prodes_id_bioma  RENAME TO idx_prodes_id_bioma_carga_manual_antiga;
ALTER INDEX vetorial.idx_prodes_id_estado RENAME TO idx_prodes_id_estado_carga_manual_antiga;
ALTER INDEX vetorial.idx_prodes_uuid      RENAME TO idx_prodes_uuid_carga_manual_antiga;
ALTER INDEX vetorial.prodes_desmatamento_geom_geom_idx RENAME TO idx_prodes_geom_carga_manual_antiga;
ALTER TABLE vetorial.prodes_desmatamento_carga_manual_antiga RENAME CONSTRAINT prodes_desmatamento_id_bioma_fkey  TO prodes_desmatamento_id_bioma_fkey_carga_manual_antiga;
ALTER TABLE vetorial.prodes_desmatamento_carga_manual_antiga RENAME CONSTRAINT prodes_desmatamento_id_estado_fkey TO prodes_desmatamento_id_estado_fkey_carga_manual_antiga;
ALTER TABLE vetorial.prodes_desmatamento_carga_manual_antiga RENAME CONSTRAINT prodes_desmatamento_id_fonte_fkey  TO prodes_desmatamento_id_fonte_fkey_carga_manual_antiga;
ALTER SEQUENCE vetorial.prodes_desmatamento_id_seq RENAME TO prodes_desmatamento_carga_manual_antiga_id_seq;
COMMENT ON TABLE vetorial.prodes_desmatamento_carga_manual_antiga IS
  'GUARDADA: PRODES da carga manual de 2026-09 (ogr2ogr), substituida em 2026-10-21 pelo espelho versionado vetorial.prodes_desmatamento. state truncado em 2 letras. Apagar so com aprovacao do usuario.';

-- 2) o espelho assume o nome
ALTER TABLE prodes_novo.prodes_desmatamento SET SCHEMA vetorial;
ALTER TABLE vetorial.prodes_desmatamento RENAME CONSTRAINT prodes_novo_fk_fonte  TO prodes_desmatamento_id_fonte_fkey;
ALTER TABLE vetorial.prodes_desmatamento RENAME CONSTRAINT prodes_novo_fk_bioma  TO prodes_desmatamento_id_bioma_fkey;
ALTER TABLE vetorial.prodes_desmatamento RENAME CONSTRAINT prodes_novo_fk_estado TO prodes_desmatamento_id_estado_fkey;
GRANT SELECT ON vetorial.prodes_desmatamento TO leitura, geoserver, analistas;

-- 3) catalogo: as coletas e cargas feitas na tabela de construcao passam a ser da tabela definitiva
UPDATE catalogo.coletas SET dataset = 'vetorial.prodes_desmatamento' WHERE dataset = 'prodes_novo.prodes_desmatamento';
UPDATE catalogo.cargas  SET dataset = 'vetorial.prodes_desmatamento' WHERE dataset = 'prodes_novo.prodes_desmatamento';
UPDATE catalogo.datasets SET
    nome = 'PRODES - Desmatamento anual por bioma (INPE/TerraBrasilis)',
    ano_referencia = (SELECT max(year) FROM vetorial.prodes_desmatamento WHERE vigente_ate IS NULL),
    data_importacao = current_date,
    observacoes = 'Espelho versionado do INPE (yearly_deforestation por bioma; Amazonia tambem a nao-floresta). Vigente = vigente_ate IS NULL. Ver prodes/desmatamento/LEIAME_prodes_desmatamento.md.'
WHERE schema_tabela = 'vetorial.prodes_desmatamento';

-- 4) schema de construcao vazio: sai
DROP SCHEMA prodes_novo;

COMMIT;

ANALYZE vetorial.prodes_desmatamento;
SELECT 'vetorial.prodes_desmatamento (espelho, em uso)' AS item, count(*)::text AS valor FROM vetorial.prodes_desmatamento
UNION ALL SELECT '  vigentes', count(*)::text FROM vetorial.prodes_desmatamento WHERE vigente_ate IS NULL
UNION ALL SELECT 'vetorial.prodes_desmatamento_carga_manual_antiga (guardada)', count(*)::text FROM vetorial.prodes_desmatamento_carga_manual_antiga
UNION ALL SELECT 'coletas do PRODES', count(*)::text FROM catalogo.coletas WHERE dataset = 'vetorial.prodes_desmatamento';
