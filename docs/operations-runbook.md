# Operations runbook

Practical operating notes for the local Kalshi Temps FastAPI + SQLite dashboard.

## Local app

- Install with `python -m pip install -e .` or run commands with `PYTHONPATH=src`.
- Initialize the database: `PYTHONPATH=src python -m kalshi_temps init-db`.
- Start locally: `PYTHONPATH=src uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000`.
- Check local health: `curl http://127.0.0.1:8000/health/json`.
- Check non-sensitive ops status: `curl http://127.0.0.1:8000/api/ops/status`.

The app has no real authentication. Keep it on localhost or trusted tailnet-only access unless proper auth is implemented.

## Collectors

Run collectors manually and keep provenance labels clear:

```bash
PYTHONPATH=src python -m kalshi_temps collect-nws-discussion
PYTHONPATH=src python -m kalshi_temps collect-metar --station KSEA
```

Treat failed, stale, demo, proxy, or manually edited records as research-only until source and settlement rules are verified.

## Backups

Create a timestamped backup before schema changes, imports, or manual edits:

```bash
scripts/backup_sqlite.sh
scripts/backup_sqlite.sh --db data/research.sqlite3 --backup-dir data/backups
```

Backups are written under `data/backups` by default, do not overwrite existing files, and use `cp -p` to preserve permissions where practical.

## Restore

Restores refuse to overwrite an existing database unless `--force` is supplied:

```bash
scripts/restore_sqlite.sh --backup data/backups/<backup>.sqlite3 --db data/restore-test.sqlite3
scripts/restore_sqlite.sh --backup data/backups/<backup>.sqlite3 --force
PYTHONPATH=src python -m kalshi_temps init-db
```

After restore, run `/health/json`, `/api/ops/status`, and load `/dashboard`.

## Tailscale and binding

Prefer `127.0.0.1`. For phone access, use Tailscale Serve, SSH forwarding, or bind directly to a Tailscale `100.x.y.z` IP. Avoid `0.0.0.0`, Tailscale Funnel, and public reverse proxies unless real auth, logging, and data sensitivity have been reviewed. See `docs/tailscale-remote-access.md` and `scripts/check_tailscale_access.sh`.

## Logs

Run uvicorn in the foreground during local operations so request and error logs stay visible. Capture terminal output before changing code or restoring data. Do not log secrets, account credentials, API keys, or private trading instructions.

## Incident response

1. Stop collectors and the app.
2. Preserve the current database with `scripts/backup_sqlite.sh` if it is safe to read.
3. Record the command, time, database path, and observed error.
4. If exposure is suspected, remove broad binds/proxies first, then review logs and Tailscale/firewall posture.
5. Restore from a known-good backup only after preflight succeeds and overwrite is intentional.
