#!/bin/sh
set -eu

i=0
until alembic upgrade head; do
  i=$((i + 1))
  if [ "$i" -ge 15 ]; then
    echo "alembic upgrade failed" >&2
    exit 1
  fi
  sleep 2
done

python -m app.db.seed

if [ -n "${MAX_TOKEN:-}" ]; then
  python -m app.max_client.publish || echo "command publish failed" >&2
fi

if [ -n "${MAX_WEBHOOK_URL:-}" ]; then
  python -m app.max_client.subscribe || echo "webhook subscribe failed" >&2
fi

port="${PORT:-8000}"
exec uvicorn main:app --host 0.0.0.0 --port "$port"
