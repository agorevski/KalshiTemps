# Product Shortcomings and Roadmap

This document is the honest gap list for Kalshi Temps. It separates the high-quality local implementation now present in this repository from the external dependencies and operational risks that still block production or trading-adjacent reliance. It is intentionally conservative: the project must not imply arbitrage, guaranteed edge, financial advice, or suitability for automated trading.

For a more detailed accuracy-focused plan for Seattle daily high-temperature signals, including settlement reconciliation, station/source discipline, intraday nowcasting, historical backfill, and calibrated bucket probabilities, see [high-precision-roadmap.md](high-precision-roadmap.md).

## Current product boundary

The repository is now a working local research application with a tested SQLite/FastAPI dashboard, deterministic ingestion foundations, official source/station metadata, market-rule verification records, settlement replay, model adapter foundations, marine/cloud nowcast signals, backfill/calibration records, collector and scheduler status visibility, DB ops checks, monitoring alerts/daily reports, operational posture checks, paper-live tracking, optional env-token access gating, and precision dashboard/API integration. Full local validation has passed across Python tests, compile checks, script syntax checks, CLI smoke checks, and FastAPI endpoint smoke checks.

Implemented in-repository foundations include:

- FastAPI dashboard and read-only APIs for observations, sources, station metadata/official observations, model runs, model spread/adapters, market snapshots, settlement replays, fusion summary, market-rule verification, collector/scheduler health, weather/nowcast features, calibration/backfill plan/run summaries, monitoring alerts/daily reports, DB health, paper-live status, and local ops status.
- SQLite schema and repository methods for source metadata, observations, official observations, station metadata, model runs/probability buckets/extraction metadata/deltas, market snapshots, settlement replays, marine indicators, cloud features, weather-regime features, intraday features, nowcast snapshots, collector poll runs, market rules, official outcomes, prediction snapshots, backfill runs, bias summaries, calibration metrics, paper-live runs/notes/soak metrics, risk guards, and app events.
- Public, no-secret collectors and CLI helpers for NWS Seattle forecast discussion text, Aviation Weather METAR-style observations, and api.weather.gov station observations, with retry-ready manual runs, poll records, health summaries, deterministic hashes, and injectable fetchers for tests.
- Official station/source metadata imports and climate daily-summary imports for research fixtures and official-observation records.
- Market-rule metadata capture plus settlement replay workflow that stores settlement source, station/product, rounding, cutoff, fallback, correction policy, reviewer, verification timestamp, replay status, mismatch reasons, payload hashes, and actionability state.
- Forecast-model adapter foundations for manual or URL-fetched HRRR/NAM/GFS/NBM-style records, model spread persistence, run-to-run deltas, extraction metadata, probability bucket storage, and market-implied probability comparisons.
- Weather-feature and nowcast foundations for forecast-discussion regime language, marine-layer indicators, cloud feature proxy records, fixed-hour nowcast snapshots, and remaining-upside context.
- Historical backfill/calibration foundations for public backfill planning, frozen fixture replay, dry-run records, official outcome records, prediction snapshots, train/test-aware calibration reports, bias summaries, and bucket calibration metrics.
- Paper-live operations foundations for no-betting run tracking, checklists, prediction notes, postmortems, reconciliation notes, soak metrics, and readiness summaries.
- Local security and operations hardening for loopback-first access guidance, optional `KALSHI_TEMPS_ACCESS_TOKEN` protection on `/dashboard` and `/api/*`, local database/disk/access status, DB integrity/schema checks, backup verification, backup pruning dry-runs, restore preflight, scheduler locks/status, monitoring alert records/daily reports, secrets/runtime-data exclusions, and dashboard caveats.

Unless implemented outside this repository and independently verified, assume the following remain **unresolved**:

