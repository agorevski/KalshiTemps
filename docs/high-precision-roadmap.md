# High-Precision Seattle Temperature Signal Roadmap

This roadmap is for maximizing the accuracy and precision of Seattle daily high-temperature signals in a research-only workflow. It must not be read as financial advice, compliance approval, arbitrage guidance, or support for automated trading.

## Operating principles

- Verify the settlement source before trusting any signal.
- Preserve raw records, hashes, timestamps, station metadata, normalization assumptions, and derived features so every result can be replayed.
- Prefer official NOAA/NWS and verified station observations over convenience feeds.
- Treat disagreement, latency, missingness, source mismatch, and model spread as first-class uncertainty signals.
- Produce calibrated probability distributions by market bucket, not only a point forecast.
- Run real paper-live and operational soak before any trading-adjacent use.

## Status summary

In-repository foundations are now implemented for settlement replay, official source and station metadata, model adapters, marine/cloud nowcast records, backfill/calibration records, paper-live tracking, optional token-gated local access, and dashboard/API integration. The remaining acceptance criteria still require external dependencies: user-verified market-specific rules, live Kalshi credentials/feed permissions, paid ECMWF/GraphCast licensing, actual satellite image processing, sufficient historical backfill, proven calibrated model performance, long-running paper-live soak, compliance/legal review, and production-grade auth/deployment.

## Ordered roadmap

### P0: Settlement-source verification and official reconciliation — foundation implemented; real rules still external

Goal: make every market outcome replayable and auditable before building signal confidence.

Implemented foundations:

- `market_rules` stores ticker, rule text, source, station/product, units, rounding, cutoff, fallback, correction policy, reviewer, and verification status.
- `official_outcomes` and `settlement_replays` store official outcomes, replay status, normalized/rounded values, mismatch reasons, correction/fallback flags, payload hashes, and rule-version context.
- CLI/API support exists through `record-official-outcome`, `replay-settlement`, `/api/settlement/replays`, and `/api/market/verification`.

Still required:

1. The user or trusted reviewer must verify each real market's exact official rule text from market terms.
2. Maintain an exception log for ambiguous rule text, late corrections, fallback use, outages, and manual review decisions.
3. Build enough real replay history to prove zero reconciliation errors for verified markets, excluding documented official corrections.

Acceptance criteria not yet proven:

- 100% of paper-live markets have verified rule records before analysis is labeled actionable.
- Official outcome replay from raw payload plus rule metadata exactly reproduces the settlement bucket.
- Reconciliation error rate is zero for verified markets, excluding documented official corrections.

### P1: Station metadata, KSEA discipline, QC, latency, rounding, and cutoff correctness — foundation implemented; verification depth pending

Implemented foundations:

- `station_metadata` and `official_observations` persist station class, network, location/elevation, source class, metadata hash, official observation fields, QC status/report, provenance hash, and source poll links.
- CLI/API support exists through `import-stations`, `list-stations`, `collect-nws-observation`, `import-climate-daily-summaries`, `list-official-observations`, and `/api/official/observations`.
- Basic deterministic validators and collector health summaries track freshness, plausible ranges, duplicates, stale records, and poll latency.

Still required:

- Treat KSEA or any other station as authoritative only when the market rule explicitly verifies it.
- Add source-specific official QC flags, station-change histories, richer same-time source consistency checks, and comprehensive DST/cutoff/rounding tests for every verified rule family.
- Track station mismatch, missingness, stale-record rates, and latency percentiles on real feeds over time.

### P2: Official NOAA/NWS collectors and nearby ASOS/AWOS network — foundation implemented; production operation pending

Implemented foundations:

- Public NWS discussion, Aviation Weather METAR, and api.weather.gov station observation collectors can run as explicit one-shot commands with poll records, payload hashes, and health summaries.
- Station metadata imports support KSEA/proxy network context.

Still required:

- Production scheduling, retries/backoff, monitoring, alerting, broad fixture replay, and nearby ASOS/AWOS coverage depth.
- Confirmation that the collected product is the verified settlement product for each market.
- PWS data must remain out of primary models unless independently calibrated and quality controlled.

### P3: Forecast-model ingestion and forecast-hour alignment — adapter foundation implemented; licensed/production feeds pending

Implemented foundations:

- `model_adapters.py`, `import-model-forecasts`, and `fetch-model-forecasts` normalize supported JSON/CSV/URL payloads for HRRR/NAM/GFS/NBM-style records.
- `model_runs`, `model_run_extractions`, `model_run_deltas`, `model_probability_buckets`, and `model_spread` persist run/valid/extraction metadata, run-to-run deltas, bucket probabilities, and spread.
- `/api/model/adapters` exposes model run metadata and deltas.

Still required:

- Production-grade HRRR/NAM/GFS/NBM feed contracts and source-specific parsers.
- Paid ECMWF/GraphCast access, licenses, and storage terms before those feeds are used.
- Forecast-hour skill reports by model, lead time, snapshot hour, season, and regime on real backfill.

### P4: Seattle-specific marine layer, clouds, fog/stratus, wind shift, and solar features — manual/proxy foundation implemented; actual satellite processing pending

Implemented foundations:

