# icmbio/areas_embargadas — Áreas embargadas do ICMBio

Espelho versionado, em `vetorial.icmbio_areas_embargadas`, da camada pública **"Embargos ICMBio"** do ArcGIS Online do Instituto Chico Mendes de Conservação da Biodiversidade
(a mesma do painel linkado na [página de áreas embargadas](https://www.gov.br/icmbio/pt-br/assuntos/fiscalizacao-1/areas-embargadas) do gov.br). **14.779 polígonos** (camada editada em 06/10/2026).
Mesma mecânica das outras fontes vivas (regras em `scripts_comuns/dwlib/espelho.py`): polígono novo entra; alterado fecha a versão antiga e insere a nova; o que a camada deixou de
publicar tem a versão **fechada** (nada é apagado); o que sumiu e voltou **idêntico** tem a versão **reaberta**. Vigente = `vigente_ate IS NULL`.

```
icmbio/areas_embargadas/
├── LEIAME_areas_embargadas.md · HISTORICO.md
├── config.yaml                          URL da camada, campos esperados, limites de sanidade
├── sql/01_tabela.sql                    fonte em dim.fontes, tabela, índices, mapa de colunas e permissões (rodar como postgres)
└── scripts/areas_embargadas.py          baixa a camada (paginada) e reconcilia (usa dwlib/espelho.py e dwlib/documento.py)
```

```powershell
.\infra\scripts\dw.ps1 etl icmbio/areas_embargadas/scripts/areas_embargadas.py --verificar   # total e data da última edição na origem x banco
.\infra\scripts\dw.ps1 etl icmbio/areas_embargadas/scripts/areas_embargadas.py --simular     # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl icmbio/areas_embargadas/scripts/areas_embargadas.py               # baixa e reconcilia (~20 s)
```

100% automático: o servidor entrega no máximo 2.000 feições por pedido; o pipeline pagina por `OBJECTID`, confere que baixou o total anunciado e confere o esquema (se o ICMBio mudar os
campos, nada é gravado).

## Dado pessoal (LGPD) — mesma decisão do IBAMA

A camada traz **nome do autuado e CPF/CNPJ**. Regra do projeto: entra tudo como a fonte publica, **exceto o CPF de pessoa física**, que nunca é guardado em claro: vira HMAC-SHA256 dos 11 dígitos
(`cpf_autuado_hash`), com **a mesma chave do IBAMA** (fora do banco e do git). Um CPF consultado casa com o mesmo hash nas duas fontes (586 CPFs aparecem em ambas). A limpeza e o hash são do
módulo comum `dwlib/documento.py`. Sem a chave o pipeline **para** (não cria chave nova: hashes de chaves diferentes não casariam). **Não publique esta tabela no GeoServer sem tirar `autuado`.**

Para buscar um CPF ou CNPJ sem expor chave nem documento: `infra/scripts/consultar_documento.py` (ver [GUIA_DE_USO.md](../../GUIA_DE_USO.md)).

## O que a fonte tem de particular

- **Não há id único.** Um embargo (`numero_emb`) tem vários polígonos (até 68, iguais nos demais campos), e `numero_emb` repete entre séries. A chave (`chave_linha`) é a identidade do polígono:
  `numero_emb | serie | numero_ai | documento (hash ou CNPJ) | nome_uc | município | UF | data | processo`, com ordinal (`#2`...) só nos polígonos idênticos (1.218 hoje), ordenados por área.
  Mudar um desses campos cria um registro novo (e fecha o antigo); mudar os demais cria nova **versão**. `objectid` e `vw_num_emb` não entram na comparação (mudam entre republicações).
- **A fonte usa um espaço (`' '`) no lugar de vazio e `'None'` como texto**: viram `NULL`.
- **`cpf_cnpj` vem sujo.** 11.022 CPFs (só hash), 1.081 CNPJs, 2 textos livres (`DESCONHECIDO`...), 8 placeholders (`0`, `.`, `00000000000`) e 2.666 vazios. Zeros à esquerda perdidos são repostos
  (CPF até 11 dígitos, CNPJ até 14); formato com pontuação é aceito. `doc_valido` diz se os dígitos verificadores conferem: **442 documentos não conferem** (provável erro de digitação na fonte); mesmo assim
  um número de até 11 dígitos é tratado como CPF (e não guardado), na dúvida.
- **`area` é texto livre** (`2,55ha`, `300 m²`, `Não informada`, `Tamanho total das áreas embargadas: 1,33ha`). `area_informada_ha` só é preenchida quando o texto é um número com ha/hectare(s)/m²
  (9.906 linhas); **não é a área do polígono** (use a geometria) e o "total" do embargo se repete em todos os seus polígonos.
- **278 polígonos não têm geometria** na fonte (`geom` NULL) e **444 são inválidos pelo PostGIS** (gravados como vêm; repare com `ST_MakeValid` na análise). 18 linhas sem UF (`id_estado` NULL).
- `Shape__Area` e `Shape__Length` (artefatos do ArcGIS) não são guardados.
- Se o IBAMA e o ICMBio embargarem a mesma área, as duas camadas **se sobrepõem**: são fontes distintas, não some áreas entre elas.

## Licença

Dados abertos do ICMBio; confirmar os termos de uso e a citação exigida antes de redistribuir.

## Atualização agendada
Entra na atualização agendada (domingos alternados, 00:10) desde 2026-10-27; a retenção de 30 dias já cobre a tabela.
