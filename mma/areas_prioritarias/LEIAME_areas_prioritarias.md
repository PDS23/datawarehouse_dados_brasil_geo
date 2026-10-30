# mma/areas_prioritarias — Áreas Prioritárias para a Conservação da Biodiversidade (MMA)

Espelho versionado, em `vetorial.mma_areas_prioritarias`, das **Áreas Prioritárias para a Conservação, Utilização Sustentável e Repartição dos Benefícios da Biodiversidade**, instrumento de política
pública do Ministério do Meio Ambiente (Decreto 5.092/2004), no [portal de dados abertos do MMA](https://dados.mma.gov.br/dataset/f0dde837-8db0-4221-989f-45944c1f09ee).
Edição carregada: a **2ª atualização (2022)**, **2.081 áreas** em 7 arquivos. É uma edição estática: rodar de novo não muda nada, mas uma edição nova do MMA seria detectada (espelho versionado:
`vigente_ate IS NULL` = versão vigente; nada é apagado na coleta).

```
mma/areas_prioritarias/
├── LEIAME_areas_prioritarias.md · HISTORICO.md
├── config.yaml                          CKAN, mapa de campos de cada shapefile, limites de sanidade
├── sql/01_tabela.sql                    tabela, índices, mapa de colunas e permissões (rodar como postgres)
└── scripts/areas_prioritarias.py        lê o CKAN, baixa os 7 zips e reconcilia (usa dwlib/espelho.py)
```

```powershell
.\infra\scripts\dw.ps1 etl mma/areas_prioritarias/scripts/areas_prioritarias.py --simular   # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl mma/areas_prioritarias/scripts/areas_prioritarias.py             # baixa (~40 MB) e reconcilia (~20 s)
```

100% automático: links diretos do CKAN, sem login. O pipeline confere que os 7 arquivos continuam no pacote e que cada shapefile tem os campos esperados (senão, nada é gravado).

## O que a fonte tem de particular

- **Sete shapefiles com esquemas diferentes**, um por região: Amazônia (860), Cerrado e Pantanal (294), Caatinga (275), Mata Atlântica (265), Zona Costeira e Marinha (114), Pampa (110) e Áreas
  Híbridas (163). Uma tabela só: `camada_origem` diz o arquivo; a chave é `(camada_origem, cod_area)`.
- **Colunas comuns harmonizadas** (de qual campo vem cada uma está em `config.yaml`): `cod_area`, `nome_area` (só algumas camadas), `importancia_biologica`, `prioridade_acao`, `acao_principal`,
  `acao_principal_codigo`, `acoes_complementares`, `estados` (só Cerrado e Pantanal) e `area_ha`. **Tudo o que a fonte publica** fica em `atributos_originais` (jsonb), menos `OBJECTID` e `Shape_*`.
- **Ação principal:** algumas camadas trazem o texto (`acao_principal`), outras só o código (`acao_principal_codigo`, na Mata Atlântica e no Pampa) e a Amazônia traz os dois. O texto de cada código
  está nas **listas de ações** em CSV do MMA (4 arquivos, 4 formatos diferentes), que **não são espaciais e não foram carregadas**.
- **A capitalização varia** (`Extremamente alta` e `Extremamente Alta`; há 1 `Muita Alta`, provável erro de digitação, e 1 área sem prioridade): compare com `lower()`.
- **Polígonos com Z** na fonte; o Z é descartado e tudo vira MultiPolygon em SIRGAS 2000 (4674). **42 polígonos são inválidos pelo PostGIS** e entram como vêm (use `ST_MakeValid` na análise).
- A zona costeira e marinha inclui áreas oceânicas enormes (a "Área Insuficientemente Conhecida" tem 198 milhões de ha e vai de 37°S a 8°N), por isso a caixa de conferência vai até a ZEE.
- **Sobreposição:** as áreas de camadas diferentes (e as marinhas com as terrestres) podem se sobrepor; não some `area_ha` entre camadas sem conferir.

## Licença

Creative Commons Atribuição (portal do MMA); citar o MMA como fonte.
