-- Ajustes pontuais de 2026-10-15 (executado uma vez, como postgres, numa transacao). So ASCII de proposito
-- (acentos por escape unicode U&'...'). Rodar:
--   Get-Content infra\postgres\ajustes_2026-10-15.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1
BEGIN;

-- 1) PAM: sobraram linhas que nao foram pedidas (todas as culturas de 2023-2025 e de 1974/1975). Ficam so as
--    culturas pedidas: erva-mate (40147) e laranja (40151). dim.cultura nao muda. Recarregar sob demanda.
SELECT 'ibge_pam antes' AS passo, count(*) FROM tabular.ibge_pam;
DELETE FROM tabular.ibge_pam WHERE id_cultura NOT IN (40147, 40151);
SELECT 'ibge_pam depois' AS passo, count(*) FROM tabular.ibge_pam;

-- 2) SICAR: 64 imoveis de Boa Esperanca do Norte/MT ficaram sem id_municipio porque o municipio nao existia na
--    dimensao quando a carga foi feita. O campo texto 'municipio' dos 64 e esse nome e todos os pontos caem
--    dentro da geometria do municipio (conferido antes).
UPDATE vetorial.sicar_imoveis s
SET id_municipio = 5101837
WHERE s.id_municipio IS NULL AND s.cod_estado = 'MT' AND s.municipio = U&'Boa Esperan\00e7a do Norte'
  AND EXISTS (SELECT 1 FROM dim.municipios m WHERE m.id_municipio = 5101837 AND ST_Intersects(m.geom, ST_PointOnSurface(s.geom)));
SELECT 'sicar sem municipio depois' AS passo, count(*) FROM vetorial.sicar_imoveis WHERE id_municipio IS NULL;

-- 3) Nomes de 5 municipios: passam para a grafia da lista oficial do IBGE (SIDRA 6579).
UPDATE dim.municipios SET nome_municipio = U&'S\00e3o Luiz do Anau\00e1' WHERE id_municipio = 1400605 AND nome_municipio = U&'S\00e3o Luiz';
UPDATE dim.municipios SET nome_municipio = U&'Ass\00fa'                  WHERE id_municipio = 2400208 AND nome_municipio = U&'A\00e7u';
UPDATE dim.municipios SET nome_municipio = 'Arez'                        WHERE id_municipio = 2401206 AND nome_municipio = U&'Ar\00eas';
UPDATE dim.municipios SET nome_municipio = 'Graccho Cardoso'             WHERE id_municipio = 2802601 AND nome_municipio = 'Gracho Cardoso';
UPDATE dim.municipios SET nome_municipio = U&'Bar\00e3o do Monte Alto'   WHERE id_municipio = 3105509 AND nome_municipio = U&'Bar\00e3o de Monte Alto';
SELECT id_municipio, nome_municipio FROM dim.municipios WHERE id_municipio IN (1400605, 2400208, 2401206, 2802601, 3105509) ORDER BY 1;

COMMIT;
