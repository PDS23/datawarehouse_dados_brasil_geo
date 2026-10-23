# infra/ — Docker, banco, GeoServer e operação

Tudo o que não é "fonte de dado": a stack em Docker (PostgreSQL 18 + PostGIS 3.6 e GeoServer), o contêiner que roda os pipelines (`etl`), o SQL de
administração, e as rotinas de operação (backup, retenção, atualização agendada, diagrama do banco). Visão geral do projeto: [README](../README.md).

```
infra/
├── LEIAME_infra.md
├── docker-compose.stack.yml   PostGIS (dw-postgis) e GeoServer 2.28.2 (dw-geoserver), versões fixas
├── docker-compose.etl.yml     contêiner `etl` (Python 3.13) que roda os pipelines de coleta
├── .env.example               modelo (copiar para .env; o .env nunca é versionado)
├── etl/                       Dockerfile e requirements do contêiner de ETL
├── postgres/                  SQL de administração: papel `etl`, permissões de retenção e de manutenção (ANALYZE), ajustes pontuais
├── retencao.yaml              prazo único da retenção das versões fechadas (hoje 30 dias; ver ARQUITETURA.md, "Espelhos versionados")
├── estilos/                   estilos SLD do GeoServer (gerados dos .qml do QGIS)
├── diagrama/                  esquema do banco GERADO do catálogo do PostgreSQL + descricoes_colunas.yaml (texto do balão de cada coluna)
└── scripts/
    ├── dw.ps1                         comandos do dia a dia: consulta (somente leitura), psql, etl, backup, sync-drive, status
    ├── atualizar_fontes.ps1           atualização periódica das fontes vivas (backup antes, PRODES, MapBiomas, SICAR, retenção, backup depois)
    ├── registrar_tarefa_atualizacao.ps1   registra essa rotina no Agendador de Tarefas do Windows (domingos alternados, 00:10)
    ├── backup_banco.ps1               pg_dump em formato de diretório, conferido, com retenção e cópia externa opcional
    ├── limpar_versoes_fechadas.py     retenção: apaga, depois do prazo, o que a fonte retirou e não voltou; sem --apagar só relata
    ├── criar_papel_etl.ps1            cria o papel de serviço `etl` com senha aleatória, sem exibi-la
    ├── gerar_diagrama_banco.py · aplicar_descricoes_colunas.py   diagrama do banco e comentários de coluna
    └── publicar_geoserver.py · qml_para_sld.py                   publica o catálogo do GeoServer via REST; converte estilos QGIS em SLD
```

## Subir a stack

```powershell
cd infra
Copy-Item .env.example .env      # depois editar as senhas no .env
docker compose -f docker-compose.stack.yml up -d
docker compose -f docker-compose.stack.yml logs -f    # esperar "Server startup" e sair com Ctrl+C
```

Os pipelines rodam no contêiner `etl` (`docker-compose.etl.yml`), de preferência pelo atalho `scripts/dw.ps1 etl <script> [opções]`; o guia está em
[`scripts_comuns/LEIAME_pipelines.md`](../scripts_comuns/LEIAME_pipelines.md). Painel do GeoServer (usuário e senha do `.env`):
`http://localhost:8080/geoserver` (as portas ficam presas em `127.0.0.1` por padrão).

## Publicar o catálogo (GeoServer já no ar)

A configuração do GeoServer é código: `scripts/publicar_geoserver.py` sobe
tudo que o projeto serve, na ordem certa.

```powershell
& "C:\Program Files\QGIS 3.44.11\apps\Python312\python.exe" infra\scripts\publicar_geoserver.py
& "C:\Program Files\QGIS 3.44.11\apps\Python312\python.exe" infra\scripts\publicar_geoserver.py --apenas vetoriais rasters
```

Partes: `workspace`, `estilos`, `stores`, `vetoriais`, `rasters`, `limites`.

