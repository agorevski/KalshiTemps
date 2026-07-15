# High-Precision Seattle Temperature Signal Roadmap

This roadmap is for maximizing the accuracy and precision of Seattle daily high-temperature signals in a research-only workflow. It must not be read as financial advice, compliance approval, arbitrage guidance, or support for automated trading.

## Operating principles

- Verify the settlement source before trusting any signal.
- Preserve raw records, hashes, timestamps, station metadata, normalization assumptions, and derived features so every result can be replayed.
- Prefer official NOAA/NWS and verified station observations over convenience feeds.
- Treat disagreement, latency, missingness, source mismatch, and model spread as first-class uncertainty signals.
- Produce calibrated probability distributions by market bucket, not only a point forecast.
- Run paper-live and operational soak before any trading-adjacent use.

## Ordered roadmap

### P0: Settlement-source verification and official reconciliation

Goal: make every market outcome replayable and auditable before building signal confidence.

1. Record each market's exact rule text, ticker, contract title, expiration, source, station, product, units, rounding method, daily cutoff, time zone, fallback source, correction policy, and reviewer.
2. Classify markets as `not_actionable_pending_rule_verification` until the exact official settlement source is verified from the market terms.
3. Build a replayable official outcome reconciliation pipeline:
   - Store the first published official outcome separately from later corrected outcomes.
   - Link each official outcome to raw source payload or immutable hash.
   - Compare normalized official result to expected market bucket using the recorded settlement rule.
   - Flag source, station, product, rounding, cutoff, and correction mismatches.
4. Maintain an exception log for ambiguous rule text, late corrections, fallback use, outages, and manual review decisions.

Acceptance criteria:

- 100% of paper-live markets have verified rule records before analysis is labeled actionable.
- Official outcome replay from raw payload plus rule metadata exactly reproduces the settlement bucket.
- Reconciliation error rate is zero for verified markets, excluding documented official corrections.

### P1: Station metadata, KSEA discipline, QC, latency, rounding, and cutoff correctness

Goal: prevent station/source drift from overwhelming forecast skill.

1. Treat KSEA or any other station as authoritative only when the market rule explicitly verifies it.
2. Maintain station metadata for KSEA and all proxies: station class, network, latitude/longitude, elevation, water exposure, land-cover context, sensor type where available, operating status, known moves, and maintenance notes.
3. Enforce observation QC before feature generation:
   - Reject impossible ranges, future timestamps, stale records, frozen sensors, duplicate payloads, unit ambiguity, and failed official QC flags.
   - Track ingest time separately from observation valid time.
   - Store source latency for every poll.
4. Implement exact local-day cutoff, DST handling, daily maximum definition, unit conversion, and rounding behavior from the verified rule.
5. Compare same-time KSEA values across NOAA/NWS/METAR/Weather Underground-style displays only as source consistency checks unless one is verified as the settlement product.

Acceptance criteria:

- Station mismatch frequency is tracked daily and reviewed for every settlement-source family.
- Source latency p50/p90/p99 is available by source and station.
- Missingness and stale-record rates are visible by source, station, and hour.
- Rounding/cutoff tests cover local midnight, DST transitions, Fahrenheit/Celsius conversion, and bucket boundaries.

### P2: Official NOAA/NWS collectors and nearby ASOS/AWOS network

Goal: build the observation backbone from trusted public sources before lower-trust context.

1. Productionize official NOAA/NWS climate and observation collectors relevant to the verified settlement product.
2. Collect KSEA plus nearby ASOS/AWOS stations for calibrated proxy context, including but not limited to stations representing Puget Sound, inland warming, marine influence, and regional wind shifts.
3. Store raw payload hashes, normalized rows, source URLs, poll status, retry metadata, and newest observation timestamps.
4. Add collector health dashboards for freshness, latency, missingness, parse errors, source changes, and station availability.
5. Keep PWS data out of primary models unless a station has independent calibration, metadata, QC, and stable history.

Acceptance criteria:

- Official source collectors can replay historical payload fixtures deterministically.
- Nearby station observations include metadata and QC status before they can influence predictions.
- Collector health reports source latency percentiles, missingness, and parse-failure rates.

### P3: Forecast-model ingestion and forecast-hour alignment

Goal: compare guidance precisely instead of mixing incompatible runs and horizons.

1. Ingest HRRR, NAM, GFS, and NBM with run time, valid time, forecast hour, model cycle, product, grid point or station extraction method, and availability timestamp.
2. Align model values to the verified settlement local day and station/proxy target.
3. Store run-to-run deltas for predicted high, hourly temperature path, and bucket probabilities where available.
4. Track forecast-hour-specific skill rather than treating all lead times equally.
5. Preserve model disagreement as a signal: spread, direction of revisions, late-cycle trend, and outlier model flags.

Acceptance criteria:

- Every model feature has run time, valid time, forecast hour, extraction location, and ingest latency.
- MAE is reported by model, forecast hour, hour-of-day snapshot, season, and regime.
- Run-to-run deltas are available for current-day updates and historical evaluation.