- Real market-specific rule verification by the user or another trusted reviewer for every ticker.
- Production-grade Kalshi ingestion, order-book depth, account/portfolio integration, order placement, and feed-permission validation. Read-only market discovery/snapshot support may exist, but it is not trading automation.
- Paid/licensed ECMWF archive/API access, GraphCast/AI weather feeds, and associated storage/license compliance.
- Actual satellite image processing and quantitative cloud/stratus burn-off extraction from imagery.
- Real long-running paper-live soak with installed/soaked scheduled collectors, retries, monitoring/alert routing, backups, restore drills, and weeks of reconciliation.
- Sufficient historical backfill depth for reliable regime bias, market replay, or out-of-sample calibration.
- Proven calibrated model performance across seasons, regimes, horizons, and buckets.
- Compliance/legal review for trading-adjacent use, data licenses, exchange rules, account permissions, and organizational policy.
- Production-grade authentication, authorization, deployment, secrets management, and security review beyond the local env-token gate.
- Automated trading, order entry, portfolio management, and execution controls remain deliberately out of scope.

## Current product limitations and risks

### Data ingestion and operations gaps

- **Collector operations are foundational, not production**: manual and one-shot collector commands can persist poll records and health summaries, and scheduler locks/status plus systemd examples exist, but live scheduling installation, daemon supervision, alert routing, retry policy validation, and multi-week soak are still required.
- **Kalshi data remains limited**: read-only market discovery/snapshots can persist candidate metadata and top-of-book prices, but production-grade ingestion, order-book depth, account integration, and trading controls are not implemented.
- **Paid model feeds are unresolved**: ECMWF and GraphCast references remain external dependencies until valid licenses, endpoints, terms, and collectors exist.
- **Satellite imagery is not processed**: cloud features can be imported as manual/proxy records, but actual image processing for cloud/stratus burn-off is not implemented.
- **Historical data is shallow**: official outcomes, snapshots, bias summaries, calibration metrics, and backfill runs can be stored and computed locally, but there is not enough real backfill to claim calibrated probabilities.

### Settlement and source risks

- **Settlement source must be verified per market**: every Kalshi contract can differ by source, station, product, fallback, rounding, correction policy, and local-day cutoff. The app can store verification records and replay outcomes, but a human or trusted process must complete real verification.
- **KSEA is not automatically authoritative**: Weather Underground/KSEA, NOAA/KSEA, METAR/KSEA, or Aviation Weather/KSEA claims must be checked against the exact market rule before analysis is treated as actionable.
- **Station/source mismatch can dominate edge**: METAR, NWS climate products, Weather Underground summaries, nearby ASOS/AWOS, and PWS records may disagree by enough to change a bucket.
- **Rounding and daily-max definitions matter**: hourly METAR values may miss between-report extremes; climate summaries may revise; local-day boundaries and DST handling must match settlement text.
- **Fallback and correction behavior must be captured**: late corrections, outages, fallback stations, and official revisions can change the final result after an early read.

### Demo/manual data limitations

- Demo rows are useful for UI development and smoke tests only.
- Manual-live rows, imported station metadata, cloud features, model records, and official observations are research scaffolding unless their source, timestamp, license, and market-rule linkage are verified.
- Demo/manual/derived records must remain visibly labeled and separated from replay, paper-live, and any future production-live records.
- Demo-derived charts must not be confused with live observations, live market prices, or backtested accuracy.

### Observation, forecast, and calibration quality risks

- **Deterministic validators exist but are not full QC**: current validation covers required fields, freshness, plausible ranges, future/stale timestamps, duplicate hints, frozen-temperature hints, and provenance warnings. It does not replace official QC flags, station history, or source-specific quality controls.
- **Latency and revision risk**: observation feeds, model files, market data, and official settlement sources can arrive late, out of order, or be corrected after first publication.
- **Proxy-station risk**: nearby stations can diverge due to elevation, water exposure, urban heat, marine push, wind shift, or sensor siting.
- **Model availability risk**: HRRR/NAM/GFS/NBM products can be delayed, missing, changed, or superseded; paid products require license compliance.
- **Calibration gap**: no trained calibration model or validated conditional bias table should be assumed until enough historical data has been collected, split, evaluated, and monitored.

### Dashboard and access limitations

