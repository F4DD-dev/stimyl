#!/bin/sh
# Порт открывается сразу. Миграции и воркер идут рядом и не держат сокет.
set -eu

python -m app.boot

host="${HOST:-0.0.0.0}"
port="${PORT:-8000}"

(
  python -m app.db.migrate || echo "migrate failed" >&2
  python -m app.db.seed || echo "seed failed" >&2
  if [ -n "${MAX_TOKEN:-}" ]; then
    python -m app.max_client.publish || echo "command publish failed" >&2
  fi
  if [ -n "${MAX_WEBHOOK_URL:-}" ]; then
    python -m app.max_client.subscribe || echo "webhook subscribe failed" >&2
  fi
) &
side=$!

python -m app.worker &
worker=$!

uvicorn main:app --host "$host" --port "$port" &
api=$!

stop=0
trap 'stop=1; kill "$api" "$worker" "$side" 2>/dev/null || true' TERM INT

while kill -0 "$api" 2>/dev/null; do
  if ! kill -0 "$worker" 2>/dev/null; then
    echo "worker stopped; web keeps the port, /ready stays 503 until the worker returns" >&2
    python -m app.worker &
    worker=$!
  fi
  sleep 2
done

kill "$worker" "$side" 2>/dev/null || true
wait "$api" 2>/dev/null || true
if [ "$stop" -eq 1 ]; then
  exit 0
fi
exit 1
