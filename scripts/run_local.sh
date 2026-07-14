#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
DB_PATH="${KALSHI_TEMPS_DB:-data/kalshi_temps.sqlite3}"

mkdir -p "$(dirname "$DB_PATH")"
export KALSHI_TEMPS_DB="$DB_PATH"
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

python -m kalshi_temps init-db >/dev/null
exec python -m uvicorn kalshi_temps.app:app --host "$HOST" --port "$PORT"