- **Only local token gating exists**: setting `KALSHI_TEMPS_ACCESS_TOKEN` protects `/dashboard` and `/api/*` with a bearer or `X-Access-Token` value, but this is not production-grade identity, authorization, session handling, audit, or deployment security.
- **Tailscale is private networking, not application authorization**: tailnet exposure still requires review of who can access the device, what data appears on screen, and whether credentials or trading-sensitive information are exposed.
- **Avoid public exposure by default**: Tailscale Funnel, broad `0.0.0.0` binds, public reverse proxies, and shared devices increase risk and need explicit controls.
- **No role-based permissions yet**: the product does not distinguish viewer, researcher, admin, or trading-approval roles.
- **Audit history is foundational**: events, outcomes, snapshots, replays, and paper-live notes can be stored, but financial reliance would require durable review workflows, retention policy, and security review.

### Financial, legal, and compliance caveats

- Kalshi markets are regulated financial products; users must follow Kalshi rules, data-provider licenses, account permissions, and applicable law.
- The product supports research and recordkeeping only; it is not financial advice.
- Do not present forecast disagreement, stale data, early official-looking values, or market-price gaps as guaranteed arbitrage.
- Expected-value calculations, if added, must include uncertainty, fees, liquidity, spread, slippage, settlement ambiguity, stale data, and human/compliance review.
- Automated trading remains out of scope until explicit approvals, credential controls, kill switches, audit logs, position/loss limits, and compliance procedures exist.

## Testing and validation status

### Completed local validation

A full local validation pass has completed:

- 119 tests passed.
- Python `compileall` passed for source and tests.
- Script syntax checks passed.
- CLI smoke checks passed.
- FastAPI endpoint smoke checks passed.

Implemented tests cover local foundations without requiring live network access:

- Forecast discussion normalization and persistence, including product, issued time, source URL, text, and deterministic hashes.
- METAR-like and api.weather.gov-style observation normalization and persistence, including station, timestamp, temperature, dew point, wind, pressure, ceiling, source URL, QC/provenance, and hashes.
- Official source/station metadata import, official observation storage, and climate daily-summary fixture import.
- NWS discussion, METAR, and NWS observation collector behavior using injected fetchers, poll records, provenance, hashes, and error paths.
- Market-rule completeness, verification, non-actionability behavior, settlement replay, mismatch reasons, correction/fallback flags, and replay summaries.
- Model-high import, model adapter imports/fetches, extraction metadata, model deltas, model spread, bucket probabilities, market snapshot normalization, implied probabilities, and invalid-price handling.
- Weather-regime, cloud feature, intraday feature, and nowcast snapshot foundations.
- Backfill runs, official outcomes, prediction snapshots, historical bias summaries, split-aware calibration reports, and calibration metric foundations.
- Paper-live run/checklist/prediction/reconciliation/soak helpers and readiness/status summaries.
- Optional env-token access gate, SQLite repository/integration flows, seeded and empty states, CLI smoke checks, FastAPI endpoints, collector health, ops status, and dashboard rendering.

### Remaining validation gaps

- No end-to-end live proof that a market can be discovered, verified, ingested, analyzed, displayed, audited, reconciled against official settlement, and operated for weeks without manual repair.
- No broad recorded-payload fixture suite covering real NOAA/NWS/METAR/Kalshi variations, missing fields, corrections, out-of-order records, daylight-saving transitions, or unit conversions.
- No live-network validation should be inferred from mocked collector tests.
- No validated station-metadata layer from authoritative station-history sources for distance, elevation, source class, water exposure, and station changes.
- No benchmark showing forecast error by model, regime, bucket, or time of day on sufficient historical data.
- No calibration report proving probability outputs are reliable out of sample.
- No production security tests for full authentication, authorization, session handling, least-privilege deployment, or accidental exposure.
- No operational soak tests for scheduler failures, retry behavior, database locks, backup/restore drills, disk-full conditions, external alert routing, or alert fatigue.

## Prioritized future improvements

### P0: External verification and live operational proof

- Verify market-specific settlement rules for each real ticker before actionability language is shown.
- Install and soak scheduled collector orchestration with tested retry/backoff, rate-limit handling, latency metrics, alert routing, and idempotency.
- Run paper-live for multiple weeks and reconcile predictions, features, market snapshots, settlement replays, and official outcomes.
- Extend backup/restore operations with reviewed scheduling, migration safeguards, retention policy, disk-space checks, verified backups, pruning review, and restore drills.

