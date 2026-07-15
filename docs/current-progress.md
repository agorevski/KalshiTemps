# Current Implementation Progress

Last audited: 2026-07-14.

Kalshi Temps is currently a **local Seattle high-temperature market research tool**. It has a working FastAPI dashboard, SQLite persistence, public/manual collector foundations, deterministic validators, and calibration scaffolding. It is **not** a production-calibrated trading system: it does not provide financial advice, guaranteed arbitrage, automated betting/order entry, compliance approval, authenticated access, live permitted Kalshi ingestion, licensed paid model feeds, or proven multi-week live operations. Settlement rules must be verified per market before any research conclusion is treated as actionable context.

## Implemented modules

- `app.py`: FastAPI app, dashboard rendering, health checks, and read-only JSON API surfaces.
- `cli.py` / `__main__.py`: command-line entry points for local database, ingestion, market-rule, feature, calibration, and ops workflows.
- `db.py`: SQLite path handling, schema initialization, lightweight column migrations, indexes, and collector-run view.
- `repository.py`: persistence/query layer for sources, observations, discussions, models, market snapshots, rules, collector health, features, outcomes, calibration, risk guards, and dashboard summaries.
- `ingest.py`: public NWS discussion and Aviation Weather METAR-style collector foundations plus manual model/market normalization and provenance hashes.
- `quality.py`: deterministic freshness, timestamp, plausibility, duplicate, and source-quality checks.
- `fusion.py`: model spread, run-change, market-implied probability, bucket-delta, freshness, and risk-guard utilities. Edge-like deltas are descriptive only.
- `weather_features.py`: deterministic weather-regime and intraday feature extraction scaffolding.
- `market_rules.py`: market settlement-rule completeness, verification, and actionability-state helpers.
- `calibration.py`: official-outcome, prediction-snapshot, historical-bias, and bucket-calibration computations.
- `ops.py`: local SQLite/disk/access posture checks and backup-path helpers.
- `seed.py`: demo data for local dashboard development only.

## Implemented SQLite/storage areas

Schema initialization currently creates storage for:

- Source/evidence records: `data_sources`, `observations`, `forecast_discussions`, `source_polls` plus `collector_runs` view.
- Market research records: `market_snapshots`, `market_rules`, `model_runs`, `model_spread`, `model_probability_buckets`.
- Weather/research features: `marine_layer_indicators`, `weather_regime_features`, `intraday_features`.
- Calibration scaffolding: `official_outcomes`, `prediction_snapshots`, `historical_bias`, `calibration_metrics`.
- Audit/ops events: `app_events`.

The default database is `data/kalshi_temps.sqlite3` and can be overridden with `KALSHI_TEMPS_DB` or `--db`.

## CLI commands at a high level

Implemented commands include:

- Database/demo setup: `init-db`, `init-db --seed`, `seed-demo`.
- Public/manual collection: `collect-nws-discussion`, `collect-metar`, `run-collectors`, `collector-runs`, `collector-health`.
- Manual model/market research: `import-model-highs`, `list-model-spread`, `extract-weather-features`.
- Market-rule workflow: `add-market-rule`, `verify-market-rule`, `list-market-rules`.
- Calibration scaffolding: `record-official-outcome`, `record-prediction-snapshot`, `compute-calibration`.
- Local operations: `ops-status`, `backup-path`; shell scripts cover local run, demo seed, Tailscale access check, backup, and restore syntax.

## API and dashboard surfaces

Implemented FastAPI routes include:

- `/` redirecting to `/dashboard`, plus `/dashboard` for the local HTML research dashboard.
- `/health` and `/health/json`.
- `/api/ops/status`, `/api/observations`, `/api/sources`, `/api/fusion/summary`, `/api/market-snapshots`, `/api/model-runs`, `/api/model-spread`, `/api/market/verification`, `/api/collector/health`, `/api/weather/features`, and `/api/calibration/summary`.

The dashboard surfaces observations, source/provenance context, daily high, model runs/spread, market snapshots, market-rule verification, collector health, weather features, calibration summaries, events, fusion/risk-guard notes, and ops posture. It is intended for loopback or carefully reviewed private access, not public exposure.

## Testing and validation status

Current local validation run: `PYTHONPATH=src python -m pytest tests -q` passed with **67 tests** on 2026-07-14.

Covered areas include repository flows, ingestion normalization, collector behavior with injected fetchers, market-rule verification, model spread/probability utilities, weather-feature extraction, calibration scaffolding, ops helpers, CLI smoke paths, FastAPI endpoints, dashboard rendering, and script syntax checks. These tests do not prove live-network reliability, live Kalshi ingestion, authenticated access, data-license compliance, production scheduling, operational soak, or out-of-sample probability calibration.

## Current boundary and caveats

Use this project as local research support and recordkeeping only. Do not present outputs as financial advice, guaranteed arbitrage, automated betting instructions, or a calibrated production trading signal. Market settlement source, station/product, timezone, cutoff, units, rounding, fallback, and correction behavior must be verified for each contract. Forecast/model/market probability comparisons must account for stale data, source mismatch, fees, spread, liquidity, slippage, and human/compliance review.

For future work and unresolved gaps, see [shortcomings-and-roadmap.md](shortcomings-and-roadmap.md).
