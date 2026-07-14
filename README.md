# Kalshi Temps

Kalshi Temps is a Python/FastAPI project for researching temperature-related Kalshi markets, recording market observations in SQLite, and viewing results in a local dashboard.

## Project shape

- Python package: `kalshi_temps/`
- FastAPI app: `kalshi_temps.app:app`
- SQLite-backed logging and demo data utilities
- Local browser dashboard served by the FastAPI app
- Project documentation in `docs/`

## Data-fusion strategy

The research plan combines six evidence layers without treating any one layer as conclusive:

1. Raw forecast-model disagreement.
2. Seattle marine layer timing and related local weather regime signals.
3. KSEA and surrounding-station observations.
4. Historical conditional model bias by regime and station context.
5. Live intraday nowcasting of the remaining high-temperature risk.
6. Kalshi market-implied probabilities for comparison.

See [docs/index.md](docs/index.md), [temperature forecasting plan](docs/temperature-forecasting-plan.md), [data sources](docs/data-sources.md), and [market workflow and risk controls](docs/market-workflow-and-risk-controls.md) for the detailed planning context.

Future ML work should start with a gradient-boosted bucket-probability model after enough historical observations, forecasts, outcomes, and market snapshots have been collected. The goal is calibrated output distributions by temperature bucket that can be compared with Kalshi implied probabilities; this is not intended to start as a neural-network-first project or to promise arbitrage.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

If the package metadata is not present yet, install dependencies from the scaffold once it is added.

## Database

Use a local SQLite database for research logs, market snapshots, and dashboard data. Keep runtime data out of source control.

Recommended convention:

```text
./data/kalshi_temps.sqlite3
```

Initialize and optionally seed demo data:

```bash
mkdir -p data
python -m kalshi_temps init-db
python -m kalshi_temps seed-demo
```

If the implementation supports an environment variable, prefer pointing it at the local database explicitly:

```bash
export KALSHI_TEMPS_DB=./data/kalshi_temps.sqlite3
```

## Run locally

Start the API and dashboard on loopback only:

```bash
uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
```

Or use the helper script:

```bash
./scripts/run_local.sh
```

Expected local URLs:

- Dashboard: <http://127.0.0.1:8000/dashboard> or <http://127.0.0.1:8000/>
- API docs: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health/json>

## Remote access with Tailscale

For private remote access, keep Uvicorn bound to `127.0.0.1` for local-only use, or intentionally bind to the machine's Tailscale IP / `0.0.0.0` only after reviewing exposure. Use `docs/tailscale-remote-access.md` and `scripts/check_tailscale_access.sh` to identify phone URLs.

Typical SSH tunnel pattern:

```bash
ssh -L 8000:127.0.0.1:8000 <tailscale-host>
```

Then open <http://127.0.0.1:8000/> on the client machine.

Do not expose the dashboard publicly unless authentication, authorization, and data handling have been reviewed.

## Docs map

- [docs/index.md](docs/index.md) — documentation home, research plan, operations notes, and safety caveats.
- [docs/temperature-forecasting-plan.md](docs/temperature-forecasting-plan.md) — detailed Seattle temperature research methodology.
- [docs/data-sources.md](docs/data-sources.md) — source priority, station context, and provenance requirements.
- [docs/market-workflow-and-risk-controls.md](docs/market-workflow-and-risk-controls.md) — market workflow, risk controls, and decision logging.
- [docs/tailscale-remote-access.md](docs/tailscale-remote-access.md) — private remote access notes.

## Safety and compliance

This project is for research and recordkeeping. Kalshi markets are regulated financial products. Do not treat dashboard output, demo data, forecasts, or generated analysis as financial advice. Before trading, review Kalshi rules, applicable laws, market-specific terms, fees, risk limits, and account compliance obligations. Keep API credentials and private market data out of git.
