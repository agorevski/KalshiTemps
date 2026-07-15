# Kalshi Temps

Kalshi Temps is a local Python/FastAPI + SQLite research product for collecting,
normalizing, and reviewing evidence around Seattle daily high-temperature markets.
It is designed for decision support, provenance, and recordkeeping—not guaranteed
arbitrage, financial advice, or unattended trading.

The current application is a working local research scaffold with validated
SQLite/FastAPI flows, public weather collectors, station metadata, market-rule
verification, settlement replay, forecast-model adapter foundations,
marine/cloud nowcast signals, backfill/calibration records, collector health,
paper-live tracking, token-gated local access, and precision dashboard/API
integration. Full local validation has passed across 95 tests, compile checks,
script syntax checks, CLI smoke checks, and FastAPI endpoint smoke checks. It
still depends on external work for real market-specific rule verification by the
user, permitted live Kalshi feeds, paid ECMWF or GraphCast licensing, actual
satellite image processing, sufficient historical backfill, proven calibrated
performance, long-running paper-live soak, compliance/legal review,
production-grade auth/deployment, and any trading controls.

## What the product is for

Kalshi Temps helps a human researcher answer:

- What is the latest observed high-temperature evidence?
- Which source produced each value, when was it observed, and how fresh is it?
- How much do forecast models disagree?
- Is Seattle's marine layer likely to cap the high?
- What do model/research bucket probabilities imply relative to market prices?
- Which caveats block confidence, such as stale data or unverified settlement
  rules?

Outputs should be read as research aids and audit records. They are not
instructions to trade.

## Current capability and status

Implemented in this repository:

- FastAPI app with dashboard routes at `/` and `/dashboard`.
- Health endpoints at `/health` and `/health/json`.
- JSON endpoints for observations, sources, official observations/station
  metadata, model runs, model spread/adapters, settlement replays, market
  snapshots, fusion summary, market verification, collector health, weather and
  nowcast signals, calibration/backfill summaries, paper-live status, and ops
  status.
- SQLite schema initialization and lightweight migration helpers.
- Repository methods for sources, observations, official observations, station
  metadata, collectors, market rules, settlement replays, model runs/adapters,
  model spread/deltas, marine/cloud/nowcast features, market snapshots, official
  outcomes, prediction snapshots, backfill runs, calibration metrics, paper-live
  records, risk guards, and events.
- Demo seed data for a six-layer Seattle temperature evidence view.
- Public NWS discussion, Aviation Weather METAR, and api.weather.gov station
  observation collector foundations plus station/official-observation imports.
- CLI workflows for market-rule records, settlement replay, manual/adapted model
  forecast imports, feature extraction, cloud/nowcast records, collector health,
  local ops status, official outcomes, backfill, prediction snapshots,
  calibration reports, and paper-live run notes/soak metrics.
- Pure utilities for METAR-like observation normalization, forecast-discussion
  normalization, model-high normalization, market snapshot normalization,
  provenance hashes, freshness checks, model spread, feature extraction, and
  bucket probability deltas.

Remaining unresolved risks:

- Real live operational soak with scheduled collectors, monitoring, alerting,
  backups, restore drills, and multi-week paper-live reconciliation.
- Production-grade dashboard/API authentication, deployment hardening,
  authorization, and role-based permissions beyond the local env-token gate.
- Live Kalshi feed credentials, permissions, metadata, bid/ask, and order-book
  ingestion.
- Paid/licensed ECMWF or GraphCast data access and license-compliant storage.
- Satellite image processing for quantitative cloud/stratus burn-off features.
- Real historical backfill depth and proven model calibration on sufficient
  out-of-sample data.
- User-verified market-specific settlement rules before treating any market as
  actionable research context.
- Compliance/legal review for trading-adjacent use; automated trading remains
  out of scope.

See [docs/shortcomings-and-roadmap.md](docs/shortcomings-and-roadmap.md) for the
honest gap list and phased roadmap. See
[docs/high-precision-roadmap.md](docs/high-precision-roadmap.md) for the ordered
plan to improve Seattle temperature signal precision, settlement reconciliation,
intraday nowcasting, and calibrated bucket accuracy.

## Quickstart

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
- Health check: <http://127.0.0.1:8000/health/json>

You can also start the app with:

```bash
./scripts/run_local.sh
```

If you do not install the package, prefix commands with `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m kalshi_temps init-db
PYTHONPATH=src python -m kalshi_temps seed-demo
PYTHONPATH=src uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
```

## Database and runtime data

The default SQLite database is:

```text
data/kalshi_temps.sqlite3
```

Override it with:

```bash
export KALSHI_TEMPS_DB=./data/kalshi_temps.sqlite3
```

Operational expectations:

- Keep runtime data, local databases, exports, API keys, and private market data
  out of source control.
- Preserve provenance for every value that may affect research conclusions:
  source name, URL or endpoint, station/product identifier, observation/valid
  time, ingest time, raw payload or hash, parser status, and QC notes.
