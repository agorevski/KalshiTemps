# Implementation Design

This document describes the implementation architecture for Kalshi Temps. It distinguishes the validated local research scaffold now present from the production, live-feed, licensed-data, historical-depth, compliance, and deployment work that remains. It is not trading advice, does not imply guaranteed arbitrage, and assumes human review before any betting-adjacent interpretation.

## Goals and operating principles

Kalshi Temps should help research current-day Seattle high-temperature markets by preserving raw evidence, deriving auditable signals, and comparing a research probability distribution with market-implied distributions. The system should make uncertainty visible instead of hiding it.

Core principles:

- Verify the exact settlement source, station, product, local day, rounding, correction, and fallback rule before marking a market actionable.
- Treat any Weather Underground/KSEA settlement claim as unverified until confirmed in the specific market rules.
- Keep raw observations, model outputs, market snapshots, official outcomes, settlement replays, and derived probabilities separate.
- Preserve provenance, timestamps, stale-data status, and raw payload references for auditability.
- Emphasize model disagreement, marine/cloud timing, station verification, historical bias, intraday nowcasting, and market-implied distributions.
- Do not automate betting by default; the workflow is research display plus manual review.

## Six-layer product architecture

The application now exposes foundations for a six-layer data-fusion workflow, with production depth still pending:

1. **Raw model disagreement**: store HRRR, NAM, GFS, NBM, ECMWF where licensed, GraphCast where licensed/validated, and other guidance as separate model runs. Compute spread and disagreement explicitly; wide spread should reduce confidence and trigger review.
2. **Marine/cloud timing**: track morning stratus, cloud ceiling, cloud-feature proxy records, wind shift, dew point, pressure, solar proxy, and whether marine clouds cleared before 10 AM. Seattle highs can hinge on burn-off timing.
3. **KSEA and surrounding observations**: prioritize the verified settlement station, but track KSEA, ASOS/AWOS/METAR, official NOAA/NWS observations, station metadata, and calibrated proxy stations with source-quality labels.
4. **Historical conditional bias**: compare model predictions with verified actual highs by station, model, season, lead time, and regime tags such as marine layer, offshore flow, heat wave, and persistent clouds.
5. **Intraday nowcasting**: produce fixed 7 AM, 9 AM, 11 AM, noon, and latest snapshots that estimate remaining high-temperature upside risk using observations, warming rate, cloud evolution, and source freshness.
6. **Market-implied probabilities**: convert bid/ask/last/mid prices into bucket probabilities and compare them with the research distribution without treating the market as truth.

## Implementation status

The current repository has passed full local validation: 119 tests, Python compile checks, script syntax checks, CLI smoke checks, and FastAPI endpoint smoke checks. Implemented foundations include:

- SQLite/FastAPI dashboard and read-only APIs for the main research workflow.
- Market-rule metadata capture, verification records, and deterministic settlement replay against official outcomes.
- Public no-secret NWS discussion, Aviation Weather METAR, and api.weather.gov station observation collector foundations with poll records and health summaries.
- Official station metadata and climate daily-summary import foundations.
- Manual/model-adapter forecast ingestion, model spread, run-to-run deltas, extraction metadata, market snapshot normalization, and probability comparison utilities.
- Deterministic weather-regime, cloud-feature, intraday, and nowcast signal foundations.
- Frozen-fixture backfill orchestration, official outcome records, prediction snapshots, bias summaries, split-aware calibration reports, and bucket calibration metric scaffolding.
- Paper-live no-betting run tracking, checklists, prediction notes, reconciliation/postmortem notes, soak metrics, and readiness/status summaries.
- Optional local env-token gate for dashboard and API paths, plus local ops posture checks for database, disk, backup path, loopback-first access, and dashboard caveats.

