# Product Shortcomings and Roadmap

This document is the honest gap list for Kalshi Temps. It describes what is missing before the project can be considered a reliable research tool, what must be validated before any financial use, and what future phases should deliver. It is intentionally conservative: the project should not imply arbitrage, guaranteed edge, or suitability for automated trading.

## Current product boundary

The repository is currently best understood as a local demo and planning scaffold for temperature-market research. It can document a workflow, store or display demo-style records where supported by the app, and guide future data engineering. It is not yet a live, calibrated, authenticated, production decision system.

Unless implemented elsewhere outside this repository and independently verified, assume the following are **not yet present**:

- Live NOAA, NWS, METAR, Weather Underground, MADIS, satellite, model, or Kalshi ingestion.
- Paid ECMWF access, licensed ECMWF archive access, or GraphCast/AI weather-model feeds.
- Automated Kalshi order placement, portfolio management, or execution controls.
- Authenticated multi-user dashboard access.
- Production deployment, systemd service management, monitored backups, or production on-call runbooks.
- Trained model calibration from historical Seattle market, forecast, and official-outcome data.

## Current product limitations and risks

### Data ingestion gaps

- **No verified live collectors yet**: the system should not claim current NOAA/Kalshi awareness until collectors exist, are scheduled, and are monitored.
- **No live Kalshi price feed yet**: market-implied probabilities are conceptual until bid/ask/order-book ingestion is implemented and timestamped.
- **No paid model access**: ECMWF and GraphCast references are roadmap items unless a valid license, endpoint, and collector are configured.
- **No NWS discussion scraper yet**: marine-layer and forecaster-text signals are not automatically extracted.
- **No satellite/cloud feature pipeline yet**: morning stratus, fog, and burn-off timing are not currently quantified.
- **No historical backfill yet**: there is not enough normalized history to train bias tables or probability calibration.

### Settlement and source risks

- **Settlement source must be verified per market**: every Kalshi contract can differ by source, station, product, fallback, rounding, correction policy, and local-day cutoff.
- **KSEA is not automatically authoritative**: Weather Underground/KSEA or NOAA/KSEA claims must be checked against the exact market rule before analysis is treated as actionable.
- **Station/source mismatch can dominate edge**: METAR, NWS climate products, Weather Underground summaries, nearby ASOS/AWOS, and PWS records may disagree by enough to change a bucket.
- **Rounding and daily-max definitions matter**: hourly METAR values may miss between-report extremes; climate summaries may revise; local-day boundaries and DST handling must match settlement text.
- **Fallback and correction behavior must be captured**: late corrections, outages, fallback stations, and official revisions can change the final result after an early read.

### Demo data limitations

- Demo or seed rows are useful for UI development only.
- Demo records may not reflect real latency, missingness, QC flags, station metadata, model spread, market microstructure, or official settlement behavior.
- Demo-derived charts must be labeled clearly so they are not confused with live observations, live market prices, or backtested accuracy.
- Demo data must not be mixed with live research records without a durable `is_demo`/environment/provenance flag.

### Observation and forecast quality risks

- **Latency risk**: observation feeds, model files, market data, and official settlement sources can arrive late or out of order.
- **Revision risk**: official data and third-party summaries may be corrected after first publication.
- **QC risk**: outages, frozen sensors, maintenance, station relocation, bad timestamps, or unit conversion errors can create false confidence.
- **Proxy-station risk**: nearby stations can diverge due to elevation, water exposure, urban heat, marine push, wind shift, or sensor siting.
- **PWS low-trust status**: personal weather stations should remain qualitative, low-trust context unless individually calibrated and quality-controlled.
- **Model availability risk**: HRRR/NAM/GFS/NBM products can be delayed, missing, changed, or superseded; paid products require license compliance.
- **Model calibration gap**: no trained calibration model or validated conditional bias table should be assumed until historical data has been collected, split, evaluated, and monitored.

### Dashboard and access limitations

