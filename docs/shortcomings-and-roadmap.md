# Product Shortcomings and Roadmap

This document is the honest gap list for Kalshi Temps. It separates the high-quality local implementation now present in this repository from the risks that still block production or trading-adjacent reliance. It is intentionally conservative: the project must not imply arbitrage, guaranteed edge, financial advice, or suitability for automated trading.

For a more detailed accuracy-focused plan for Seattle daily high-temperature signals, including settlement reconciliation, station/source discipline, intraday nowcasting, historical backfill, and calibrated bucket probabilities, see [high-precision-roadmap.md](high-precision-roadmap.md).

## Current product boundary

The repository is now a working local research application with a tested SQLite/FastAPI dashboard, deterministic ingestion foundations, market-rule verification records, weather-feature extraction, collector health visibility, operational posture checks, and historical-calibration scaffolding. Full local validation has passed across 67 tests, Python compile checks, script syntax checks, CLI smoke checks, and FastAPI endpoint smoke checks.

Implemented in-repository foundations include:

- FastAPI dashboard and read-only APIs for observations, sources, model runs, model spread, market snapshots, fusion summary, market-rule verification, collector health, weather features, calibration summaries, and local ops status.
- SQLite schema and repository methods for source metadata, observations, model runs and probability buckets, market snapshots, marine indicators, weather-regime features, intraday features, collector poll runs, market rules, official outcomes, prediction snapshots, bias summaries, calibration metrics, risk guards, and app events.
- Public, no-secret collectors and CLI helpers for NWS Seattle forecast discussion text and Aviation Weather METAR-style observations, with retry-ready manual runs, poll records, health summaries, deterministic hashes, and injectable fetchers for tests.
- Market-rule metadata capture and verification workflow that stores settlement source, station/product, rounding, cutoff, fallback, correction policy, reviewer, verification timestamp, and actionability state.
- Forecast-model ingestion foundations for manual HRRR/NAM/GFS/NBM-style model-high records, model spread persistence, probability bucket storage, and market-implied probability comparisons.
- Weather-feature extraction foundations for forecast-discussion regime language, marine-layer indicators, and intraday feature records.
- Historical-calibration foundations for official outcome records, prediction snapshots, bias summaries, and bucket calibration metrics.
- Security and operations hardening for loopback-first access guidance, local database/disk/access status, backup-path generation, secrets/runtime-data exclusions, and dashboard caveats.
- Dashboard research workflow sections that distinguish demo/manual-live/derived records, show verification and collector health context, and keep no-automated-trading warnings visible.

Unless implemented outside this repository and independently verified, assume the following remain **unresolved**:

- Real live operational soak: scheduled collectors, retries, monitoring, alerting, backups, restore drills, and weeks of paper-live reconciliation have not been proven.
- Authenticated dashboard/API access control, role-based permissions, session handling, and dashboard security tests are not implemented.
- Live Kalshi feed credentials, account permissions, market metadata, bid/ask, order-book, and private API ingestion are not configured or validated.
- Paid/licensed ECMWF archive/API access, GraphCast/AI weather feeds, and associated storage/license compliance are not resolved.
- Satellite image processing and quantitative cloud/stratus burn-off extraction are not implemented.
- Real historical backfill depth is insufficient for reliable regime bias, market replay, or out-of-sample calibration.
- Model calibration has not been trained and validated on sufficient historical data across seasons, regimes, horizons, and buckets.
- Compliance/legal review for trading-adjacent use, data licenses, exchange rules, account permissions, and organizational policy remains required.
- Automated trading, order entry, portfolio management, and execution controls are deliberately out of scope.

## Current product limitations and risks

### Data ingestion and operations gaps

- **Collector operations are foundational, not production**: manual and one-shot collector commands can persist poll records and health summaries, but live scheduling, daemon supervision, alerting, retry policy validation, backfill, and multi-week soak are still required.
- **Live Kalshi data is not connected**: market-implied probabilities remain demo/manual/placeholder records until permitted Kalshi metadata and bid/ask/order-book ingestion is implemented, timestamped, and audited.
- **Paid model feeds are unresolved**: ECMWF and GraphCast references remain roadmap items until valid licenses, endpoints, terms, and collectors exist.
- **Weather features are early deterministic signals**: forecast-discussion regime extraction and intraday features are useful scaffolding, not a validated satellite/cloud-processing or physical nowcasting pipeline.
- **Historical data is shallow**: official outcomes, snapshots, bias summaries, and calibration metrics can be stored and computed locally, but there is not enough real backfill to claim calibrated probabilities.

