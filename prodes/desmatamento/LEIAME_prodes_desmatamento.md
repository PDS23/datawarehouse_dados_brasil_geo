# prodes/desmatamento — PRODES (INPE/TerraBrasilis): polígonos de desmatamento por bioma

PRODES é uma fonte **por edição**: o INPE publica o vetor de cada bioma de tempos em tempos, e cada edição traz as feições
dos anos anteriores mais as novas. O ano (`year`, `main_class = dAAAA`) é dado, não pasta. Cruzamentos derivados do PRODES
vivem em `analises/` (`ponte_prodes_municipio`, `desmatamento_imovel`), não nesta pasta.

## Pipeline (desde 2026-10-21): espelho versionado do INPE, download + carga num comando só

O banco é um **espelho do INPE**, igual ao SICAR: cada feição tem versões (`vigente_desde`/`vigente_ate`; vigente = `vigente_ate IS NULL`).
Feição nova entra; feição alterada fecha a versão antiga e insere a nova; feição que o INPE retirou tem a versão fechada (nada é apagado).

```
prodes/desmatamento/
├── LEIAME_prodes_desmatamento.md
├── config.yaml                       catálogo do TerraBrasilis, um bloco por bioma (dataset, padrão do arquivo, camadas, id_bioma), paralelismo
├── sql/01_tabela.sql                 tabela (em prodes_novo), catalogo.coletas.edicao, mapa de colunas
├── sql/02_indices_chaves.sql         índices e chaves estrangeiras depois da carga
├── scripts/prodes_desmatamento.py    descobre a edição mais recente, baixa, reconcilia cada bioma
└── bruto/<bioma>/                    GeoPackage como veio + manifesto.json (versão, bytes, sha256) — fora do git
```

```powershell
# a partir de D:\data_warehouse\infra
docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl prodes/desmatamento/scripts/prodes_desmatamento.py --verificar   # fonte x banco: o que há de novo
... run --rm etl prodes/desmatamento/scripts/prodes_desmatamento.py --biomas cerrado --simular                                                      # ensaio, sem gravar
... run --rm etl prodes/desmatamento/scripts/prodes_desmatamento.py                                                                                 # baixa e reconcilia o que tem edição nova
```

**Como baixa.** O TerraBrasilis monta a página de downloads a partir de um catálogo JSON (`/business/api/v1/download/all`). O nome do
arquivo leva a data da publicação (`prodes_biome_<bioma>_vAAAAMMDD.gpkg.zip`) e muda a cada edição: o script consulta o catálogo, acha o
arquivo de cada bioma pelo padrão do `config.yaml` e usa a versão mais recente (`--versao AAAAMMDD` fixa uma). Baixa vários biomas ao
mesmo tempo (`--paralelo`, padrão 3, máx. 4), com retomada (o servidor derruba conexões em arquivos grandes: foram até 3 quedas por
arquivo, todas retomadas) e conferência de tamanho; o zip é descartado depois de extraído e o sha256 fica no manifesto.

**Como grava.** Cada bioma é lido e reconciliado num processo próprio, com conexão própria (o papel `etl` tem limite de 5), numa
transação: as feições vão para uma tabela temporária, são comparadas com as versões vigentes do bioma (atributos e geometria), e
só então gravadas. Bioma cuja edição já foi carregada é pulado (`catalogo.coletas.edicao`). Travas: se mais de 10% das feições
vigentes sumirem na edição, o bioma não é gravado (`--aceitar-queda` libera); a conferência exige inseridas = novas + alteradas.
Cada execução vira uma linha em `catalogo.cargas` e cada bioma uma em `catalogo.coletas`.

Regras: a identidade da feição é **(bioma, `uuid`)**: o mesmo `uuid` pode estar nos arquivos de dois biomas (polígonos de divisa; 2 casos
no Cerrado) e fica nos dois. `uuid` repetido entre camadas do mesmo bioma: vale a primeira camada do `config.yaml`. Feição sem
geometria ou com a caixa fora do Brasil entra com `geom` NULL, `geom_anomala = true` e o EWKT original em `geom_origem_texto` (hoje: as
2 feições da Amazônia com X/Y trocados). `state` entra como o INPE entrega, sem truncar. Só a camada `yearly_deforestation` de cada
bioma é carregada (na Amazônia, também `yearly_deforestation_nf_biome`); desmatamento acumulado, hidrografia, resíduo e nuvem não.

**Feição retirada e depois republicada** (regra de 2026-10-21, igual ao SICAR): se o INPE retira uma feição, a versão é fechada
(`vigente_ate`). Se ela volta **idêntica** à última versão fechada, essa versão é **reaberta** (`vigente_ate` volta a NULL, mesmo `id`,
`reaberto_em` registra a data), então a ponte por município e os resultados que apontam para o `id` continuam valendo. Se volta
**diferente**, entra uma versão nova (`id` novo) e a antiga continua fechada. Há sempre no máximo uma versão vigente por
(bioma, `uuid`). Testado numa cópia do Pantanal: 3 reabertos, 3 novos, 1 alterado, vigentes = fonte, nenhuma duplicada.

