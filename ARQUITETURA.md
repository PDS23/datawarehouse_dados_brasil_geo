# Arquitetura — Data Warehouse GIS Brasil

Este é o documento de **padrões/convenções** do projeto — a "constituição"
que toda tabela, schema e pasta nova deveria seguir. Diferente do
[ROADMAP.md](ROADMAP.md), que muda toda hora (status, próximos passos),
este documento só muda quando uma convenção em si é revista.

Decidido em 2026-09-27, depois de rodar o primeiro dataset real
(PRODES) ponta a ponta no PostGIS.

## Schemas do PostGIS

| Schema | Guarda | Exemplo |
|---|---|---|
| `vetorial` | Dado espacial importado, como veio da fonte | `vetorial.prodes_desmatamento` |
| `tabular` | Dado não-espacial importado | `tabular.ibge_producao_agricola` |
| `dim` | Tabelas de dimensão/lookup, compartilhadas entre `vetorial` e `tabular` | `dim.fontes`, `dim.cultura`, `dim.municipio` |
| `resultados` | O que a gente **calcula** (não importa pronto) — declividade média de uma fazenda, % de área por classe, área desmatada por propriedade | `resultados.declividade_propriedade` |
| `catalogo` | Registro único de todo dataset do projeto (vetor, raster ou tabular) | `catalogo.datasets` |

Regra de decisão pra saber onde uma tabela nova entra:
- Tem geometria e é dado **bruto/importado**? → `vetorial`
- Não tem geometria e é dado **bruto/importado**? → `tabular`
- É uma **categoria que se repete** (fonte, cultura, classe, município)? → `dim`
- É algo que **calculamos** a partir de outros dados? → `resultados`

## Convenção de nome de tabela

`<fonte>_<assunto>`, sempre `snake_case`, minúsculo, sem acento.
Exemplos: `prodes_desmatamento`, `sicar_imoveis`, `ibge_producao_agricola`.

Tabelas de dimensão não levam o prefixo da fonte, só o assunto:
`dim.fontes`, `dim.cultura`, `dim.municipio` (a fonte de uma dimensão fica
registrada dentro dela mesma, não no nome).

## Convenção de coluna — o que toda tabela nova deve ter

| Coluna | Tipo | Obrigatória em |
|---|---|---|
| `id` | `serial`/`bigserial`, chave primária | tabelas de `vetorial`/`tabular`/`resultados` |
| `id_<dimensao>` (ex.: `id_fonte`, `id_estado`, `id_bioma`) | `smallserial`, chave primária (**ou o código oficial da fonte, `smallint`, quando existir** — ver "Decisão (2026-10-05)" abaixo) | tabelas de `dim` |
| `geom` | `geometry(Geometry ou tipo específico, 4674)` | tabelas de `vetorial` e `dim` que tiverem geometria |
| `id_fonte` | `smallint`, chave estrangeira pra `dim.fontes` | todas as tabelas de `vetorial`/`tabular`/`dim` (exceto a própria `dim.fontes`) |
| `importado_em` | `date` ou `timestamp` | todas as tabelas de `vetorial`/`tabular`/`dim` |

**Por que a chave primária de `dim` é `id_<dimensao>` e não `id`**: tabela de
`dim` existe pra ser referenciada por outras tabelas via chave estrangeira —
nomear a PK já com o nome que a FK vai ter em qualquer outra tabela
(`id_estado`, `id_bioma`) evita ambiguidade em `JOIN` e deixa óbvio de onde
vem cada `id_*` que aparece em uma tabela de `vetorial`/`tabular`.

### Decisão (2026-10-05): chave de dimensão = código oficial, quando existir

`dim.estados.id_estado` e `dim.biomas.id_bioma` foram numerados na ordem em
que as tabelas foram carregadas (SP = 2, RS = 1...): arbitrário, ruim de ler
em filtro e diferente do código que todo dado brasileiro já usa.
`dim.municipios.id_municipio` já é o código IBGE de 7 dígitos, e os dois
primeiros dígitos são o `cd_uf`. A regra passa a ser: **se a dimensão tem
código oficial, ele é a chave** (`smallint`, sem `serial`); só dimensão sem
código oficial (ex.: `dim.fontes`) usa `smallserial`.

