# sfb/florestas_publicas — Cadastro Nacional de Florestas Públicas (CNFP, Serviço Florestal Brasileiro)

Espelho versionado, em `vetorial.sfb_florestas_publicas`, do **Cadastro Nacional de Florestas Públicas** do Serviço Florestal Brasileiro (SFB), publicado no portal de dados abertos
([dataset](https://dados.florestal.gov.br/dataset/cadastro-nacional-de-florestas-publicas-cnfp)). Edição carregada: **2025** (zip de 26/06/2026), **12.874 polígonos**.
Mesma mecânica das outras fontes vivas (regras em `scripts_comuns/dwlib/espelho.py`): registro novo entra; alterado fecha a versão antiga e insere a nova; registro que a edição
nova não traz tem a versão **fechada** (nada é apagado); o que sumiu e voltou **idêntico** tem a versão **reaberta**. Vigente = `vigente_ate IS NULL`.

## O que é o CNFP

Um único mapa das áreas **públicas com floresta** (ou potencial florestal), de qualquer esfera, em categorias que no resto do banco estão em fontes separadas ou ainda faltam:
**assentamentos do INCRA** (PA, PAE, PDS, PCA... ≈ 7,6 mil polígonos; o WFS do INCRA está fora do ar, ver ROADMAP), unidades de conservação federais, estaduais e municipais, terras
indígenas, glebas arrecadadas sem destinação (`TIPO B`), áreas militares, quilombolas. Cada polígono diz a categoria, o órgão, o ato legal, o bioma e os municípios.
**Não substitui** as fontes próprias (FUNAI para terras indígenas, CNUC para UCs): é a visão consolidada do SFB, com o recorte de floresta pública.

## Coleta 100% automatizada

```
sfb/florestas_publicas/
├── LEIAME_florestas_publicas.md · HISTORICO.md
├── config.yaml                          CKAN, padrão do recurso, URL do download, campos esperados, chave, limites de sanidade
├── sql/01_tabela.sql                    fonte em dim.fontes, tabela, índices, mapa de colunas e permissões (rodar como postgres)
└── scripts/florestas_publicas.py        CKAN -> escolhe a edição -> baixa o zip -> reconcilia (usa dwlib/espelho.py)
```

O CKAN do SFB lista um recurso "AAAA - Cadastro Nacional de Florestas Públicas" por ano, que aponta para um **item público do portal ArcGIS do SFB** (`mapas.florestal.gov.br`).
O item é um shapefile ZIP baixável sem login em `.../sharing/rest/content/items/<id>/data`. O pipeline lê o CKAN, pega a edição mais recente, baixa (≈ 230 MB, ≈ 50 s), descompacta
em área temporária e reconcilia. **Edição nova no CKAN = carga automática da edição nova**; nada manual.

```powershell
.\infra\scripts\dw.ps1 etl sfb/florestas_publicas/scripts/florestas_publicas.py --verificar   # qual a edição mais recente do CKAN e qual o banco tem
.\infra\scripts\dw.ps1 etl sfb/florestas_publicas/scripts/florestas_publicas.py --simular     # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl sfb/florestas_publicas/scripts/florestas_publicas.py               # baixa e reconcilia (~2 min)
```

`--edicao AAAA` carrega outra edição (o CKAN tem de 2009 a 2025; ver "Edições"); `--guardar-bruto` guarda o zip em `bruto/` (padrão: não guarda). Fica **fora** da atualização
agendada até o usuário decidir (regra 7 do projeto); o SFB publica uma edição por ano.

## Particularidades

- **O shapefile não tem id.** A chave (`chave_linha`) é a identidade do registro: `nome | categoria | classe | uf | geocodigo | atolegal | anocriacao | orgao`, com ordinal (`#2`) só
  nos 4 casos idênticos (ordenados por área). Mudar um desses campos na edição nova cria um registro novo (e fecha o antigo); mudar os demais (área, estágio, geometria...) cria
  uma nova **versão** do mesmo registro.
- **Edição = ano.** `edicao` é dado, não pasta. Uma edição nova substitui a vigente (o que ela não traz é fechado); o histórico das anteriores fica nas versões fechadas.
- **Polígonos com Z** na fonte (`Polygon Z`); o Z é descartado e tudo vira MultiPolygon em SIRGAS 2000 (4674).
- **1.638 polígonos são inválidos pelo PostGIS** (auto-interseções típicas de edição em ArcGIS). Entram como vêm, sem reparo; repare na análise com `ST_MakeValid` se precisar.
- **`anocriacao` tem três formatos** (`AAAA-MM-DD`, `DD-MM-AAAA`, `AAAA/MM/DD hh:mm:ss.000`) e 1.333 vazios; guardamos como vem e derivamos `ano_criacao`.
- **Dupla afetação:** `categoria` e `classe` trazem `A / B` (ex.: `PA / APA`) quando a área é, ao mesmo tempo, assentamento e UC; `sobreposic = SIM` marca sobreposição com outro registro.
  **Não some `area_ha` sem filtrar:** há sobreposições entre registros.
- `uf` é uma sigla por registro (`id_estado` derivado); `municipio` e `geocodigo` são listas separadas por `/`. `codigo` e `observacao` vêm vazios na edição 2025.
- `Shape_Leng` e `Shape_Area` (comprimento e área em graus, artefato do ArcGIS) **não são guardados**; use `area_ha` ou calcule na geometria.
- O esquema é conferido: se o SFB mudar os campos do shapefile, nada é gravado. Também aborta se o zip vier truncado (menos de 50 MB) ou com menos de 10 mil polígonos.

## Edições anteriores

O CKAN também tem os shapefiles de 2009 a 2022 e 2024 (cada um como item do portal) e CSV sem geometria. Só a mais recente é carregada; para comparar anos, rode com `--edicao`
(a edição carregada por último passa a ser a vigente).

## Licença

Dados abertos do SFB; confirmar os termos de uso e a citação exigida antes de redistribuir.
