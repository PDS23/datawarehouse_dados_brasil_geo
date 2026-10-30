-- Views que o GeoServer publica (nenhuma tabela de fonte e publicada direto). Idempotente (CREATE OR REPLACE).
-- Rodar como postgres:
--   .\infra\scripts\dw.ps1 psql -Arquivo infra\postgres\views_geoserver.sql
--
-- Regras:
--  1. So a versao VIGENTE (vigente_ate IS NULL): o analista ve o retrato de hoje, nao as versoes fechadas.
--  2. SEM DADO PESSOAL: as fontes de embargo (IBAMA, ICMBio, SEMA-MT) trazem nome e documento do embargado; as views deixam FORA nome, CPF/CNPJ, hash de CPF, tipo e validade do
--     documento e os campos de texto livre que podem citar pessoas (observacoes, justificativas, localizacao). FICAM os identificadores do termo (numero do TAD/termo/auto/processo)
--     para rastrear o embargo: o nome e o CNPJ de quem foi embargado se obtem com infra/scripts/consultar_embargo.py (so quem tem acesso ao banco).
--  3. Uma geometria por view (o GeoServer exige): o IBAMA tem poligono em parte dos termos e ponto em outra, entao sao duas views, sem repetir o termo.
-- A lista suja do MTE e tabular e nao e publicada no GeoServer.

-- Fontes sem dado pessoal ---------------------------------------------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW vetorial.v_funai_terras_indigenas AS
SELECT id, terrai_codigo, terrai_nome, etnia_nome, municipio_nome, uf_sigla, id_estado, superficie_perimetro_ha, fase_ti, modalidade_ti, reestudo_ti, faixa_fronteira,
       undadm_nome, undadm_sigla, dominio_uniao, data_atualizacao, vigente_desde, geom
FROM vetorial.funai_terras_indigenas WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_mma_unidades_conservacao AS
SELECT id, cd_cnuc, nome_uc, categoria, grupo, esfera, uf, municipio, org_gestor, cria_ato, ano_criacao, ha_total, quali_pol, pl_manejo, co_gestor, edicao, vigente_desde, geom
FROM vetorial.mma_unidades_conservacao WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_mma_areas_prioritarias AS
SELECT id, camada_origem, cod_area, nome_area, importancia_biologica, prioridade_acao, acao_principal_codigo, acao_principal, acoes_complementares, estados, area_ha, edicao, vigente_desde, geom
FROM vetorial.mma_areas_prioritarias WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_sfb_florestas_publicas AS
SELECT id, nome, categoria, protecao, tipo, governo, comunitari, classe, orgao, sobreposic, atolegal, ano_criacao, estagio, uf, id_estado, bioma, municipio, area_ha, edicao, vigente_desde, geom
FROM vetorial.sfb_florestas_publicas WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_deter_alertas AS
SELECT id, id_bioma, gid, classname, view_date, publish_month, sensor, satellite, areatotalkm, areamunkm, uc, municipality, mun_geocod, uf, id_estado, id_municipio, vigente_desde, geom
FROM vetorial.deter_alertas WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_mapbiomas_alerta AS
SELECT id, alert_code, area_ha, sources, biomes, states, cities, detected_at, year_detected_at, published_at, deforestation_driver, status_name,
       crossed_special_territories, crossed_rural_properties_total, vigente_desde, geom
FROM vetorial.mapbiomas_alerta WHERE vigente_ate IS NULL AND geom IS NOT NULL;

-- Fontes de embargo: identificadores, SEM nome nem documento -------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW vetorial.v_ibama_embargos_poligonos AS
SELECT id, chave_tad, num_tad, ser_tad, seq_tad, dat_embargo, num_processo, num_auto_infracao, municipio, uf, id_estado, id_municipio, qtd_area_embargada, nome_imovel, tipo_area,
       deter_prodes, sit_cancelado, sit_desembargo, tipo_desembargo, dat_desembargo, unid_controle, operacao, data_embargo_suspeita, vigente_desde, geom
FROM vetorial.ibama_embargos WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_ibama_embargos_pontos AS         -- termos SEM poligono, so com o ponto (latitude/longitude do termo)
SELECT id, chave_tad, num_tad, ser_tad, seq_tad, dat_embargo, num_processo, num_auto_infracao, municipio, uf, id_estado, id_municipio, qtd_area_embargada, nome_imovel, tipo_area,
       deter_prodes, sit_cancelado, sit_desembargo, tipo_desembargo, dat_desembargo, unid_controle, operacao, data_embargo_suspeita, vigente_desde, geom_ponto AS geom
FROM vetorial.ibama_embargos WHERE vigente_ate IS NULL AND geom IS NULL AND geom_ponto IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_icmbio_areas_embargadas AS
SELECT id, numero_emb, serie, origem, numero_ai, tipo_infra, desc_infra, desc_sanc, artigo_1, artigo_2, nome_uc, cnuc, municipio, uf, id_estado, data_embargo, ano, julgamento,
       area AS area_texto, area_informada_ha, processo, gr_nome, vigente_desde, geom
FROM vetorial.icmbio_areas_embargadas WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_sema_mt_areas_embargadas AS
SELECT id, t_embargo, n_processo, a_infrac, propriedad, dano, ano_desmat, dat_lavrat, data_lavratura, fonte, area_ha, vigente_desde, geom
FROM vetorial.sema_mt_areas_embargadas WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_sema_mt_areas_desembargadas AS   -- embargo ENCERRADO: nao e embargo vigente
SELECT id, t_embargo, n_processo, a_infrac, propriedad, dano, ano_desmat, dat_lavrat, data_lavratura, fonte, area_ha, vigente_desde, geom
FROM vetorial.sema_mt_areas_desembargadas WHERE vigente_ate IS NULL AND geom IS NOT NULL;