| Dimensão | Chave nova | Observação |
|---|---|---|
| `dim.estados` | `id_estado` = `cd_uf` IBGE (SP = 35, RS = 43, AC = 12) | `id_municipio / 100000` = `id_estado` |
| `dim.biomas` | `id_bioma` = `codigo_bioma` IBGE (1 Amazônia, 2 Caatinga, 3 Cerrado, 4 Mata Atlântica, 5 Pampa, 6 Pantanal, 7 Ilhas Oceânicas) | já é ordem alfabética; 7 foi acrescentado por nós |

Mapeamento antigo → novo (para o `UPDATE ... CASE` da migração):

- `id_estado`: 1→43, 2→35, 3→32, 4→33, 5→41, 6→42, 7→31, 8→23, 9→52,
  10→24, 11→21, 12→53, 13→22, 14→50, 15→51, 16→27, 17→12, 18→28, 19→13,
  20→25, 21→26, 22→11, 23→16, 24→17, 25→29, 26→14, 27→15.
- `id_bioma`: 1→1, 2→4, 3→3, 4→6, 5→7, 6→2, 7→5.

**Quando: na migração notebook → desktop, não antes.** Mudar o valor de uma
chave reescreve `vetorial.prodes_desmatamento` (6,88 mi de linhas, 16 GB) e
`vetorial.sicar_imoveis` (8,36 mi), e cada `UPDATE` mexe em todos os índices
(foi o que deixou o retrofit de `id_estado` lento). Na migração as tabelas
serão reescritas de qualquer jeito, e dá pra aplicar o mapeamento **entre a
carga dos dados e a criação dos índices/chaves** (ver
[infra/MIGRACAO_DESKTOP.md](infra/MIGRACAO_DESKTOP.md)), onde o `UPDATE` é
barato. Custo aceito: até lá, a numeração antiga continua valendo, e
filtros/projetos salvos que usem `id_estado`/`id_bioma` precisam ser
trocados depois. Quem filtra por `sigla_uf`/`nome_uf` (via `dim.estados`)
não é afetado.

✅ **Aplicado em 2026-10-06, no banco do desktop** (script
[infra/migracao/renumerar_chaves.sql](infra/migracao/renumerar_chaves.sql),
entre as seções `data` e `post-data` do `pg_restore`). Com os dados reais:
`UPDATE` de `prodes_desmatamento` ~2 min e de `sicar_imoveis` ~1 min 40 s, 7 min
21 s no total (a maior parte foi a tabela de conferências, sem índices). As 8
conferências deram 0; as contagens por estado e bioma (89 grupos), com o
mapeamento aplicado ao "antes", ficaram idênticas ao "depois"; o NULL do PRODES
continuou NULL; AC = 12 tem 77.999 polígonos (a referência do Acre). **O banco
do notebook continua com a numeração antiga** até o corte: qualquer consulta
salva com `id_estado`/`id_bioma` fixo vale para um banco e não para o outro.

**Regra pra scripts:** nunca gravar `id_estado`/`id_bioma` fixo; buscar por
sigla/código na dimensão (`SELECT id_estado FROM dim.estados WHERE
sigla_uf='AC'`), como já fazem `atualizar_imoveis_sicar.py` e
`construir_ponte_municipio.sql`. Assim a renumeração não quebra nada.

**Por que `id_fonte` (dimensão) e não uma coluna `fonte` (texto solto)**:
mesma lógica do `dim_cultura` que já discutimos — fonte é uma categoria que
se repete (INPE, IBGE, CPRM...) e cresce devagar. Uma dimensão evita nome de
fonte escrito de formas diferentes em tabelas diferentes (`"INPE"` vs
`"Inpe"` vs `"I.N.P.E."`), e permite guardar mais informação da fonte (URL,
licença) uma vez só.

**Quando NÃO vale a pena virar dimensão**: um conjunto de valores pequeno e
que praticamente nunca muda (ex.: `tipo` do catálogo, só
`'vetor'/'raster'/'tabular'`) — aí um `CHECK` na própria coluna já resolve,
sem precisar de tabela extra. Regra prática: menos de ~5 valores fixos e
estáveis → `CHECK`; mais que isso, ou vai crescer → dimensão.

