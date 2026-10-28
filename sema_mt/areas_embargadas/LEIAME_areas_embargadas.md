# sema_mt/areas_embargadas — Áreas embargadas e desembargadas da SEMA-MT

Espelhos versionados das duas camadas do **Geoportal da SEMA-MT** (Secretaria de Estado de Meio Ambiente de Mato Grosso), servidas por WFS:

| Camada da fonte | Tabela | Polígonos |
|---|---|---|
| `AREAS_EMBARGADAS_SEMA` (embargo vigente) | `vetorial.sema_mt_areas_embargadas` | 8.357 |
| `AREAS_DESEMBARGADAS_SEMA` (embargo encerrado) | `vetorial.sema_mt_areas_desembargadas` | 4.729 |

**São duas tabelas de propósito**: uma verificação de embargo vigente não pode, por engano, contar um embargo já encerrado. O esquema é o mesmo. Só vale para **Mato Grosso**.
Mesma mecânica das outras fontes vivas (regras em `scripts_comuns/dwlib/espelho.py`): polígono novo entra; alterado fecha a versão antiga e insere a nova; o que a camada deixou de publicar
tem a versão **fechada** (nada é apagado); o que sumiu e voltou **idêntico** tem a versão **reaberta**. Vigente (no sentido de versão) = `vigente_ate IS NULL`.

```
sema_mt/areas_embargadas/
├── LEIAME_areas_embargadas.md · HISTORICO.md
├── config.yaml                          catálogo, camadas, campos esperados, limites de sanidade
├── sql/01_tabela.sql                    fonte em dim.fontes, as duas tabelas, índices, mapa de colunas e permissões (rodar como postgres)
└── scripts/areas_embargadas.py          lê o link do catálogo, baixa o SHAPE-ZIP de cada camada e reconcilia (usa dwlib/espelho.py e dwlib/documento.py)
```

```powershell
.\infra\scripts\dw.ps1 etl sema_mt/areas_embargadas/scripts/areas_embargadas.py --verificar   # os links ainda estão no catálogo? quantas linhas o banco tem
.\infra\scripts\dw.ps1 etl sema_mt/areas_embargadas/scripts/areas_embargadas.py --simular     # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl sema_mt/areas_embargadas/scripts/areas_embargadas.py               # as duas camadas (~10 s); --camadas embargadas para uma só
```

## A `authkey` (chave de acesso) do WFS

O WFS exige uma `authkey`, **mas a própria SEMA a publica**: ela vem dentro dos links de download do catálogo GeoNetwork (`geonetwork.sema.mt.gov.br`), abertos a qualquer visitante, e sem ela o servidor
não lista camada nenhuma. O pipeline **lê o catálogo a cada execução** e usa o link publicado (a chave nunca é fixada no código nem no repositório). Se a SEMA tirar o link ou a chave do catálogo,
o pipeline para com mensagem clara (nada é gravado).

## Dado pessoal (LGPD) — mesma decisão do IBAMA

Nome e CPF/CNPJ do embargado. Entra tudo como a fonte publica, **exceto o CPF de pessoa física**, que vira HMAC-SHA256 (`cpf_embargado_hash`, **mesma chave** do IBAMA/ICMBio/MTE, via
`dwlib/documento.py`). Sem a chave o pipeline para. **Não publique estas tabelas no GeoServer sem tirar `nome`.** Para buscar um CPF/CNPJ: `infra/scripts/consultar_documento.py` (ver `GUIA_DE_USO.md`).
Hoje: embargadas 7.636 CPFs (só hash), 555 CNPJs; desembargadas 4.037 CPFs, 676 CNPJs. 770 CPFs aparecem também no IBAMA.

## O que a fonte tem de particular

- **Não há id único** (um termo de embargo tem vários polígonos): `chave_linha` = `t_embargo | n_processo | a_infrac | documento | propriedad | dat_lavrat | ano_desmat`, com ordinal só nos polígonos
  idênticos (561 e 463). `objectid` não entra na comparação.
- A fonte grava `'None'` e espaços no lugar de vazio: viram `NULL`. `dat_lavrat` é `DD/MM/AAAA` e às vezes incompleta (`00/07/2017`): `data_lavratura` fica `NULL` nesses casos (176 nas embargadas).
- **Documentos:** 87 (embargadas) e 50 (desembargadas) não passam no dígito verificador (`doc_valido = false`, provável erro de digitação); são tratados como CPF se têm até 11 dígitos e
  nunca guardados em claro.
- `coord_x` e `coord_y` são texto em graus, minutos e segundos; a geometria é a do polígono (SIRGAS 2000). 0 polígonos inválidos; 1 polígono das desembargadas cai fora de Mato Grosso
  (`geom` NULL, `geom_anomala`, texto original em `geom_origem_texto`).
- Um polígono que passa de embargado a desembargado aparece como fechado em uma tabela e novo na outra.

## Licença

Dados do Geoportal da SEMA-MT; confirmar os termos de uso e a citação exigida antes de redistribuir.

## Atualização agendada
Entra na atualização agendada (domingos alternados, 00:10) desde 2026-10-28; a retenção de 30 dias já cobre as duas tabelas.