- **No authenticated dashboard yet**: local or tailnet access should not be treated as user-level authentication.
- **Tailscale is private networking, not application authorization**: tailnet exposure still requires review of who can access the device, what data appears on screen, and whether credentials or trading-sensitive information are exposed.
- **Avoid public exposure by default**: Tailscale Funnel, broad `0.0.0.0` binds, public reverse proxies, and shared devices increase risk and need explicit controls.
- **No role-based permissions yet**: the product does not distinguish viewer, researcher, admin, or trading-approval roles.
- **No durable audit UI yet**: hypotheses, revisions, manual decisions, and official outcomes need auditable history before financial reliance.

### Financial, legal, and compliance caveats

- Kalshi markets are regulated financial products; users must follow Kalshi rules, data-provider licenses, and applicable law.
- The product should support research and recordkeeping, not financial advice.
- Do not present forecast disagreement, stale data, early official-looking values, or market-price gaps as guaranteed arbitrage.
- Expected-value calculations, if added, must include uncertainty, fees, liquidity, spread, slippage, settlement ambiguity, stale data, and human/compliance review.
- Automated trading is out of scope until explicit approvals, account controls, kill switches, audit logs, and compliance procedures exist.

## Testing and validation gaps

### Current gaps

- No end-to-end validation that a market can be discovered, verified, ingested, analyzed, displayed, audited, and reconciled against official settlement.
- No known fixture suite covering real NOAA/NWS/METAR/Kalshi payload variations, missing fields, corrections, out-of-order records, daylight-saving transitions, or unit conversions.
- No validated station-metadata layer for distance, elevation, source class, water exposure, and station changes.
- No benchmark showing forecast error by model, regime, bucket, or time of day.
- No calibration report proving probability outputs are reliable out of sample.
- No dashboard security tests for authentication, authorization, session handling, or accidental exposure.
- No operational tests for scheduler failures, retry behavior, database locks, backups, restore, or disk-full conditions.

### Isolated component test strategy

Each component should be testable without live network access:

1. **Market-rule parser and verifier**
   - Fixtures for settlement text, station names, products, rounding, fallback rules, and correction language.
   - Tests that unverified or ambiguous rules block actionable output.
2. **Source collectors**
   - Recorded payload fixtures for NOAA/NWS, METAR, model files, satellite metadata, and Kalshi markets.
   - Tests for missing fields, stale timestamps, HTTP errors, retries, rate limits, schema changes, and source-specific terms metadata.
3. **Normalization and provenance**
   - Tests for unit conversion, local/UTC timestamps, DST boundaries, raw payload hashing, duplicate handling, and immutable audit records.
4. **Observation QC**
   - Tests for frozen sensors, implausible jumps, stale reports, source mismatch, missing QC flags, and proxy-station downgrades.
5. **Feature generation**
   - Tests for intraday max, warming rate, model spread, marine-layer flags, NWS-discussion keyword extraction, and satellite/cloud derived fields.
6. **Bias tables and calibration**
   - Tests for train/test splitting by date, leakage prevention, minimum sample sizes, regime tags, reliability curves, Brier/log-loss metrics, and recalibration behavior.
7. **Market probability conversion**
   - Tests for bid/ask/mid implied probabilities, fees, spread, illiquid books, stale prices, crossed markets, and bucket normalization.
8. **Dashboard/API**
   - Tests for demo/live labeling, stale-data warnings, source-verification warnings, error states, mobile layout, and access controls once added.
9. **Persistence and operations**
   - Tests for migrations, SQLite concurrency, backup/restore, scheduler idempotency, and crash recovery.

### Full integration validation strategy

A fully integrated test should run in staged modes:

