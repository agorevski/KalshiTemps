#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${KALSHI_TEMPS_DB:-data/kalshi_temps.sqlite3}"
BACKUP_DIR="data/backups"

usage() {
  cat >&2 <<USAGE
Usage: $0 [--db PATH] [--backup-dir DIR]

Creates a timestamped SQLite backup without overwriting an existing file.
USAGE
}

while (($#)); do
  case "$1" in
    --db)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      DB_PATH="$2"
      shift 2
      ;;
    --backup-dir)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      BACKUP_DIR="$2"
      shift 2
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

if [[ "$DB_PATH" = "" || "$BACKUP_DIR" = "" ]]; then
  echo "Database path and backup directory must be non-empty." >&2
  exit 2
fi
if [[ ! -f "$DB_PATH" ]]; then
  echo "Database file not found: $DB_PATH" >&2
  exit 1
fi
if [[ ! -r "$DB_PATH" ]]; then
  echo "Database file is not readable: $DB_PATH" >&2
  exit 1
fi
if [[ -d "$BACKUP_DIR" && ! -w "$BACKUP_DIR" ]]; then
  echo "Backup directory is not writable: $BACKUP_DIR" >&2
  exit 1
fi

mkdir -p -- "$BACKUP_DIR"
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
BACKUP_PATH="$(python -m kalshi_temps --db "$DB_PATH" backup-path --backup-dir "$BACKUP_DIR")"

if [[ -e "$BACKUP_PATH" ]]; then
  echo "Refusing to overwrite existing backup: $BACKUP_PATH" >&2
  exit 1
fi

umask 077
cp -p -- "$DB_PATH" "$BACKUP_PATH"
if ! python -m kalshi_temps verify-backup "$BACKUP_PATH" >/dev/null; then
  rm -f -- "$BACKUP_PATH"
  echo "Backup verification failed; removed invalid backup: $BACKUP_PATH" >&2
  exit 1
fi
echo "$BACKUP_PATH"
