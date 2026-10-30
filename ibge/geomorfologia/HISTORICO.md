# ibge/geomorfologia — histórico

- **2026-10-30** — levantamento: o IBGE publica o BDiA em `geoftp.ibge.gov.br/informacoes_ambientais/` com uma pasta `versao_AAAA` por edição (2017 a 2026); o zip da camada de polígonos tem 350 a 500 MB.
  Os arquivos locais antigos (geomorfologia e pedologia de 2021) não eram fonte: o pipeline baixa de novo.
- **2026-10-30** — pipeline criado sobre o módulo comum `scripts_comuns/dwlib/bdia.py` e primeira carga da edição 2026: 120.218 feições, 82 polígonos inválidos (gravados como vêm); segunda execução sem mudança.
  Fora da atualização agendada (edições raras).
