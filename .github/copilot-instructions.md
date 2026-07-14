# Copilot instructions for Kalshi Temps

Kalshi Temps is a Python 3.11/FastAPI + SQLite research product for Seattle daily high-temperature evidence and Kalshi climate-market decision support. It is a local/demo research and recordkeeping tool unless live collectors, calibration, authentication, deployment, and compliance controls are explicitly implemented and verified. Never imply guaranteed arbitrage, financial advice, or unattended trading.

## Core commands

Run commands from the repository root. Use `PYTHONPATH=src` unless the package is installed editable.

```bash
PYTHONPATH=src python -m kalshi_temps init-db
PYTHONPATH=src python -m kalshi_temps seed-demo
PYTHONPATH=src uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src pytest
```

Use `KALSHI_TEMPS_DB` to override the default local database path, `data/kalshi_temps.sqlite3`. Keep runtime data under `data/` out of source control.

## Architecture map

- `src/kalshi_temps/app.py` — FastAPI app, dashboard routes, read-only JSON endpoints, health checks, startup DB initialization. Keep routes thin.
- `src/kalshi_temps/db.py` — SQLite connection, schema initialization, lightweight column migrations. Enable foreign keys per connection.
- `src/kalshi_temps/repository.py` — repository boundary for direct SQL. Return plain dictionaries or typed records; avoid burying domain policy in SQL helpers.
- `src/kalshi_temps/ingest.py` — deterministic normalization, provenance hashes, and fetch helpers/stubs for future collectors.
- `src/kalshi_temps/fusion.py` — pure data-fusion utilities: model spread, market-implied probability conversion, freshness checks, and risk guards.
- `src/kalshi_temps/seed.py` — visibly demo-only sample data.
- `src/kalshi_temps/cli.py` / `python -m kalshi_temps` — local DB and demo-data commands.
- `templates/dashboard.html`, `static/styles.css` — local/mobile-first dashboard UI.
- `tests/` — focused unit tests for pure utilities and integration tests for FastAPI + SQLite.
- `docs/` — planning, source, schema, Tailscale, roadmap, and safety documentation.

## Engineering standards

- Prefer small, dependency-light, well-tested changes. Use the standard library where practical.
- Keep domain logic deterministic and testable in pure modules. FastAPI handlers should orchestrate repository/service calls rather than calculate forecasts or parse payloads inline.
- Keep raw observations, normalized records, derived features, hypotheses, market snapshots, and official outcomes separate.
- Do not silently coerce or ignore malformed weather/market inputs. Raise clear `ValueError`s, log explicit app events, or mark records stale/invalid using existing patterns.
- Avoid broad exception handlers, hidden fallbacks, unnecessary casts, success-shaped defaults, and network-dependent tests.
- Preserve backward-compatible SQLite initialization where possible. Add indexes and schema fields deliberately, and document schema/risk changes.
- Add/update tests for behavior changes: pure parser/fusion unit tests first; SQLite/FastAPI integration tests for persistence or routes.

## Data and provenance rules

For every collected or derived value, preserve enough metadata to audit the conclusion:

- source name/type, endpoint or URL, license/terms note when relevant;
- station/product/location identifier and source class;
- observation time, valid time, issue time, ingest/capture time, and local-day interpretation when settlement depends on it;
- raw payload or stable raw-payload hash, normalized values, units, conversion method, parser status, QC flags/notes, and stale-data status.

Use UTC for canonical timestamps where possible, plus Seattle/local-market timestamps where daily cutoff, DST, or settlement wording matters. Treat demo, replay, paper-live, and live records as distinct states; never mix them without durable labeling.

## Weather and market-research rules

- Verify the market-specific Kalshi settlement rule before treating a signal as actionable. Record source, station, product, time zone, daily cutoff, units, rounding, fallback/correction rules, and verification timestamp.
- Treat any KSEA / Weather Underground settlement claim as a hypothesis until confirmed in the exact market text.
- Preserve forecast disagreement. Store HRRR, NAM, GFS, NBM, ECMWF only where licensed, and AI/GraphCast-style products only where access and validation are legitimate. Surface model spread and run-to-run changes; do not average away uncertainty.
- For Seattle, make marine-layer timing first-class: morning stratus/fog, visible satellite trend, cloud ceiling, marine push, wind shift, dew point, pressure, solar radiation, and whether clouds cleared before 10 AM.
- Track the verified settlement station first, then KSEA and surrounding ASOS/AWOS/METAR/NWS stations as context. Label Personal Weather Stations as low-trust unless individually calibrated.
- Do not treat METAR hourly/rounded values as official daily highs unless the market settles on that exact product.
- Build historical bias by verified outcome, model, station, season, lead time, and regime: marine layer, offshore flow, heat wave, persistent clouds, and similar tags.
- Intraday nowcasts should produce bucket probability distributions and caveats, not a single “answer.”
- Kalshi prices are another signal, not truth. Convert bid/ask/mid to implied probabilities, compare with research distributions, and surface spread, liquidity, stale-data, proxy-source, and unverified-rule guards.

## Dashboard and UX expectations

- Optimize for phone readability over private access: concise cards, obvious timestamps, status chips, and minimal dense tables.
- The dashboard should quickly answer: verified settlement status, current observed high, source freshness, model disagreement, marine-layer status, bucket probabilities, market-implied probabilities, and action-blocking caveats.
- Demo data must be unmistakably labeled. Do not display demo values as live observations, live market prices, calibrated probabilities, or official outcomes.
- Never hide stale data, settlement uncertainty, proxy-only observations, high model spread, or uncalibrated output behind a green/success UI.

## Documentation expectations

- Update docs when behavior, schema, commands, deployment posture, data semantics, or risk posture changes.
- Keep `docs/shortcomings-and-roadmap.md` honest about missing live ingestion, live Kalshi data, calibration, authentication, operations, and compliance controls.
- Prefer explicit assumptions and future work over language implying the product is production-ready.
- Do not edit `README.md` or `docs/runbook.md` unless the task specifically requires it.

## Safety and compliance boundaries

- This repository must not provide financial advice. Use language such as “research signal,” “probability delta,” or “expected-value candidate with caveats,” never “guaranteed arbitrage.”
- Do not add automated betting, order placement, account management, or execution controls unless explicitly requested and accompanied by human confirmation, risk limits, audit logging, kill-switch, credentials, and compliance-review design.
- Do not commit secrets, API keys, account identifiers, private exports, paid/licensed data, or credentials.
- Do not expose the dashboard publicly without authentication, authorization, logging, and data-handling review. Prefer loopback binding and private Tailscale/SSH access; distinguish Tailscale Serve from Funnel.
- Respect data-provider licenses, Kalshi terms, and applicable law. Keep research output auditable and challengeable.

## Do not do

- Do not claim live NOAA/NWS/METAR/model/Kalshi ingestion, calibrated ML, authentication, production deployment, or trading controls exist unless verified in code.
- Do not make “actionable” output when settlement source is unverified, data are stale, observations are proxy-only, or market data are missing.
- Do not collapse uncertainty into a single recommendation.
- Do not add heavy dependencies, hidden network calls, background schedulers, or public exposure as incidental changes.
- Do not weaken provenance, demo/live labeling, or safety caveats to make the UI look complete.