### Settlement and source risks

- **Settlement source must be verified per market**: every Kalshi contract can differ by source, station, product, fallback, rounding, correction policy, and local-day cutoff. The app can store verification records, but a human or trusted process must complete them.
- **KSEA is not automatically authoritative**: Weather Underground/KSEA, NOAA/KSEA, METAR/KSEA, or Aviation Weather/KSEA claims must be checked against the exact market rule before analysis is treated as actionable.
- **Station/source mismatch can dominate edge**: METAR, NWS climate products, Weather Underground summaries, nearby ASOS/AWOS, and PWS records may disagree by enough to change a bucket.
- **Rounding and daily-max definitions matter**: hourly METAR values may miss between-report extremes; climate summaries may revise; local-day boundaries and DST handling must match settlement text.
- **Fallback and correction behavior must be captured**: late corrections, outages, fallback stations, and official revisions can change the final result after an early read.

### Demo/manual data limitations

- Demo rows are useful for UI development and smoke tests only.
- Manual-live rows and imported model records are research scaffolding unless their source, timestamp, license, and market-rule linkage are verified.
- Demo/manual/derived records must remain visibly labeled and separated from replay, paper-live, and any future production-live records.
- Demo-derived charts must not be confused with live observations, live market prices, or backtested accuracy.

### Observation, forecast, and calibration quality risks

- **Deterministic validators exist but are not full QC**: current validation covers required fields, freshness, plausible ranges, future/stale timestamps, duplicate hints, frozen-temperature hints, and provenance warnings. It does not replace official QC flags, station metadata, or source-specific quality controls.
- **Latency and revision risk**: observation feeds, model files, market data, and official settlement sources can arrive late, out of order, or be corrected after first publication.
- **Proxy-station risk**: nearby stations can diverge due to elevation, water exposure, urban heat, marine push, wind shift, or sensor siting.
- **PWS low-trust status**: personal weather stations should remain qualitative, low-trust context unless individually calibrated and quality-controlled.
- **Model availability risk**: HRRR/NAM/GFS/NBM products can be delayed, missing, changed, or superseded; paid products require license compliance.
- **Calibration gap**: no trained calibration model or validated conditional bias table should be assumed until enough historical data has been collected, split, evaluated, and monitored.

### Dashboard and access limitations

- **No authenticated dashboard yet**: local or tailnet access should not be treated as user-level authentication.
- **Tailscale is private networking, not application authorization**: tailnet exposure still requires review of who can access the device, what data appears on screen, and whether credentials or trading-sensitive information are exposed.
- **Avoid public exposure by default**: Tailscale Funnel, broad `0.0.0.0` binds, public reverse proxies, and shared devices increase risk and need explicit controls.
- **No role-based permissions yet**: the product does not distinguish viewer, researcher, admin, or trading-approval roles.
- **Audit history is foundational**: events, outcomes, and snapshots can be stored, but financial reliance would require durable review workflows, retention policy, and security review.

### Financial, legal, and compliance caveats

- Kalshi markets are regulated financial products; users must follow Kalshi rules, data-provider licenses, account permissions, and applicable law.
- The product supports research and recordkeeping only; it is not financial advice.
- Do not present forecast disagreement, stale data, early official-looking values, or market-price gaps as guaranteed arbitrage.
- Expected-value calculations, if added, must include uncertainty, fees, liquidity, spread, slippage, settlement ambiguity, stale data, and human/compliance review.
- Automated trading remains out of scope until explicit approvals, credential controls, kill switches, audit logs, position/loss limits, and compliance procedures exist.

## Testing and validation status

### Completed local validation

A full local validation pass has completed:

- 67 tests passed.
- Python `compileall` passed for source and tests.
- Script syntax checks passed.
- CLI smoke checks passed.
- FastAPI endpoint smoke checks passed.