CRS padrão pra geometria: **SIRGAS 2000, EPSG:4674** (mesmo já usado no
PRODES e recomendado pelo IBGE pro Brasil).

## Ordem de trabalho: dimensão antes de fato

Criar uma tabela de `dim` é sempre **2 passos obrigatórios, na mesma tarefa**,
nunca só o primeiro:

1. Criar e popular a tabela `dim.<dimensao>` (com `id_<dimensao>` como PK).
2. **Imediatamente depois**, adicionar a coluna `id_<dimensao>` (FK) em toda
   tabela de `vetorial`/`tabular` que já tenha um atributo de texto
   equivalente (ex.: `bioma`, `state`), e popular essa coluna via `JOIN`/
   `UPDATE`.

O passo 2 **não é opcional nem "faz depois"** — sem ele a dimensão vira só
uma tabela solta no banco, sem cumprir a função de ser referenciada (ver
justificativa em "Por que a chave primária de `dim`..." acima). Regra
descoberta na prática em 2026-09-28: criamos `dim.estados` e `dim.biomas`
sem retrofitar `id_estado`/`id_bioma` em `prodes_desmatamento` na hora — e
só lembramos depois, quando a tabela já tinha 6,88 milhões de linhas
importadas, tornando o retrofit um `UPDATE` caríssimo (reescreve toda linha,
inclusive geometria; levou mais de 1h, e ainda competiu por E/S com o
autovacuum automático disparado pelo próprio `UPDATE` anterior).

**Pra todo dataset novo a partir de agora, a ordem correta é a inversa**:
antes de importar a tabela principal (`vetorial`/`tabular`), checar se algum
atributo dela é uma dimensão nova ou já existente (`dim.classes_solo`,
`dim.formacao_geologica`, etc.). Se for:

1. Criar/confirmar a `dim.<dimensao>` primeiro (mesmo que vazia ou com poucos
   registros de amostra).
2. Criar a tabela principal já **com a coluna `id_<dimensao>` desde o
   `CREATE TABLE`** (não como `ALTER TABLE` depois).
3. Popular `id_<dimensao>` no momento do import, ou logo em seguida —
   idealmente **por lote pequeno** (ex.: bioma por bioma, como já fazemos no
   PRODES) em vez de um `UPDATE` único no fim cobrindo milhões de linhas de
   uma vez. Um `UPDATE` sobre um lote de ~1-2 milhões de linhas recém-
   importadas é muito mais barato que o mesmo `UPDATE` depois que a tabela já
   acumulou o dataset inteiro.

Checklist rápido antes de importar qualquer tabela nova: "essa tabela tem
alguma coluna de texto que se repete/categoriza? Se sim, a `dim`
correspondente já existe? Se não existir, crio ela **antes** de importar,
não depois."

## `dim.fontes` — desenho

```sql
CREATE TABLE dim.fontes (
    id_fonte   smallserial PRIMARY KEY,
    nome       text NOT NULL UNIQUE,
    sigla      text,
    url        text,
    descricao  text
);
```

## `catalogo.datasets` — desenho

Registro único de cada dataset do projeto, seja ele um arquivo raster em
disco ou uma tabela no PostGIS. Aproveita que já estamos no PostGIS pra
guardar a **cobertura geográfica como geometria de verdade** (não só um
texto de bbox), permitindo perguntar em SQL "quais datasets cobrem esse
ponto/essa fazenda".

```sql
CREATE TABLE catalogo.datasets (
    id                serial PRIMARY KEY,
    nome              text NOT NULL,
    tipo              text NOT NULL CHECK (tipo IN ('vetor','raster','tabular')),
    id_fonte          smallint REFERENCES dim.fontes(id_fonte),
    schema_tabela     text,
    caminho_arquivo   text,
    cobertura         geometry(Geometry, 4674),
    ano_referencia     int,
    data_importacao   date,
    licenca           text,
    observacoes       text
);
```

- `schema_tabela` preenchido quando o dataset é uma tabela no banco (ex.:
  `'vetorial.prodes_desmatamento'`), `NULL` quando é arquivo raster.
