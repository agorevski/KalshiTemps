# Kalshi Temps documentation

This documentation ties together the current Kalshi Temps project: a Python FastAPI application, SQLite logging, public weather collector foundations, official source/station metadata, settlement replay, market-rule verification records, model adapter foundations, marine/cloud nowcast signals, backfill/calibration records, paper-live tracking, optional local token gating, and precision dashboard/API integration. Start with [current-progress.md](current-progress.md) for the implementation inventory; use roadmap documents for future or unresolved work.

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
- [Product shortcomings and roadmap](shortcomings-and-roadmap.md) is the conservative gap list and future-work plan. Do not treat unresolved external dependencies as solved.
- [High-precision Seattle temperature signal roadmap](high-precision-roadmap.md) now marks in-repository foundations that are complete while preserving acceptance criteria that still require real data, permissions, licensing, or soak.
- Current status: local research support with public/manual collectors, settlement replay, station metadata, model adapter/nowcast/backfill/paper-live foundations, and precision dashboard/API surfaces. Not financial advice, not guaranteed arbitrage, not automated betting, and not a production-calibrated trading system. Settlement rules must be verified per market.

## Research plan

1. Identify temperature-related Kalshi markets and document the market rules before collecting or analyzing data.
2. Record market metadata, observations, prices, timestamps, station/source metadata, and derived research notes in SQLite.
3. Keep raw observations separate from derived signals so assumptions can be audited.
4. Use demo seed data for dashboard development and avoid mixing demo rows with live research records.
5. Review results manually; this project is research support, not financial advice or automated trading.

### Six-layer data fusion

The implemented dashboard and APIs now surface a concise view of six research layers while linking to the detailed plans rather than duplicating them:

1. **Raw model disagreement** across short-range and probabilistic guidance.
2. **Seattle marine layer timing** and related regime/cloud/nowcast signals that can change the daily high.
3. **KSEA and surrounding observations** for official-station tracking and calibrated proxy context.
4. **Historical conditional model bias** segmented by station, season, hour, and weather regime.
5. **Intraday nowcasting scaffolding** for remaining-upside research before the settlement window closes.
6. **Market-implied probabilities** from Kalshi prices for comparison against the research distribution.

Detailed planning lives in [temperature-forecasting-plan.md](temperature-forecasting-plan.md), [data-sources.md](data-sources.md), and [market-workflow-and-risk-controls.md](market-workflow-and-risk-controls.md).

For day-to-day local operation, validation, database lifecycle, provenance checks, and troubleshooting, use the [runbook](runbook.md). For backup/restore, token-gated local access posture, Tailscale posture, logs, and incident-response steps, use the [operations runbook](operations-runbook.md).

### Calibration roadmap

The repository can store official outcomes, prediction snapshots, backfill runs, bias summaries, and bucket calibration metrics, but sufficient real historical backfill and proven out-of-sample performance do not yet exist. After enough clean history is collected, start with transparent baselines and only then consider gradient-boosted bucket-probability models. Do not describe model output as guaranteed arbitrage.

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
- Manage station/official-source records with `import-stations`, `list-stations`, `collect-nws-observation`, and `import-climate-daily-summaries`.
- Manage market-rule records and replays with `add-market-rule`, `verify-market-rule`, `list-market-rules`, `record-official-outcome`, and `replay-settlement`.
- Import model/nowcast/backfill research records with `import-model-forecasts`, `import-cloud-features`, `generate-nowcast-snapshots`, and `run-backfill`.
- Inspect collector, paper-live, and local ops posture with `collector-health`, `list-paper-live-runs`, and `ops-status`.
- Keep `data/` runtime files untracked unless a fixture is intentionally added.
- Back up the SQLite file before schema migrations or bulk imports.

## Dashboard

Run the local FastAPI app:

```bash
uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
```

Optional local token gate:

```bash
export KALSHI_TEMPS_ACCESS_TOKEN='<local-secret-token>'
```

Expected routes include `/dashboard`, `/docs`, `/health/json`, `/api/official/observations`, `/api/model/adapters`, `/api/settlement/replays`, `/api/nowcast/signals`, `/api/backfill/reports`, `/api/paper-live/status`, `/api/market/verification`, `/api/collector/health`, `/api/weather/features`, `/api/calibration/summary`, and `/api/ops/status`.

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

Before using Tailscale Serve, Funnel, or any public exposure, review authentication, authorization, logging, data sensitivity, and whether credentials or trading-related information could be exposed. The env-token gate is useful local hardening but is not production-grade auth/deployment.

## Safety and compliance caveats

- Kalshi markets are regulated financial products; follow Kalshi terms, market rules, and applicable law.
- This project does not provide financial advice, compliance approval, guaranteed arbitrage, or automated trading.
- Treat forecasts and dashboard metrics as research aids, not instructions to trade.
- Never commit API keys, account identifiers, credentials, or private exports.
- Document assumptions for each market so analysis can be reproduced and challenged.
