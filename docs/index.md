# Kalshi Temps documentation

This documentation ties together the current Kalshi Temps project: a Python FastAPI application, SQLite logging, public weather collector foundations, market-rule verification records, local research dashboard, calibration scaffolding, and optional private remote access over Tailscale. Start with [current-progress.md](current-progress.md) for the implementation inventory; use roadmap documents for future or unresolved work.

## Quick start

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
mkdir -p data
python -m kalshi_temps init-db
python -m kalshi_temps seed-demo
uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
```

Open:

- Dashboard: <http://127.0.0.1:8000/>
- FastAPI docs: <http://127.0.0.1:8000/docs>

You can also start the local app with `./scripts/run_local.sh`.


## Current status vs roadmap

- [Current implementation progress](current-progress.md) is the audited inventory of what exists now, including modules, storage, CLI, API/dashboard surfaces, validation status, and product boundary.
- [Product shortcomings and roadmap](shortcomings-and-roadmap.md) is the conservative gap list and future-work plan. Do not treat roadmap items as implemented.
- [High-precision Seattle temperature signal roadmap](high-precision-roadmap.md) is the ordered plan for improving settlement-source discipline, KSEA/proxy station quality, intraday nowcasting, historical backfill, and calibrated bucket accuracy.
- Current status: local research support with public/manual collectors and foundations. Not financial advice, not guaranteed arbitrage, not automated betting, and not a production-calibrated trading system. Settlement rules must be verified per market.

## Research plan

1. Identify temperature-related Kalshi markets and document the market rules before collecting or analyzing data.
2. Record market metadata, observations, prices, timestamps, and derived research notes in SQLite.
3. Keep raw observations separate from derived signals so assumptions can be audited.
4. Use demo seed data for dashboard development and avoid mixing demo rows with live research records.
5. Review results manually; this project is research support, not financial advice or automated trading.

### Six-layer data fusion

The implemented dashboard and APIs now surface a concise view of six research layers while linking to the detailed plans rather than duplicating them:

1. **Raw model disagreement** across short-range and probabilistic guidance.
2. **Seattle marine layer timing** and related regime signals that can change the daily high.
3. **KSEA and surrounding observations** for official-station tracking and calibrated proxy context.
4. **Historical conditional model bias** segmented by station, season, hour, and weather regime.
5. **Intraday nowcasting scaffolding** for remaining-upside research before the settlement window closes.
6. **Market-implied probabilities** from Kalshi prices for comparison against the research distribution.

Detailed planning lives in [temperature-forecasting-plan.md](temperature-forecasting-plan.md), [data-sources.md](data-sources.md), and [market-workflow-and-risk-controls.md](market-workflow-and-risk-controls.md).

For day-to-day local operation, validation, database lifecycle, provenance checks, and troubleshooting, use the [runbook](runbook.md). For backup/restore, Tailscale posture, logs, and incident-response steps, use the [operations runbook](operations-runbook.md).

### Calibration roadmap

The repository can store official outcomes, prediction snapshots, bias summaries, and bucket calibration metrics, but sufficient real historical backfill does not yet exist. After enough clean history is collected, start with transparent baselines and only then consider gradient-boosted bucket-probability models. Do not describe model output as guaranteed arbitrage.

## SQLite logging

Recommended local database path:

```text
./data/kalshi_temps.sqlite3
```

Recommended environment variable:

```bash
export KALSHI_TEMPS_DB=./data/kalshi_temps.sqlite3
```

Operational expectations:

- Initialize schema with `python -m kalshi_temps init-db`.
- Load sample rows with `python -m kalshi_temps seed-demo` or `./scripts/seed_demo_data.sh`.
- Run public collector foundations with `python -m kalshi_temps run-collectors` when network access is appropriate.
- Manage market-rule records with `add-market-rule`, `verify-market-rule`, and `list-market-rules`.
- Inspect collector and local ops posture with `collector-health` and `ops-status`.
- Keep `data/` runtime files untracked unless a fixture is intentionally added.
- Back up the SQLite file before schema migrations or bulk imports.

## Dashboard

Run the local FastAPI app:

```bash
uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
```

Expected routes:

- `/dashboard` for the local dashboard; `/` redirects there
- `/docs` for FastAPI-generated API documentation
- `/health/json` for health status
- `/api/market/verification`, `/api/collector/health`, `/api/weather/features`, `/api/calibration/summary`, and `/api/ops/status` for high-level research and operations summaries

The dashboard should make provenance clear: demo, manual-live, replay/paper-live, live, and derived calculations should be distinguishable.

## Tailscale remote access

Prefer private access over Tailscale rather than binding the app to a public interface.

Recommended pattern:

```bash
ssh -L 8000:127.0.0.1:8000 <tailscale-host>
```

Keep the app command bound to loopback:

```bash
uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
```

Before using Tailscale Serve, Funnel, or any public exposure, review authentication, authorization, logging, data sensitivity, and whether credentials or trading-related information could be exposed.

## Safety and compliance caveats

- Kalshi markets are regulated financial products; follow Kalshi terms, market rules, and applicable law.
- This project does not provide financial advice, compliance approval, or automated trading.
- Treat forecasts and dashboard metrics as research aids, not instructions to trade.
- Never commit API keys, account identifiers, credentials, or private exports.
- Document assumptions for each market so analysis can be reproduced and challenged.
