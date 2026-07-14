# Copilot instructions for Kalshi Temps

Kalshi Temps is a Python/FastAPI + SQLite research product for Seattle daily high-temperature evidence. The goal is decision support and recordkeeping for Kalshi climate-market research, not guaranteed arbitrage or unattended trading.

## Core engineering practices

- Prefer small, well-tested, dependency-light changes. Use the Python standard library where practical.
- Keep runtime data out of source control. The default local database is `data/kalshi_temps.sqlite3`, configurable with `KALSHI_TEMPS_DB`.
- Preserve provenance for every collected value: source name, endpoint or URL, station/product identifier, observation/valid/issue time, ingest time, raw payload or hash, parser status, and QC notes.
- Do not silently coerce or ignore malformed weather/market inputs. Raise clear errors, log explicit app events, or mark records stale/invalid using existing patterns.
- Keep domain logic deterministic and testable in pure modules where possible. FastAPI routes should orchestrate repository/domain calls rather than embedding calculations.
- Maintain a clear separation between raw observations, normalized records, derived features, hypotheses, and market snapshots.
- Add or update tests for new behavior. Prefer focused unit tests for parsers/fusion utilities and integration tests for SQLite + FastAPI routes.
- Avoid unnecessary casts, broad exception handlers, hidden fallbacks, and success-shaped defaults.
- Do not add automated betting behavior unless explicitly requested and accompanied by compliance, risk-control, and human-confirmation design.

## Existing project shape

- App: `src/kalshi_temps/app.py`
- SQLite schema and migration helpers: `src/kalshi_temps/db.py`
- Repository layer: `src/kalshi_temps/repository.py`
- Demo seed data: `src/kalshi_temps/seed.py`
- CLI: `src/kalshi_temps/cli.py` via `python -m kalshi_temps`
- Dashboard template and styles: `templates/dashboard.html`, `static/styles.css`
- Planning docs: `docs/`

Useful commands:

```bash
PYTHONPATH=src python -m kalshi_temps init-db
PYTHONPATH=src python -m kalshi_temps seed-demo
PYTHONPATH=src uvicorn kalshi_temps.app:app --host 127.0.0.1 --port 8000
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src pytest
```

## Weather-research guidance

Approach Seattle daily high prediction as a data-fusion problem. A strong weather researcher would treat disagreement, timing, metadata, and uncertainty as first-class signals.

### 1. Verify settlement before analysis

- Always verify the market-specific Kalshi settlement rule before treating a signal as actionable.
- Record station, product, source, time zone, daily cutoff, rounding behavior, correction/fallback rules, and rule verification timestamp.
- Treat the KSEA / Weather Underground settlement claim as a hypothesis until confirmed in the specific market text.

### 2. Forecast models: preserve disagreement

- Collect raw guidance rather than relying on consumer weather blends.
- Track HRRR, NAM, GFS, NBM, ECMWF where licensed, and GraphCast/AI products where available.
- Store run time, model cycle, valid date/time, target date, predicted high, source URL, provenance, and notes.
- Model spread is a signal. Do not average it away without also surfacing spread, run-to-run change, and regime context.

### 3. Seattle marine layer is central

- For Seattle, morning marine clouds/fog/stratus burn-off timing can move the final high by multiple degrees.
- Prioritize 8-10 AM local updates: visible satellite trends, cloud ceiling, cloud cover, Puget Sound fog, marine push, wind shift, dew point, pressure, and solar radiation.
- Encode whether the marine layer cleared before 10 AM as a feature, not a narrative-only note.

### 4. Observations need station discipline

- Track the verified settlement station first, then KSEA and surrounding ASOS/AWOS/METAR/NWS stations as context.
- Personal Weather Stations are low-trust context unless calibrated; label them accordingly.
- Watch for station mismatch, elevation difference, water exposure, rooftop/urban heat-island effects, sensor outages, frozen values, implausible jumps, and timestamp ambiguity.
- METAR values may be rounded and may miss intrahour extremes; do not treat them as official daily highs unless the market settles on that exact product.

### 5. Build historical bias by regime

- Store predicted high versus official actual high for each model and day.
- Segment errors by weather regime: marine layer, offshore flow, heat wave, persistent clouds, season, and time of day.
- Prefer calibrated bias tables and transparent rules before complex models.
- Example hypothesis to test: HRRR may overestimate highs when marine clouds persist after 10 AM.

### 6. Intraday nowcasting

- Generate recurring 7 AM, 9 AM, 11 AM, and noon snapshots.
- Include current temperature, intraday max, warming rate, dew point, wind, pressure, cloud trend, yesterday comparison, model spread, and bucket probabilities.
- Express output as a probability distribution over temperature buckets, not a single “answer.”

### 7. Market data is another signal, not truth

- Convert bid/ask/mid prices to implied probabilities by bucket.
- Compare market-implied distributions to model/research distributions and show deltas.
- Use cautious language: “research edge,” “probability delta,” or “expected-value candidate,” never “guaranteed arbitrage.”
- Always surface stale-data, unverified-rule, wide-spread, and proxy-only guards before any decision support.

## Dashboard and UX expectations

- Optimize for phone readability over Tailscale: concise cards, clear status labels, minimal dense tables, and visible timestamps.
- The dashboard should answer: what is the current observed high, how fresh are sources, how much do models disagree, what is the marine-layer status, what buckets are implied by the market, and what caveats block action?
- Demo data must be visibly distinguishable from live data once live ingestion exists.
- Never hide settlement-source uncertainty or stale-source status behind a “green” UI.

## Documentation expectations

- Update docs when behavior, schema, commands, or risk posture changes.
- Keep `docs/shortcomings-and-roadmap.md` honest about missing ingestion, calibration, live market data, authentication, deployment, and compliance controls.
- Document assumptions and future work explicitly rather than implying the product is complete when it is only demo/local research capable.

## Safety and compliance

- This repository must not provide financial advice.
- Do not commit secrets, API keys, account identifiers, private exports, or paid/licensed data.
- Do not expose the dashboard publicly without authentication, authorization, and data-handling review.
- Tailscale/tailnet access should default to private access; distinguish Tailscale Serve from Funnel and warn before public exposure.
- Automated trading requires explicit human approval, risk limits, audit logs, compliance review, and separate implementation instructions.