### P4: Seattle-specific marine layer, clouds, fog/stratus, wind shift, and solar features

Goal: capture local processes that drive current-day Seattle high-temperature misses.

1. Detect marine layer and Puget Sound fog/stratus regimes from NWS discussions, cloud ceiling, visibility, dew point, pressure, wind, and satellite-derived features.
2. Add visible satellite/cloud features when licensing and implementation are clear:
   - Morning cloud extent over Puget Sound and KSEA.
   - Stratus edge position and burn-off timing.
   - Cloud-clearing velocity and persistence after 9-11 AM.
3. Track wind direction shifts, onshore push, offshore flow, convergence-zone influence, and sea-breeze timing.
4. Add solar radiation or solar proxy features where available, including expected clear-sky radiation versus observed/estimated reduction.
5. Label regimes consistently for historical bias and calibration.

Acceptance criteria:

- Daily regime tags are reproducible from stored inputs.
- MAE and bucket error are reported separately for marine-layer, persistent-stratus, offshore-flow, heat, and ordinary regimes.
- Feature missingness is tracked so absent satellite/solar data does not masquerade as clear sky.

### P5: Intraday nowcasting snapshots at 7, 9, 11, and noon

Goal: estimate remaining upside from observed warming, cloud clearing, and current max.

1. Generate fixed local snapshots at 7 AM, 9 AM, 11 AM, and noon.
2. Store current temperature, intraday max so far, dew point, wind, pressure, cloud ceiling, visibility, cloud trend, solar proxy, warming rate, and source freshness.
3. Compute remaining-upside distributions conditioned on:
   - Current max and recent warming rate.
   - Time of year and solar window remaining.
   - Marine layer clearance status.
   - Wind shift and dew point trend.
   - Latest HRRR/NBM short-range updates and run-to-run deltas.
4. Show widening uncertainty when sources disagree or observations are stale.

Acceptance criteria:

- Snapshot completeness is reported by hour and source.
- MAE is reported by snapshot hour and regime.
- Bucket Brier score and log loss improve or are explicitly justified versus a persistence/climatology baseline.

### P6: Historical backfill and conditional model bias

Goal: learn when each source is wrong, not just its average error.

1. Backfill official outcomes, observations, model runs, forecast discussions, model deltas, proxy stations, and daily regime labels.
2. Build conditional bias tables by station, model, season, lead time, forecast hour, snapshot hour, regime, and source-latency state.
3. Use strict train/validation/test splits by date to avoid leakage.
4. Require sample size, recency, uncertainty intervals, and holdout metrics before applying a bias correction.
5. Keep original raw forecasts and adjusted forecasts side by side.

Acceptance criteria:

- Bias tables include sample count, mean error, median error, MAE, p90 absolute error, and confidence interval.
- Holdout MAE and bucket scoring are reported by regime and season.
- Bias adjustments are disabled or downgraded when sample size is too small or regime labels are missing.

### P7: Calibrated probabilistic bucket models and reliability metrics

Goal: output honest probabilities for settlement buckets.

1. Start with transparent baselines: climatology, latest official high so far, model consensus, NBM probabilities, and regime-adjusted bias tables.
2. Add calibrated probabilistic models only after clean history exists.
3. Predict the full distribution over temperature buckets and thresholds.
4. Calibrate with isotonic, Platt, temperature scaling, or other documented methods as appropriate.
5. Evaluate using reliability curves, expected calibration error, Brier score, log loss, sharpness, and coverage.
6. Keep market-implied probabilities as a comparison input only when prices are fresh, liquid enough, and clearly timestamped.

Acceptance criteria:

- Bucket Brier score, log loss, reliability curves, and calibration error are reported for each snapshot hour.
- Calibration reports include separate results by regime, season, and lead time.
- Probability output includes uncertainty warnings for stale data, source mismatch, high spread, and unverified rules.

### P8: Paper-live shadow mode and operational soak

Goal: prove reliability before any trading-adjacent workflow.

1. Run paper-live with no betting, no order entry, and no automated execution.
2. Capture every input, prediction, probability distribution, market-price snapshot if permitted, and human note before official settlement.
3. Reconcile against official outcomes after release and after correction windows.
4. Track operational health: uptime, source latency, missingness, retry behavior, database growth, backup success, restore drills, and alert fatigue.
5. Review daily misses and update only documented, versioned assumptions.

Acceptance criteria:

- Multi-week shadow mode completes with daily reconciliation reports.
- Reconciliation error, source latency percentiles, missingness, station mismatch frequency, MAE, Brier score, log loss, and calibration curves are reviewed before escalation.
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

Kalshi markets are regulated financial products. Users must follow Kalshi terms, market rules, data-provider licenses, account permissions, organizational policy, and applicable law. This project supports research, auditability, and recordkeeping only; it is not financial advice, compliance approval, or a trading system. Any future trading-adjacent use requires explicit human review, legal/compliance approval, credential controls, risk limits, kill switches, audit logs, and security review.