Remaining design risks include user verification of real market rules, live Kalshi credentials and feed permissions, paid/licensed ECMWF or GraphCast access, actual satellite image processing, real historical backfill depth, proven calibrated model performance, long-running paper-live soak, compliance/legal review, production-grade auth/deployment, and the deliberate absence of automated trading.

## Runtime components

### FastAPI app

The FastAPI process is the local application shell. It owns request routing, lightweight API serialization, dashboard rendering, health checks, optional token gating, and startup database initialization.

Current responsibilities:

- Initialize SQLite on startup.
- Serve the dashboard for the human-facing research workflow.
- Serve read-only JSON endpoints for observations, sources, official observations/station metadata, fusion summary, model runs/spread/adapters, settlement replays, market snapshots, market verification, collector health, weather/nowcast features, calibration/backfill summaries, paper-live status, and local ops status.
- Apply `KALSHI_TEMPS_ACCESS_TOKEN` protection to dashboard and API paths when configured.
- Keep request handlers thin: validate query parameters, open a database connection, call repository/service objects, and render responses.
- Avoid embedding data-ingestion or forecasting logic directly in route functions.

### SQLite persistence

SQLite is the local source of truth for development and single-user operation. It stores append-friendly evidence and derived records with enough metadata to reproduce a daily research conclusion.

Design expectations:

- Use one database file under `data/` by default.
- Enable foreign keys per connection.
- Use UTC timestamps for canonical storage where possible, plus local-market timestamps when local-day settlement matters.
- Keep raw payload text or raw payload hashes for reproducibility.
- Prefer append-only derived records over destructive updates for hypotheses, source polls, settlement replays, paper-live notes, and official-result reconciliation.
- Add indexes around target date, market ticker, station, observed time, captured time, and model run time as tables grow.

### Repository boundary

Repository classes should be the only layer that executes SQL directly. Current repository methods cover:

- Upsert/list data sources.
- Add/list observations, official observations, station metadata, and forecast discussions.
- Add/list collector poll runs and collector health summaries.
- Add/list market-rule verification records and settlement replays.
- Add/list model runs, extraction metadata, run deltas, probability buckets, and model spread.
- Add/list marine-layer indicators, cloud features, weather-regime features, intraday features, and nowcast snapshots.
- Add/list market snapshots and bucket probability comparisons.
- Add/list official outcomes, prediction snapshots, backfill runs, bias summaries, calibration metrics, risk guards, paper-live records, and app events.

Repositories should return plain dictionaries or typed records and should not perform business scoring beyond small query projections.

### Service and domain boundary

Domain modules hold implementation logic that combines records or applies rules. Current foundations include:

- `market_rules`: checks rule completeness, verification state, and non-actionability when required settlement fields are missing.
- `settlement`: replays official outcomes against verified rule metadata, including normalization, rounding, correction/fallback flags, and mismatch reasons.
- `official_sources`: normalizes station metadata, public station observations, and climate daily-summary fixtures.
- `ingest`: normalizes public weather text, METAR-like observations, model-high records, market snapshots, provenance hashes, and collected payload metadata.
- `model_adapters`: loads/fetches JSON/CSV model forecast payloads into normalized model-run records with extraction metadata.
- `fusion`: computes model spread, freshness, risk guards, implied probabilities, and bucket deltas.
- `weather_features` and `nowcast`: extract deterministic forecast-discussion regime features, cloud features, and fixed-hour nowcast records.
- `backfill`: replays frozen fixture bundles into local SQLite and records run summaries.
- `calibration`: computes historical bias summaries and bucket calibration metrics from stored local outcomes and snapshots.
- `paper_live`: manages no-betting paper-live runs and notes.
- `auth` and `ops`: provide optional local access gating, database/disk/access posture, and paper-live readiness helpers.

Future service work should add scheduler-safe orchestration, permitted live Kalshi ingestion, licensed model ingestion, actual satellite processing, stronger QC, production-grade auth/deployment, and monitored operations.

## Collector and ingestion jobs

