-- Ponte PRODES x municipio (relacao muitos-pra-muitos: um poligono pode
-- cruzar a divisa entre municipios; no Acre, 1,49% dos poligonos cruzam).
-- Construida em 2026-10-05; total 7.028.540 pares pra 6.880.422 poligonos.
-- REFEITA em 2026-10-20 com a malha municipal 2025 (7.027.719 pares, mesmos 6.880.422 poligonos): para refazer de novo
-- use analises/ponte_prodes_municipio/scripts/refazer_ponte_municipio.ps1 (mesmo metodo, em lotes paralelos, tabela nova + validacao + troca;
-- 31 lotes em ~6 min). Este arquivo fica como documentacao do metodo e da estrutura.
-- Rodar no psql (cada comando separado). Pre-requisitos: dim.municipios e
-- vetorial.prodes_desmatamento com indices GIST.

-- 1) Tabela. Restricoes SO depois da carga (validar FK linha a linha
--    durante o insert seria bem mais lento).
CREATE TABLE resultados.prodes_municipio (
    id           bigserial PRIMARY KEY,
    id_prodes    integer NOT NULL,
    id_municipio integer NOT NULL,
    calculado_em date NOT NULL DEFAULT CURRENT_DATE
);

-- 2) Indice unico ANTES de carregar o grosso: o banco recusa duplicata se
--    algum lote rodar duas vezes por engano.
CREATE UNIQUE INDEX uq_prodes_municipio ON resultados.prodes_municipio (id_prodes, id_municipio);

-- 3) Carga em LOTES por faixa de id (ids de cada bioma sao contiguos).
--    Lotes de ~250-500 mil poligonos (3 a 10 min cada); varios em paralelo.
--    Cada INSERT e atomico: se falhar, nada fica pela metade.
--    Trocar bioma e faixa; Amazonia/Cerrado sao ~2x mais lentos por
--    poligono que Caatinga (municipios grandes e complexos).
INSERT INTO resultados.prodes_municipio (id_prodes, id_municipio)
SELECT p.id, m.id_municipio
FROM vetorial.prodes_desmatamento p
JOIN dim.municipios m ON ST_Intersects(p.geom, m.geom)
WHERE p.bioma = '<bioma>' AND p.id BETWEEN <id_min> AND <id_max>;

-- Faixas usadas (bioma, id_min, id_max):
--   com SELECT bioma, min(id), max(id), count(*) por lote de 500000:
--   (row_number() OVER (PARTITION BY bioma ORDER BY id) - 1) / 500000

-- 4) Fechamento
CREATE INDEX idx_prodes_municipio_id_municipio ON resultados.prodes_municipio (id_municipio);
ALTER TABLE resultados.prodes_municipio ADD CONSTRAINT fk_prodes_municipio_prodes
    FOREIGN KEY (id_prodes) REFERENCES vetorial.prodes_desmatamento (id);
ALTER TABLE resultados.prodes_municipio ADD CONSTRAINT fk_prodes_municipio_municipio
    FOREIGN KEY (id_municipio) REFERENCES dim.municipios (id_municipio);
ANALYZE resultados.prodes_municipio;

-- 5) View pra publicar no GeoServer: expoe id_municipio como coluna comum,
--    entao o filtro por chave funciona em qualquer cliente (sem viewparams).
--    Poligono que cruza divisa aparece uma vez por municipio tocado.
--    id_ponte e o identificador unico da linha.
CREATE VIEW vetorial.v_prodes_municipio AS
SELECT b.id AS id_ponte, b.id_municipio, p.id AS id_prodes, p.year,
       p.main_class, p.class_name, p.area_km, p.image_date,
       p.id_bioma, p.id_estado, p.geom
FROM resultados.prodes_municipio b
JOIN vetorial.prodes_desmatamento p ON p.id = b.id_prodes;

-- Validacao (referencia: Acre = 79159 pares, 77999 poligonos, 1160 em >1 municipio):
-- WITH ac AS (SELECT b.id_prodes, count(*) n FROM resultados.prodes_municipio b
--   JOIN vetorial.prodes_desmatamento p ON p.id=b.id_prodes
--   WHERE p.id_estado=(SELECT id_estado FROM dim.estados WHERE sigla_uf='AC') GROUP BY b.id_prodes)
-- SELECT sum(n), count(*), count(*) FILTER (WHERE n>1) FROM ac;
