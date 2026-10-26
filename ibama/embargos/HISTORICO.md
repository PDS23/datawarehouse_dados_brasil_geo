# ibama/embargos — histórico

- **2026-10-23** — levantamento de fontes: o CSV dos dados abertos do IBAMA serve (o shapefile anunciado no portal, `adm_embargo_ibama_a.shp.zip`, dá 404); traz nome e CPF/CNPJ.
- **2026-10-26** — amostra mostrada ao usuário; decisão (opção 1): tudo como a fonte publica, exceto o CPF de pessoa física, só como hash. Descobertas: o dado pessoal **não** vem mascarado;
  `NUM_TAD`+`SER_TAD` não é único (chave = `NUM_TAD|SER_TAD|SEQ_TAD`); `ULTIMA_ATUALIZACAO_RELATORIO` muda todo dia (fora da comparação); 8 datas de embargo absurdas (erros de digitação,
  marcadas); 1 polígono com anel aberto (geom NULL + texto original). Pipeline criado (`scripts/embargos.py`) e primeira carga: 116.944 termos (88.791 CPFs só como hash, 17.784 CNPJs,
  59.769 polígonos); segunda execução sem nenhuma mudança (hash estável). Ficou fora da atualização agendada até o usuário decidir (regra 7).