-- BDiA do IBGE (geologia, geomorfologia, pedologia, vegetacao): sem dado pessoal; so a versao vigente
CREATE OR REPLACE VIEW vetorial.v_ibge_geologia AS
SELECT id, id1, ordem, cd_fcim, leg_carga, id_unidade, nm_unidade, letra_simb, nm_lito1, nm_lito2, nm_lito3, nm_lito4, ar_poli_km, nm_tempo_g, nm_provinc, nm_sub_pro, cd_prov_id, cd_sub_pro, nm_tp_roc, nm_stp_roc, edicao, vigente_desde, geom
FROM vetorial.ibge_geologia WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_ibge_geomorfologia AS
SELECT id, id1, cd_fcim, leg_carga, nm_dominio, nm_regiao, id_unidade, nm_unidade, letra_simb, categoria, natureza, caract, forma, dens_dren, aprof_inci, niv_alt, leg_sup, cd_leg_sup, legenda, ar_poli_km, compartime, cd_comp_id, cd_dominio, cd_unid_id, edicao, vigente_desde, geom
FROM vetorial.ibge_geomorfologia WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_ibge_pedologia AS
SELECT id, id1, cd_fcim, nom_unidad, cod_simbol, val_ncompo, legenda, ordem, subordem, grande_gru, subgrupos, textura, horizonte, erosao, pedregosid, rochosidad, relevo, componente, component1, component2, component3, inclu_p1, inclu_p2, inclu_p3, ar_poli_km, leg_ordem, legenda_2, cd_ord_id, cd_leg2_id, edicao, vigente_desde, geom
FROM vetorial.ibge_pedologia WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_ibge_vegetacao AS
SELECT id, id1, cd_fcim, leg_carga, cd_fito, cd_leg_2, clas_domi, leg_uveg, nm_uveg, leg_uantr, nm_uantr, leg_contat, nm_contat, veg_pretet, nm_pretet, leg_sec1, nm_sec1, leg_sec2, nm_sec2, leg_sup, legenda_1, legenda_2, legenda, ar_poli_km, leg1_id, leg2_id, edicao, vigente_desde, geom
FROM vetorial.ibge_vegetacao WHERE vigente_ate IS NULL AND geom IS NOT NULL;


-- BHO 1:250.000 da ANA (hidrografia): sem dado pessoal; so a versao vigente
CREATE OR REPLACE VIEW vetorial.v_ana_bho_trechos_drenagem AS
SELECT id, drn_pk, cotrecho, noorigem, nodestino, cocursodag, cobacia, nucomptrec, nudistbact, nudistcdag, nuareacont, nuareamont, nogenerico, noligacao, noespecif, noriocomp, nooriginal, cocdadesag, nutrjus, nudistbacc, nuareabacc, nuordemcda, nucompcda, nunivotto, nunivotcda, nustrahler, dedominial, dsversao, edicao, vigente_desde, geom
FROM vetorial.ana_bho_trechos_drenagem WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_ana_bho_cursos_dagua AS
SELECT id, wtc_pk, idcda, cocursodag, nudistbacc, nucompcda, nuareabacc, cocdadesag, nunivotcda, nuordemcda, dedominial, dsversao, edicao, vigente_desde, geom
FROM vetorial.ana_bho_cursos_dagua WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_ana_bho_linha_costa AS
SELECT id, colinhacosta, nooriginal, edicao, vigente_desde, geom
FROM vetorial.ana_bho_linha_costa WHERE vigente_ate IS NULL AND geom IS NOT NULL;

CREATE OR REPLACE VIEW vetorial.v_ana_bho_bacias_otto AS
SELECT id, wts_pk, wts_cd_pfafstetterbasin, wts_cd_pfafstetterbasincodelevel, wts_gm_area, edicao, vigente_desde, geom
FROM vetorial.ana_bho_bacias_otto WHERE vigente_ate IS NULL AND geom IS NOT NULL;

DO $$
DECLARE v text;
BEGIN
  FOREACH v IN ARRAY ARRAY['v_funai_terras_indigenas','v_mma_unidades_conservacao','v_ana_bho_trechos_drenagem','v_ana_bho_cursos_dagua','v_ana_bho_linha_costa','v_ana_bho_bacias_otto','v_ibge_geologia','v_ibge_geomorfologia','v_ibge_pedologia','v_ibge_vegetacao','v_mma_areas_prioritarias','v_sfb_florestas_publicas','v_deter_alertas','v_mapbiomas_alerta','v_ibama_embargos_poligonos',
                           'v_ibama_embargos_pontos','v_icmbio_areas_embargadas','v_sema_mt_areas_embargadas','v_sema_mt_areas_desembargadas'] LOOP
    EXECUTE format('GRANT SELECT ON vetorial.%I TO leitura, geoserver, analistas', v);
    EXECUTE format('COMMENT ON VIEW vetorial.%I IS %L', v, 'Publicada no GeoServer: so a versao vigente' ||
                   CASE WHEN v ~ 'embargo|embargad' THEN ', SEM nome nem documento do embargado (use infra/scripts/consultar_embargo.py)' ELSE '' END || '. Ver infra/postgres/views_geoserver.sql.');
  END LOOP;
END $$;

SELECT table_name, (SELECT count(*) FROM information_schema.columns c WHERE c.table_schema = 'vetorial' AND c.table_name = v.table_name) AS colunas
FROM information_schema.views v WHERE table_schema = 'vetorial' AND table_name LIKE 'v\_%' ORDER BY 1;
