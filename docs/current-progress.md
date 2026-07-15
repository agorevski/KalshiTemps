# Current Implementation Progress

Last audited: 2026-07-14.

Kalshi Temps is currently a **local Seattle high-temperature market research tool**. It has a working FastAPI dashboard, SQLite persistence, public/manual collector foundations, official source and station metadata storage, deterministic validators, settlement replay, model adapter foundations, marine/cloud nowcast signals, backfill/calibration records, paper-live tracking, optional env-token access gating, and precision dashboard/API integration. It is **not** a production-calibrated trading system: it does not provide financial advice, guaranteed arbitrage, automated betting/order entry, compliance approval, permitted live Kalshi ingestion, licensed paid model feeds, actual satellite image processing, proven multi-week live operations, or production-grade auth/deployment. Settlement rules must be verified per market by the user before any research conclusion is treated as actionable context.

## Implemented modules

- `app.py`: FastAPI app, dashboard rendering, health checks, optional access middleware, and read-only JSON API surfaces.
- `cli.py` / `__main__.py`: command-line entry points for local database, ingestion, market-rule, settlement replay, station metadata, model adapter, feature, backfill, calibration, paper-live, and ops workflows.
- `db.py`: SQLite path handling, schema initialization, lightweight column migrations, indexes, and collector-run view.
- `repository.py`: persistence/query layer for sources, observations, station metadata, official observations, discussions, models, market snapshots, rules, settlement replays, collector health, features, outcomes, backfill, calibration, paper-live records, risk guards, and dashboard summaries.
- `ingest.py`: public NWS discussion and Aviation Weather METAR-style collector foundations plus manual model/market normalization and provenance hashes.
- `official_sources.py`: official station metadata, public station-observation, and climate daily-summary import foundations.
- `settlement.py`: deterministic replay of official outcomes through verified market-rule metadata, including rounding/correction/fallback flags and mismatch reasons.
- `model_adapters.py`: JSON/CSV/URL model forecast adapter foundations for HRRR/NAM/GFS/NBM-style records with run/valid/extraction metadata.
- `nowcast.py`: cloud feature and fixed-hour nowcast signal foundations for marine/cloud, warming-rate, wind, ceiling, solar proxy, and remaining-upside context.
- `backfill.py`: fixture replay/backfill orchestration into local SQLite with run summaries.
- `calibration.py`: official-outcome, prediction-snapshot, historical-bias, train/test split, and bucket-calibration computations.
- `paper_live.py`: no-betting paper-live run, checklist, prediction note, postmortem, reconciliation, and soak-metric helpers.
- `auth.py`: optional `KALSHI_TEMPS_ACCESS_TOKEN` gate for `/dashboard` and `/api/*`; this is local hardening, not production auth.
- `ops.py`: local SQLite/disk/access posture checks, backup-path helpers, and paper-live readiness summaries.
- `quality.py`, `fusion.py`, `weather_features.py`, `market_rules.py`, `seed.py`: deterministic QC, model spread/probability/risk utilities, weather feature extraction, market-rule actionability helpers, and demo data.

## Implemented SQLite/storage areas

Schema initialization currently creates storage for:

- Source/evidence records: `data_sources`, `observations`, `official_observations`, `forecast_discussions`, `source_polls` plus `collector_runs` view.
- Station/source metadata: `station_metadata` and source/provenance fields needed for official-vs-proxy discipline.
- Market research records: `market_snapshots`, `market_rules`, `settlement_replays`, `model_runs`, `model_run_extractions`, `model_run_deltas`, `model_spread`, `model_probability_buckets`.
- Weather/research features: `marine_layer_indicators`, `cloud_features`, `weather_regime_features`, `intraday_features`, `nowcast_snapshots`.
- Calibration/backfill: `official_outcomes`, `prediction_snapshots`, `backfill_runs`, `historical_bias`, `calibration_metrics`.
- Paper-live and audit/ops events: `paper_live_runs`, `paper_live_checklist_entries`, `paper_live_prediction_notes`, `paper_live_reconciliation_notes`, `paper_live_soak_metrics`, `app_events`.

The default database is `data/kalshi_temps.sqlite3` and can be overridden with `KALSHI_TEMPS_DB` or `--db`.