Implemented tests cover local foundations without requiring live network access:

- Forecast discussion normalization and persistence, including product, issued time, source URL, text, and deterministic hashes.
- METAR-like observation normalization and persistence, including station, timestamp, temperature, dew point, wind, pressure, ceiling, source URL, and hashes.
- NWS discussion and METAR collector behavior using injected fetchers, poll records, provenance, hashes, and error paths.
- Market-rule completeness, verification, and non-actionability behavior for incomplete rules.
- Model-high import, model spread, bucket probabilities, market snapshot normalization, implied probabilities, and invalid-price handling.
- Weather-regime and intraday feature extraction foundations.
- Official outcomes, prediction snapshots, historical bias summaries, and calibration metric foundations.
- SQLite repository/integration flows, seeded and empty states, CLI smoke checks, FastAPI endpoints, collector health, ops status, and dashboard rendering.

### Remaining validation gaps

- No end-to-end live proof that a market can be discovered, verified, ingested, analyzed, displayed, audited, reconciled against official settlement, and operated for weeks without manual repair.
- No broad recorded-payload fixture suite covering real NOAA/NWS/METAR/Kalshi variations, missing fields, corrections, out-of-order records, daylight-saving transitions, or unit conversions.
- No live-network validation should be inferred from mocked collector tests.
- No validated station-metadata layer for distance, elevation, source class, water exposure, and station changes.
- No benchmark showing forecast error by model, regime, bucket, or time of day on sufficient historical data.
- No calibration report proving probability outputs are reliable out of sample.
- No dashboard security tests for authentication, authorization, session handling, or accidental exposure.
- No operational soak tests for scheduler failures, retry behavior, database locks, backups, restore, disk-full conditions, or alert fatigue.

### Full integration validation strategy

A fully integrated research product should still be validated in staged modes:

1. **Offline replay**: replay frozen historical payloads through collectors, normalization, feature generation, dashboard rendering, and outcome reconciliation.
2. **Paper-live shadow mode**: collect live data without trading, record hypotheses, and compare against official outcomes after release.
3. **Calibration evaluation**: evaluate probability buckets over enough market days to show calibration quality, confidence intervals, and failure regimes.
4. **Operational soak**: run scheduled ingestion for weeks, tracking uptime, latency, missing data, database growth, backup success, and alert noise.
5. **Security review**: verify authentication, authorization, secrets handling, dashboard exposure, audit logs, and least-privilege deployment.
6. **Human decision review**: require documented review of market rule, source freshness, uncertainty, liquidity, and compliance before any trading-adjacent use.

## Prioritized future improvements

### P0: Live operational soak and production readiness gap

- Add scheduled collector orchestration with tested retry/backoff, rate-limit handling, latency metrics, alerting, and idempotency.
- Run paper-live for multiple weeks and reconcile predictions, features, market snapshots, and official outcomes.
- Extend the existing backup/restore scripts with scheduling, migration safeguards, retention policy, disk-space checks, and restore drills.
- Record operator notes, source failures, stale-data incidents, and postmortems.

### P1: Authenticated access and security

- Add authentication and authorization for dashboard/API access.
- Add role-based permissions for viewer, researcher, admin, and any future trading-approval role.
- Add secrets management for API keys and credentials.
- Add dashboard/API security tests and least-privilege deployment documentation.
- Review Tailscale Serve/Funnel or public exposure only after authentication and data-sensitivity review.

### P2: Live Kalshi and market-rule operations

- Keep market-rule verification mandatory for each ticker before any actionability language is shown.
- Implement Kalshi market metadata and bid/ask/order-book ingestion where permitted by credentials, account permissions, terms, and rate limits.
- Preserve raw payloads or hashes plus normalized rows for auditability.
- Add market liquidity, spread, stale-price, crossed-market, and permission-failure warnings.

### P3: Model and weather data depth

- Productionize HRRR, NAM, GFS, and NBM ingestion with run time, valid time, forecast high, hourly path, and percentiles when available.
- Add ECMWF ingestion only after paid access, licensing, and storage terms are resolved.
- Add GraphCast or other AI-model ingestion only after a reliable endpoint, licensing, and validation approach exist.
- Add satellite/cloud image processing for morning cloud cover, Puget Sound stratus extent, fog presence, and burn-off timing.
- Extend weather-regime extraction with verified station metadata, sunrise/solar features, dew point, wind, pressure, and cloud ceiling snapshots.

