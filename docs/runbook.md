# Kalshi Temps runbook

This runbook is for operating the current local Kalshi Temps research scaffold. It covers database lifecycle, demo data, local dashboard/API operation, validation, source/provenance QA, remote-access cautions, and common recovery steps.

## Operating assumptions

- The project is a local FastAPI + SQLite research tool for Seattle daily high-temperature evidence.
- The current repository supports local database initialization, demo data, a dashboard, API routes, normalizers, and documented ingestion stubs.
- Unless independently implemented and verified elsewhere, assume there is no scheduled live weather ingestion, live Kalshi market feed, authentication, production deployment, or automated trading.
- Dashboard output is research and recordkeeping only. It is not financial advice and must not be treated as a trade instruction.

## Prerequisites

- Python 3.11 or newer.
- Repository dependencies installed from `pyproject.toml`.
- A writable local `data/` directory for SQLite runtime files.

Recommended setup from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

If using commands without an editable install, set:

```bash
export PYTHONPATH=src
```

## Environment variables

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `KALSHI_TEMPS_DB` | `data/kalshi_temps.sqlite3` | CLI, app, scripts | SQLite database path. Keep runtime databases out of source control. |
| `PYTHONPATH` | unset | direct module runs | Use `src` when the package is not installed. Scripts prepend `src` automatically. |
| `HOST` | `127.0.0.1` | `scripts/run_local.sh` | Keep loopback as the safe default. |
| `PORT` | `8000` | `scripts/run_local.sh` | Local dashboard/API port. |

## Database lifecycle

### Initialize or migrate the schema

```bash
mkdir -p data
PYTHONPATH=src python -m kalshi_temps init-db
```

Expected result:

```text
Initialized database: data/kalshi_temps.sqlite3
```

The app also calls `initialize_database()` during FastAPI startup, but operators should still initialize explicitly before loading data or troubleshooting.

### Use a separate database

```bash
export KALSHI_TEMPS_DB=data/research.sqlite3
PYTHONPATH=src python -m kalshi_temps init-db
```

Use separate database files for demo, replay, and live-research experiments unless the schema has durable environment/source labels that prevent confusion.

### Reset local data

For a local-only reset, stop the app, back up the file if it contains anything worth preserving, then remove the SQLite file and reinitialize:

```bash
cp data/kalshi_temps.sqlite3 data/kalshi_temps.sqlite3.bak
rm data/kalshi_temps.sqlite3
PYTHONPATH=src python -m kalshi_temps init-db
```

Do not reset a research database that may contain raw evidence, market snapshots, hypotheses, or audit-relevant notes without first preserving a copy.

### Seed demo data

```bash
PYTHONPATH=src python -m kalshi_temps seed-demo
```

or:

```bash
./scripts/seed_demo_data.sh
```

Demo rows populate weather observations, model runs, model spread, marine-layer indicators, market snapshots, and app events. Treat them as UI/test fixtures only. They are not live weather, market data, or settlement evidence.

## Run the dashboard and API

Safe local default:

```bash
PYTHONPATH=src uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
```

Helper script:

```bash
./scripts/run_local.sh
```

Open:

- Dashboard: <http://127.0.0.1:8000/dashboard> or <http://127.0.0.1:8000/>
- API docs: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health/json>

Health should return JSON with `status: ok`, `service: kalshi-temps`, and non-sensitive database status. Use `kalshi-temps ops-status` locally when you need the full configured path.

## Validation checks

Documentation-only changes usually do not require a test run. For code or operational changes, use the smallest command that covers the behavior:

```bash
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src pytest
```

Manual smoke check after initialization and optional demo seeding:

1. Start the app on `127.0.0.1`.
2. Confirm `/health/json` returns `status: ok`.
3. Confirm `/dashboard` loads.
4. If seeded, confirm demo observations, model disagreement, market snapshots, source freshness, and risk guards are visible.
5. If unseeded, confirm the dashboard shows empty-state messages rather than misleading green status.

## Source and provenance QA checklist

Before adding or trusting any weather, model, market, or manual record, confirm:

