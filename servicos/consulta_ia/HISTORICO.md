# Histórico: consulta por IA (servidor MCP)

## 2026-11-19: fase 1 (stdio, só nesta máquina)

- Desenho aprovado pelo usuário no mesmo dia:
  - MCP em vez de uma IA própria (o analista pluga a IA que preferir);
  - papel próprio só de leitura, com permissão por coluna em vez de views novas;
  - pasta `servicos/consulta_ia/`.
- Papel `consulta_ia` criado (`sql/papel_consulta_ia.sql`), senha gerada por `infra/scripts/senha_papel_servico.ps1` (vai só para o
  `.env`), linha no `pg_hba.conf` (rede do Docker, `scram-sha-256`).
- Colunas de dado pessoal marcadas em `infra/diagrama/descricoes_colunas.yaml` (`colunas_pessoais`): 33 colunas em 5 tabelas (IBAMA,
  ICMBio, SEMA-MT embargadas e desembargadas, MTE).
- Permissões geradas e aplicadas: 71 tabelas e views, 1.303 colunas liberadas, 33 ocultas, nenhum aviso da rede de segurança.
- Servidor (`scripts/servidor.py`, SDK `mcp` 2.3.0) com 5 ferramentas, as regras do banco como instruções, prompt e recurso.
  Imagem `dw-consulta-ia:local` (`infra/consulta_ia/`), serviço em `infra/docker-compose.consulta_ia.yml`.
- Achado na implementação: `public.geometry_columns` esconde tabelas de quem só tem permissão por coluna. O `descrever_tabela` lê tipo e SRID
  do modificador da coluna (`postgis_typmod_type` e `postgis_typmod_srid`).
- Achado na calibração: o custo do `EXPLAIN` superestima as junções espaciais (Altamira: 256 mi de custo, 5,4 s). Limite fixado em 1 bilhão.
  Tabela no LEIAME.
- Testes (`scripts/testar.py`): 32 de 32, incluindo o protocolo MCP de ponta a ponta. O comando exato do cliente (`docker compose ... run
  --rm -T consulta_ia`) responde ao aperto de mão do protocolo com saída padrão limpa.
