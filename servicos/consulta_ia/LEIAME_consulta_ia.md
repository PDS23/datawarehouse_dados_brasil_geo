# Consulta por IA: servidor MCP do data warehouse

Um **servidor MCP** (Model Context Protocol) que deixa a IA que o analista já usa (Claude, ChatGPT, um modelo local) consultar o banco em
linguagem natural: a IA descobre o que existe, lê a documentação de cada fonte, escreve o SQL e devolve a resposta **com a fonte e a data da
coleta**. Somente leitura e **sem dado pessoal**.

Por que MCP e não "uma IA nossa": o MCP é um protocolo aberto. O servidor é escrito uma vez e qualquer cliente compatível o usa, então o
projeto não mantém modelo, chave de API nem interface de chat. O que é específico do projeto (as regras do banco, as proteções, o
catálogo) fica aqui, versionado, e vale para todas as IAs.

Estado: **fase 1** (2026-11-19). Roda só nesta máquina, pelo transporte stdio. A fase 2 (equipe, pela tailnet) está no fim deste documento.

## Como o MCP funciona, em uma página

- O servidor declara **ferramentas**: funções com nome, descrição e parâmetros. O cliente de IA lê essa lista ao conectar e **decide sozinho**
  quando chamar cada uma. A docstring de cada função em `scripts/servidor.py` é exatamente o texto que a IA lê: é instrução, não comentário.
- Além de ferramentas, o servidor entrega **instruções** (lidas na conexão), **prompts** (textos prontos que o usuário escolhe) e **recursos**
  (documentos legíveis). Aqui os três carregam `regras_do_banco.md`.
- **Transporte stdio:** o cliente inicia o processo (aqui, um contêiner) e troca mensagens JSON-RPC pela entrada e saída padrão. Regra de
  ouro: nada pode ir para a saída padrão além do protocolo; avisos vão para a saída de erro.
- A lógica fica em `scripts/consulta.py`, funções Python comuns testáveis sem MCP. O `servidor.py` só as expõe (SDK oficial `mcp`, versão 2.3.0:
  no 2.x a classe se chama `MCPServer`; o `FastMCP` dos tutoriais antigos é o 1.x).

## Ferramentas

| Ferramenta | O que faz |
|---|---|
| `listar_fontes` | datasets do `catalogo.datasets`: fonte oficial, tabela, última e primeira coleta, cobertura, retenção das versões antigas |
| `listar_tabelas` | tabelas e views liberadas, com descrição, tamanho estimado e se são versionadas ou espaciais |
| `descrever_tabela` | colunas com tipo e descrição (de `infra/diagrama/descricoes_colunas.yaml`), chaves, chaves estrangeiras, índices, geometria e SRID, colunas ocultas |
| `ler_documentacao` | LEIAMEs das fontes, `ARQUITETURA.md`, `GUIA_DE_USO.md`, `README.md` (nunca `projetos/`, segredos ou a infraestrutura interna) |
| `consultar` | um SELECT somente leitura; devolve colunas, linhas, **proveniência** (tabelas lidas, dataset, fonte, última coleta) e avisos |

As **regras do banco** (`regras_do_banco.md`) vão junto na conexão: versão vigente e retrato por data, área em hectares e não em graus,
território pelos códigos IBGE, **ausência de dado só vale dentro da cobertura da fonte**, sempre citar fonte e data.

## Segurança: defesa em camadas

