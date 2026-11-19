# Imagem do servidor MCP de consulta (servicos/consulta_ia): Python + SDK do MCP + driver do PostgreSQL.
# Separada da imagem do ETL: o ETL escreve no banco e baixa da internet; esta só lê o banco e conversa com a IA pela entrada/saída padrão.
# O código NÃO vai na imagem: o repositório é montado em /app (somente leitura). Reconstruir só quando requirements.txt mudar.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# não roda como root: o processo só precisa ler /app e escrever o log
RUN useradd --create-home --uid 10001 consulta
USER consulta

WORKDIR /app
ENTRYPOINT ["python", "servicos/consulta_ia/scripts/servidor.py"]