- `caminho_arquivo` preenchido quando é raster em disco, `NULL` quando é
  tabela no banco.
- `cobertura` fica `NULL` quando o dataset já é Brasil inteiro (não precisa
  desenhar o contorno do país toda vez).

## Estrutura padrão de uma fonte (REGRA TRAVADA, 2026-10-20)

O repositório é também um case de portfólio e será lido por pessoas: **toda fonte tem a mesma estrutura**, e ela cresce
sempre do mesmo jeito. Quem entende uma fonte entende todas. Antes de criar uma fonte nova, copie este padrão; não invente.

```
<orgao>/<fonte>/                  ex.: sicar/imoveis, incra/assentamentos, ibge/PAM, prodes/desmatamento
├── LEIAME_<fonte>.md             o que é, origem, tabela(s), método, como rodar, limites conhecidos
├── HISTORICO.md                  (quando houver) métodos anteriores e mudanças de método, em ordem cronológica
├── config.yaml                   URL, parâmetros e tolerâncias (nada fixo no código)
├── sql/                          NN_*.sql numerados na ordem de execução
├── scripts/                      pipeline(s) da fonte, nomeados pelo que fazem
├── bruto/                        dado baixado como veio, logs (fora do git e do Drive)
└── processado/                   só para fontes que ficam em arquivo (raster); vetor vai para o PostGIS
```

Regras:
1. **Dois níveis: grupo e fonte.** O grupo é o órgão produtor ou o tema (`ibge`, `incra`, `sicar`, `prodes`, `elevacao`,
   `mapbiomas`). Pasta e LEIAME levam o nome da **fonte**, nunca da ferramenta ou do protocolo
   (WFS, GDAL, API...). A ferramenta é explicada dentro do LEIAME, em "como baixamos".
2. **Ano, edição e versão são dados, não pastas.** Existe uma pasta por fonte, para sempre.
   - Fonte **viva** (muda continuamente, sem edições datadas; ex.: SICAR): o banco espelha o estado atual e guarda
     versões (`vigente_desde`/`vigente_ate`); não há ano de referência.
   - Fonte **por edição** (releases datados; ex.: PRODES, PAM, Censo Agro, malha municipal): o ano ou a edição é uma
     coluna na tabela e um parâmetro do pipeline (`--ano`, `--edicao`); o LEIAME tem a tabela "edições carregadas".
     Arquivos do `bruto/` podem levar o ano no nome.
3. **Histórico**: um único `HISTORICO.md` por fonte, nunca uma pasta com um arquivo por episódio.
4. **Fonte com vários temas independentes** (caso de `ibge/`) tem um nível de órgão e uma pasta por tema, cada uma com o
   esqueleto acima.
5. **Análises derivadas** (cruzamentos entre fontes, ex.: desmatamento por imóvel) e **projetos de cliente** (`projetos/`)
   ficam fora da pasta de qualquer fonte; as análises seguem o mesmo esqueleto internamente.
6. **Código compartilhado** fica em `scripts_comuns/dwlib`; configuração de infraestrutura em `infra/`.

Alinhado ao padrão em 2026-10-20: `sicar/imoveis`, `ibge/censo_agropecuario` (era `censo_agro_2017`), `prodes/desmatamento`
(cruzamentos movidos para `analises/desmatamento_imovel` e `analises/ponte_prodes_municipio`). Os LEIAMEs de
`prodes/desmatamento`, `elevacao/topodata`, `mapbiomas/uso_do_solo` e `ibge/` foram **restaurados de textos do notebook**
(3 semanas atrás) e levam aviso no topo; o repositório do D: é o original e o espelho do Drive segue o D:, nunca o contrário.

**Lacunas conhecidas** (fontes que ainda não cumprem o padrão por falta de pipeline reexecutável): `prodes/desmatamento`
(só o download é script; falta `config.yaml`, `sql/` e carga), `elevacao/topodata` e `mapbiomas/uso_do_solo` (processamento
feito por comandos soltos documentados no LEIAME; falta script). Os rasters ficam onde estão: GeoServer e
`catalogo.datasets` apontam para esses caminhos. Em `ibge/`, `municipios/` e `PAM/` ainda têm sobras fora do padrão
(sem sobras: `PAM/mate` foi para `projetos/mate_rs/` em 2026-10-20).

