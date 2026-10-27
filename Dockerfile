FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY pyproject.toml README.md alembic.ini main.py ./
COPY app ./app
COPY alembic ./alembic
COPY certs ./certs
COPY docker/entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir . \
    && chmod +x /entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

ENV MAX_ROOT_CA_PATH=/app/certs/russian_trusted_root_ca.pem

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