### P1: Production-grade auth, deployment, and security

- Replace the local env-token gate with real authentication and authorization for dashboard/API access.
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
- Add actual satellite/cloud image processing for morning cloud cover, Puget Sound stratus extent, fog presence, and burn-off timing.
- Extend weather-regime extraction with authoritative station metadata, sunrise/solar features, dew point, wind, pressure, and cloud ceiling snapshots.

### P4: Historical backfill and calibration

- Backfill observations, model forecasts, market prices, official outcomes, prediction snapshots, settlement replays, and weather-regime tags.
- Create conditional bias tables by model, station, season, forecast hour, marine-layer regime, heat regime, and persistent-cloud regime.
- Include sample size, recency, confidence interval, and holdout performance for every bias adjustment.
- Protect against leakage by separating training data from evaluation dates.
- Train transparent baselines first, then consider gradient-boosted probability models only after clean history exists.

### P5: Dashboard workflow refinement

- Continue improving research workflow sections for rule verification, settlement replay, collector health, weather/nowcast features, calibration, market comparison, paper-live status, ops status, and audit events.
- Add clear status chips: demo/manual-live/replay/paper-live/production-live, rule verified/unverified, stale/fresh, source match/mismatch, calibrated/uncalibrated.
- Add drill-down pages for raw observations, forecast discussions, model runs, market prices, hypotheses, official outcomes, settlement replays, and calibration diagnostics.
- Add exportable daily research reports with provenance and caveats.

### P6: Compliance controls and optional trading-adjacent tooling

- Add compliance checklist templates for market eligibility, data licenses, account permissions, and organizational policy.
- Add configurable position-limit placeholders, daily-loss placeholders, and correlated-exposure placeholders only after legal/compliance review.
- Add paper-trading or decision-journal features before any broker/order API integration.
- If order-entry tooling is ever considered, require explicit human approval, kill switch, audit logs, restricted credentials, pre-trade checks, and separate review.
- Keep automated trading disabled unless a future, separately approved design proves controls, compliance, and operational safety.

## Acceptance criteria by phase

### Phase 1: Local precision foundation — implemented and validated

The repository meets the local foundation bar when:

- A developer can initialize the database, seed demo data, run collector/import/settlement/nowcast/backfill/calibration/paper-live helper commands, start the local app, and view the dashboard without private external services.
- Demo data is unmistakably labeled and cannot be mistaken for live market or weather data.
- The dashboard shows source/provenance, station metadata, market-rule verification, settlement replay, collector health, weather/nowcast features, calibration/backfill scaffolding, paper-live status, ops status, caveats, and automated-trading-disabled warnings.
- Documentation clearly states that user-verified real rules, live Kalshi ingestion, licensed weather feeds, actual satellite processing, deep historical calibration, long-running soak, compliance review, production auth/deployment, and automated trading are not present.
- Local tests, compile checks, CLI smoke checks, and FastAPI endpoint smoke checks pass.
- No financial recommendation, guaranteed arbitrage language, or automated action is presented.

### Phase 2: Live research product — not yet complete

The product is fully working as a live research tool only when:

- Each tracked market has verified settlement source, station/product, units, rounding, cutoff, fallback, and correction policy.
- Live collectors ingest verified official-source observations, relevant proxy observations, model guidance, and permitted Kalshi market data with timestamps and provenance.
- Collector health, latency, retry behavior, stale-data flags, and source mismatch warnings are visible and monitored.
- Demo/replay/manual-live/paper-live records are separated in storage and UI.
- Raw payloads or hashes, normalized rows, settlement replays, and audit logs support reproducibility.
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

Trading-adjacent tooling is acceptable only when all prior phases are stable and explicit legal/compliance/security review approves it. Automated betting and order entry are not implemented and should remain disabled unless a separate future design proves controls, credential safety, kill switches, auditability, limits, monitoring, and human approval.
