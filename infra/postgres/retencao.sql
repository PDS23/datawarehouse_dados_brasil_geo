-- Permissoes da rotina de retencao (infra/scripts/limpar_versoes_fechadas.py): o papel etl so tem DML nas tabelas que ele escreve;
-- para apagar versoes fechadas precisa de DELETE nestas tabelas especificas (nada mais).
-- Rodar como postgres:
--   Get-Content infra\postgres\retencao.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
-- Idempotente. Cada GRANT so roda se a tabela existir (as de resultados.* nascem quando o calculo correspondente e rodado).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['vetorial.prodes_desmatamento', 'vetorial.sicar_imoveis', 'vetorial.mapbiomas_alerta', 'vetorial.funai_terras_indigenas', 'vetorial.deter_alertas', 'vetorial.ibama_embargos', 'resultados.prodes_municipio',
                           'resultados.desmatamento_imovel', 'resultados.desmatamento_imovel_controle'] LOOP
    IF to_regclass(t) IS NOT NULL THEN
      EXECUTE format('GRANT SELECT, DELETE ON %s TO etl', t);
      RAISE NOTICE 'DELETE concedido ao etl em %', t;
    END IF;
  END LOOP;
END $$;

