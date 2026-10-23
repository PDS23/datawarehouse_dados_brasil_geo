# mapbiomas/alerta — MapBiomas Alerta: alertas de desmatamento validados

Espelho versionado, em `vetorial.mapbiomas_alerta`, da camada pública `dashboard-alert-shapefile` do servidor de mapas do MapBiomas Alerta
(`maps.alerta.mapbiomas.org`, WFS aberto, sem login). Mesma mecânica do SICAR e do PRODES: alerta novo entra; alterado fecha a versão antiga e insere a
nova; alerta que o servidor deixou de publicar tem a versão **fechada** (nada é apagado na coleta); alerta que sumiu e voltou **idêntico** tem a versão
**reaberta**. Vigente = `vigente_ate IS NULL`. **Roda só sob demanda.**

```
mapbiomas/alerta/
├── LEIAME_mapbiomas_alerta.md
├── config.yaml                      servidor, camada, fatias, tolerâncias
├── sql/01_tabela.sql                tabela, mapa de colunas e permissões (rodar como postgres)
├── sql/02_indices_chaves.sql        índices e chave estrangeira, depois da primeira carga
├── scripts/mapbiomas_alerta.py      baixa em fatias, em paralelo, e reconcilia
└── bruto/wfs/                       fatias baixadas (SHAPE-ZIP), fora do git e do Drive
```

```powershell
# a partir de D:\data_warehouse\infra
docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl mapbiomas/alerta/scripts/mapbiomas_alerta.py --simular    # ensaio, nada gravado
... run --rm etl mapbiomas/alerta/scripts/mapbiomas_alerta.py                                                                                # baixa tudo e reconcilia
... run --rm etl mapbiomas/alerta/scripts/mapbiomas_alerta.py --so-baixar                                                                    # só guarda os arquivos em bruto/, sem banco
... run --rm etl mapbiomas/alerta/scripts/mapbiomas_alerta.py --codigos 200000-230000                                                        # só uma faixa (testes)
```

## É o mesmo arquivo do dashboard?

Comparado em 2026-10-21 com `dashboard_alerts-shapefile.shp` (Drive, exportado em 03/03/2026): **mesma estrutura**. Polígonos, SIRGAS 2000 (EPSG:4674),
e os 9 campos do arquivo existem na camada, com nomes em inglês; a camada traz campos a mais. O conteúdo é mais novo, como esperado (arquivo: 506.846
alertas, nenhum de 2026; servidor em 2026-10-21: 543.378).

| Arquivo do dashboard | Camada do servidor (e coluna no banco) |
|---|---|
| `CODEALERTA` | `alert_code` |
| `FONTE` (entre chaves: `{SAD,GLAD}`) | `sources` (sem chaves) |
| `BIOMA` / `ESTADO` / `MUNICIPIO` | `biomes` / `states` / `cities` |
| `AREAHA` (2 casas) | `area_ha` (4 casas) |
| `ANODETEC` / `DATADETEC` | `year_detected_at` / `detected_at` |
| `DTIMGANT` | `image_before_at` |
| (não existe) | `published_at`, `image_after_at`, `deforestation_driver`, `status_name`, `lat`, `lng`, `crossed_special_territories`, `crossed_rural_properties_total` |

## Particularidades da fonte

- **A camada traz alertas cancelados** (`status_name = 'cancelled'`, cerca de 0,5%: 78 em 15.672 numa faixa testada) junto com os publicados. Filtre na análise.
- **Precisão das coordenadas:** GeoJSON e GML do servidor cortam as coordenadas em **4 casas decimais** (~5 m de deslocamento por vértice). O **SHAPE-ZIP** traz a
  precisão completa (idêntica à do arquivo do dashboard); por isso o script baixa em SHAPE-ZIP. Com `srsName=EPSG:4674` (forma curta) as coordenadas vêm em
  longitude/latitude; a forma `urn:ogc:def:crs:EPSG::4674` inverte os eixos.
- **Custo por pedido:** ~17 s fixos por pedido no servidor, qualquer que seja o tamanho; paginar por posição (`startIndex`) é lento. O script fatia por **faixa de
  `alert_code`** (filtro rápido e estável): ~15 a 20 mil alertas por fatia, em ~30 s, 4 fatias ao mesmo tempo (`--paralelo`, máx. 6).
- **A camada muda ao vivo** (publicação e revalidação contínuas; o alerta mais recente tinha sido publicado no dia anterior): o script confere o total baixado contra o
  anunciado (tolerância de 0,2%) e não grava se mais de 10% dos vigentes sumirem (`--aceitar-queda` libera).
- Nomes de campo do shapefile vêm truncados em 10 letras (`detected_a`, `deformat`...); o script traduz para os nomes completos.
- ~2% das geometrias chegam inválidas (autointerseção), mantidas como entregues: use `ST_MakeValid` na análise.
- Há outras camadas no mesmo servidor (por exemplo, `dashboard-alert-rural-properties-shapefile`, alertas por imóvel rural, e versões "staging"); não carregadas.

## Estado

**Carga completa feita em 2026-10-21:** 543.378 alertas (2018 a 2026; 2.947 cancelados), todos vigentes, 865 MB com índices; download em 323 s e gravação em 362 s no total
(28 fatias, 6 ao mesmo tempo). Por ano: 2018 1.941 | 2019 56.822 | 2020 99.394 | 2021 91.741 | 2022 85.798 | 2023 85.088 | 2024 61.147 | 2025 46.350 | 2026 15.097.
Reexecutar atualiza só o que mudou (teste em faixa: repetição sem regravar nada). Retenção das versões fechadas: `infra/retencao.yaml` (1 ano).

Licença: dados abertos do MapBiomas Alerta; confirmar os termos de uso e a citação antes de redistribuir.
