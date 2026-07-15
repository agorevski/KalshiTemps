# Operations runbook

Practical operating notes for the local Kalshi Temps FastAPI + SQLite dashboard.

## Local app

- Install with `python -m pip install -e .` or run commands with `PYTHONPATH=src`.
- Initialize the database: `PYTHONPATH=src python -m kalshi_temps init-db`.
- Optionally set a local token gate: `export KALSHI_TEMPS_ACCESS_TOKEN='<local-secret-token>'`.
- Start locally: `PYTHONPATH=src uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000`.
- Check local health: `curl http://127.0.0.1:8000/health/json`.
- Check non-sensitive ops status: `curl http://127.0.0.1:8000/api/ops/status`.
- Check DB integrity/schema posture: `curl http://127.0.0.1:8000/api/ops/db-health`.
- Check scheduler/monitoring surfaces: `curl http://127.0.0.1:8000/api/scheduler/status` and `curl http://127.0.0.1:8000/api/monitoring/alerts`.

When `KALSHI_TEMPS_ACCESS_TOKEN` is set, dashboard and API routes require `Authorization: Bearer <token>` or `X-Access-Token: <token>`. This is local hardening only, not production-grade authentication, authorization, sessions, deployment security, or compliance approval. Keep the app on localhost or trusted tailnet-only access unless production auth/deployment is implemented and reviewed.

## Collectors and precision workflows

Run collectors manually and keep provenance labels clear:

```bash
PYTHONPATH=src python -m kalshi_temps collect-nws-discussion
PYTHONPATH=src python -m kalshi_temps collect-metar --station KSEA
PYTHONPATH=src python -m kalshi_temps collect-nws-observation --station KSEA
PYTHONPATH=src python -m kalshi_temps run-collectors
PYTHONPATH=src python -m kalshi_temps run-scheduled-collectors --collectors nws_discussion,metar --dry-run
PYTHONPATH=src python -m kalshi_temps run-scheduled-collectors --collectors nws_discussion,metar
scripts/run_collectors_once.sh
PYTHONPATH=src python -m kalshi_temps scheduler-status
PYTHONPATH=src python -m kalshi_temps collector-runs
PYTHONPATH=src python -m kalshi_temps collector-health
```

Station/source, settlement, model, nowcast, backfill, and paper-live helper commands:

```bash
PYTHONPATH=src python -m kalshi_temps import-stations <stations.json-or-csv>
PYTHONPATH=src python -m kalshi_temps import-climate-daily-summaries <daily.json-or-csv>
PYTHONPATH=src python -m kalshi_temps add-market-rule --help
PYTHONPATH=src python -m kalshi_temps verify-market-rule <TICKER> --verified-by <NAME>
PYTHONPATH=src python -m kalshi_temps replay-settlement <TICKER> --target-date YYYY-MM-DD
PYTHONPATH=src python -m kalshi_temps import-model-forecasts <models.json-or-csv>
PYTHONPATH=src python -m kalshi_temps import-cloud-features <cloud.json-or-csv>
PYTHONPATH=src python -m kalshi_temps generate-nowcast-snapshots
PYTHONPATH=src python -m kalshi_temps create-backfill-plan --station KSEA --start-date YYYY-MM-DD --end-date YYYY-MM-DD --output data/backfill-plan.json --persist
PYTHONPATH=src python -m kalshi_temps run-backfill <fixture-dir-or-file>
PYTHONPATH=src python -m kalshi_temps run-backfill --plan-file data/backfill-plan.json --dry-run
PYTHONPATH=src python -m kalshi_temps compute-calibration
PYTHONPATH=src python -m kalshi_temps calibration-report --output data/calibration-report.json
PYTHONPATH=src python -m kalshi_temps start-paper-live-run --name seattle-shadow --target-date YYYY-MM-DD
```

Treat failed, stale, demo, proxy, imported, or manually edited records as research-only until source, provenance, license, and settlement rules are verified. Settlement replay, calibration reports, nowcast signals, and paper-live notes are audit scaffolding; they are not proof of production calibration, guaranteed arbitrage, financial advice, or permission to trade. No automated betting or order entry exists. systemd timer/service snippets are documentation-only in `docs/systemd-examples.md`; this repository does not install cron or systemd units, and a one-shot scheduler is not a production scheduled service until configured, monitored, and soaked.