| Parte | O que garante |
|---|---|
| `workspace` | workspace `dw` com namespace `http://dw.local` |
| `estilos` | os 5 SLD de `estilos/` (cria ou atualiza) |
| `stores` | `dw_dim` (schema `dim`) e `dw_vetorial` (schema `vetorial`), papel `geoserver`, "Expose primary keys" ligado |
| `vetoriais` | `biomas`, `estados`, `municipios`, `sicar_imoveis`, `v_prodes_municipio`, com título, resumo e estilo |
| `rasters` | `mapbiomas_1985/2008/2015/2025`, `topodata_declividade_graus_rs_sc` e `_pct_rs_sc` |
| `limites` | WFS 100.000 feições; WMS 60 s / 65.536 KB / 1.000 erros; WCS leitura 524.288, saída 262.144, overview `NEAREST` |

Idempotente e só aditivo: o que existe é atualizado, nada é apagado. Lê
usuário, senha e endereço do `.env`. O que muda pra publicar uma camada nova é
só a lista no topo do script (`VETORIAIS`, `RASTERS`, `ESTILOS`). A senha do
papel `geoserver` (`GEOSERVER_DB_PASSWORD` no `.env`) só é necessária pra
**criar** um store; store existente é mantido sem reenviar senha. Pra gerar
um SLD novo a partir de um `.qml`: `qml_para_sld.py <entrada.qml> <saida.sld>
--nome <id> --titulo "<texto>"`.

Testado em 2026-10-06 contra o GeoServer em uso: rodar tudo não alterou
nenhum valor configurado (comparação antes/depois dos limites), e a criação
de camada vetorial e de workspace foi exercitada com objetos temporários
(criados, consultados por WFS e apagados). **Não testado ainda:** criação do
store PostGIS a partir do zero (exige a senha do papel); será exercitado na
migração para o desktop.

Pegadinhas da API REST pra camadas vetoriais:

- Criar um workspace por REST cria também um namespace `http://<nome>`; o
  script o troca pelo URI do projeto (`PUT /namespaces/dw`). Dois namespaces
  não podem ter o mesmo URI.
- A extensão (bbox) anunciada das camadas é um retângulo fixo do Brasil
  (`BBOX_BRASIL`), de propósito: calculá-la no banco varre a tabela, e na
  `v_prodes_municipio` varreria a junção de 7 milhões de linhas.
- O log do contêiner (`docker logs dw-geoserver`) mostra linhas `ERROR ...
  No such workspace/style` ao rodar o script num GeoServer vazio: são os
  404 das checagens de existência que o script faz antes de criar cada
  objeto, não falhas. Medido no desktop (2026-10-06): 25 linhas, todas desse
  tipo. Falha de verdade aparece como `ERRO ... HTTP` na saída do script e
  como código de saída diferente de 0.
- Regravar as configurações de serviço faz o GeoServer preencher campos
  novos com o padrão dele (ex.: `allowGlobalQueries`); os valores
  configurados não mudam.

Pegadinhas da API REST do GeoServer 2.28 (descobertas ao escrever o script):

- O endpoint `external.geotiff` **não achou** `file:///rasters/...` (erro
  "Failed to locate the input file"), embora a tela aceite o mesmo caminho.
  O script cria o store por JSON com `url` e publica a cobertura em seguida.
- A cobertura nativa de um GeoTIFF tem o **nome do arquivo sem extensão**.
- `?list=available` em `coverages` não devolveu a lista de disponíveis;
  usar o nome do arquivo direto.
- **Cobertura criada por REST só com o nome funciona no WMS mas não no WCS**
  (QGIS mostra "camada não disponível"). A tela preenche sozinha formatos
  de saída, métodos de interpolação e SRS de requisição/resposta; sem eles
  o `DescribeCoverage` fica quase vazio (507 bytes contra ~2,5 KB numa
  camada completa) e o cliente não sabe como pedir o dado. O script agora
  cadastra esses campos (`METADADOS_WCS`), inclusive em camada já
  existente. Como conferir sem credencial: `DescribeCoverage` anônimo,
  `.../wcs?service=WCS&version=1.0.0&request=DescribeCoverage&coverage=dw:<camada>`.
