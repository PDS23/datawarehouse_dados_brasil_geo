# Imagem da coleta automatizada (ETL): Python + bibliotecas de banco, HTTP e leitura de shapefile.
# O codigo NAO vai na imagem: o repositorio e montado em /app (infra/docker-compose.etl.yml),
# entao editar um pipeline nao exige reconstruir nada. Reconstruir so quando requirements.txt mudar.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/scripts_comuns \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

WORKDIR /app
ENTRYPOINT ["python"]