## Monitoring and daily reports

Monitoring checks can persist idempotent alert records and export daily reports for review:

```bash
PYTHONPATH=src python -m kalshi_temps run-monitoring-checks
PYTHONPATH=src python -m kalshi_temps list-alerts
PYTHONPATH=src python -m kalshi_temps resolve-alert --id <ALERT_ID> --resolved-by <NAME>
PYTHONPATH=src python -m kalshi_temps export-daily-report --output data/daily-report.md --format markdown
```

The dashboard links `/api/monitoring/alerts` and `/api/monitoring/daily-report`. Alert presence means "review required"; it is not an automated trading block, order signal, or compliance system.

## External dependencies checklist

Before relying on any live or trading-adjacent workflow, confirm:

- User/trusted reviewer has verified real market-specific settlement rules.
- Live Kalshi credentials, feed permissions, terms, and rate limits permit the intended metadata/price/order-book use.
- Paid ECMWF/GraphCast or other licensed data have valid licenses and storage terms.
- Satellite image processing is actually implemented and licensed, not represented by manual cloud proxy records.
- Historical backfill is sufficient for the target season/regime/horizon/bucket.
- Calibration performance is proven out of sample with documented metrics.
- Paper-live soak has run long enough with reconciliations, backups, restore drills, and incident review.
- Compliance/legal review and production-grade auth/deployment are complete.

## Backups

Create a timestamped backup before schema changes, imports, backfill, paper-live runs, or manual edits:

```bash
scripts/backup_sqlite.sh
scripts/backup_sqlite.sh --db data/research.sqlite3 --backup-dir data/backups
```

Backups are written under `data/backups` by default, do not overwrite existing files, and use `cp -p` to preserve permissions where practical.

Before and after backups/restores, run the DB checks:

```bash
PYTHONPATH=src python -m kalshi_temps db-check
PYTHONPATH=src python -m kalshi_temps verify-backup data/backups/<backup>.sqlite3
PYTHONPATH=src python -m kalshi_temps prune-backups --dry-run
```

Only use `prune-backups --delete` after the dry-run candidate list and minimum retention settings are reviewed.

## Restore

Restores refuse to overwrite an existing database unless `--force` is supplied:

```bash
scripts/restore_sqlite.sh --backup data/backups/<backup>.sqlite3 --db data/restore-test.sqlite3
scripts/restore_sqlite.sh --backup data/backups/<backup>.sqlite3 --force
PYTHONPATH=src python -m kalshi_temps init-db
```

The restore script performs safe preflight and refuses to overwrite unless `--force` is supplied. After restore, run health, `db-check`, ops status, scheduler status, monitoring alerts/daily report, settlement replays, backfill reports, paper-live status, and load the dashboard.

## Tailscale and binding

Prefer `127.0.0.1`. For phone access, use Tailscale Serve, SSH forwarding, or bind directly to a Tailscale `100.x.y.z` IP. Avoid `0.0.0.0`, Tailscale Funnel, and public reverse proxies unless real auth, logging, and data sensitivity have been reviewed. See `docs/tailscale-remote-access.md` and `scripts/check_tailscale_access.sh`.

## Logs

Run uvicorn in the foreground during local operations so request and error logs stay visible. Capture terminal output before changing code, restoring data, or starting paper-live runs. Do not log secrets, access tokens, account credentials, API keys, private market data, or trading instructions.

## Incident response

1. Stop collectors and the app.
2. Preserve the current database with `scripts/backup_sqlite.sh` if it is safe to read.
3. Record the command, time, database path, source/market/run IDs, and observed error.
4. If exposure is suspected, rotate `KALSHI_TEMPS_ACCESS_TOKEN` and any real credentials, remove broad binds/proxies first, then review logs and Tailscale/firewall posture.
5. Restore from a known-good backup only after preflight succeeds and overwrite is intentional.
6. Mark affected paper-live runs, settlement replays, calibration reports, or source polls as needing review in notes/events where practical.
