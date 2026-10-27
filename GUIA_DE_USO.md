# Guia de uso do banco (para quem consulta, não para quem carrega)

Este guia junta as armadilhas e os atalhos que, até aqui, estavam espalhados nos LEIAME de cada fonte. Para **como cada tabela é carregada**, veja o LEIAME da fonte; para **o desenho**,
`ARQUITETURA.md`; para **o que cada coluna significa**, o diagrama do banco (balões) ou `catalogo.mapa_colunas`.

## 1. Onde está cada coisa

| Schema | O que tem | Exemplo |
|---|---|---|
| `vetorial` | Dado espacial como a fonte publica | `vetorial.sicar_imoveis`, `vetorial.prodes_desmatamento`, `vetorial.sfb_florestas_publicas` |
| `tabular` | Dado sem geometria | `tabular.sidra_valor`, `tabular.ibge_pam` |
| `dim` | Dimensões (ids → nomes) | `dim.estados`, `dim.municipios`, `dim.biomas`, `dim.fontes` |
| `resultados` | O que a gente **calcula** (derivados sob demanda) | `resultados.prodes_municipio` |
| `catalogo` | Metadados: o que foi carregado, quando, de onde | `catalogo.cargas`, `catalogo.coletas`, `catalogo.datasets`, `catalogo.mapa_colunas` |

Rasters (MapBiomas, Topodata) **não estão no banco**: ficam em arquivo e são servidos pelo GeoServer (ver `infra/LEIAME_infra.md`).

Descobrir o que existe:

```sql
SELECT * FROM catalogo.datasets;                                  -- fonte, ano de referência, licença de cada tabela
SELECT * FROM catalogo.v_ultima_coleta;                           -- última coleta de cada tabela
SELECT coluna, origem, fonte, observacao
FROM catalogo.mapa_colunas WHERE tabela = 'vetorial.ibama_embargos';   -- de onde vem cada coluna (fonte, derivado, controle)
```

## 2. Regra nº 1: sempre filtre a versão vigente

As fontes vivas (SICAR, PRODES, MapBiomas Alerta, FUNAI, DETER, IBAMA, CNUC, CNFP, SIDRA) são **espelhos versionados**: quando um registro muda, a versão antiga é **fechada**
(`vigente_ate` preenchido) e entra uma nova; nada é apagado na coleta. Sem filtro, você conta o mesmo registro duas vezes.

```sql
SELECT count(*) FROM vetorial.mma_unidades_conservacao WHERE vigente_ate IS NULL;      -- retrato de hoje
-- retrato em uma data passada (o que o banco achava em 2026-09-01):
SELECT count(*) FROM vetorial.mma_unidades_conservacao
WHERE vigente_desde <= DATE '2026-09-01' AND (vigente_ate IS NULL OR vigente_ate > DATE '2026-09-01');
```

A retenção (`infra/retencao.yaml`) apaga versões fechadas há mais de 30 dias, então o histórico "para trás" é curto: serve para auditar mudanças recentes, não para séries longas.
Os índices espaciais e de busca são **parciais** (`WHERE vigente_ate IS NULL`): consulta sem esse filtro não os usa e fica lenta.

## 3. Geometria

- **SRID 4674 (SIRGAS 2000, graus)** em todas as tabelas de `vetorial`. Tudo se cruza sem `ST_Transform`.
- **Área e distância não se calculam em graus.** Use `geography` (exato, mais lento) ou um sistema métrico de área igual para o Brasil, **EPSG 5880** (SIRGAS 2000 / Brazil Polyconic):

```sql
SELECT ST_Area(geom::geography) / 10000 AS ha_geodesico FROM vetorial.funai_terras_indigenas WHERE vigente_ate IS NULL LIMIT 3;
SELECT ST_Area(ST_Transform(geom, 5880)) / 10000 AS ha_5880 FROM vetorial.funai_terras_indigenas WHERE vigente_ate IS NULL LIMIT 3;
```

  Os dois métodos diferem pouco (ex.: uma terra indígena deu 242.406 ha geodésicos e 244.177 ha em 5880); as colunas de área da própria fonte (hectares) são a medida oficial dela e também podem diferir.