**Decisão explícita**: a raiz do repositório é organizada **por fonte**,
não por tipo de dado (`vetorial/`, `raster/` como pastas físicas) — essa
segunda dimensão já existe nos schemas do PostGIS (`vetorial`/`tabular`),
não precisa ser duplicada no sistema de arquivos. Organizar por fonte
também casa com a forma natural de pensar o trabalho (uma fonte = um
lugar pra rebaixar, reprocessar, documentar).

## Diagrama do banco (gerado, não desenhado à mão)

[`infra/diagrama/modelo_banco.svg`](infra/diagrama/modelo_banco.svg) mostra as tabelas, as colunas principais e as chaves estrangeiras; a
versão interativa (clique numa tabela para ver todas as colunas) é `infra/diagrama/modelo_banco_pagina.html`. Os dois são **gerados a partir do
catálogo do PostgreSQL** por `infra/scripts/gerar_diagrama_banco.py` (rode de novo sempre que o esquema mudar; não há desenho manual para
desatualizar). `id_fonte → dim.fontes` existe em quase toda tabela e aparece como a etiqueta `fonte`, sem linha, para o desenho não virar um novelo.

## Espelhos versionados (regra de 2026-10-21; SICAR e PRODES)

Fonte que se atualiza pelo que a origem publica (SICAR, PRODES) é um **espelho versionado**: cada registro tem versões
(`vigente_desde`, `vigente_ate`; vigente = `vigente_ate IS NULL`) e há no máximo **uma versão vigente por chave** (índice único
parcial). Reconciliação a cada coleta: **novo** entra; **alterado** fecha a versão antiga e insere a nova; **ausente** na fonte tem a
versão **fechada** (nada é apagado na coleta); **retirado e republicado idêntico** à última versão fechada tem **essa versão
reaberta** (mesmo `id`, `reaberto_em`); republicado diferente vira versão nova. Trava de segurança: se mais de 10% dos vigentes
sumirem de uma vez, a carga não grava. Cada coleta fica em `catalogo.coletas` (com a edição da fonte, quando há).

- **Resultados derivados** (ponte, desmatamento por imóvel) guardam o `id` da versão usada, **não** copiam uma coluna "vigente"
  (ficaria desatualizada); o status vem do cruzamento com a origem. Cada resultado registra de que edição das fontes depende, para
  ser recalculado quando ela mudar, e as **views `v_*_vigente`** mostram só o que ainda vale.
- **Retenção:** versões fechadas de registros que a origem retirou e não voltaram são apagadas, com os resultados dependentes,
  depois de um prazo (padrão 365 dias; `infra/retencao.yaml`) pela rotina `infra/scripts/limpar_versoes_fechadas.py`. Só relata
  sem `--apagar`; o agendamento é decisão do usuário. O prazo é também a janela em que uma retirada pode ser revertida por reabertura.

## Pegadinhas / lições aprendidas (pra não repetir)

- **Índice espacial não é automático quando a tabela é pré-criada à mão.**
  O `ogr2ogr` só cria o índice GIST em `geom` sozinho quando é ele quem cria
  a tabela do zero. Se a tabela for criada manualmente antes (como fizemos
  em `dim.estados`, pra controlar nome/tipo de coluna) e o `ogr2ogr` só
  entrar com `-append`, o índice espacial **não** aparece sozinho — precisa
  criar à mão: `CREATE INDEX idx_<tabela>_geom ON <schema>.<tabela> USING
  GIST (geom);` logo depois do import. Checklist pra toda tabela nova com
  geometria: depois de importar, rodar `\d schema.tabela` e conferir se
  `gist (geom)` aparece na lista de índices.
- **Console do Windows pode exibir acento errado mesmo com o dado certo no
  banco.** Se aparecer texto tipo `"Amapß"` em vez de `"Amapá"` no SQL
  Shell, não é o dado que está errado — é a página de código do console
  (850) não bater com a que o `psql` usa pra enviar o texto. Corrigir com
  `chcp 65001` na janela **antes** de abrir o SQL Shell. Pra confirmar que o
  dado em si está certo sem depender do console, comparar
  `length(coluna)` (caracteres) vs `octet_length(coluna)` (bytes) — se
  diferirem exatamente pela quantidade de caracteres acentuados, o UTF-8
  está correto.
