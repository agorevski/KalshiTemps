#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${KALSHI_TEMPS_DB:-data/kalshi_temps.sqlite3}"
BACKUP_PATH=""
FORCE=0

usage() {
  cat >&2 <<USAGE
Usage: $0 --backup PATH [--db PATH] [--force]

Restores a SQLite backup. Existing target databases are never overwritten
unless --force is supplied.
USAGE
}

while (($#)); do
  case "$1" in
    --backup)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      BACKUP_PATH="$2"
      shift 2
      ;;
    --db)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      DB_PATH="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$BACKUP_PATH" || -z "$DB_PATH" ]]; then
  usage
  echo "Backup and database paths must be provided." >&2
  exit 2
fi
if [[ ! -f "$BACKUP_PATH" ]]; then
  echo "Backup file not found: $BACKUP_PATH" >&2
  exit 1
fi
if [[ -e "$DB_PATH" && "$FORCE" -ne 1 ]]; then
  echo "Refusing to overwrite existing database without --force: $DB_PATH" >&2
  exit 1
fi

TARGET_DIR="$(dirname -- "$DB_PATH")"
mkdir -p -- "$TARGET_DIR"

export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
python - "$BACKUP_PATH" "$DB_PATH" "$FORCE" <<'PY'
from __future__ import annotations

import sys
from kalshi_temps.ops import OpsError, safe_restore_preflight

try:
    safe_restore_preflight(sys.argv[1], sys.argv[2], force=sys.argv[3] == "1")
except OpsError as exc:
    print(f"Restore preflight failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY

RESTORE_TMP="${DB_PATH}.restore.$$"
rm -f -- "$RESTORE_TMP"
cp -p -- "$BACKUP_PATH" "$RESTORE_TMP"
if [[ -e "$DB_PATH" ]]; then
  chmod --reference="$DB_PATH" -- "$RESTORE_TMP" 2>/dev/null || true
fi
mv -f -- "$RESTORE_TMP" "$DB_PATH"
echo "Restored $BACKUP_PATH to $DB_PATH"
