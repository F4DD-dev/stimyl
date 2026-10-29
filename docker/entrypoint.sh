#!/bin/sh
set -u

listen() {
  echo "listen $1"
  uvicorn main:app --host 0.0.0.0 --port "$1" &
}

listen 80
listen 8000
listen 8080
if [ -n "${PORT:-}" ]; then
  case "$PORT" in
    80|8000|8080) ;;
    *) listen "$PORT" ;;
  esac
fi

if [ -n "${DATABASE_URL:-}" ]; then
  i=0
  until alembic upgrade head; do
    i=$((i + 1))
    if [ "$i" -ge 15 ]; then
      echo "alembic upgrade failed" >&2
      break
    fi
    sleep 2
  done
  python -m app.db.seed || echo "seed failed" >&2
  if [ -n "${MAX_TOKEN:-}" ]; then
    python -m app.max_client.publish || echo "command publish failed" >&2
  fi
  if [ -n "${MAX_WEBHOOK_URL:-}" ]; then
    python -m app.max_client.subscribe || echo "webhook subscribe failed" >&2
  fi
fi

wait
