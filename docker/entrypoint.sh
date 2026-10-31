#!/bin/sh
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

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

python -m app.worker &
worker=$!
uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" &
api=$!
trap 'kill "$worker" "$api" 2>/dev/null || true' TERM INT
while kill -0 "$worker" 2>/dev/null && kill -0 "$api" 2>/dev/null; do
  sleep 2
done
kill "$worker" "$api" 2>/dev/null || true
wait || true
exit 1
