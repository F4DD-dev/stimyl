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

# Один сертификат для httpx. Бандл Минцифры в каталог rehash не кладём:
# openssl пропускает файл, в котором больше одного сертификата.
ENV MAX_ROOT_CA_PATH=/app/certs/russian_trusted_root_ca.pem
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