- Back up the SQLite file before schema migrations, bulk imports, or live-data
  experiments.
- Keep demo/replay/live records distinguishable before relying on comparisons.

## Key commands

```bash
# Initialize or migrate the configured SQLite database
python -m kalshi_temps init-db

# Initialize and insert demo Seattle evidence
python -m kalshi_temps seed-demo

# Initialize and seed in one command
python -m kalshi_temps init-db --seed

# Run public weather collectors once, recording poll health
python -m kalshi_temps run-collectors
python -m kalshi_temps collect-nws-discussion
python -m kalshi_temps collect-metar --station KSEA
python -m kalshi_temps collect-nws-observation --station KSEA
python -m kalshi_temps collector-runs

# Add/list/verify market settlement-rule metadata
python -m kalshi_temps add-market-rule --help
python -m kalshi_temps verify-market-rule <TICKER> --verified-by <NAME>
python -m kalshi_temps list-market-rules

# Import station/official observation metadata
python -m kalshi_temps import-stations <stations.json-or-csv>
python -m kalshi_temps import-climate-daily-summaries <daily.json-or-csv>
python -m kalshi_temps list-official-observations

# Import model forecasts, inspect spread/deltas, and extract weather/nowcast features
python -m kalshi_temps import-model-highs <file.json-or-csv>
python -m kalshi_temps import-model-forecasts <file.json-or-csv>
python -m kalshi_temps fetch-model-forecasts <url>
python -m kalshi_temps list-model-spread
python -m kalshi_temps list-model-deltas
python -m kalshi_temps extract-weather-features
python -m kalshi_temps import-cloud-features <file.json-or-csv>
python -m kalshi_temps generate-nowcast-snapshots

# Record outcomes, replay settlement, run backfill, and compute calibration reports
python -m kalshi_temps record-official-outcome --target-date YYYY-MM-DD --high-temperature-f 75
python -m kalshi_temps replay-settlement <TICKER> --target-date YYYY-MM-DD
python -m kalshi_temps run-backfill <fixture-dir-or-file>
python -m kalshi_temps record-prediction-snapshot --model-name manual --target-date YYYY-MM-DD
python -m kalshi_temps compute-calibration
python -m kalshi_temps calibration-report --output data/calibration-report.json

# Track paper-live runs without betting or order entry
python -m kalshi_temps start-paper-live-run --name seattle-shadow --target-date YYYY-MM-DD
python -m kalshi_temps record-paper-live-prediction-note <RUN_ID> --note "research note"
python -m kalshi_temps record-paper-live-soak-metric <RUN_ID> --uptime-status observed
python -m kalshi_temps list-paper-live-runs

# Inspect collector and local ops posture
python -m kalshi_temps collector-health
python -m kalshi_temps ops-status

# Run the local app on loopback
uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000

# Validate Python syntax
PYTHONPATH=src python -m compileall -q src tests

# Run tests
PYTHONPATH=src pytest
```

## Architecture and project layout

```text
src/kalshi_temps/
  app.py              FastAPI routes, dashboard rendering, health/API checks
  cli.py              init, collector, rule, feature, ops, and calibration CLI
  db.py               SQLite path resolution, connections, schema initialization
  repository.py       SQL repository boundary for app/domain data
  ingest.py           deterministic normalization and provenance utilities
  fusion.py           model spread, freshness, risk guard, probability utilities
  market_rules.py     settlement-rule completeness and verification helpers
  weather_features.py deterministic weather-regime and intraday features
  official_sources.py public official source/station metadata import helpers
  settlement.py       rule-driven official outcome replay helpers
  model_adapters.py   normalized model forecast adapter/fetch/load helpers
  nowcast.py          cloud and fixed-hour nowcast signal helpers
  backfill.py         fixture replay/backfill orchestration
  calibration.py      historical bias and bucket calibration foundations
  paper_live.py       no-betting paper-live run/note/soak helpers
  auth.py             optional env-token access gate for local dashboard/API
  ops.py              local database/disk/access posture helpers
  seed.py             local demo data

templates/
  dashboard.html  local research dashboard

static/
  styles.css      dashboard styles

scripts/
  run_local.sh
  seed_demo_data.sh
  backup_sqlite.sh / restore_sqlite.sh
  check_tailscale_access.sh

docs/
  detailed design, source, workflow, schema, roadmap, and access notes

tests/
  parser, fusion, repository, CLI, and FastAPI integration tests
```

Design boundaries:

- FastAPI routes should orchestrate repositories and rendering, not embed
  collection or forecasting logic.
- Repository classes own SQL access.
- Domain utilities should stay deterministic, dependency-light, and easy to
  test without network access.
- Raw observations, normalized records, derived features, hypotheses, and market
  snapshots should remain separable.

## Research workflow

The intended research loop is conservative:

1. Verify the exact market settlement rule before treating any signal as
   actionable: station, source/product, local day, time zone, rounding,
   corrections, fallback behavior, and verification timestamp.