## CLI commands at a high level

Implemented commands include:

- Database/demo setup: `init-db`, `init-db --seed`, `seed-demo`.
- Public/manual collection: `collect-nws-discussion`, `collect-metar`, `collect-nws-observation`, `run-collectors`, `collector-runs`, `collector-health`.
- Official source/station metadata: `import-stations`, `list-stations`, `import-climate-daily-summaries`, `list-official-observations`.
- Manual/adapted model research: `import-model-highs`, `import-model-forecasts`, `fetch-model-forecasts`, `list-model-spread`, `list-model-deltas`.
- Weather/nowcast signals: `extract-weather-features`, `import-cloud-features`, `list-cloud-features`, `generate-nowcast-snapshots`, `list-nowcast-snapshots`.
- Market-rule and settlement workflow: `add-market-rule`, `verify-market-rule`, `list-market-rules`, `record-official-outcome`, `replay-settlement`.
- Backfill/calibration: `run-backfill`, `record-prediction-snapshot`, `compute-calibration`, `calibration-report`.
- Paper-live and local operations: `start-paper-live-run`, `list-paper-live-runs`, `close-paper-live-run`, `record-paper-live-checklist`, `record-paper-live-prediction-note`, `record-paper-live-postmortem`, `record-paper-live-soak-metric`, `ops-status`, `backup-path`; shell scripts cover local run, demo seed, Tailscale access check, backup, and restore syntax.

## API and dashboard surfaces

Implemented FastAPI routes include:

- `/` redirecting to `/dashboard`, plus `/dashboard` for the local HTML research dashboard.
- `/health` and `/health/json`.
- `/api/ops/status`, `/api/paper-live/runs`, `/api/paper-live/runs/{run_id}`, `/api/paper-live/status`, `/api/observations`, `/api/sources`, `/api/official/observations`, `/api/fusion/summary`, `/api/market-snapshots`, `/api/model-runs`, `/api/model-spread`, `/api/model/adapters`, `/api/settlement/replays`, `/api/market/verification`, `/api/collector/health`, `/api/weather/features`, `/api/nowcast/signals`, `/api/calibration/summary`, and `/api/backfill/reports`.

The dashboard surfaces observations, source/provenance context, station metadata, official observations, daily high, model runs/spread/deltas, market snapshots, settlement replay summaries, market-rule verification, collector health, marine/cloud/nowcast features, calibration/backfill summaries, paper-live status, events, fusion/risk-guard notes, access posture, and ops posture. It is intended for loopback or carefully reviewed private access, not public exposure.

## Testing and validation status

Current local validation run: `PYTHONPATH=src python -m pytest tests -q` passed with **95 tests** on 2026-07-14.

Covered areas include repository flows, ingestion normalization, collector behavior with injected fetchers, official source/station metadata, market-rule verification, settlement replay, model adapters and deltas, model spread/probability utilities, weather/cloud/nowcast feature extraction, backfill/calibration scaffolding, paper-live helpers, env-token access gating, ops helpers, CLI smoke paths, FastAPI endpoints, dashboard rendering, and script syntax checks. These tests do not prove live-network reliability, live Kalshi ingestion, data-license compliance, production scheduling, operational soak, production-grade authorization/deployment, or out-of-sample probability calibration.

## Current boundary and caveats

Use this project as local research support and recordkeeping only. Do not present outputs as financial advice, guaranteed arbitrage, automated betting instructions, or a calibrated production trading signal. Market settlement source, station/product, timezone, cutoff, units, rounding, fallback, and correction behavior must be verified for each contract by the user or another trusted review process. Forecast/model/market probability comparisons must account for stale data, source mismatch, fees, spread, liquidity, slippage, and human/compliance review.

Unresolved external dependencies remain: real market-specific rule verification by the user, live Kalshi credentials/feed permissions, paid ECMWF/GraphCast licensing, actual satellite image processing, real long-running paper-live soak, sufficient historical backfill data, proven calibrated model performance, compliance/legal review, and production-grade auth/deployment.

For future work and unresolved gaps, see [shortcomings-and-roadmap.md](shortcomings-and-roadmap.md).
