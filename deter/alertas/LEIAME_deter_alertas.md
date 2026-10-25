# deter/alertas — DETER (INPE/TerraBrasilis): alertas de desmatamento da Amazônia e do Cerrado

Espelho versionado, em `vetorial.deter_alertas`, das camadas DETER do servidor de mapas do TerraBrasilis (WFS aberto, sem login), o mesmo servidor do PRODES:
`deter-amz:deter_amz` (Amazônia, ~464 mil linhas) e `deter-cerrado-nb:deter_cerrado` (Cerrado, ~135 mil). O INPE atualiza diariamente. Só estes dois biomas têm DETER
publicado ali.

**DETER é um sistema de alerta, não o dado oficial de desmatamento.** Serve para acompanhar o que está acontecendo agora (e priorizar fiscalização); a taxa
oficial anual é o PRODES (`prodes/desmatamento`). Os dois não se somam nem se substituem.

Mesma mecânica do SICAR, do PRODES, do MapBiomas Alerta e da FUNAI (regras em `scripts_comuns/dwlib/espelho.py`): alerta novo entra; alterado fecha a versão antiga e
insere a nova; alerta que o servidor deixou de publicar tem a versão **fechada** (nada é apagado na coleta); alerta que sumiu e voltou **idêntico** tem a versão
**reaberta**. Vigente = `vigente_ate IS NULL`.

```
deter/alertas/
├── LEIAME_deter_alertas.md · HISTORICO.md
├── config.yaml                       servidor, camada de cada bioma, paralelismo, tolerâncias
├── sql/01_tabela.sql                 tabela, índices, mapa de colunas e permissões (rodar como postgres)
├── scripts/deter_alertas.py          baixa as duas camadas e reconcilia (usa dwlib/espelho.py)
└── bruto/<bioma>/deter_AAAA-MM.zip   SHAPE-ZIP de cada mês de publicação, como veio (fora do git e do Drive)
```

```powershell
.\infra\scripts\dw.ps1 etl deter/alertas/scripts/deter_alertas.py --simular                       # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl deter/alertas/scripts/deter_alertas.py                                 # baixa e reconcilia os dois biomas
.\infra\scripts\dw.ps1 etl deter/alertas/scripts/deter_alertas.py --biomas cerrado --a-partir 2026-09 --simular   # recorte de teste
```

## Como baixamos

- **SHAPE-ZIP, não GeoJSON.** O GeoJSON (e o GML) do servidor corta as coordenadas em 4 casas decimais (~10 m); o SHAPE-ZIP traz a precisão completa.
  O preço é o nome dos campos truncado em 10 letras (`municipali`, `publish_mo`, `created_da`, `areatotalk`), que o script devolve aos nomes da fonte.
- **Fatiado por mês de publicação** (`publish_month`), uns 110 meses por bioma, 4 ao mesmo tempo. A primeira fatia fica sem piso e a última sem teto, para um alerta
  publicado durante a coleta não se perder. Os poucos alertas sem `publish_month` (2 no Cerrado) entram numa fatia própria.
- **Conferência:** cada fatia tem de trazer exatamente o que o servidor anunciou (`resultType=hits`); o total baixado não pode ficar abaixo de
  `1 - tolerancia_coleta` do anunciado; e a trava `max_queda` (10%) protege contra uma coleta que perdeu alertas.

## Chave: (`id_bioma`, `gid`, `chave_linha`)

**O `gid` não identifica o polígono, e nenhum campo isolado é único.** Descobrimos na primeira carga completa:

- o `gid` se repete **entre os biomas** (`100003_hist` existe nos dois);
- repete **uma vez por município que o polígono cruza** (cada linha com a sua `areamunkm`);
- e, na Amazônia, é **reutilizado por alertas diferentes**: `17641_hist` aparece em 2019, 2020, 2021, 2022 e 2024, em municípios e classes distintos.

Com (`gid`, município) a Amazônia perdia 10.152 de 464.353 linhas; com (`gid`, município, data da imagem, classe) ainda sobravam 3 colisões. Só somando a
`areamunkm` as 464.353 linhas (e as 135.184 do Cerrado) ficam únicas. A coluna derivada `chave_linha` = `município|view_date|classname|areamunkm` completa a chave.
Consequência: se o INPE corrigir a área de um alerta, a linha antiga é fechada e a nova entra (não conta como "alterada"); o histórico preserva as duas.
Para a área total de um polígono, some `areamunkm` das linhas do mesmo `gid` e da mesma data (ou use `areatotalkm`, só no Cerrado).

## Colunas

Nomes da fonte (mapa em `catalogo.mapa_colunas`). A Amazônia não publica `created_date` nem `areatotalkm`; o Cerrado não publica `mun_geocod`: ficam `NULL` no outro.
`id_estado` vem de `uf` (`dim.estados`); `id_municipio` vem de `mun_geocod` (`dim.municipios`) e fica `NULL` no Cerrado, onde a fonte só traz o nome.
`classname` é a classe do alerta (desmatamento por corte raso, com vegetação, mineração, cicatriz de queimada, corte seletivo desordenado...).

## Licença

Dados abertos do INPE/TerraBrasilis; confirmar os termos de uso e a citação exigida antes de redistribuir.