**Retenção:** feições que o INPE retirou e não voltaram são apagadas, com os resultados que dependem delas, depois de um prazo
(padrão 365 dias) pela rotina `infra/scripts/limpar_versoes_fechadas.py` (config em `infra/retencao.yaml`). Sem `--apagar` ela só
relata; não é agendada. Tabelas derivadas usam só a versão vigente (`v_prodes_municipio`, `v_desmatamento_imovel_vigente`).

## Carga do zero e validação (2026-10-21, tabela de construção `prodes_novo.prodes_desmatamento`; produção intocada)

Os 6 biomas foram baixados e carregados do zero pelo script: **6.936.963 feições** (a produção tem 6.880.431), todas vigentes.
Comparação com a produção (por bioma + `uuid`; `main_class` sem diferenciar maiúsculas; área com tolerância de 1e-9):

| Bioma | Edição | Feições | Resultado frente à produção |
|---|---|---|---|
| Caatinga | v20260805 | 2.260.564 | idêntico (atributos e geometrias) |
| Mata Atlântica | v20260806 | 1.113.709 | idêntico |
| Pampa | v20260807 | 213.638 | idêntico |
| Pantanal | v20260717 | 37.155 | idêntico |
| Amazônia | v20261016 | 923.182 | +4.372 novas, −634 que o INPE retirou, 669 geometrias e 484 áreas revisadas |
| Cerrado | v20261016 | 2.388.715 | +53.304 novas (52.934 do ano **2026**), −510 retiradas, 347 geometrias e 235 áreas revisadas |

- Reexecutar é idempotente: Pantanal e Pampa, com `--forcar --simular`, deram 0 novos, 0 alterados, 0 ausentes.
- **`state` da produção antiga está truncado em 2 letras** em 546.817 linhas (`RI` por "RIO GRANDE DO SUL", `MI`, `SÃ`, `DI`): efeito da
  largura declarada no GeoPackage na carga manual de 2026-09. O `id_estado` estava correto; a tabela nova grava o texto inteiro.
- `main_class` vem em minúsculas (`desmatamento`) em parte das feições da edição nova da Amazônia: filtre com `lower()`.
- 7 geometrias inválidas na camada não-floresta da Amazônia (mantidas como entregues; use `ST_MakeValid` na análise); 1 feição da
  Mata Atlântica sem estado casável (`id_estado` NULL).
- **Troca feita em 2026-10-21** (depois do backup `20261021-141807-antes-troca-prodes`, no D: e no Drive): o espelho assumiu
  `vetorial.prodes_desmatamento` (`sql/03_troca.sql`); a ponte `resultados.prodes_municipio` foi refeita só com polígonos vigentes
  (7.084.906 pares, 6.936.952 polígonos; 11 vigentes sem município: as 2 anômalas da Amazônia e 9 já conhecidos); a view
  `vetorial.v_prodes_municipio` mostra só os vigentes e a camada do GeoServer foi republicada. Guardadas até o usuário aprovar
  apagar: `vetorial.prodes_desmatamento_carga_manual_antiga` (6.880.431 linhas, com `state` truncado) e
  `resultados.prodes_municipio_carga_manual_antiga` (7.027.719 pares). O schema de testes `prodes_teste` também aguarda aprovação.

> O restante deste documento é o **histórico da carga inicial (2026-09-22/27)**, escrito no notebook, que foi feita por
> comandos `ogr2ogr` soltos. Mantido como registro das particularidades da fonte; o método de carga vigente é o pipeline acima.

## Por que por bioma, não "Brasil inteiro"

