# mte/cadastro_empregadores — histórico

- **2026-10-27** — levantamento: CSV oficial no gov.br (76 KB, Windows-1252, 508 linhas, 10 colunas), atualizado semestralmente; o `HEAD` dá 403, o `GET` funciona.
- **2026-10-27** — pipeline criado (`scripts/cadastro_empregadores.py`) e primeira carga: 508 empregadores (341 CPFs só hash, 167 CNPJs, todos os documentos com dígito verificador correto, 2 chaves
  com ordinal); segunda execução sem mudança. Primeira tabela da família sem geometria no modo `com_geometria=False` de `dwlib/espelho.py`.
