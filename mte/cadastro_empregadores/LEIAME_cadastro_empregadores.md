# mte/cadastro_empregadores — Cadastro de Empregadores (a "lista suja" do trabalho escravo, MTE)

Espelho versionado, em `tabular.mte_cadastro_empregadores`, do **Cadastro de Empregadores que submeteram trabalhadores a condições análogas à escravidão**, do Ministério do Trabalho e Emprego
([página](https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/combate-ao-trabalho-escravo-e-analogo-ao-de-escravo), Portaria Interministerial 18/2024).
**508 empregadores** na carga de 27/10/2026 (341 pessoas físicas e 167 jurídicas). A tabela **não tem geometria** (só o endereço do estabelecimento em texto).
Mesma mecânica das outras fontes vivas (regras em `scripts_comuns/dwlib/espelho.py`, modo `com_geometria=False`).

**"Consta na lista hoje" = `vigente_ate IS NULL`.** A lista é atualizada semestralmente e o MTE **retira os nomes ao fim de 2 anos**: o que a edição nova não traz tem a versão **fechada** (nada é
apagado). Um empregador que saiu e volta idêntico tem a versão reaberta.

```
mte/cadastro_empregadores/
├── LEIAME_cadastro_empregadores.md · HISTORICO.md
├── config.yaml                          URL do CSV, cabeçalho esperado, limites de sanidade
├── sql/01_tabela.sql                    fonte em dim.fontes, tabela, índices, mapa de colunas e permissões (rodar como postgres)
└── scripts/cadastro_empregadores.py     baixa o CSV e reconcilia (usa dwlib/espelho.py e dwlib/documento.py)
```

```powershell
.\infra\scripts\dw.ps1 etl mte/cadastro_empregadores/scripts/cadastro_empregadores.py --simular   # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl mte/cadastro_empregadores/scripts/cadastro_empregadores.py             # baixa e reconcilia (~1 s)
```

100% automático: o CSV está numa URL estável do gov.br (sem login; o `HEAD` responde 403, o `GET` funciona). O pipeline confere o cabeçalho exato e aborta se o arquivo vier pequeno demais
(menos de 20 KB) ou com menos de 300 linhas.

## Dado pessoal (LGPD) — mesma decisão do IBAMA

A lista é **pública por lei** e traz nome e CPF/CNPJ do empregador. Entra como a fonte publica, **exceto o CPF de pessoa física**, que vira HMAC-SHA256 (`cpf_empregador_hash`, **mesma chave** do
IBAMA, ICMBio e SEMA-MT, via `dwlib/documento.py`). Sem a chave o pipeline para. Para buscar um CPF/CNPJ sem expor chave nem documento: `infra/scripts/consultar_documento.py` (ver `GUIA_DE_USO.md`).
Hoje 15 CPFs da lista também têm embargo no IBAMA e 2 na SEMA-MT; 3 CNPJs aparecem no IBAMA.

## O que a fonte tem de particular

- **Codificação Windows-1252**, separador `;`. O `ID` do arquivo é só a ordem da linha na edição (muda a cada edição): não é chave. `chave_linha` = `documento | ano da ação fiscal | estabelecimento`,
  com ordinal só nos idênticos (2 hoje); `id_arquivo` não entra na comparação.
- **`inclusao_cadastro` pode ser uma lista de datas e períodos** (reinclusões); guardamos o texto e derivamos `inclusao_cadastro_data` (a última data). A mesma lógica vale para a decisão administrativa.
- Os 508 documentos passam no dígito verificador (CPFs e CNPJs; `doc_valido`).
- **Fora desta tabela:** o cadastro de empregadores em ajustamento de conduta (TAC) citado na mesma página não tem link de dados que se encontre por script; fica registrado como pendência no ROADMAP.
- É a lista **da edição vigente**: não use para "já esteve na lista" (a retenção apaga as versões fechadas depois de 30 dias e o MTE retira os nomes após 2 anos).

## Licença

Dados abertos do MTE; confirmar os termos de uso e a citação exigida antes de redistribuir.
