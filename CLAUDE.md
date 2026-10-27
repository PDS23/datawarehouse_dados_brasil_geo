# Data warehouse GIS — regras para quem trabalha neste repositório

Responda em português (pt-BR). O repositório é um **case de portfólio** (transição de analista GIS para data engineer geoespacial):
será lido por humanos, então títulos, nomes e documentação dizem a **fonte** e o que ela é, sem pressupor contexto.
Estado e decisões: `ROADMAP.md` (o que falta), `ARQUITETURA.md` (como é), diário compartilhado (artefato claude.ai, coleção `diario`).

## Autonomia: o que fazer direto e o que perguntar

**Faça direto, sem perguntar** (o pedido do usuário já cobre):
- criar e alterar código, SQL e documentação no repositório, seguindo a estrutura padrão abaixo;
- rodar pipelines em `--simular` e no modo normal **para o produto que o usuário pediu**;
- criar tabelas e views **novas** (build-alongside), rodar `ANALYZE`, validar contra a tabela atual;
- backup com etiqueta antes de mexer em dado existente (`infra/scripts/backup_banco.ps1`);
- sincronizar `D:` → Drive (`infra/scripts/dw.ps1 sync-drive`); registrar no diário; atualizar ROADMAP, LEIAME e memória;
- **depois de criar, alterar ou remover tabela, view ou chave estrangeira, regenerar o diagrama** (`dw.ps1 etl infra/scripts/gerar_diagrama_banco.py`; se uma tabela nova
  não aparecer, acrescente-a ao `LAYOUT` do script) **e republicar o artefato do esquema** (https://claude.ai/artifact/1EkaSLVbEXyWXg6QW9xPiW, arquivo `infra/diagrama/modelo_banco_pagina.html`). **Descreva toda coluna nova** em
  `infra/diagrama/descricoes_colunas.yaml` (o que é e de onde vem) e aplique (`dw.ps1 etl infra/scripts/aplicar_descricoes_colunas.py`, depois `dw.ps1 psql -Arquivo infra/diagrama/descricoes_colunas.sql`): é o texto do balão do esquema;
- comandos longos em segundo plano, adiantando o resto enquanto rodam.

**Pergunte (e espere o "sim") só para:**
- apagar dado, tabela, volume ou arquivo do usuário (olhar o alvo antes); trocar tabela em uso (o *swap*) e guardar a antiga;
- senhas, papéis e permissões do banco; política do Tailscale; qualquer exposição fora da tailnet;
- carga completa que o usuário não pediu (ver "Coleta só sob demanda");
- decisão de **desenho** que ainda não foi aprovada. Se o desenho já foi aprovado, execute de ponta a ponta sem voltar a perguntar.

Nunca leia nem imprima senhas, chaves ou o `.env`. **Nunca toque em `pff-postgis`** (porta 5433): é de outro projeto.
Não pergunte o que o pedido já respondeu; se houver duas opções razoáveis, escolha a conservadora, diga qual foi e siga.

## Regras travadas do projeto

1. **Estrutura padrão de uma fonte** (`ARQUITETURA.md`): `<grupo>/<fonte>/` com `LEIAME_<fonte>.md`, `HISTORICO.md`, `config.yaml`, `sql/`, `scripts/`,
   `bruto/` (e `processado/` só para raster). Idêntica em toda fonte: copie o padrão antes de criar uma nova.
2. **Nomes pela fonte, não pela ferramenta** (nada de "WFS" ou "GDAL" em nome de pasta ou arquivo; a ferramenta se explica no LEIAME).
3. **Ano, edição e versão são dados, não pastas.**
4. **Uma fonte e uma metodologia por tabela**; resultados derivados só sob demanda, guardando o `id` da versão usada.
5. **Ids em vez de texto** nas tabelas de fato (dimensões em `dim.*`).
6. **Espelho versionado (SCD2)** para fontes vivas: `vigente_desde`/`vigente_ate`; nada é apagado na coleta; retenção em `infra/retencao.yaml`.
7. **Coleta só sob demanda**: pipelines carregam só o produto pedido; nada de carga completa "para adiantar". Única exceção aprovada: a atualização agendada das fontes vivas
   (PRODES, MapBiomas Alerta, FUNAI, DETER, SICAR; domingos alternados às 00:10, com retenção de 30 dias; `infra/scripts/atualizar_fontes.ps1`). SIDRA segue só sob demanda; não agendar nada além disso sem o usuário decidir.
8. **Reprodutível por script e SEMPRE automatizado (regra de 2026-10-23)**: metodologia fica em script + LEIAME, nunca ajuste manual de linhas. Dado novo entra **só por pipeline que
   baixa direto da fonte** (WFS, API, download estável); nada de arquivo baixado à mão. Só o usuário diz quando uma carga manual é aceitável; sem esse aviso, a prioridade é
   sempre achar a automação (se a fonte não oferece, relatar e propor o que fazer, sem improvisar um upload manual). Exceção autorizada (2026-10-27): unidades de conservação do CNUC (MMA), cujo shapefile recente só existe em SharePoint; o usuário baixa o zip, o pipeline lê de `bruto/` e `--verificar` avisa quando o link direto voltar. Arquivos antigos no Drive não são fonte: o pipeline baixa de novo.
9. **Fonte da verdade é `D:\data_warehouse`**; a cópia no Drive é espelho (só código e documentação; sem `bruto/`, `processado/`, `.env`).
10. Todo pipeline usa `dwlib.catalogo.Carga` (registro em `catalogo.cargas` e `ANALYZE` ao fim).

## Ambiente

- Windows 11, Docker (`dw-postgis` 5432, `dw-geoserver` 8080, `dw-tailscale`). Pipelines rodam no contêiner `etl`: `infra/scripts/dw.ps1 etl <script> [args]`.
- SQL de administração roda como `postgres`; os pipelines usam o papel `etl` (sem DDL fora dos schemas dele).
- Chamada de ferramenta tem teto de 10 min: carga longa vai em segundo plano com log. Se um comando morrer, descubra o que ficou feito antes de repetir.
- PowerShell 5.1: `NOTICE` do psql no stderr vira erro (use `dw.ps1 psql`); evite aspas embutidas em argumentos nativos; here-string fecha na coluna 0.
- `dw.ps1 psql/consulta` mandam o SQL por arquivo (o pipe do PowerShell 5.1 troca acentos por `?`), então acento em SQL funciona; evite só digitar acento em comando nativo direto.
