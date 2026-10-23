"""dwlib: peças comuns da coleta automatizada do data warehouse.

- db        conexão (papel de serviço "etl") e upsert em lote idempotente
- sidra     cliente da API de valores do SIDRA/IBGE (só apisidra.ibge.gov.br)
- bruto     guarda o dado bruto coletado (jsonl.gz + manifesto com data e hash)
- catalogo  registro de cada execução (catalogo.cargas) e do dataset (catalogo.datasets)

Cada pipeline fica na pasta da sua fonte (ex.: ibge/PAM/scripts/pam.py) e usa esta biblioteca.
Rodam dentro do contêiner "etl" (infra/docker-compose.etl.yml).
"""