- **Conflito de `PROJ_LIB`** entre o QGIS e o PostGIS Bundle — ver
  [LEIAME_prodes_desmatamento.md](prodes/desmatamento/LEIAME_prodes_desmatamento.md) (seção do erro de PROJ). Vale
  pra qualquer import via `ogr2ogr` do QGIS, não só PRODES.
- **`UPDATE` num retrofit de FK numa tabela grande pode competir com
  autovacuum na mesma tabela.** Um `UPDATE` que reescreve milhões de linhas
  gera lixo (versões antigas via MVCC) suficiente pra disparar o autovacuum
  automático sozinho — e se o próximo `UPDATE` for rodado logo em seguida,
  os dois ficam competindo por E/S na mesma tabela ao mesmo tempo, deixando
  tudo mais lento. Dá pra checar se isso está acontecendo com
  `SELECT pid, state, wait_event_type, wait_event, now()-query_start FROM
  pg_stat_activity WHERE datname='data_warehouse' AND state != 'idle';` — se
  aparecer uma linha de `autovacuum: VACUUM ANALYZE <tabela>` correndo junto
  com o seu `UPDATE`, pode cancelar só o autovacuum com
  `SELECT pg_cancel_backend(<pid_do_autovacuum>);` sem perder o progresso do
  `UPDATE` (autovacuum volta a rodar sozinho depois, quando precisar de
  novo). Ver também "Ordem de trabalho: dimensão antes de fato" acima — o
  jeito de evitar isso na origem é nunca deixar a coluna `id_<dimensao>` pra
  retrofitar depois que a tabela já está grande.
- **Coluna de texto pode ser truncada silenciosamente pelo `ogr2ogr` sem erro
  nenhum.** No retrofit de `id_estado` (2026-09-28), a coluna `state` de
  `prodes_desmatamento` tinha sido criada como `varchar(2)` (herdado
  automaticamente da largura declarada no primeiro GeoPackage importado, que
  usava sigla de 2 letras). Quando um bioma trouxe o nome do estado por
  extenso em vez de sigla (Pampa = "RIO GRANDE DO SUL"; e descobrimos que
  isso também acontece em parte do Cerrado, pra MG/SP/DF), o valor foi
  cortado pra 2 caracteres na hora do import, sem nenhum aviso/erro. Lição:
  ao criar uma tabela nova a partir de `ogr2ogr`, checar a largura de
  colunas de texto com `\d schema.tabela` logo depois do primeiro import —
  se vier estreita demais (`varchar(2)`, `varchar(3)`), alargar pra `text`
  antes de acumular mais dado.
- **(Automatizado em 2026-10-22: a classe `Carga` de `scripts_comuns/dwlib/catalogo.py` roda `ANALYZE` na tabela do dataset ao fim de todo pipeline que termina bem; o papel `etl` tem `MAINTAIN`, ver `infra/postgres/manutencao.sql`. A regra abaixo vale para cargas feitas fora dos pipelines.)**
- **Rodar `ANALYZE <tabela>` manualmente depois de qualquer carga ou
  atualização em massa (import inicial, retrofit de FK, etc.), não confiar
  só no autovacuum.** Descoberto em 2026-10-01: nenhuma tabela do projeto
  tinha `ANALYZE` manual registrado — só o automático do autovacuum, que
  além de poder demorar a disparar, foi **interrompido no meio** mais de
  uma vez nesta sessão (ver incidente do autovacuum concorrente acima). Sem
  estatísticas atualizadas, o planejador de consultas do Postgres decide
  plano de execução ruim mesmo com os índices certos já criados — por
  exemplo, a contagem estimada de linhas (`n_live_tup` em
  `pg_stat_user_tables`) do `sicar_imoveis` chegou a divergir do `COUNT(*)`
  real em quase 73 mil linhas, puro reflexo de estatística desatualizada
  depois de vários imports/deletes no mesmo dia. Checklist pra toda tabela
  nova/atualizada: depois de importar e criar os índices, rodar `ANALYZE
  schema.tabela;` antes de considerar o dataset "pronto".