### Geometrias inválidas: use `ST_MakeValid`

Os dados entram **como a fonte publica**, sem reparo. Parte vem inválida para o PostGIS (auto-interseção de anel, anel aberto): CNFP tem 1.638, embargos do IBAMA 130, e há casos no SICAR e no
PRODES. `ST_Intersection`, `ST_Union` e `ST_Intersects` podem **falhar com erro** (`TopologyException`) ou dar resultado errado nelas. A receita:

```sql
-- cruzar duas camadas sem tropeçar nas inválidas
SELECT i.cod_imovel, t.terrai_nome,
       ST_Area(ST_Intersection(ST_MakeValid(i.geom), ST_MakeValid(t.geom))::geography) / 10000 AS ha_sobreposicao
FROM vetorial.sicar_imoveis i
JOIN vetorial.funai_terras_indigenas t ON ST_Intersects(i.geom, t.geom)          -- o índice espacial trabalha na versão crua
WHERE i.vigente_ate IS NULL AND t.vigente_ate IS NULL AND i.cod_imovel = 'XX-0000000-00000000000000000000000000000000';
```

Dicas: (1) deixe o **filtro de vizinhança** (`ST_Intersects`, `&&`) na geometria crua, que usa o índice, e aplique `ST_MakeValid` só **dentro** de `ST_Intersection`/`ST_Union`/`ST_Area`;
(2) `ST_MakeValid` pode virar `GeometryCollection`: se precisar de polígono, use `ST_CollectionExtract(ST_MakeValid(geom), 3)`; (3) para saber quais são inválidas: `WHERE NOT ST_IsValid(geom)` (o PostGIS imprime um `NOTICE` por polígono; `SET client_min_messages = warning;` silencia) e, para saber o porquê, `ST_IsValidReason(geom)`.

### Geometria nula ou "anômala"

Se a fonte traz geometria fora do Brasil ou ilegível, a tabela grava `geom` **NULL**, `geom_anomala = true` e o texto original em `geom_origem_texto`. Cruzamentos espaciais ignoram essas linhas
(NULL); para contar tudo, não filtre por geometria. Nos embargos do IBAMA e nas UCs do CNUC há também `geom_ponto` (ponto derivado de lon/lat) para quem só tem coordenada.

## 4. Ids em vez de texto: junte com `dim.*`

Tabelas de fato guardam `id_estado`, `id_municipio`, `id_bioma`, `id_fonte`; os nomes ficam nas dimensões.

```sql
SELECT e.sigla_uf, count(*) AS embargos, round(sum(b.qtd_area_embargada)) AS ha
FROM vetorial.ibama_embargos b JOIN dim.estados e USING (id_estado)
WHERE b.vigente_ate IS NULL GROUP BY 1 ORDER BY 2 DESC;
```

Quando a fonte não tem o id (ex.: `uf`/`municipio` do CNUC são **listas em texto** de UCs que cruzam UFs), a ligação correta é **espacial**, com `dim.municipios.geom`.

## 5. Armadilhas por fonte

