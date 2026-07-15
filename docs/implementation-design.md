# Implementation Design

This document describes the implementation architecture for Kalshi Temps. It distinguishes the validated local research scaffold now present from the production, authentication, licensed-feed, historical-depth, compliance, and trading-control work that remains. It is not trading advice, does not imply guaranteed arbitrage, and assumes human review before any betting-adjacent interpretation.

## Goals and operating principles

Kalshi Temps should help research current-day Seattle high-temperature markets by preserving raw evidence, deriving auditable signals, and comparing a research probability distribution with market-implied distributions. The system should make uncertainty visible instead of hiding it.

Core principles:

- Verify the exact settlement source, station, product, local day, rounding, correction, and fallback rule before marking a market actionable.
- Treat any Weather Underground/KSEA settlement claim as unverified until confirmed in the specific market rules.
- Keep raw observations, model outputs, market snapshots, and derived probabilities separate.
- Preserve provenance, timestamps, stale-data status, and raw payload references for auditability.
- Emphasize model disagreement, marine-layer timing, KSEA verification, historical bias, intraday nowcasting, and market-implied distributions.
- Do not automate betting by default; the default workflow is research display plus manual review.

## Six-layer product architecture

The application now exposes foundations for a six-layer data-fusion workflow, with production depth still pending:

1. **Raw model disagreement**: store HRRR, NAM, GFS, ECMWF where licensed, NBM, and other guidance as separate model runs. Compute spread and disagreement explicitly; wide spread should reduce confidence and trigger review.
2. **Marine-layer timing**: track morning stratus, cloud ceiling, satellite trend, wind shift, dew point, pressure, solar radiation, and whether marine clouds cleared before 10 AM. Seattle highs can hinge on burn-off timing.
3. **KSEA and surrounding observations**: prioritize the verified settlement station, but track KSEA, ASOS/AWOS/METAR, official NOAA/NWS observations, and calibrated proxy stations with source-quality labels.
4. **Historical conditional bias**: compare model predictions with verified actual highs by station, model, season, lead time, and regime tags such as marine layer, offshore flow, heat wave, and persistent clouds.
5. **Intraday nowcasting**: produce 7 AM, 9 AM, 11 AM, and latest snapshots that estimate remaining high-temperature upside risk using observations, warming rate, cloud evolution, and prior-day error.
6. **Market-implied probabilities**: convert bid/ask/last/mid prices into bucket probabilities and compare them with the research distribution without treating the market as truth.

## Implementation status

The current repository has passed full local validation: 67 tests, Python compile checks, script syntax checks, CLI smoke checks, and FastAPI endpoint smoke checks. Implemented foundations include:

- SQLite/FastAPI dashboard and read-only APIs for the main research workflow.
- Market-rule metadata capture and verification records.
- Public no-secret NWS discussion and Aviation Weather METAR collector foundations with poll records and health summaries.
- Manual model-high ingestion, model spread, market snapshot normalization, and probability comparison utilities.
- Deterministic weather-regime and intraday feature extraction foundations.
- Official outcome, prediction snapshot, bias summary, and calibration metric scaffolding.
- Local ops posture checks for database, disk, backup path, and loopback-first access guidance.

Remaining design risks include real live operational soak, authenticated dashboard/access control, live Kalshi credentials and permissions, paid/licensed ECMWF or GraphCast access, satellite image processing, real historical backfill depth, model calibration on sufficient data, compliance/legal review, and the deliberate absence of automated trading.

## Runtime components

### FastAPI app

The FastAPI process is the local application shell. It should own request routing, lightweight API serialization, dashboard rendering, health checks, and startup database initialization.

Current responsibilities:

- Initialize SQLite on startup.
- Serve `/` as a redirect and `/dashboard` for the human-facing research dashboard.
- Serve read-only JSON endpoints for observations, sources, fusion summary, model runs/spread, market snapshots, market verification, collector health, weather features, calibration summaries, and local ops status (`/api/ops/status`).
- Keep request handlers thin: validate query parameters, open a database connection, call repository/service objects, and render responses.
- Avoid embedding data-ingestion or forecasting logic directly in route functions.

### SQLite persistence

SQLite is the local source of truth for development and single-user operation. It should store append-friendly evidence and derived records with enough metadata to reproduce a daily research conclusion.

Design expectations:

- Use one database file under `data/` by default.
- Enable foreign keys per connection.
- Use UTC timestamps for canonical storage where possible, plus local-market timestamps when local-day settlement matters.
- Keep raw payload text or raw payload hashes for reproducibility.
- Prefer append-only derived records over destructive updates for hypotheses, source polls, risk checks, and official-result reconciliation.
- Add indexes around target date, market ticker, station, observed time, captured time, and model run time as tables grow.

### Repository boundary

Repository classes should be the only layer that executes SQL directly. Current repository methods cover:

- Upsert/list data sources.
- Add/list observations and forecast discussions.
- Add/list collector poll runs and collector health summaries.
- Add/list market-rule verification records.
- Add/list model runs, probability buckets, and model spread.
- Add/list marine-layer indicators, weather-regime features, and intraday features.
- Add/list market snapshots and bucket probability comparisons.
- Add/list official outcomes, prediction snapshots, bias summaries, calibration metrics, risk guards, and app events.

Repositories should return plain dictionaries or typed records and should not perform business scoring beyond small query projections.

### Service and domain boundary

Domain modules hold implementation logic that combines records or applies rules. Current foundations include:

- `market_rules`: checks rule completeness, verification state, and non-actionability when required settlement fields are missing.
- `ingest`: normalizes public weather text, METAR-like observations, model-high records, market snapshots, provenance hashes, and collected payload metadata.
- `fusion`: computes model spread, freshness, risk guards, implied probabilities, and bucket deltas.
- `weather_features`: extracts deterministic forecast-discussion regime features and intraday feature records.
- `calibration`: computes historical bias summaries and bucket calibration metrics from stored local outcomes and snapshots.
- `ops`: reports local database, disk, backup-path, and access-posture status.

Future service work should add scheduler-safe orchestration, live Kalshi ingestion, licensed model ingestion, satellite processing, stronger QC, authenticated access, and monitored operations.

## Collector and ingestion jobs

Ingestion starts as explicit CLI commands and should later move to scheduled jobs. Current commands can collect public NWS discussion and Aviation Weather METAR records, run both collectors once with poll records, import manual model highs, extract weather features, manage market rules, record outcomes and prediction snapshots, compute calibration summaries, and inspect collector/ops status.

Production-grade jobs still needed:

- **Market rules job**: keep ticker metadata, settlement text, source, station, time zone, cutoff, fallback, correction policy, reviewer, and verification status current.
- **Observation job**: poll verified settlement station, KSEA, ASOS/METAR, NOAA/NWS products, and calibrated surrounding stations with source-specific QC.
- **Marine-layer job**: collect satellite/cloud trend fields, cloud ceilings, fog/stratus notes, wind shifts, and 8-10 AM burn-off signals.
- **Model guidance job**: ingest HRRR/NAM/GFS/NBM and, only when licensed, ECMWF/GraphCast-style guidance with run cycles and bucket probabilities.
- **Market snapshot job**: capture permitted Kalshi metadata/order-book/price snapshots and convert to implied bucket probabilities.
- **Official result job**: ingest the authoritative high after release and reconcile hypotheses, model error, and historical bias.

Every job should be idempotent where natural keys exist, store provenance, and write clear stale/error events when a source fails.

## Data-fusion utilities

Data-fusion utilities are deterministic and auditable before any ML layer is introduced. Current foundations include:

- Bucket and price-to-probability helpers using bid/ask/mid with explicit caveats for spread and liquidity.
- Model spread calculation: min, max, mean, count, spread, and model-family notes.
- Source freshness checks, validation statuses, and latency calculations.
- Distribution comparison between research probabilities and market-implied probabilities.
- Rule-verification and risk-guard outputs for unverified markets, stale data, source mismatch, and wide model spread.
- Deterministic regime and intraday feature extraction.
- Historical bias and bucket calibration summaries from stored outcomes and prediction snapshots.

Future ML should begin with transparent baselines and only move to calibrated gradient-boosted models once historical data are clean and sufficient. Output should be bucket probabilities with calibration diagnostics, not opaque trade instructions.

## Dashboard information architecture

The dashboard should be organized around decisions a human researcher needs to audit quickly:

1. **Safety and verification banner**: settlement source, KSEA/Weather Underground status, rule verification, stale-data warnings, and automated-betting disabled status.
2. **Today summary**: current estimated high range, latest observed high, current bucket probabilities, confidence label, and last update time.
3. **Layer 1 model disagreement**: latest model runs, run cycles, predicted highs, probability buckets, and spread.
4. **Layer 2 marine layer**: cloud/fog trend, ceiling, satellite notes, burn-off-before-10-AM flag, and marine-push indicators.
5. **Layer 3 observations**: verified settlement station first, KSEA next, then surrounding stations with QC and latency.
6. **Layer 4 historical bias**: regime-specific model errors, sample size, recency, and impact on today’s distribution.
7. **Layer 5 intraday nowcast**: snapshot timeline, warming rate, max so far, remaining-upside estimate, and stale flags.
8. **Layer 6 market comparison**: market-implied distribution by bucket, research distribution, difference, liquidity/spread caveats, and no-arbitrage guarantee caveat.
9. **Audit/events**: source polls, errors, manual notes, risk checks, and official-result reconciliation.

The dashboard should distinguish demo, manual-live, replay/paper-live, future production-live, and derived signals. It should never present an actionable recommendation without explicit risk-control context, and automated trading remains disabled.

## Tailscale access posture

Default app binding should remain loopback-only, for example `127.0.0.1:8000`. Remote access should prefer private Tailscale SSH forwarding instead of public binding.

Recommended posture:

- Run FastAPI on loopback unless a deliberate deployment change is made.
- Use Tailscale SSH port forwarding for private access.
- Avoid Tailscale Funnel or public exposure by default.
- If Tailscale Serve is considered, review authentication, authorization, logs, credentials, market data sensitivity, and dashboard content first.
- Do not expose API keys, account identifiers, private exports, or betting controls through the dashboard.

## Phased build roadmap

Phases 0-1 local foundations are substantially implemented and validated. Later phases remain constrained by live operational soak, access control, licensed feeds, satellite processing, historical depth, calibration, and compliance review.

### Phase 0: Documentation and baseline skeleton — implemented

- Document architecture and schema intent.
- Keep the FastAPI, SQLite, repository, seed, and dashboard skeleton working.
- Use demo data only for display development.

### Phase 1: Persistence hardening — implemented foundation

- Market metadata/rule records, source polls, collector health, and audit-friendly events exist.
- Source freshness, verification statuses, model spread, features, outcomes, snapshots, and calibration scaffolding are persisted.
- Lightweight schema initialization/migration helpers exist, but production migrations and restore drills remain future work.

### Phase 2: Ingestion foundations — partially implemented

- Manual CLI ingestion exists for public NWS/METAR collectors, model-high imports, market-rule records, outcomes, prediction snapshots, weather features, and calibration summaries.
- Normalization preserves timestamps, station IDs, source URLs, payload hashes, and provenance metadata where supported.
- Failed polls and stale sources can be recorded, but production scheduling, monitoring, retries, Kalshi live feeds, licensed models, and satellite processing remain future work.

### Phase 3: Derived signals — implemented foundation

- Model spread, probability buckets, deterministic regime features, intraday features, market-implied distributions, and calibration scaffolding are present.
- Risk checks and market-rule verification can block actionability when settlement source is unverified or data quality is insufficient.
- These signals are not yet calibrated on sufficient real history.

### Phase 4: Dashboard refinement — implemented foundation

- The dashboard surfaces the main research workflow sections, including verification, collectors, model spread, weather features, calibration scaffolding, market comparison, ops posture, and audit events.
- Further filters, drill-down pages, report exports, and stronger demo/manual-live/replay/paper-live/production-live labels remain useful improvements.
- Uncertainty, stale data, no-automated-trading, and model disagreement should remain prominent.

### Phase 5: Historical bias and backtesting — scaffolding implemented, data depth missing

- Official results and prediction snapshots can be stored.
- Bias and bucket calibration summaries can be computed from stored records.
- Real historical backfill, sufficient sample sizes, holdout evaluation, and recurring-bias analysis remain required.

### Phase 6: Optional ML and automation controls — future only

- Train transparent calibrated models only after historical data are clean and sufficient.
- Keep outputs probabilistic and auditable.
- Complete compliance/legal review before any trading-adjacent use.
- Automated trading is not implemented and should require explicit human approval, separate risk-control implementation, credential controls, kill switches, audit logs, and monitored operations before it is even considered.