- **Nem todo preenchimento de FK precisa de cálculo — às vezes é só
  atribuição direta.** Depois de descobrir a truncagem acima, a primeira
  tentativa de corrigir foi um `UPDATE` com `ST_Intersects` (join espacial,
  ponto contra polígono do estado) — tecnicamente correto, mas caríssimo
  (rodou por mais de 1h30 pra "só" 546 mil linhas, testando geometria
  complexa do IBGE linha a linha). Só depois percebemos que os valores
  truncados eram **mapeamento 1-pra-1 conhecido** (`"RI"` só pode ser Rio
  Grande do Sul dentro do bioma Pampa; `"MI"`/`"SÃ"`/`"DI"` só podem ser
  MG/SP/DF dentro do Cerrado) — trocando o `UPDATE` espacial por 4
  atribuições diretas (`SET id_estado = <valor fixo> WHERE bioma=... AND
  state=...`, sem nenhum cálculo geométrico), o mesmo trabalho terminou em
  minutos. Lição: antes de resolver um `id_<dimensao>` faltante com
  geometria/`JOIN` complexo, checar se o mapeamento já não é conhecido e
  fixo — é sempre mais barato que calcular.

## Pegadinha: `% de área` pode passar de 100% em overlay com imóveis minúsculos

Descoberto no primeiro overlay real do schema `resultados`
(`resultados.desmatamento_imovel`, Acre, 2026-10-01): 21 de 115.485 linhas
(0,018%) ficaram com `pct_area_imovel > 100%` — fisicamente impossível
(não dá pra desmatar mais do que 100% de um imóvel). Investigado: todos os
casos são imóveis com `num_area` **minúsculo** (ex.: 0,0005 ha — menos de
1m²), geometria válida, e a área recalculada bate muito próxima do
declarado. Em escala tão pequena, qualquer diferença de método de cálculo
de área (o nosso via `ST_Area(geography(...))` vs o que o SICAR usou pra
declarar `num_area`) vira uma porcentagem absurda, porque o denominador é
quase zero — não é erro de overlay, é ruído de digitalização no próprio
cadastro do SICAR (imóveis sub-hectare provavelmente não são propriedades
reais). **Não "corrigir" limitando em 100%** — isso esconderia a causa
real. Documentar/filtrar esses casos na hora da análise (ex.: excluir
imóveis com `num_area` abaixo de algum limiar mínimo plausível), não na
hora do cálculo do overlay.

## Padrão: relação espacial N:N = tabela-ponte + view, não coluna

Decidido em 2026-10-05, ao precisar filtrar o PRODES por município. A ideia
natural era somar uma coluna `id_municipio` em `prodes_desmatamento`
(cruzando com `dim.municipios`). Descartada, por três motivos medidos:

- **Um polígono pode tocar mais de um município.** No Acre, **1,49%** dos
  polígonos cruzam divisa. Coluna única guarda um valor só, e quem filtrasse
  o município vizinho **não veria** esses polígonos (perda silenciosa).
- **Reescrever a tabela grande é caro.** `ALTER TABLE ... ADD COLUMN` +
  `UPDATE` reescreve as 6,88 milhões de linhas (foi o que levou horas com
  `id_estado`).
- **Não é preciso.** Uma tabela estreita faz o trabalho sem tocar na grande.

Desenho: `resultados.prodes_municipio` (`id` próprio como PK,
`id_prodes`, `id_municipio`, `calculado_em`), uma linha por município
tocado, com `UNIQUE (id_prodes, id_municipio)` e as duas FKs; mais uma
**view** `vetorial.v_prodes_municipio` que junta ponte e polígono e expõe
`id_municipio` como coluna comum. O `id` da ponte é o identificador único
que o GeoServer precisa. Resultado: filtro por chave em ~0,2 s, em qualquer
cliente, sem `viewparams`. SQL completo em
[construir_ponte_municipio.sql](analises/ponte_prodes_municipio/scripts/construir_ponte_municipio.sql).

