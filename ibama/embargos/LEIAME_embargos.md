# ibama/embargos — Termos de embargo (IBAMA)

Espelho versionado, em `vetorial.ibama_embargos`, do CSV `termo_de_embargo.csv` dos dados abertos do IBAMA (pacote "Fiscalização - termo de embargo" no portal
`dadosabertos.ibama.gov.br`): 116.944 termos, de 1997 a 2026, em todas as UFs. O arquivo (~210 MB) fica no armazenamento público do IBAMA, sem login, e é **regerado
todo dia**. Mesma mecânica do SICAR, do PRODES, do MapBiomas Alerta, da FUNAI e do DETER (regras em `scripts_comuns/dwlib/espelho.py`): termo novo entra; alterado fecha a
versão antiga e insere a nova; termo que o IBAMA deixou de publicar tem a versão **fechada** (nada é apagado na coleta); termo que sumiu e voltou **idêntico** tem a
versão **reaberta**. Vigente = `vigente_ate IS NULL`.

```
ibama/embargos/
├── LEIAME_embargos.md · HISTORICO.md
├── config.yaml                  URL do CSV, limites de sanidade, caixa do Brasil, caminho da chave do hash
├── sql/01_tabela.sql            fonte em dim.fontes, tabela, índices, mapa de colunas e permissões (rodar como postgres)
├── scripts/embargos.py          baixa o CSV e reconcilia (usa dwlib/espelho.py)
└── segredo/chave_hash_cpf.key   chave do hash do CPF (criada na 1ª carga; fora do git e do Drive)
```

```powershell
.\infra\scripts\dw.ps1 etl ibama/embargos/scripts/embargos.py --simular     # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl ibama/embargos/scripts/embargos.py               # baixa e reconcilia (~35 s)
```

## Dado pessoal (decisão de 2026-10-26)

O IBAMA publica o **nome** e o **CPF/CNPJ completos** dos embargados (88.791 CPFs de 11 dígitos, 17.784 CNPJs; não vem mascarado). A decisão do projeto: **entra tudo
como a fonte publica, exceto o CPF de pessoa física**, que é guardado só como **hash**.

- `nome_embargado`, `num_pessoa_embargo` e o CNPJ (`cpf_cnpj_embargado`) entram como vêm.
- O CPF de 11 dígitos **não é guardado**: `cpf_embargado_hash` = HMAC-SHA256 do CPF com uma chave secreta (`segredo/chave_hash_cpf.key`, ou a variável `DW_CHAVE_HASH_CPF`). Serve para
  contar embargos por pessoa sem expor o número. (Um hash simples seria reversível por força bruta, pois há só ~10⁹ CPFs; por isso a chave.)
- **Guarde uma cópia da chave** fora do repositório. Se ela se perder, o pipeline se recusa a criar outra enquanto houver hashes no banco (criar outra mudaria o hash de todo mundo).
- `bruto/` não guarda o CSV por padrão (ele traz o CPF completo); `--guardar-bruto` guarda em `bruto/`, fora do git e do Drive.
- O papel `analistas` e o `geoserver` têm `SELECT` na tabela como nas demais; **não publique `vetorial.ibama_embargos` no GeoServer sem tirar `nome_embargado`**.

## Como baixamos (e o que o arquivo tem de particular)

- **Cabeçalho conferido:** são exatamente as 51 colunas esperadas; se o IBAMA mudar o esquema, nada é gravado. Também aborta se o arquivo vier truncado (menos de 100 MB ou 100 mil linhas).
- **Sem identificador único.** `NUM_TAD`+`SER_TAD` repete 325 vezes e `SEQ_TAD` vem vazio em ~3 mil termos; os **três juntos** são únicos nas 116.944 linhas.
  Por isso a chave é `chave_tad` = `NUM_TAD|SER_TAD|SEQ_TAD`.
- **`ULTIMA_ATUALIZACAO_RELATORIO` muda em todas as linhas todo dia** (é a hora em que o IBAMA gerou o CSV). É guardada, mas **não entra na comparação**; senão toda carga
  marcaria os 117 mil termos como alterados.
- **Datas de embargo absurdas:** 8 termos têm `DAT_EMBARGO` no futuro (2063, 2080, 2090, 2925) ou antes de 1989 (uma em 166x e três em 198x). Um embargo não tem prazo de pena, então são
  erros de digitação (3 dos 4 futuros estão cancelados). Entram como vêm e ficam com `data_embargo_suspeita = true`.
- **Geometria:** o WKT (`GEOM_AREA_EMBARGADA`) existe em ~51% dos termos (59.770); os demais têm só o ponto latitude/longitude (`geom_ponto`, derivado; ~15% não têm nem isso).
  O IBAMA não declara o CRS: tratamos como SIRGAS 2000 (as coordenadas caem todas no Brasil). 130 polígonos são inválidos pelo PostGIS e entram como vêm; **1** tem um anel não
  fechado, que o PostGIS recusa: entra com `geom` NULL, `geom_anomala` e o texto original em `geom_origem_texto`.
- **Formatos:** datas `AAAA-MM-DD HH:MM:SS` (`timestamp`, sem fuso), área com vírgula decimal, ids com `.0000000000` (viram `bigint`).
- `id_municipio` vem de `COD_MUNICIPIO` (2 linhas trazem só 6 dígitos; casam pelo código IBGE sem o dígito verificador); 38 termos ficam sem `id_municipio`.

## Colunas

As 51 colunas da fonte, em minúsculas (mapa em `catalogo.mapa_colunas`; descrições nos balões do esquema), mais as derivadas: `chave_tad`, `tipo_doc_embargado`, `cpf_embargado_hash`, `id_estado`,
`id_municipio`, `data_embargo_suspeita` e `geom_ponto`. `deter_prodes`/`id_poligono` ligam ~1% dos termos ao polígono de desmatamento do DETER ou do PRODES que originou o embargo.
Cancelados e excluídos vêm misturados com os ativos (`des_status_formulario`, `sit_cancelado`) e o desembargo vem em colunas próprias (`sit_desembargo`, `dat_desembargo`): filtre na análise.

## Outras tabelas do mesmo pacote (não carregadas)

`termo_embargo_itens`, `..._coordenadas` (vértices), `..._anexos`, `..._decisao` (decisões judiciais), `..._enquadramento`, `..._historico`. O histórico e os enquadramentos
legais são candidatos a tabelas próprias se a análise pedir.

## Licença

Dados abertos do IBAMA; confirmar os termos de uso e a citação exigida antes de redistribuir.

## Atualização agendada
Entra na atualização agendada (domingos alternados, 00:10) desde 2026-10-27; a retenção de 30 dias já cobre a tabela.