1. **Privilégio do banco (a camada que não depende do código).** Papel próprio, `consulta_ia` (`sql/papel_consulta_ia.sql`): só `SELECT`,
   **coluna a coluna**, nos schemas `catalogo`, `dim`, `resultados`, `tabular` e `vetorial`. Nenhum `CREATE`; nada do schema `analises`.
   - As colunas de **dado pessoal** (nome, CPF/CNPJ, hash de CPF, tipo e validade do documento, texto livre) das fontes de embargo e da lista
     suja ficam de fora. Elas estão listadas em `colunas_pessoais`, no fim de `infra/diagrama/descricoes_colunas.yaml`, a mesma regra das
     views do GeoServer. Importa porque o que a IA lê vai para o provedor de IA que o analista escolheu.
   - **Falha fechada:** as permissões são geradas por `scripts/gerar_permissoes.py` para toda tabela, coluna a coluna. Tabela ou coluna nova só
     aparece para a IA depois de rodar o gerador de novo: o erro possível é a IA não ver um dado, nunca ver um dado pessoal por esquecimento.
     O gerador avisa se uma coluna listada não existe (erro de digitação) e se alguma coluna liberada tem cara de dado pessoal.
   - Lê **todas as versões** (vigentes e fechadas): o histórico é o diferencial do banco. O papel `leitura` não serve aqui: ele lê tudo.
2. **Limites do papel:** sessão somente leitura, `statement_timeout` de 120 s, `temp_file_limit` de 5 GB, no máximo 5 conexões.
3. **O servidor** (`scripts/consulta.py`):
   - uma conexão nova por chamada, em transação `READ ONLY` que termina em `ROLLBACK`: nada do que a consulta fizer sobrevive à chamada,
     nem um `set_config`;
   - o SQL vai **embrulhado como subconsulta** e com parâmetro, pelo protocolo estendido do PostgreSQL, que aceita um comando só:
     `; DROP ...` e `; SET ...` viram erro;
   - `SET LOCAL statement_timeout` de 60 s a cada chamada;
   - **`EXPLAIN` antes**, recusando custo acima de 1 bilhão com a explicação de como reescrever (ver "Calibração");
   - no máximo 500 linhas e 400 caracteres por célula;
   - **geometria resumida** (tipo, área em ha, comprimento em km, centroide) em vez do WKB, que estouraria o contexto da IA;
   - avisos quando a consulta lê tabela versionada sem filtrar a versão, ou usa `ST_Area` em graus.
4. **Contêiner:** repositório montado **somente leitura**, processo sem root; a única pasta com escrita é o registro.
5. **Registro:** cada chamada vira uma linha JSONL em `infra/logs/consulta_ia/AAAA-MM.jsonl`, fora do git: ferramenta, SQL, ok ou erro, tempo,
   linhas, tabelas lidas, origem e usuário (na fase 2).

## Instalação (uma vez, como administrador do banco)

```powershell
.\infra\scripts\dw.ps1 psql -Arquivo servicos\consulta_ia\sql\papel_consulta_ia.sql               # cria o papel (sem senha)
.\infra\scripts\senha_papel_servico.ps1 -Papel consulta_ia -Variavel CONSULTA_IA_PASSWORD         # senha gerada, vai só para o .env
.\infra\scripts\dw.ps1 etl servicos/consulta_ia/scripts/gerar_permissoes.py                       # escreve sql/permissoes_consulta_ia.sql
.\infra\scripts\dw.ps1 psql -Arquivo servicos\consulta_ia\sql\permissoes_consulta_ia.sql          # aplica (transação única)
```

- **Senha:** é de máquina, como a do `etl`: gerada, nunca impressa, só no `.env` e no banco.
- **Entrada pela rede do Docker:** no `pg_hba.conf`, a linha `host data_warehouse consulta_ia samenet scram-sha-256` antes do `reject`,
  seguida de `SELECT pg_reload_conf();`.
- **Imagem:** `docker compose -f infra/docker-compose.stack.yml -f infra/docker-compose.consulta_ia.yml --profile consulta_ia build consulta_ia`.
- **Depois de criar ou alterar tabela ou coluna:** marque em `colunas_pessoais` o que for dado pessoal e rode de novo o gerador e o SQL
  (passos 3 e 4).

## Ligar a uma IA

**Claude Desktop:** em `%APPDATA%\Claude\claude_desktop_config.json`, dentro de `"mcpServers"`, e reinicie o aplicativo:

