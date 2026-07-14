# Temperature Data Sources

Use multiple sources, but rank them by settlement relevance and trust. Every source must retain provenance, raw payload metadata, and ingestion timestamps.

## Source Priority

1. **Verified Kalshi settlement source**: exact station/product named in the contract. This is authoritative once verified.
2. **KSEA observations**: track because of a user-reported claim that some Seattle markets settle using Weather Underground's KSEA station; verify against each market's settlement rule before action.
3. **Official NOAA/NWS observations and climate products** for the settlement station or KSEA.
4. **NOAA APIs and feeds**: NOAA/NWS API, Aviation Weather Center/ADDS-style METAR data, MADIS where available and appropriate.
5. **Nearby ASOS/AWOS/METAR stations**: calibrated context for local gradients.
6. **Forecast models**: HRRR hourly, NAM/GFS 6-hourly, ECMWF twice daily where licensed, GraphCast/AI daily where available, and NBM hourly/percentiles.
7. **Personal Weather Stations**: low-trust context only.
8. **Market prices**: useful as implied probabilities, not as meteorological truth.

## Official NOAA/NWS and Weather Underground/KSEA Verification

Before use, document:

- Product endpoint, station identifier, and station metadata.
- Whether the source is NOAA/NWS, Weather Underground, METAR, climate daily summary, or another product.
- Observation units, rounding, daily max definition, and correction behavior.
- Observation time, valid time, issue time, and ingest time.
- Seattle local-day cutoff and daylight-saving handling.
- QC flags, outage/fallback procedures, and latency profile.

## Forecast Model Sources

Collect model runs with run time, valid time, forecast high, hourly path, and bucket probabilities when available:

- HRRR hourly for near-term temperature, cloud, wind, and marine-layer timing.
- NAM 6-hourly for mesoscale context.
- GFS 6-hourly for synoptic trend.
- ECMWF twice daily where access and license permit.
- GraphCast/AI daily products where available.
- NBM hourly and percentile guidance for calibrated probabilistic context.

Store model spread and run-to-run changes. Disagreement is a signal for uncertainty and should not be hidden by a simple average.

## Marine Layer Sources

Seattle high-temperature edges often come from cloud timing. Collect:

- Visible satellite imagery or derived cloud-cover features.
- Fog/stratus presence over Puget Sound.
- Marine push indicators, wind shift, dew point, cloud ceiling, and stratus depth if available.
- NWS forecast discussion text mentioning marine layer, stratus, offshore flow, heat, or persistent clouds.
- 8-10 AM updates because burn-off timing can shift expected highs by 2-6F.

## Sensor Observations

For KSEA, official stations, ASOS/AWOS, METAR, and surrounding stations, record:

- Current temperature, dew point, wind direction/speed, pressure, cloud ceiling, and solar radiation if available.
- Intraday maximum and warming rate.
- Distance, bearing, elevation difference, water exposure, station type, and siting notes.
- QC status, latency, and reporting cadence.

METAR temperatures may be rounded and may miss exact daily extremes between reports. Use as evidence, not proof, unless the market explicitly settles on that product.

## Rooftop, Urban, and Personal Weather Stations

Flag rooftop, wall-mounted, dense urban heat-island, water-adjacent, shaded, or unknown-exposure sensors. PWS data should be labeled `low_trust_context` and used only for qualitative neighborhood gradients unless independently calibrated.

## Historical and Market Data

Daily historical feature collection should include:

- Model predicted highs versus actual official highs.
- Conditional regime tags: marine layer, offshore flow, heat wave, persistent clouds.
- Yesterday's forecast error, day of year, sunrise time, sunrise cloud cover, and ensemble spread.
- Forecast update history across model runs.
- Market-implied probabilities by Kalshi bucket from bid/ask/mid prices.

## Data Provenance Requirements

For each record, store source name, endpoint, station/location ID, observation/valid/issue/ingest times, raw and normalized values, units, conversion method, QC flags, parser status, raw payload hash, and license/terms notes.