Ingestion starts as explicit CLI commands and may later move to scheduled jobs. Current commands can collect public NWS discussion, Aviation Weather METAR records, and api.weather.gov station observations; run collectors once with poll records; import station metadata, official observations, model highs/forecasts, and cloud features; extract weather features; generate nowcast snapshots; manage market rules; replay settlement; run backfill; record outcomes and prediction snapshots; compute/export calibration summaries; manage paper-live runs; and inspect collector/ops status.

Production-grade jobs still needed:

- **Market rules job**: keep ticker metadata, settlement text, source, station, time zone, cutoff, fallback, correction policy, reviewer, and verification status current after user/trusted review.
- **Observation job**: poll verified settlement station, KSEA, ASOS/METAR, NOAA/NWS products, and calibrated surrounding stations with source-specific QC.
- **Marine/cloud job**: process actual satellite/cloud imagery plus cloud ceilings, fog/stratus notes, wind shifts, and 8-10 AM burn-off signals.
- **Model guidance job**: ingest HRRR/NAM/GFS/NBM and, only when licensed, ECMWF/GraphCast-style guidance with run cycles and bucket probabilities.
- **Market snapshot job**: capture permitted Kalshi metadata/order-book/price snapshots and convert to implied bucket probabilities.
- **Official result job**: ingest the authoritative high after release and reconcile hypotheses, model error, settlement replays, and historical bias.

Every job should be idempotent where natural keys exist, store provenance, and write clear stale/error events when a source fails.

## Data-fusion utilities

Data-fusion utilities are deterministic and auditable before any ML layer is introduced. Current foundations include:

- Bucket and price-to-probability helpers using bid/ask/mid with explicit caveats for spread and liquidity.
- Model spread and run-to-run delta calculations.
- Source freshness checks, validation statuses, and latency calculations.
- Distribution comparison between research probabilities and market-implied probabilities.
- Rule-verification, settlement-replay, and risk-guard outputs for unverified markets, stale data, source mismatch, and wide model spread.
- Deterministic regime, cloud, intraday, and nowcast feature extraction.
- Historical bias and bucket calibration summaries from stored outcomes and prediction snapshots.

Future ML should begin with transparent baselines and only move to calibrated gradient-boosted models once historical data are clean and sufficient. Output should be bucket probabilities with calibration diagnostics, not opaque trade instructions.

## Dashboard information architecture

The dashboard is organized around decisions a human researcher needs to audit quickly:

1. **Safety and verification banner**: settlement source, KSEA/Weather Underground status, rule verification, token/access posture, stale-data warnings, and automated-betting disabled status.
2. **Today summary**: current estimated high range, latest observed high, current bucket probabilities, confidence label, and last update time.
3. **Layer 1 model disagreement**: latest model runs, run cycles, extraction metadata, predicted highs, probability buckets, run deltas, and spread.
4. **Layer 2 marine/cloud layer**: cloud/fog trend, ceiling, satellite-proxy notes, burn-off-before-10-AM flag, and marine-push indicators.
5. **Layer 3 observations**: verified settlement station first, KSEA next, then surrounding stations with metadata, QC, and latency.
6. **Layer 4 historical bias/backfill**: regime-specific model errors, sample size, recency, calibration summaries, and backfill reports.
7. **Layer 5 intraday nowcast**: snapshot timeline, warming rate, max so far, remaining-upside estimate, and stale flags.
8. **Layer 6 market comparison**: market-implied distribution by bucket, research distribution, difference, liquidity/spread caveats, and no-arbitrage guarantee caveat.
9. **Settlement and paper-live audit**: settlement replays, source polls, errors, manual notes, risk checks, official-result reconciliation, paper-live runs, and soak notes.

The dashboard should distinguish demo, manual-live, replay/paper-live, future production-live, and derived signals. It should never present an actionable recommendation without explicit risk-control context, and automated trading remains disabled.

## Tailscale and access posture

