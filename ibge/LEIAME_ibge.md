# ibge/ — IBGE (várias camadas de referência)

Diferente das outras fontes do projeto (1 fonte = 1 dataset), o IBGE
contribui com **várias camadas temáticas independentes**, cada uma na sua
própria subpasta, todas seguindo o mesmo padrão interno
(`bruto/processado`).

> **Atualizado em 2026-10-20.** O texto abaixo vem do notebook (2026-10-13). Hoje, neste repositório, as fontes do IBGE com
> pipeline completo (padrão de ARQUITETURA.md) são **`municipios/`** (malha municipal e estadual versionada), **`PAM/`**
> (SIDRA 5457) e **`censo_agropecuario/`** (SIDRA 6956, edição 2017). As camadas de geologia, geomorfologia, pedologia,
> vegetação e clima ainda não têm pasta aqui (só existiam como download no notebook; importar só sob demanda).

## Organização

```
ibge/
├── LEIAME_ibge.md              este arquivo (índice das fontes do IBGE)
├── municipios/                 malha municipal e estadual (dim.municipios, dim.estados) — pipeline
├── PAM/                        Produção Agrícola Municipal — pipeline
├── censo_agropecuario/         Censo Agropecuário (hoje a edição 2017) — pipeline
└── (a criar, sob demanda)      geologia, geomorfologia, pedologia, vegetação, clima: uma pasta por camada, no padrão
```

## Status por camada

| Camada | Status | Onde foi parar no PostGIS |
|---|---|---|
| estados (hoje em `municipios/`) | ✅ Importado; malha 2025 aplicada em 2026-10-20 | `dim.estados` (27 UF) |
| biomas | ✅ Importado (2026-09-27); carga feita à mão, sem pasta/pipeline neste repositório | `vetorial.ibge_dominios_naturais`, `vetorial.ibge_regioes_naturais`, `dim.biomas` (dissolvido) |
| `municipios/` | ✅ Pipeline; malha 2025 (5.573) aplicada em 2026-10-20 | `dim.municipios` (`id_municipio` = código IBGE) |
| `geol_area/` (geologia) | ⏳ Baixado, não importado (131.547 feições) | — |
| `geom_area/` (geomorfologia) | ⏳ Baixado, não importado (120.218 feições) | — |
| `pedo_area/` (pedologia) | ⏳ Baixado, não importado (114.658 feições) | — |
| `vege_area/` (vegetação) | ⏳ Baixado, não importado (145.458 feições) | — |
| `PAM/` (produção agrícola) | ✅ Pipeline sob demanda (por produto) | `tabular.ibge_pam` |
| `censo_agropecuario/` | ✅ Pipeline sob demanda (por produto; hoje laranja) | `tabular.ibge_censoagro2017_estab_lavoura_perm` |
| `Clima_5000mil/` | ⏳ Baixado, nunca investigado | — |

## Versões e links verificados (2026-10-13)

Servidor de arquivos do IBGE: <https://geoftp.ibge.gov.br/>. Os caminhos abaixo
foram abertos e responderam HTTP 200; o ano das camadas BDiA foi inferido pela
data de atualização gravada no `.dbf` de cada arquivo (`ogrinfo`, campo
`DBF_DATE_LAST_UPDATE`) cruzada com as pastas `versao_AAAA` do IBGE.

| Camada local | O que é | Ano | Escala | Download |
|---|---|---|---|---|
| `estados/` | `BR_UF_2025` | 2025 | n/d | `organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/Brasil/BR_UF_2025.zip` |
| `municipios/` | malha municipal, 5.572 unidades | **2022–2024** (sem Boa Esperança do Norte/MT, instalado em 2025; a malha 2025 tem 5.573) | n/d | `.../malhas_municipais/` (pastas `municipio_AAAA`) |
| `biomas/` | domínios e regiões naturais | 2025 | 1:250.000 | `informacoes_ambientais/estudos_ambientais/biomas/dominios_regioes_naturais_do_brasil/2025/dados_geoespaciais/dmRgNtTrBmBr_v2025_vetor_e250K.zip` |
| `geol_area/` | BDiA geologia | 2026 (`.dbf` 22/07/2026) | 1:250.000 | `informacoes_ambientais/geologia/levantamento_geologico/vetores/escala_250_mil/versao_2026/geol_area.zip` |
| `geom_area/` | BDiA geomorfologia | 2021 (`.dbf` 23/06/2021) | 1:250.000 | `informacoes_ambientais/geomorfologia/vetores/escala_250_mil/versao_2021/geom_area.zip` |
| `pedo_area/` | BDiA pedologia | 2021 (`.dbf` 24/06/2021) | 1:250.000 | `informacoes_ambientais/pedologia/vetores/escala_250_mil/versao_2021/pedo_area.zip` |
| `vege_area/` | BDiA vegetação | 2026 (`.dbf` 08/06/2026) | 1:250.000 | `informacoes_ambientais/vegetacao/vetores/escala_250_mil/versao_2026/vege_area.zip` |
| `Clima_5000mil/` | Mapa de Climas do Brasil | 2002 | 1:5.000.000 | `informacoes_ambientais/climatologia/vetores/brasil/Clima_5000mil.zip` |
| `projetos/mate_rs/` | SIDRA Tabela 1613 (erva-mate, RS; coleta manual, projeto) | 2023–2025 | n/a | <https://sidra.ibge.gov.br/tabela/1613> |

Pastas de versão existentes hoje para geologia, geomorfologia, pedologia e
vegetação: 2017, 2018, 2019, 2021, 2023, 2025 e 2026. **Geomorfologia e
pedologia locais são da versão 2021 (há 2023, 2025 e 2026 mais novas)**; vale
atualizar antes de importar. O registro de metadados do IBGE para o clima lista
denominador 15.000.000, provável erro de digitação (o título do produto é
1:5.000.000).

As 4 camadas pendentes de vetor (geologia/geomorfologia/pedologia/
vegetação) já foram inspecionadas uma vez (confirmado: todas UTF-8 via
`.cpg`, todas EPSG:4674, extensão Brasil inteiro) — faltou só decidir
dimensões/FKs e importar de fato, seguindo a regra "dimensão antes de
fato" do ARQUITETURA.md.

## Pegadinha já conhecida (herdada do SICAR, vale aqui também)

Camadas de vetor do IBGE até agora sempre vieram em **Shapefile**, que tem
largura de coluna fixa no `.dbf` — mesmo risco de truncagem silenciosa que
já mordeu o SICAR (`state varchar(2)`). Antes de pré-criar qualquer tabela
nova a partir dessas camadas, usar `text` pras colunas de texto (nunca
`varchar(n)` curto), independente do que o `ogrinfo` reportar de largura
declarada.