```json
"consulta-dw": {
  "command": "docker",
  "args": ["compose", "-f", "D:\\data_warehouse\\infra\\docker-compose.stack.yml",
           "-f", "D:\\data_warehouse\\infra\\docker-compose.consulta_ia.yml", "run", "--rm", "-T", "consulta_ia"]
}
```

**Claude Code** (no terminal):

```bash
claude mcp add consulta-dw -- docker compose -f D:/data_warehouse/infra/docker-compose.stack.yml -f D:/data_warehouse/infra/docker-compose.consulta_ia.yml run --rm -T consulta_ia
```

Outros clientes MCP usam o mesmo comando. O `-T` é obrigatório: sem ele o Docker abre um terminal virtual e mistura caracteres no protocolo.

## Testes

```bash
docker compose -f infra/docker-compose.stack.yml -f infra/docker-compose.consulta_ia.yml run --rm -T --entrypoint python consulta_ia servicos/consulta_ia/scripts/testar.py
```

O `scripts/testar.py` roda 32 testes, sem IA, e sai com código 1 se algum falhar:
- **as ferramentas**;
- **os ataques que precisam ser barrados:**
  - coluna pessoal, `SELECT *` em tabela com dado pessoal, hash de CPF;
  - `DELETE` e `CREATE`;
  - dois comandos, e fechar a subconsulta para emendar um `SET`;
  - o schema `analises`;
  - `pg_read_file`;
  - cruzamento de uma UF inteira (custo);
  - `pg_sleep` (tempo);
  - `set_config` vazando para a chamada seguinte;
- **as perguntas de referência** (`perguntas_referencia.yaml`): o SQL que uma IA bem orientada deveria escrever e a faixa esperada do
  resultado. Servem também para avaliar uma IA: faça a pergunta e compare;
- **o protocolo MCP de ponta a ponta:** sobe o servidor por stdio, como o Claude Desktop, lista as ferramentas, chama uma e confere o erro
  legível.

Em 2026-11-19, os 32 passaram.

## Calibração do limite de custo (2026-11-19)

O custo do `EXPLAIN` não é tempo: o planejador superestima bastante as junções espaciais. Medido com PRODES × CAR por município (soma da área
de interseção, `ST_Intersects` + `ST_Intersection`):

| Recorte | Custo estimado | Tempo real |
|---|---|---|
| Senador Guiomard (AC) | 74 mi | 1,0 s |
| Sorriso (MT) | 74 mi | 2,3 s |
| Rio Branco (AC) | 74 mi | 3,0 s |
| Altamira (PA), o maior município | 256 mi | 5,4 s |
| Mato Grosso inteiro | 4,4 bi | recusado |

Com limite de **1 bilhão**, qualquer município passa e UF ou Brasil inteiros são recusados com a orientação de dividir. O teto de 60 s segura o
que o custo não prevê. Os dois valores estão em `config.yaml`.

## Limitações conhecidas

- Os rasters (MapBiomas uso do solo, TOPODATA) ficam fora do banco e não são consultáveis por aqui.
- Os avisos de versão e de área são heurísticas de texto: ajudam a IA, não garantem o SQL certo. A garantia é a IA mostrar o SQL e a
  proveniência, e o analista conferir.
- A IA não grava nada (nem no schema `analises`). Gravar resultado com a versão das fontes usada é a próxima etapa.
- O schema temporário (`CREATE TEMP TABLE`) continua possível, porque o PostgreSQL o concede a todos (`PUBLIC`). Não toca em dado nenhum; o
  `statement_timeout` limita o tamanho.

## Fase 2: equipe pela tailnet (a fazer, depende de aprovação)

- Transporte HTTP (Streamable HTTP do MCP) atrás do Tailscale Serve que já existe no `dw-tailscale`.
- O Tailscale repassa quem está acessando (`Tailscale-User-Login`); isso vai para o registro e dá identidade sem senha na aplicação.
- Exige uma regra nova na política do Tailscale. Fica para depois da fase 1 validada no uso.