- Source name and source type are explicit.
- Endpoint or URL is recorded where available.
- Station/product identifier is captured, especially for KSEA, official settlement products, model cycles, and NWS text products.
- Observation, valid, issue, capture, and ingest times are unambiguous and timezone-aware where possible.
- Raw payload or stable provenance hash is retained.
- Parser status is explicit: accepted, rejected with a clear error, stale, or manually reviewed.
- Demo data is labeled and isolated from live or replay records.
- Proxy stations, Personal Weather Stations, or consumer summaries are marked as lower-trust context unless calibrated.
- Malformed data is not silently coerced into success-shaped defaults.

## Settlement-rule and stale-data guardrails

Do not treat a dashboard value or probability as actionable unless the market-specific rule has been reviewed and recorded:

- Kalshi ticker and title.
- Exact settlement source, station, product, and units.
- Local time zone, daily cutoff, and daylight-saving handling.
- Rounding, correction, outage, and fallback rules.
- Rule text URL or captured source plus verification timestamp.

Current repository guard status is intentionally conservative: repository code treats settlement-source verification as false and surfaces stale/source/proxy/model-spread guards in the research summary. Keep that posture until verified live ingestion and rule records exist.

## Backups and restore

SQLite backup before schema changes, bulk imports, or manual experiments:

```bash
scripts/backup_sqlite.sh
```

Restore:

```bash
scripts/restore_sqlite.sh --backup data/backups/<backup-file>.sqlite3 --force
PYTHONPATH=src python -m kalshi_temps init-db
```

After restore, run the health endpoint and a dashboard smoke check. If a restored database predates schema additions, `init-db` applies the repository's idempotent table/column creation logic.

## Remote access cautions

Prefer private access. Keep the app bound to loopback unless you have reviewed exposure:

```bash
uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
```

Typical private tunnel:

```bash
ssh -L 8000:127.0.0.1:8000 <tailscale-host>
```

Use `docs/tailscale-remote-access.md` and `scripts/check_tailscale_access.sh` for Tailscale-specific checks. Do not use Tailscale Funnel, broad `0.0.0.0` binds, or public reverse proxies unless authentication, authorization, logging, data sensitivity, and credential exposure have been reviewed.

## Troubleshooting

### `ModuleNotFoundError: kalshi_temps`

Install the package or set `PYTHONPATH`:

```bash
python -m pip install -e .
# or
export PYTHONPATH=src
```

### Empty dashboard

An empty dashboard is expected after a fresh `init-db`. Seed demo data if you are validating UI behavior:

```bash
PYTHONPATH=src python -m kalshi_temps seed-demo
```

### Database path surprises

Check the health endpoint and environment:

```bash
echo "$KALSHI_TEMPS_DB"
curl http://127.0.0.1:8000/health/json
```

The public health and ops endpoints avoid full local paths. Run `PYTHONPATH=src python -m kalshi_temps ops-status` on the machine to inspect the configured path. Scripts default to `data/kalshi_temps.sqlite3` and export that value.

### SQLite lock or write failures

- Stop duplicate app or script processes using the same database.
- Confirm the `data/` directory and database file are writable.
- Avoid running bulk writes while the dashboard is serving from the same file.
- Back up the database before attempting manual repair.

### Port already in use

Choose another port:

```bash
PORT=8001 ./scripts/run_local.sh
```

### Remote phone cannot reach the dashboard

- Confirm the app is running and bound to the intended interface.
- Confirm Tailscale is connected on both devices.
- Prefer an SSH tunnel or Tailscale Serve over broad public exposure.
- Check firewall rules and use `scripts/check_tailscale_access.sh` to print likely URLs.

### Source looks fresh but research should still be blocked

Freshness alone is not enough. Keep actionability blocked when settlement rules are unverified, source/product/station does not match the market, observations are proxy-only, model spread is wide, market data is stale/illiquid, or data is demo/replay rather than live.

## Escalation and safety

Stop and review before any trading-adjacent interpretation if:

- Settlement source, station, product, rounding, cutoff, or fallback rules are missing or ambiguous.
- Official and proxy observations disagree enough to change the market bucket.
- Data is stale, out of order, corrected, duplicated, or missing provenance.
- The dashboard is exposed beyond localhost/tailnet without authentication and data-handling review.
- A change would add order placement, account credentials, automated betting, or financial recommendations.

Automated trading is out of scope for the current repository. Any future order-related workflow needs explicit human approval, risk limits, audit logs, compliance review, restricted credentials, and separate implementation instructions.
