# Implementation Design

This document describes the intended implementation architecture for Kalshi Temps. It is practical design guidance for building the app, ingestion pipeline, storage layer, dashboard, and safety posture. It is not trading advice, does not imply guaranteed arbitrage, and assumes human review before any betting action.

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

The application should expose a six-layer data-fusion workflow end to end:

1. **Raw model disagreement**: store HRRR, NAM, GFS, ECMWF where licensed, NBM, and other guidance as separate model runs. Compute spread and disagreement explicitly; wide spread should reduce confidence and trigger review.
2. **Marine-layer timing**: track morning stratus, cloud ceiling, satellite trend, wind shift, dew point, pressure, solar radiation, and whether marine clouds cleared before 10 AM. Seattle highs can hinge on burn-off timing.
3. **KSEA and surrounding observations**: prioritize the verified settlement station, but track KSEA, ASOS/AWOS/METAR, official NOAA/NWS observations, and calibrated proxy stations with source-quality labels.
4. **Historical conditional bias**: compare model predictions with verified actual highs by station, model, season, lead time, and regime tags such as marine layer, offshore flow, heat wave, and persistent clouds.
5. **Intraday nowcasting**: produce 7 AM, 9 AM, 11 AM, and latest snapshots that estimate remaining high-temperature upside risk using observations, warming rate, cloud evolution, and prior-day error.
6. **Market-implied probabilities**: convert bid/ask/last/mid prices into bucket probabilities and compare them with the research distribution without treating the market as truth.

## Runtime components

### FastAPI app

The FastAPI process is the local application shell. It should own request routing, lightweight API serialization, dashboard rendering, health checks, and startup database initialization.

Recommended responsibilities:

- Initialize SQLite on startup.
- Serve `/dashboard` for the human-facing research dashboard.
- Serve read-only JSON endpoints for observations, sources, model spread, market snapshots, events, and future hypothesis summaries.
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

Repository classes should be the only layer that executes SQL directly. They should provide stable methods such as:

- Upsert/list data sources.
- Add/list observations.
- Add/list model runs and probability buckets.
- Calculate or retrieve model spread.
- Add/list marine-layer indicators.
- Add/list market snapshots.
- Add/list events, source polls, hypotheses, and risk checks.

Repositories should return plain dictionaries or typed records and should not perform business scoring beyond small query projections.

### Service boundary

Service modules should hold implementation logic that combines records or applies domain rules. Planned services include:

- `settlement_service`: verifies market rules, station/source assumptions, local day boundaries, and actionability flags.
- `ingestion_service`: normalizes external weather, model, and market payloads before repository writes.
- `fusion_service`: combines model runs, observations, marine-layer indicators, and historical bias into a research distribution.
- `nowcast_service`: creates intraday snapshots and bucket probabilities for the rest of the day.
- `market_service`: converts market prices into implied distributions and spread/latency metadata.
- `risk_service`: blocks or flags outputs when rule verification is missing, data are stale, spread is wide, liquidity is thin, or source assumptions conflict.

Services should be callable from future scheduled jobs, CLI commands, tests, and web routes.

## Future ingestion jobs

Ingestion should start as explicit CLI commands and later move to scheduled jobs. Each job should record source poll metadata and app events.

Planned jobs:

- **Market rules job**: capture ticker metadata, settlement text, source, station, time zone, cutoff, and verification status.
- **Observation job**: poll verified settlement station, KSEA, ASOS/METAR, NOAA/NWS products, and calibrated surrounding stations.
- **Marine-layer job**: collect satellite/cloud trend fields, cloud ceilings, fog/stratus notes, wind shifts, and 8-10 AM burn-off signals.
- **Model guidance job**: ingest model high forecasts, hourly temperatures, run cycles, percentiles, and bucket probabilities.
- **Market snapshot job**: capture Kalshi order book/price snapshots and convert to implied bucket probabilities.
- **Official result job**: ingest the authoritative high after release and reconcile hypotheses, model error, and historical bias.

Every job should be idempotent where natural keys exist, store provenance, and write clear stale/error events when a source fails.

## Data-fusion utilities

Data-fusion utilities should be deterministic and auditable before any ML layer is introduced. Initial utilities should include:

- Bucket parser and bucket-boundary helpers.
- Price-to-probability conversion using bid/ask/mid with explicit caveats for spread and liquidity.
- Model spread calculation: min, max, mean, count, spread, and model-family notes.
- Regime tagging: marine layer, persistent clouds, offshore flow, heat wave, weak mixing, or unknown.
- Bias lookup by model, station, lead time, season, and regime tag.
- Intraday warming-rate and remaining-upside estimators.
- Source freshness checks and latency calculations.
- Distribution comparison between research probabilities and market-implied probabilities.

Future ML should begin with calibrated gradient-boosted models once historical data are clean. Output should be bucket probabilities with calibration diagnostics, not opaque trade instructions.

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

The dashboard should distinguish demo data, live data, and derived signals. It should never present an actionable recommendation without explicit risk-control context.

## Tailscale access posture

Default app binding should remain loopback-only, for example `127.0.0.1:8000`. Remote access should prefer private Tailscale SSH forwarding instead of public binding.

Recommended posture:

- Run FastAPI on loopback unless a deliberate deployment change is made.
- Use Tailscale SSH port forwarding for private access.
- Avoid Tailscale Funnel or public exposure by default.
- If Tailscale Serve is considered, review authentication, authorization, logs, credentials, market data sensitivity, and dashboard content first.
- Do not expose API keys, account identifiers, private exports, or betting controls through the dashboard.

## Phased build roadmap

### Phase 0: Documentation and baseline skeleton

- Document architecture and schema intent.
- Keep the existing FastAPI, SQLite, repository, seed, and dashboard skeleton working.
- Use demo data only for display development.

### Phase 1: Persistence hardening

- Add market metadata, source polls, and audit-friendly events.
- Add explicit source freshness and verification statuses.
- Introduce migrations or versioned schema initialization before data volume grows.

### Phase 2: Ingestion foundations

- Build manual CLI ingestion for observations, model runs, marine indicators, and market snapshots.
- Normalize timestamps, local day, station IDs, and raw payload metadata.
- Record failed polls and stale sources.

### Phase 3: Derived signals

- Implement model spread, probability buckets, marine-layer regime tags, intraday features, and market-implied distributions.
- Add risk checks that block actionability when settlement source is unverified or data quality is insufficient.

### Phase 4: Dashboard refinement

- Rework the dashboard into the nine information sections above.
- Add filters by market/date/source and clear demo/live/derived labels.
- Surface uncertainty, stale data, and model disagreement prominently.

### Phase 5: Historical bias and backtesting

- Store official results and daily prediction snapshots.
- Compute model error by model, lead time, station, and weather regime.
- Backtest bucket probability calibration and identify recurring biases such as HRRR overestimation on late marine-layer days.

### Phase 6: Optional ML and automation controls

- Train transparent calibrated models only after historical data are clean.
- Keep outputs probabilistic and auditable.
- Require explicit human approval and separate risk-control implementation before any trading automation is considered.