- **Não editar "Detalhes de Cobertura de Banda"** na tela de uma camada de
  raster. Camada criada pela tela traz esse bloco preenchido; editar o
  nome da banda deixou um nome `null`, e o `DescribeCoverage` passou a dar
  erro (`Value of attribute name was set to null`) em WCS **1.1.1 e 2.0.1**
  (o QGIS usa essas versões, daí "Camada não encontrada"), embora o 1.0.0
  continuasse funcionando. Camada criada pelo script não tem o bloco e o
  GeoServer calcula sozinho. Correção: apagar camada e store e rodar o
  script de novo. Teste de regressão: `DescribeCoverage` nas 3 versões
  (1.0.0, 1.1.1 com `identifiers=dw:<camada>`, 2.0.1 com
  `coverageId=dw__<camada>`) — todas devem dar HTTP 200.
- O QGIS guarda em cache o que a conexão WCS anunciou: depois de corrigir
  o servidor, remover a camada e recarregar a conexão.

## Filtros espaciais pelo WFS (testados em 2026-10-05)

Camada `dw:v_prodes_municipio`, parâmetro `cql_filter` (adicionar
`resultType=hits` pra só contar). Exemplos com Ribeirão Preto (id_municipio
3543402, 29 polígonos PRODES):

| Filtro | Resultado |
|---|---|
| `id_municipio=3543402` | 29 |
| `DWITHIN(geom, POINT(-21.17 -47.81), 100, kilometers)` | 8.451 (baixa em ~3 s) |
| mesmo + `AND year>=2020` | 514 |
| mesmo + `AND year>=2020 AND area_km>=0.1` | 21 |

**Pegadinha: ordem dos eixos.** Em WFS 2.0.0 com EPSG:4674 o GeoServer espera
**lat lon** nas geometrias do filtro (`POINT(-21.17 -47.81)`). Em
lon lat (`POINT(-47.81 -21.17)`) a consulta não dá erro: **devolve 0
feições**. Resultado zero em filtro espacial = desconfiar da ordem dos eixos
antes de achar que não há dados. `BBOX(geom,x1,y1,x2,y2,'EPSG:4674')` com o
código explícito usa lon lat.

**Pegadinha: funções do Compositor SQL do QGIS.** O GeoServer não conhece
`ST_GeomFromText`. O erro que aparece no QGIS (`I dont understand the tag:
fes:ValueReference`) engana: é um erro secundário do parser antigo; a causa
está no log do container (`docker logs dw-geoserver`: `Unable to find
function ST_GeomFromText`). A função equivalente do GeoServer é `geomFromWKT`
(lista completa em `GetCapabilities`, seção `fes:Functions`). Testado por
POST em WFS 2.0: `DWithin(geom, geomFromWKT('POINT(-21.17 -47.81)'), 100000 m)`
= 8.451. Nesse caminho (função) o WKT também vai em lat lon.

`DWITHIN` em CRS geográfico converte km pra graus de forma aproximada e mede a
partir do ponto dado, não da borda do município. Pra distância exata a partir
da fronteira: buffer em CRS projetado no QGIS + "Extrair por localização".

Junção espacial entre duas camadas (ex.: PRODES × município por `ST_Intersects`)
**não** é suportada pelo WFS do GeoServer; por isso existe a ponte
`resultados.prodes_municipio` (filtro por chave).

## Decisões

- **Portas presas em `127.0.0.1` por padrão.** Expor numa rede privada é opt-in
  (`GEOSERVER_BIND_IP` e `POSTGRES_BIND_IP` no `.env`), junto com uma regra de firewall
  restrita a essa rede.
- **Configuração do GeoServer em volume nomeado** (`geoserver_data`), não em
  pasta do projeto: pastas sincronizadas na nuvem travam arquivos pequenos
  escritos o tempo todo. Backup/migração: exportar o volume (`tar`) em vez
  de copiar pasta.
- **Rasters montados somente leitura** direto de `mapbiomas/` e `elevacao/`.
  Os arquivos precisam estar de fato no disco: arquivo só-online (placeholder
  de pasta sincronizada) quebra o bind mount.
- **Sem extensões por enquanto.** WMS/WFS/WCS, GeoTIFF e o datastore PostGIS
  já vêm no GeoServer. Extensões só quando houver necessidade medida.