Default app binding should remain loopback-only, for example `127.0.0.1:8000`. Remote access should prefer private Tailscale SSH forwarding instead of public binding.

Recommended posture:

- Run FastAPI on loopback unless a deliberate deployment change is made.
- Use `KALSHI_TEMPS_ACCESS_TOKEN` as a local hardening gate when sharing within a trusted private environment, while recognizing it is not production-grade auth.
- Use Tailscale SSH port forwarding for private access.
- Avoid Tailscale Funnel or public exposure by default.
- If Tailscale Serve is considered, review authentication, authorization, logs, credentials, market data sensitivity, and dashboard content first.
- Do not expose API keys, account identifiers, private exports, or betting controls through the dashboard.

## Phased build roadmap

Phases 0-4 local precision foundations are substantially implemented and validated. Later phases remain constrained by user-verified market rules, live Kalshi permissions, licensed feeds, actual satellite processing, historical depth, calibration proof, long-running soak, compliance review, and production-grade auth/deployment.

### Phase 0: Documentation and baseline skeleton — implemented

- Document architecture and schema intent.
- Keep the FastAPI, SQLite, repository, seed, and dashboard skeleton working.
- Use demo data only for display development.

### Phase 1: Persistence hardening — implemented foundation

- Market metadata/rule records, settlement replays, station metadata, source polls, collector health, paper-live records, and audit-friendly events exist.
- Source freshness, verification statuses, model spread/deltas, features, outcomes, snapshots, backfill runs, and calibration scaffolding are persisted.
- Lightweight schema initialization/migration helpers exist, but production migrations and restore drills remain future work.

### Phase 2: Ingestion foundations — implemented foundation

- Manual CLI ingestion exists for public NWS/METAR/NWS-observation collectors, station metadata, official observations, model-high/forecast imports, market-rule records, outcomes, prediction snapshots, cloud/nowcast/weather features, backfill, paper-live notes, and calibration summaries.
- Normalization preserves timestamps, station IDs, source URLs, payload hashes, extraction metadata, and provenance metadata where supported.
- Failed polls and stale sources can be recorded, but production scheduling, monitoring, retries, Kalshi live feeds, licensed models, and actual satellite processing remain future work.

### Phase 3: Derived precision signals — implemented foundation

- Settlement replay, model spread/deltas, probability buckets, deterministic regime/cloud/intraday/nowcast features, market-implied distributions, and calibration scaffolding are present.
- Risk checks and market-rule verification can block actionability when settlement source is unverified or data quality is insufficient.
- These signals are not yet calibrated on sufficient real history.

### Phase 4: Dashboard/API refinement — implemented foundation

- The dashboard and APIs surface the main research workflow sections, including station metadata, settlement replay, verification, collectors, model adapters, weather/nowcast features, calibration/backfill, paper-live status, market comparison, ops posture, and audit events.
- Further filters, drill-down pages, report exports, and stronger demo/manual-live/replay/paper-live/production-live labels remain useful improvements.
- Uncertainty, stale data, no-automated-trading, no-guaranteed-arbitrage, and model disagreement should remain prominent.

### Phase 5: Historical bias and calibrated performance — pipeline implemented, data depth missing

- Official results, prediction snapshots, and backfill run records can be stored.
- Bias and bucket calibration summaries can be computed/exported from stored records.
- Real historical backfill, sufficient sample sizes, holdout evaluation, and recurring-bias analysis remain required.

### Phase 6: Production access, compliance, and optional trading controls — future only

- Replace local token gating with production-grade auth/deployment only after a deployment goal is approved.
- Train transparent calibrated models only after historical data are clean and sufficient.
- Keep outputs probabilistic and auditable.
- Complete compliance/legal review before any trading-adjacent use.
- Automated trading is not implemented and should require explicit human approval, separate risk-control implementation, credential controls, kill switches, audit logs, and monitored operations before it is even considered.