Verificado direto no [TerraBrasilis](https://terrabrasilis.dpi.inpe.br/downloads/)
em 2026-09-22: **não existe GeoPackage vetorial consolidado do Brasil
inteiro** — isso só existe em raster (`Brasil - PRODES (Desmatamento)` só
tem Geotiff + um PDF de mapa). O vetor completo só existe por bioma (6:
Amazônia, Caatinga, Cerrado, Mata Atlântica, Pampa, Pantanal).

Links usados (podem mudar - o nome do arquivo carrega a data de publicação,
confirme no site se o download falhar):

| Bioma | Tamanho (zip) | Link |
|---|---|---|
| Amazônia | ~820MB | `/download/dataset/amz-prodes/vector/prodes_biome_amazonia_v20260717.gpkg.zip` |
| Caatinga | ~3,4GB | `/download/dataset/caatinga-prodes/vector/prodes_biome_caatinga_v20260805.gpkg.zip` |
| Cerrado | ~1,9GB | `/download/dataset/cerrado-prodes/vector/prodes_biome_cerrado_v20260717.gpkg.zip` |
| Mata Atlântica | ~4,4GB | `/download/dataset/mata-atlantica-prodes/vector/prodes_biome_mata_atlantica_v20260806.gpkg.zip` |
| Pampa | ~290MB | `/download/dataset/pampa-prodes/vector/prodes_biome_pampa_v20260807.gpkg.zip` |
| Pantanal | ~57MB | `/download/dataset/pantanal-prodes/vector/prodes_biome_pantanal_v20260717.gpkg.zip` |

Base: `https://terrabrasilis.dpi.inpe.br`. Todos os 6 já foram baixados e
estão em `vetor/bruto/<bioma>/`.

## ⚠️ "Amazônia Legal" foi deliberadamente excluído do merge

Existe um 7º produto vetorial, "Amazônia Legal - PRODES", que **não**
entra em nenhum merge deste projeto. Motivo: verificado no metadado oficial
que o atributo `source` desse produto documenta explicitamente que ele
**incorpora polígonos de outros biomas** ("zonas da amazônia legal no
cerrado e pantanal") — ou seja, ele se sobrepõe com Bioma Amazônia e partes
de Bioma Cerrado/Pantanal. Somar "Amazônia Legal" + os 6 biomas contaria
área desmatada em dobro nessa faixa de transição. Os 6 biomas, por serem
uma partição do território (não se sobrepõem entre si), são a fonte certa
pra um mosaico nacional sem duplicação.

## Diferenças de schema entre biomas (importante pra qualquer merge)

Descobertas ao inspecionar os 6 arquivos com `ogrinfo` (2026-09-22):

1. **Nomenclatura de camada difere**: a Amazônia usa duas camadas,
   `yearly_deforestation_biome` (floresta) e `yearly_deforestation_nf_biome`
   (não-floresta) — os outros 5 biomas usam uma única camada
   `yearly_deforestation` que já cobre os dois tipos de vegetação juntos.
   **Usar só `yearly_deforestation_biome` da Amazônia deixaria de fora
   ~117 mil polígonos de desmatamento não-florestal** — confirmado
   comparando os valores de `main_class`/`class_name` (ambas as camadas da
   Amazônia usam o mesmo esquema `DESMATAMENTO`/`dAAAA`, então são partes do
   mesmo conceito, só separadas por tipo de vegetação).
2. **Coluna extra na Amazônia**: `sub_class`, que os outros 5 biomas não
   têm. Mantida no merge (fica `NULL` pros outros biomas).
3. **Formato do campo `state` inconsistente entre biomas**: a maioria usa
   sigla (`"RS"`, `"MT"`), mas o **Pampa usa o nome completo do estado**
   (`"RIO GRANDE DO SUL"`, 17 caracteres). O GeoPackage/SQLite não trunca
   (só ignora o limite declarado de largura da coluna), então o dado não se
   perde, mas **filtrar por `state = 'RS'` no resultado mesclado vai
   ignorar as linhas do Pampa** — ou normaliza esse campo antes de usar em
   filtro, ou filtra por bioma/geometria em vez de por sigla de estado.
4. **CRS consistente em todos os 6**: SIRGAS 2000 (EPSG:4674) — sem
   necessidade de reprojetar pra unir.

## ⚠️ Duas feições com coordenada X/Y trocada na Amazônia

Achado ao investigar por que a extensão espacial da camada
`yearly_deforestation_biome` da Amazônia ia até -58° de latitude (impossível
pro bioma, que vai só até ~-18°): duas feições (fid 35824 e 35989) têm
longitude e latitude trocadas — deveriam estar em ~(lon -58,6, lat -11,45),
no meio do Mato Grosso, mas estão gravadas como (lon -11,45, lat -58,6), o
que cai no oceano perto da Antártida. É um erro no dado de origem do INPE
(confirmado consultando os arquivos brutos, nada a ver com processamento
daqui). Área irrisória (~0,015 km² somadas), mas coordenada errada quebra
bounding box/índice espacial se entrar num merge. **Excluídas do merge**
(`WHERE fid NOT IN (35824, 35989)`) — o arquivo bruto original **não foi
alterado**, só o merge processado ignora essas duas.

## ✅ Status: os 6 biomas estão no PostGIS (2026-09-27)

Tabela `vetorial.prodes_desmatamento` no banco `data_warehouse`, com o
Brasil inteiro (os 6 biomas) numa tabela só:

| Bioma | Feições |
|---|---|
| Amazônia | 919.444 |
| Caatinga | 2.260.564 |
| Cerrado | 2.335.921 |
| Mata Atlântica | 1.113.709 |
| Pampa | 213.638 |
| Pantanal | 37.155 |
| **Total** | **6.880.431** |

Validação final: `COUNT(*) = COUNT(DISTINCT uuid) = 6.880.431` (zero
duplicata), zero geometria inválida (`ST_IsValid`), CRS único EPSG:4674.

Índices criados na tabela:
- `prodes_desmatamento_pkey` — chave primária (`id`)
- `prodes_desmatamento_geom_geom_idx` — **GIST** em `geom` (criado
  automaticamente pelo driver do `ogr2ogr`, é o índice espacial que faz
  consulta por polígono pequeno ser rápida mesmo com o Brasil inteiro na
  tabela)
- `idx_prodes_bioma` — btree em `bioma`, acelera filtro por bioma
- `idx_prodes_uuid` — **btree único** em `uuid`, acelera busca por uuid E
  impede fisicamente duplicata futura (ver incidente do Pantanal abaixo)

### Como foi importado

Pampa + Mata Atlântica (os 2 primeiros) via um arquivo intermediário
(`processado/prodes_desmatamento_pampa_mata_atlantica.gpkg`, ~1,36GB) gerado
pelo `montar_mosaico_vetorial.py`, importado com `ogr2ogr -f PostgreSQL`.

Os outros 4 (Caatinga, Cerrado, Pantanal, Amazônia) foram importados **direto
de `bruto/<bioma>/*.gpkg` pro Postgres**, sem gerar arquivo intermediário —
uma vez que o PostGIS já existe, não há motivo pra passar por um arquivo no
meio, é só usar `-append` direto. O "carimbo" de `bioma`/`camada_origem` que
antes era feito pelo script Python passou a ser feito na hora, via `-sql
"SELECT *, 'caatinga' AS bioma, ..."` dentro do próprio comando `ogr2ogr`. O
script `montar_mosaico_vetorial.py` continua útil pra gerar um arquivo
portátil quando precisar (ex.: levar pra fora do banco), mas deixou de ser
uma etapa obrigatória do pipeline de import.

### ⚠️ Incidente: Pantanal duplicado 4x (corrigido)

Ao rodar o import do Pantanal, o comando bateu num erro de `PROJ_LIB` (ver
seção abaixo) — mas antes de identificar a causa, o comando tinha sido
repetido algumas vezes, e cada tentativa que rodava até o fim **inserida de
novo** (o `-append` não sabe que aquele dado já estava lá). Resultado: 37.155
feições reais viraram 148.620 linhas (4x). Detectado comparando
`COUNT(*)` vs `COUNT(DISTINCT uuid)` pro bioma, corrigido com um `DELETE`
mantendo só 1 linha por `uuid` (menor `id`). **Lição**: depois de criar o
índice único em `uuid`, esse tipo de erro passa a ser impossível — o
Postgres rejeita o insert duplicado na hora, em vez de aceitar silenciosamente.

### ⚠️ Erro de `PROJ_LIB` ao rodar `ogr2ogr` do QGIS

O instalador do PostGIS Bundle registra a variável de ambiente `PROJ_LIB`
(nível de Máquina) apontando pro `proj.db` dele mesmo
(`C:\Program Files\PostgreSQL\18\share\contrib\postgis-3.6\proj`). Isso
conflita com o `ogr2ogr.exe` do QGIS, que espera a versão de PROJ dele
próprio — dá erro `PROJ: ... DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a
number >= 6 is expected`. **Não altere a variável global** (o serviço do
Postgres depende dela pras próprias funções internas) — em vez disso,
sobrescreva só na sessão do terminal antes de rodar `ogr2ogr`:
```powershell
$env:PROJ_LIB = "C:\Program Files\QGIS 3.44.11\share\proj"
```
Vale a cada janela nova do PowerShell/terminal.

### ⚠️ 13 feições duplicadas entre as camadas da Amazônia (corrigido)

Achado ao conferir `COUNT(*)` vs `COUNT(DISTINCT uuid)` do total geral: 13
`uuid` apareciam 2x, sempre dentro do bioma `amazonia` — a mesma feição
existia tanto em `yearly_deforestation_biome` (floresta) quanto em
`yearly_deforestation_nf_biome` (não-floresta), provavelmente casos de
fronteira na classificação do próprio INPE. Corrigido removendo 1 cópia de
cada (mesma lógica do Pantanal). Impacto irrisório (13 polígonos de ~6,9
milhões), mas documentado porque é mais uma particularidade real dos dados
de origem, não um erro nosso.

## Scripts

Ver "Pipeline" no início: `scripts/prodes_desmatamento.py` substitui o download avulso e os comandos `ogr2ogr` desta seção histórica.

## Próximo passo

Agendar a verificação/atualização (`--verificar` é barato e diz se há edição nova; frequência a decidir, o PRODES atualiza periodicamente, com várias edições por bioma ao longo do ano),
decidir o prazo definitivo da retenção e quando apagar as tabelas guardadas da carga manual.