2. Capture raw source evidence with provenance.
3. Normalize records without silently coercing malformed inputs.
4. Compare model guidance, station observations, marine-layer signals,
   historical bias context, intraday nowcasts, and market-implied probabilities.
5. Surface stale data, source mismatch, unverified rules, wide model spread, and
   proxy-only observations before any human decision.
6. Record assumptions and postmortems so outcomes can be audited and improved.

Seattle-specific emphasis: morning marine clouds, fog, stratus burn-off timing,
wind shifts, dew point, pressure, and solar radiation can move the daily high by
multiple degrees. Treat marine-layer timing as a first-class feature, not a
narrative afterthought.

## Data and provenance principles

- Prefer official or verified settlement sources over proxy stations.
- Treat KSEA or Weather Underground settlement claims as hypotheses until the
  specific market text is verified.
- Keep personal weather stations low-trust unless calibrated and labeled.
- Preserve model run time, cycle, target date, valid time, predicted high,
  probability bucket, source URL, raw payload/hash, and notes.
- Track market bid/ask/last/mid conventions explicitly; implied probabilities
  are descriptive comparisons, not proof of edge.
- Do not hide uncertainty behind green statuses or success-shaped defaults.

## Validation

Documentation-only edits do not require tests, but behavior changes should be
validated with the smallest relevant command:

```bash
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src pytest
```

Current validation has passed for 95 tests plus compileall, script syntax, CLI
smoke, and FastAPI endpoint smoke checks. Tests cover:

- SQLite initialization, seeding, repository flows, CLI smoke checks, and app
  endpoints.
- Parser/normalizer behavior for forecast discussions, METAR-like observations,
  model highs, market snapshots, freshness metadata, and provenance hashes.
- Collector poll records and mocked public weather collector flows.
- Market-rule verification, settlement replay, official source/station metadata,
  model adapters and deltas, weather/cloud/nowcast features, backfill and
  calibration scaffolding, paper-live run tracking, token-gated access, ops
  status, implied probabilities, freshness, and risk guards.

## Documentation map

- [docs/index.md](docs/index.md) — documentation home and quick operational
  overview.
- [docs/current-progress.md](docs/current-progress.md) — audited inventory of
  implemented modules, storage, CLI, API/dashboard surfaces, validation status,
  and current product boundary.
- [docs/runbook.md](docs/runbook.md) — local operations, validation, recovery,
  source QA, and remote-access checklist.
- [docs/implementation-design.md](docs/implementation-design.md) — intended app,
  persistence, service, ingestion, dashboard, and safety architecture.
- [docs/high-precision-roadmap.md](docs/high-precision-roadmap.md) — ordered
  roadmap for higher-accuracy Seattle high-temperature signals and calibrated
  bucket probabilities.
- [docs/schema-reference.md](docs/schema-reference.md) — current SQLite schema
  and planned schema extensions.
- [docs/temperature-forecasting-plan.md](docs/temperature-forecasting-plan.md) —
  Seattle temperature research methodology.
- [docs/data-sources.md](docs/data-sources.md) — source priority, station
  context, and provenance requirements.
- [docs/market-workflow-and-risk-controls.md](docs/market-workflow-and-risk-controls.md)
  — market workflow, caveats, and risk-control expectations.
- [docs/tailscale-remote-access.md](docs/tailscale-remote-access.md) — private
  remote-access notes.
- [docs/shortcomings-and-roadmap.md](docs/shortcomings-and-roadmap.md) — current
  limitations and phased roadmap.

## Remote access posture

Run locally on loopback by default:

```bash
uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
```

For private remote use, prefer an SSH tunnel over Tailscale:

```bash
ssh -L 8000:127.0.0.1:8000 <tailscale-host>
```

Do not expose the dashboard publicly unless authentication, authorization,
secrets handling, logging, and data-sensitivity risks have been reviewed. Treat
Tailscale as private networking, not application authorization.

## Contribution expectations

- Keep changes small, tested, dependency-light, and auditable.
- Add or update focused tests for new parser, fusion, repository, CLI, or route
  behavior.
- Do not silently ignore malformed weather or market inputs; raise clear errors,
  log explicit app events, or mark records stale/invalid.
- Preserve provenance and separation between raw, normalized, derived, and market
  records.
- Update docs when behavior, schema, commands, assumptions, limitations, or risk
  posture changes.
- Do not commit secrets, local databases, account identifiers, private exports,
  paid/licensed data, or runtime artifacts.

## Safety and compliance

Kalshi markets are regulated financial products. This repository supports
research and recordkeeping only. It does not provide financial advice, guaranteed
returns, guaranteed arbitrage, automated betting, or compliance approval.

Before any trading-adjacent use, independently review market rules, settlement
source, source freshness, fees, liquidity, spreads, slippage, data-provider
licenses, account permissions, applicable law, and organizational policy.
Automated trading would require separate explicit design, human approval, risk
limits, kill switches, audit logs, credential controls, and compliance review.