1. **Offline replay**: replay frozen historical payloads through collectors, normalization, feature generation, dashboard rendering, and outcome reconciliation.
2. **Paper-live shadow mode**: collect live data without trading, record hypotheses, and compare against official outcomes after release.
3. **Calibration evaluation**: evaluate probability buckets over enough market days to show calibration quality, confidence intervals, and failure regimes.
4. **Operational soak**: run scheduled ingestion for weeks, tracking uptime, latency, missing data, database growth, backup success, and alert noise.
5. **Security review**: verify authentication, authorization, secrets handling, dashboard exposure, audit logs, and least-privilege deployment.
6. **Human decision review**: require documented review of market rule, source freshness, uncertainty, liquidity, and compliance before any trading-adjacent use.

## Prioritized future improvements

### P0: Trust boundary and rule verification

- Add a market-rule verification workflow that stores ticker, title, settlement source, station/product, rounding, cutoff, fallback, correction policy, and reviewer timestamp.
- Add UI/API guards that mark unverified markets as `not_actionable_pending_rule_verification`.
- Label demo, replay, paper-live, and live records everywhere.
- Add source freshness, source mismatch, and PWS low-trust warnings.

### P1: Real data collectors

- Implement NOAA/NWS observation and climate-product collectors for the verified settlement source.
- Implement METAR/KSEA and nearby ASOS/AWOS collectors with station metadata.
- Implement Kalshi market metadata and bid/ask/order-book ingestion where permitted.
- Add scheduler, retries, rate-limit handling, payload hashing, latency metrics, and collector health checks.
- Preserve raw payloads or hashes plus normalized rows for auditability.

### P2: Model forecast ingestion

- Add HRRR, NAM, GFS, and NBM ingestion with run time, valid time, forecast high, hourly path, and percentiles when available.
- Add ECMWF ingestion only after paid access, licensing, and storage terms are resolved.
- Add GraphCast or other AI-model ingestion only after a reliable endpoint, licensing, and validation approach exist.
- Track run-to-run changes and model disagreement as uncertainty features.

### P3: Weather-regime context

- Build an NWS forecast discussion scraper/parser for marine layer, stratus, fog, offshore flow, heat, wind shift, and persistent-cloud language.
- Add satellite/cloud feature extraction for morning cloud cover, Puget Sound stratus extent, fog presence, and burn-off timing.
- Add sunrise, solar angle, dew point, wind, pressure, and cloud ceiling features for 7 AM, 9 AM, and 11 AM snapshots.

### P4: Historical backfill and bias tables

- Backfill observations, model forecasts, market prices, official outcomes, and weather-regime tags.
- Create conditional bias tables by model, station, season, forecast hour, marine-layer regime, heat regime, and persistent-cloud regime.
- Include sample size, recency, confidence interval, and holdout performance for every bias adjustment.
- Protect against leakage by separating training data from evaluation dates.

### P5: Probability calibration and decision support

- Train transparent baseline models before complex ML: climatology, persistence, model blend, and conditional bias adjustment.
- Add gradient-boosted probability models only after clean history exists.
- Evaluate Brier score, log loss, calibration curves, reliability by bucket, and performance by regime.
- Present calibrated probability distributions with uncertainty, not deterministic calls.
- Compare model distribution with Kalshi-implied distribution while preserving caveats about fees, liquidity, spread, and settlement ambiguity.

### P6: Alerts and workflow automation

- Add alerts for stale data, source mismatch, model spread spikes, late marine-layer burn-off, market-price moves, collector failures, and official-result publication.
- Add daily research checklists and postmortem prompts.
- Add human confirmation records for any trading-adjacent decision.
- Keep alerts informational by default; avoid automatic trading actions.

### P7: Security, access, and operations

- Add authentication and authorization for dashboard/API access.
- Add secrets management for API keys and credentials.
- Add SQLite backup/restore scripts, migration safeguards, and retention policy.
- Add deployment documentation and systemd units for collectors and the app.
- Add structured logs, health endpoints, uptime checks, disk-space checks, and alerting.
- Review Tailscale Serve/Funnel or public exposure only after authentication and data-sensitivity review.

### P8: UX refinements