### P4: Historical backfill and calibration

- Backfill observations, model forecasts, market prices, official outcomes, prediction snapshots, and weather-regime tags.
- Create conditional bias tables by model, station, season, forecast hour, marine-layer regime, heat regime, and persistent-cloud regime.
- Include sample size, recency, confidence interval, and holdout performance for every bias adjustment.
- Protect against leakage by separating training data from evaluation dates.
- Train transparent baselines first, then consider gradient-boosted probability models only after clean history exists.

### P5: Dashboard workflow refinement

- Continue improving research workflow sections for rule verification, collector health, weather features, calibration, market comparison, ops status, and audit events.
- Add clear status chips: demo/manual-live/replay/paper-live/production-live, rule verified/unverified, stale/fresh, source match/mismatch, calibrated/uncalibrated.
- Add drill-down pages for raw observations, forecast discussions, model runs, market prices, hypotheses, official outcomes, and calibration diagnostics.
- Add exportable daily research reports with provenance and caveats.

### P6: Compliance controls and optional trading-adjacent tooling

- Add compliance checklist templates for market eligibility, data licenses, account permissions, and organizational policy.
- Add configurable position-limit placeholders, daily-loss placeholders, and correlated-exposure placeholders only after legal/compliance review.
- Add paper-trading or decision-journal features before any broker/order API integration.
- If order-entry tooling is ever considered, require explicit human approval, kill switch, audit logs, restricted credentials, pre-trade checks, and separate review.
- Keep automated trading disabled unless a future, separately approved design proves controls, compliance, and operational safety.

## Acceptance criteria by phase

### Phase 1: Local research foundation — implemented and validated

The repository meets the local foundation bar when:

- A developer can initialize the database, seed demo data, run collector/import/calibration helper commands, start the local app, and view the dashboard without private external services.
- Demo data is unmistakably labeled and cannot be mistaken for live market or weather data.
- The dashboard shows source/provenance, market-rule verification, collector health, weather features, calibration scaffolding, ops status, caveats, and automated-trading-disabled warnings.
- Documentation clearly states that live Kalshi ingestion, authenticated access, licensed weather feeds, satellite processing, deep historical calibration, compliance review, and automated trading are not present.
- Local tests, compile checks, CLI smoke checks, and FastAPI endpoint smoke checks pass.
- No financial recommendation, guaranteed arbitrage language, or automated action is presented.

### Phase 2: Live research product — not yet complete

The product is fully working as a live research tool only when:

- Each tracked market has verified settlement source, station/product, units, rounding, cutoff, fallback, and correction policy.
- Live collectors ingest verified official-source observations, relevant proxy observations, model guidance, and permitted Kalshi market data with timestamps and provenance.
- Collector health, latency, retry behavior, stale-data flags, and source mismatch warnings are visible and monitored.
- Demo/replay/manual-live/paper-live records are separated in storage and UI.
- Raw payloads or hashes, normalized rows, and audit logs support reproducibility.
- The system can run in paper-live mode for multiple weeks and reconcile hypotheses against official outcomes.
- Users still make independent decisions; the product remains research support, not trading advice.

### Phase 3: Calibrated decision-support product — not yet complete

The product is fully working as calibrated decision support only when:

- Sufficient historical backfill exists across regimes, seasons, forecast horizons, and market buckets.
- Conditional bias tables and/or models are trained only on historical data and evaluated out of sample.
- Probability outputs are calibrated and reported with reliability curves, Brier/log-loss metrics, sample sizes, and regime-specific caveats.
- The UI explains uncertainty, model spread, stale data, settlement ambiguity, and source mismatch before any expected-value comparison.
- Market-implied probabilities are compared to model probabilities with fees, spread, liquidity, and slippage caveats.
- Postmortems record forecast misses, data failures, settlement surprises, and calibration updates.
- A human review workflow and audit trail are mandatory for any trading-adjacent interpretation.

### Phase 4: Optional trading-adjacent tooling — out of scope

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
