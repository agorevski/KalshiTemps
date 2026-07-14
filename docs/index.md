# Kalshi Temps documentation

This documentation ties together the intended Kalshi Temps project: a Python FastAPI application, SQLite logging, a local dashboard, and optional private remote access over Tailscale.

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

## Research plan

1. Identify temperature-related Kalshi markets and document the market rules before collecting or analyzing data.
2. Record market metadata, observations, prices, timestamps, and derived research notes in SQLite.
3. Keep raw observations separate from derived signals so assumptions can be audited.
4. Use demo seed data for dashboard development and avoid mixing demo rows with live research records.
5. Review results manually before making any trading decision.

### Six-layer data fusion

The project should surface a concise view of six research layers while linking to the detailed plans rather than duplicating them:

1. **Raw model disagreement** across short-range and probabilistic guidance.
2. **Seattle marine layer timing** and related regime signals that can change the daily high.
3. **KSEA and surrounding observations** for official-station tracking and calibrated proxy context.
4. **Historical conditional model bias** segmented by station, season, hour, and weather regime.
5. **Live intraday nowcasting** of remaining upside risk before the settlement window closes.
6. **Market-implied probabilities** from Kalshi prices for comparison against the research distribution.

Detailed planning lives in [temperature-forecasting-plan.md](temperature-forecasting-plan.md), [data-sources.md](data-sources.md), and [market-workflow-and-risk-controls.md](market-workflow-and-risk-controls.md).

### Future ML roadmap

After enough historical data is collected, the first ML target should be a gradient-boosted model that estimates probability by temperature bucket. This should produce calibrated output distributions that can be compared with Kalshi implied probabilities. Do not make this neural-network-first, and do not describe model output as guaranteed arbitrage.

## SQLite logging

Recommended local database path:

```text
./data/kalshi_temps.sqlite3
```

Recommended environment variable, if supported by the app:

```bash
export KALSHI_TEMPS_DB=./data/kalshi_temps.sqlite3
```

Operational expectations:

- Initialize schema with `python -m kalshi_temps init-db`.
- Load sample rows with `python -m kalshi_temps seed-demo` or `./scripts/seed_demo_data.sh`.
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

The dashboard should make provenance clear: demo data, live observations, and derived calculations should be distinguishable.

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
- This project should not provide financial advice or automated trading recommendations without explicit review and controls.
- Treat forecasts and dashboard metrics as research aids, not instructions to trade.
- Never commit API keys, account identifiers, credentials, or private exports.
- Document assumptions for each market so analysis can be reproduced and challenged.