- Improve mobile dashboard layout for quick source freshness, verified station, current high, bucket probabilities, and caveats.
- Add clear status chips: demo/live, rule verified/unverified, stale/fresh, source match/mismatch, calibrated/uncalibrated.
- Add drill-down pages for raw observations, model runs, market prices, hypotheses, and official outcome reconciliation.
- Add exportable daily research reports with provenance and caveats.

### P9: Compliance controls and optional trading-adjacent tooling

- Add compliance checklist templates for market eligibility, data licenses, account permissions, and organizational policy.
- Add configurable position-limit placeholders, daily-loss placeholders, and correlated-exposure placeholders only after legal/compliance review.
- Add paper-trading or decision-journal features before any broker/order API integration.
- If order-entry tooling is ever considered, require explicit human approval, kill switch, audit logs, restricted credentials, pre-trade checks, and separate review.

## Acceptance criteria by phase

### Phase 1: Local demo product

The product is fully working as a local demo when:

- A developer can initialize the database, seed demo data, start the local app, and view the dashboard without external services.
- Demo data is unmistakably labeled and cannot be mistaken for live market or weather data.
- The dashboard shows source/provenance placeholders, caveats, and unverified-market warnings.
- Documentation clearly states that live ingestion, model calibration, authentication, and automated trading are not present.
- Basic smoke tests or documented manual checks confirm the app starts, routes load, and demo records render.
- No financial recommendation, guaranteed arbitrage language, or automated action is presented.

### Phase 2: Live research product

The product is fully working as a live research tool when:

- Each tracked market has verified settlement source, station/product, units, rounding, cutoff, fallback, and correction policy.
- Live collectors ingest verified official-source observations, relevant proxy observations, model guidance, and Kalshi market data with timestamps and provenance.
- Collector health, latency, retry behavior, stale-data flags, and source mismatch warnings are visible.
- Demo/replay/live records are separated in storage and UI.
- Raw payloads or hashes, normalized rows, and audit logs support reproducibility.
- The system can run in paper-live mode for multiple weeks and reconcile hypotheses against official outcomes.
- Users still make independent decisions; the product remains research support, not trading advice.

### Phase 3: Calibrated decision-support product

The product is fully working as calibrated decision support when:

- Sufficient historical backfill exists across regimes, seasons, forecast horizons, and market buckets.
- Conditional bias tables and/or models are trained only on historical data and evaluated out of sample.
- Probability outputs are calibrated and reported with reliability curves, Brier/log-loss metrics, sample sizes, and regime-specific caveats.
- The UI explains uncertainty, model spread, stale data, settlement ambiguity, and source mismatch before any expected-value comparison.
- Market-implied probabilities are compared to model probabilities with fees, spread, liquidity, and slippage caveats.
- Postmortems record forecast misses, data failures, settlement surprises, and calibration updates.
- A human review workflow and audit trail are mandatory for any trading-adjacent interpretation.

### Phase 4: Optional trading-adjacent tooling

Trading-adjacent tooling is acceptable only when all prior phases are stable and:

- Legal, regulatory, exchange-rule, data-license, and organizational compliance reviews are complete.
- Authentication, authorization, secrets management, audit logging, backups, and monitored deployment are in place.
- Position limits, exposure limits, loss limits, stale-data blocks, source-verification blocks, and kill switches are configured and tested.
- Any order-related workflow is opt-in, separated from research display, and requires explicit human confirmation unless a future approved policy says otherwise.
- Paper-trading results and live shadow-mode logs show stable operations and realistic accounting for fees, spread, liquidity, and settlement uncertainty.
- The product still avoids promising arbitrage or guaranteed returns.

## Definition of done for roadmap execution

For every future improvement, record:

- Owner and implementation date.
- Source endpoints, licenses, and terms notes.
- Tests added or updated.
- Backfill/replay validation results.
- Operational monitoring and failure modes.
- User-visible caveats and labels.
- Post-release review of whether the change increased, reduced, or merely shifted risk.