Regra geral: **se a relação entre dois conjuntos espaciais pode ser N:N,
modelar como ponte; coluna única só quando a relação é garantidamente 1:N**
(ex.: imóvel do SICAR → município, que o próprio código do imóvel já traz).

Lições operacionais da carga (7 milhões de pares):

- **Medir antes**: piloto no Acre (24 s) mostrou o custo e a taxa de
  divisa; a validação final reproduziu o piloto exatamente (79.159 pares,
  1.160 em >1 município).
- **Lotes por faixa de id, em paralelo**, com índice único criado antes. A
  ferramenta de execução em segundo plano mata jobs com mais de 10
  minutos; lotes de 250-500 mil polígonos ficam dentro disso. Se o cliente
  cair, o `INSERT` já enviado ao Postgres **termina sozinho** no servidor.
- Amazônia e Cerrado custam ~2x mais por polígono que Caatinga: município
  grande e complexo encarece o `ST_Intersects`.
- 9 de 6.880.431 polígonos ficaram sem município (borda/litoral);
  documentado, não bloqueia.

## Status de implementação

✅ **Concluído (2026-10-05)**: ponte `resultados.prodes_municipio`
(7.028.540 pares) e view `vetorial.v_prodes_municipio`, validadas contra o
piloto do Acre. Ver seção "Padrão: relação espacial N:N".


✅ **Concluído (2026-09-27)**: schemas `dim`/`resultados`/`catalogo`
criados; `dim.fontes` com 2 registros (INPE/TerraBrasilis `id_fonte=1`,
IBGE `id_fonte=2`); `catalogo.datasets` criado com o primeiro registro
(PRODES); `vetorial.prodes_desmatamento` retrofitado com
`id_fonte`/`importado_em` (preenchido via `DEFAULT`, sem precisar reescrever
as 6,88 milhões de linhas uma a uma); `dim.estados` criado e populado (27
UF, geometria real do IBGE, índice espacial incluído).

✅ **Concluído (2026-09-28)**: retrofit de `id_bioma` e `id_estado` em
`vetorial.prodes_desmatamento` finalizado e indexado
(`idx_prodes_id_bioma`, `idx_prodes_id_estado`) — 6.880.430 de 6.880.431
linhas com `id_estado` preenchido (a 1 linha restante tem `state` vazio na
origem, anomalia irrisória do dado bruto). Retrofit caro e cheio de
lições — ver "Ordem de trabalho: dimensão antes de fato" acima e a
pegadinha do `state varchar(2)` truncado logo abaixo.

✅ **Concluído (2026-10-01)**: primeira tabela real do schema `resultados`
— `resultados.desmatamento_imovel`, overlay `SICAR × PRODES` testado no
Acre (115.485 linhas, 36.005 imóveis com desmatamento real encontrado,
anos 2002-2025). Valida que o desenho dimensional (FK `id_imovel_sicar`,
`id_bioma`) aguenta uma consulta real, não só os dados brutos.

✅ **Concluído (2026-10-01)**: padrão de pastas (`bruto/processado/scripts/
LEIAME`) aplicado em todas as 9 fontes da raiz do projeto, incluindo 4
que estavam soltas sem documentação nenhuma (`ana`, `funai`, `incra`,
`mma`) e o `ibge`, que ganhou seu primeiro LEIAME cobrindo os 9 temas que
já tinha acumulado. Ver seção "Organização de pastas em disco".

✅ **Concluído (2026-10-01)**: `dim.municipios` criado a partir do IBGE —
5.572 municípios, `id_municipio` é o próprio código IBGE (não um serial
novo, pra casar direto com qualquer outro dataset que já traga código IBGE
de município), `id_estado` referenciado desde a criação, índice espacial
incluído. Primeira dimensão criada **antes** da tabela que vai usá-la
(SICAR), seguindo a regra "dimensão antes de fato" à risca.

A partir daqui, **todo dataset novo já nasce seguindo esse padrão** (schema
certo, `id_fonte` desde a criação, registro em `catalogo.datasets` assim que
importado) — não é mais um retrofit, é o processo normal de adicionar dado
novo. Ver [ROADMAP.md](ROADMAP.md) pra status/próximos datasets.