| Tabela | Cuidado |
|---|---|
| `sfb_florestas_publicas` (CNFP) | Há dupla afetação (`PA / APA`) e sobreposição entre registros (`sobreposic = 'SIM'`): **não some `area_ha` sem filtrar**; 1.638 polígonos inválidos. |
| `mma_unidades_conservacao` | `esfera` varia a caixa (`Federal`/`federal`): use `lower()`. 170 UCs só têm ponto (`geom` NULL, `geom_ponto` preenchido). Áreas somadas contam sobreposições. |
| `ibama_embargos` | **Dado pessoal.** CPF de pessoa física só existe como HMAC (`cpf_embargado_hash`), útil para contar embargos por pessoa. `nome_embargado` vem como o IBAMA publica: **não publique a tabela no GeoServer sem tirá-lo**. 8 datas de embargo suspeitas (`data_embargo_suspeita`). |
| `icmbio_areas_embargadas` | Mesmo tratamento do IBAMA: CPF só como hash (`cpf_autuado_hash`, mesma chave), `autuado` é dado pessoal (não publicar no GeoServer). Um embargo tem vários polígonos (`numero_emb` repete); `area` é texto livre; 278 polígonos sem geometria. |
| `sema_mt_areas_embargadas` / `sema_mt_areas_desembargadas` | **Duas tabelas de propósito**: embargo vigente x encerrado; só Mato Grosso. Mesmo tratamento de CPF/nome do IBAMA (`nome` é dado pessoal). `t_embargo` repete entre polígonos; `data_lavratura` NULL quando a data da fonte é incompleta. |
| `mte_cadastro_empregadores` | Lista suja: **vigente = consta hoje** (o MTE retira nomes após 2 anos). Sem geometria; o endereço é texto. Mesmo tratamento de CPF. |
| `deter_alertas` | O `gid` da fonte **não é único**; a chave é `(id_bioma, gid, chave_linha)`. Só Amazônia e Cerrado. É alerta (sinal), **não** é o dado oficial de desmatamento (PRODES). |
| `prodes_desmatamento` vs `deter_alertas` vs `mapbiomas_alerta` | Três metodologias diferentes (PRODES = oficial anual; DETER = alerta quase em tempo real; MapBiomas Alerta = laudos validados). **Não se misturam numa soma**; cada tabela tem uma só metodologia. |
| `sicar_imoveis` | Cadastro **autodeclarado**: pode haver sobreposição entre imóveis e inconsistência. Volume alto: sempre filtre por UF/município antes de fazer join espacial. |
| `tabular.sidra_valor` e `sidra_valor_t*` | Valores do SIDRA têm unidade e variável próprias (`dim.sidra_*`, `dim.unidade`): confira a unidade antes de somar. |

### Buscar um CPF ou CNPJ nos embargos

O banco não guarda CPF de pessoa física, só o hash. Para consultar sem expor chave nem documento, use o auxiliar (IBAMA, ICMBio, SEMA-MT e a lista suja do MTE de uma vez; `--tudo` inclui os já desembargados/encerrados):

```powershell
.\infra\scripts\dw.ps1 etl infra/scripts/consultar_documento.py 123.456.789-09
```

Sem a chave do projeto (`ibama/embargos/segredo/`) não há como buscar CPF; CNPJ não depende dela.

## 6. Desempenho em duas linhas

- Filtre primeiro (UF, município, `vigente_ate IS NULL`) e só depois faça o join espacial; `EXPLAIN ANALYZE` mostra se o índice `gist` foi usado.
- Para cruzamentos grandes, grave o resultado em `resultados.*` (com o `id` da versão usada de cada fonte) em vez de refazer a conta; derivados só sob demanda, nunca "para adiantar".

## 7. Como conectar

- **Somente leitura pelo dia a dia:** `infra/scripts/dw.ps1 consulta -Sql "..."` (ou `-Arquivo consulta.sql`).
- **Cliente SQL/QGIS** (DBeaver, QGIS): host, porta 5432, banco do projeto, papel `leitura` ou `analistas` (o `etl` é dos pipelines; papéis e senhas ficam com o administrador, não estão neste repositório).
- **De fora da máquina:** só pela tailnet (Tailscale); nada é exposto na internet. Ver `infra/LEIAME_infra.md` e `infra/colab/LEIAME_colab.md` (Colab).
- **GeoServer** (`localhost:8080`): publica camadas para mapa; para análise, prefira o SQL direto.

## 8. Como saber se o dado está fresco

```sql
SELECT dataset, max(coletado_em) AS ultima_coleta, max(edicao) AS edicao FROM catalogo.coletas WHERE dataset NOT LIKE '%teste%' GROUP BY 1 ORDER BY 2;
```

A atualização agendada (domingos alternados, 00:10) cobre PRODES, MapBiomas Alerta, FUNAI, DETER, IBAMA (embargos) e SICAR; SFB (CNFP) e CNUC têm uma edição por ano/semestre e se verificam com
`--verificar` no pipeline da fonte. Log de cada atualização em `infra/logs/`.
