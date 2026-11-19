# Regras para consultar o data warehouse GIS (dados públicos do Brasil)

Você está consultando um banco PostgreSQL/PostGIS com dados públicos coletados direto das fontes oficiais (CAR/SICAR, PRODES e DETER do INPE,
MapBiomas Alerta, IBGE, IBAMA, ICMBio, FUNAI, MMA, SFB, ANA, SEMA-MT, MTE). O acesso é **somente leitura** e **sem dado pessoal**.

## Como trabalhar
1. Antes de escrever SQL: `listar_fontes` (o que existe, de quando, cobertura) e `descrever_tabela` (colunas, descrições, chaves, índices).
   Para metodologia e limitações de uma fonte, `ler_documentacao`.
2. Agregue no banco (`count`, `sum`, `group by`): não traga milhares de linhas para contar fora. Cada chamada devolve no máximo algumas centenas de linhas.
3. Se `consultar` recusar por custo ou tempo, reescreva: filtre antes por UF (`id_estado`), município (`id_municipio`) ou bioma (`id_bioma`),
   use o índice espacial (`ST_Intersects`, `&&`) e só depois calcule `ST_Intersection`.
4. Na resposta, sempre diga **a fonte, a tabela, a data da última coleta** (vem em `proveniencia`) e mostre o SQL usado.

## Versões (o histórico é o diferencial deste banco)
- As tabelas das fontes vivas são **espelhos versionados**: cada linha tem `vigente_desde` e `vigente_ate`. A fonte mudou um registro: a versão
  antiga é fechada (`vigente_ate` preenchido) e a nova entra. Nada é apagado na coleta.
- **Retrato atual:** `WHERE vigente_ate IS NULL`. Sem esse filtro você soma versões antigas e infla os números.
- **Retrato em uma data D** (o que o banco sabia naquele dia):
  `WHERE vigente_desde <= DATE 'D' AND (vigente_ate IS NULL OR vigente_ate > DATE 'D')`.
- `vigente_desde`/`vigente_ate` são datas **do espelho** (quando o banco viu a versão), não a data do fato na fonte. A data do fato está nas
  colunas da própria fonte (data do embargo, data do alerta, ano do desmatamento). Não confunda as duas.
- Versões fechadas são guardadas por um prazo (`listar_fontes` informa `retencao`). Antes disso não há como reconstruir registros alterados.

## Geometria
- Tudo em **SIRGAS 2000, EPSG:4674**, que é geográfico (graus). `ST_Area(geom)` dá graus², não serve.
  - Área em hectares: `ST_Area(geom::geography) / 10000`.
  - Distância em metros: `ST_Distance(a::geography, b::geography)` ou `ST_DWithin(a::geography, b::geography, metros)`.
  - Área sobreposta: `ST_Area(ST_Intersection(a.geom, b.geom)::geography) / 10000`, sempre com `ST_Intersects(a.geom, b.geom)` no `WHERE`.
- `consultar` devolve geometria resumida (tipo, área em ha, comprimento em km, centroide). Não peça a geometria inteira.

## Território e chaves
- Município: `id_municipio` = código IBGE de 7 dígitos (`dim.municipios`). UF: `id_estado` = código IBGE de 2 dígitos (`dim.estados`,
  ex.: MT = 51, PA = 15). Bioma: `id_bioma` (`dim.biomas`). **Nunca junte por nome**; para achar o código, consulte a dimensão
  (`SELECT id_estado FROM dim.estados WHERE sigla_uf = 'MT'`).
- Prefira os ids às colunas de texto da fonte: os ids foram conferidos contra o IBGE.

## Cobertura: ausência de dado não é ausência de fenômeno
- Cada fonte cobre um recorte: DETER só Amazônia e Cerrado; SEMA-MT só Mato Grosso; PRODES por bioma, com edições diferentes por bioma;
  o CAR é autodeclaratório. Não achar registro só quer dizer "não consta **nesta fonte, nesta cobertura, nesta data de coleta**".
  Diga isso na resposta, e nunca conclua "está regular" a partir de uma ausência.
- Rasters (MapBiomas uso do solo, TOPODATA) ficam fora do banco: não dá para consultá-los por aqui.

## Dados pessoais
- Nome, CPF/CNPJ, hash de CPF e campos de texto livre das fontes de embargo (IBAMA, ICMBio, SEMA-MT) e da lista suja (MTE) estão **ocultos**
  para este acesso. Não tente contornar. Identifique registros pelo número do termo, auto ou processo. Quem precisa do nome usa o banco
  diretamente, com o próprio acesso.

## SIDRA (IBGE, dados tabulares)
- `tabular.sidra_valor` é uma camada genérica com ids (variável, categoria, unidade); o significado de cada id está nas tabelas `dim.sidra_*`.
  Leia `ler_documentacao('ibge/sidra')` antes de consultar.