- Forecast-discussion regime extraction, `marine_layer_indicators`, `cloud_features`, and nowcast fields can persist marine/cloud, ceiling, fog/stratus, wind shift, solar proxy, burn-off, and confidence context.
- `import-cloud-features`, `list-cloud-features`, `/api/nowcast/signals`, and dashboard panels expose these signals.

Still required:

- Actual satellite image processing for quantitative morning cloud extent, stratus edge, clearing velocity, and burn-off timing.
- Verified solar inputs and enough data to evaluate MAE/bucket error by marine-layer, persistent-stratus, offshore-flow, heat, and ordinary regimes.

### P5: Intraday nowcasting snapshots at 7, 9, 11, and noon — foundation implemented; performance unproven

Implemented foundations:

- `generate-nowcast-snapshots` creates fixed-hour evidence-only snapshots from stored observations.
- `nowcast_snapshots` stores current temperature, intraday max, warming rate, dew point, wind, pressure, ceiling, visibility, solar proxy, cloud/ceiling trend, marine-push indicator, remaining-solar-window proxy, remaining-upside distribution, and data status.
- `/api/nowcast/signals` and dashboard panels expose nowcast records.

Still required:

- Real scheduled snapshot capture, source completeness reporting by hour, and performance metrics by snapshot hour and regime.
- Demonstrated Brier/log-loss improvement or documented non-improvement versus persistence/climatology baselines.

### P6: Historical backfill and conditional model bias — pipeline foundation implemented; sufficient data missing

Implemented foundations:

- `run-backfill` replays frozen JSON/CSV fixture bundles into SQLite and records `backfill_runs` summaries.
- `compute-calibration` supports split-date/gap parameters; `calibration-report` exports JSON reports.
- Bias and bucket calibration tables can be computed from stored outcomes and prediction snapshots.

Still required:

- Sufficient real historical backfill across observations, model runs, forecast discussions, market prices, official outcomes, and regimes.
- Strict train/validation/test splits by date, leakage checks, sample-size thresholds, confidence intervals, holdout metrics, and disabled/downgraded bias corrections when data are sparse.

### P7: Calibrated probabilistic bucket models and reliability metrics — metrics foundation implemented; calibration not proven

Implemented foundations:

- Local Brier/reliability-bin scaffolding exists for stored prediction snapshots and outcomes.
- Dashboard/API surfaces calibration summaries and backfill reports.

Still required:

- Clean history, transparent baselines, and out-of-sample reliability curves, expected calibration error, Brier score, log loss, sharpness, and coverage by snapshot hour/regime/season/lead time.
- Market-implied probabilities must remain comparison inputs only when fresh, liquid enough, and clearly timestamped.

### P8: Paper-live shadow mode and operational soak — tracking foundation implemented; real soak not complete

Implemented foundations:

- `paper_live_runs`, checklist entries, prediction notes, reconciliation/postmortem notes, and soak metrics are persisted.
- CLI/API support exists through `start-paper-live-run`, `list-paper-live-runs`, `close-paper-live-run`, `record-paper-live-checklist`, `record-paper-live-prediction-note`, `record-paper-live-postmortem`, `record-paper-live-soak-metric`, `/api/paper-live/status`, and `/api/paper-live/runs`.
- Ops helpers summarize paper-live readiness and explicitly keep automated betting disabled.

Still required:

- Multi-week shadow mode with no betting, no order entry, daily reconciliation, uptime/source-latency/missingness/retry/backup/restore/alert review, and postmortems.
- Any trading-adjacent use requires separate human, legal, compliance, credential, risk-limit, and security review.

## Required metrics dashboard

Track these metrics at minimum:

- **Accuracy**: MAE by snapshot hour, forecast hour, source, station, season, and weather regime.
- **Probabilistic quality**: bucket Brier score, log loss, reliability curves, expected calibration error, sharpness, and coverage.
- **Official reconciliation**: settlement replay success rate, reconciliation error rate, correction frequency, fallback frequency, and bucket-boundary discrepancies.
- **Source health**: latency p50/p90/p99, missingness, stale-record rate, parse-failure rate, retry count, and source outage duration.
- **Station discipline**: station mismatch frequency, proxy divergence, QC rejection rate, metadata-change incidents, and PWS exclusion/calibration status.
- **Operational readiness**: paper-live completion days, backup/restore success, dashboard uptime, collector success rate, and alert noise.

## What not to do

- Do not average away disagreement; model spread and source divergence are uncertainty signals.
- Do not trust PWS data without station-level calibration, metadata, QC, and stable history.
- Do not use stale market prices or treat market prices as truth.
- Do not automate betting, order entry, or execution from this research workflow.
- Do not label a station as official because it is convenient, familiar, or usually close.
- Do not mix demo, manual-live, replay, paper-live, and production-live rows without visible provenance.
- Do not claim arbitrage or guaranteed edge from early readings, model gaps, or delayed official updates.

## Financial, legal, and compliance caveats

Kalshi markets are regulated financial products. Users must follow Kalshi terms, market rules, data-provider licenses, account permissions, organizational policy, and applicable law. This project supports research, auditability, and recordkeeping only; it is not financial advice, compliance approval, guaranteed arbitrage, or a trading system. Any future trading-adjacent use requires explicit human review, legal/compliance approval, credential controls, risk limits, kill switches, audit logs, and security review.
