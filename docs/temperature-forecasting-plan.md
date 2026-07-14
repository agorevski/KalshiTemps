# Seattle Current-Day High Temperature Research Plan

Purpose: document a cautious data-fusion methodology for estimating Seattle's current-day high temperature before the official NOAA-derived value used by a Kalshi market is released. This is planning documentation only, not app code or trading advice.

## 1. Settlement Rule First

Do not treat any signal as actionable until each market contract is verified and recorded:

- Kalshi ticker, title, expiration, full settlement text, and fallback/correction rules.
- Exact official temperature source, station, product, units, rounding, and daily cutoff.
- Time zone and daylight-saving handling for the settlement day.
- User-reported claim to verify: some Seattle temperature markets may settle using Weather Underground's KSEA station. Treat this only as a hypothesis until confirmed in that market's rules.

If the station/product is unverified, mark the market `not_actionable_pending_rule_verification`.

## 2. Six-Layer Seattle Data-Fusion Strategy

### Layer 1: Raw forecast models

Collect and compare raw guidance rather than averaging it away:

- HRRR hourly.
- NAM 6-hourly.
- GFS 6-hourly.
- ECMWF twice daily where available and licensed.
- GraphCast/AI daily products where available.
- NBM hourly and percentile guidance.

Model disagreement/spread is itself a signal. Wide spread should increase uncertainty, lower position confidence, and trigger human review.

### Layer 2: Marine layer and cloud evolution

Seattle highs often hinge on morning cloud/fog/stratus burn-off timing. Track:

- Visible satellite trends, Puget Sound fog, marine push, and stratus depth.
- Cloud ceiling, cloud cover, solar radiation, dew point, wind direction/speed, and pressure.
- 8-10 AM updates; a delayed burn-off can materially change the expected high by 2-6F.

### Layer 3: Actual sensor observations

Track the verified settlement station first. Also track KSEA because of the user-reported Weather Underground/KSEA settlement claim, but verify it per market. Context sources:

- KSEA ASOS/METAR/NWS observations.
- Surrounding ASOS/AWOS stations.
- NWS official observations and climate products.
- Personal Weather Stations only as lower-trust context.

Key fields: current temperature, dew point, wind direction/speed, pressure, cloud ceiling, solar radiation where available, observation time, ingest time, QC status, and intraday max.

### Layer 4: Historical biases

Store predicted high versus official actual high by model and regime. Compute conditional bias for:

- Marine layer days.
- Offshore-flow days.
- Heat waves.
- Persistent-cloud days.

Example: HRRR may overestimate highs when marine clouds persist after 10 AM. Bias tables should include sample size, recency, error distribution, and regime tags.

### Layer 5: Live intraday features

Generate 7 AM, 9 AM, and 11 AM snapshots with:

- Current temperature, dew point, wind, pressure, cloud trend, and warming rate.
- Yesterday comparison and yesterday forecast error.
- Intraday max so far.
- Sunrise time, day of year, and whether marine layer cleared before 10 AM.
- Probability of final high by settlement bucket.

### Layer 6: Market information

Convert Kalshi prices into market-implied probability distributions by temperature bucket. Compare the market distribution to the model distribution using a Bayesian-updating frame: observations and new forecasts update priors; market prices are another information source, not truth. Expected value analysis must remain subject to risk controls.

## 3. Measurement and Hypothesis Methodology

Maintain a probabilistic hypothesis, not a deterministic claim:

- Current best estimate of final official high.
- Probability for each market bucket and threshold crossing.
- Confidence interval reflecting model spread, observation uncertainty, calibration error, latency, and settlement-rule ambiguity.
- Clear caveat that early readings can be revised, lagged, biased, or from the wrong source.

Track intraday maximum using the same units, local day, and rounding assumptions as the verified settlement rule. Preserve raw records and never overwrite observations without audit history.

## 4. Sensor Quality and Proxy Weighting

Reject, downgrade, or flag observations with failed/missing QC, implausible jumps, frozen values, ambiguous timestamps, outages, maintenance, relocation, or metadata changes.

Weight proxy stations by distance, elevation, water exposure, land cover, station class, historical correlation, and regime-specific bias. Rooftop, urban heat island, and PWS data are context only unless independently calibrated.

## 5. Forecast Blending and Threshold Probabilities

Blend official observations, proxy observations, calibrated model guidance, and live marine-layer features to estimate remaining upside risk. For each threshold or bucket:

- Estimate probability and uncertainty range.
- Highlight model disagreement and regime-specific bias.
- Downgrade confidence when data are stale, spread is wide, or station/source is unverified.
- Never describe the result as guaranteed arbitrage.

## 6. Daily Data to Collect

- HRRR, ECMWF, GFS, NAM, and NBM forecast highs and run times.
- NWS forecast discussion text and hourly forecast updates.
- Sunrise cloud cover, sunrise time, day of year, and marine-layer-clear-before-10-AM flag.
- 7 AM temperature, dew point, wind, pressure, cloud ceiling, solar radiation if available.
- 9 AM and 11 AM feature snapshots.
- Yesterday's actual high, predicted high, and model error.
- Ensemble/model spread and forecast update history.
- Intraday max and latest official/proxy observations.
- Current market-implied probabilities by bucket.

## 7. ML Roadmap

Start with transparent rules, calibration tables, and regime-specific bias adjustments. Build a clean historical feature set before adding models. Future optional ML:

- Gradient-boosted trees such as XGBoost or LightGBM.
- Output probability for each temperature bucket, not just a point forecast.
- Include calibration evaluation, feature drift checks, and out-of-sample backtests.

Avoid neural nets initially; data quality, provenance, and feature consistency are more important.

## 8. Early Read and Official Update Workflow

1. Verify market rule and official source.
2. Capture forecasts, observations, and market prices throughout the day.
3. Produce pre-release hypotheses with provenance, stale-data status, and bucket probabilities.
4. Require human confirmation before any trading action.
5. Ingest the official source as a separate authoritative record after release.
6. Compare hypothesis to official result; record error drivers and calibration updates.
7. Preserve corrections and superseded values in the audit log.

## 9. SQLite Logging Fields

Recommended tables/fields:

- `markets`: ticker, title, settlement_rule_text, official_source_name, official_station_id, timezone, daily_cutoff, rule_verified_at, verification_status, notes.
- `observations`: source, station_id, observed_at_utc, observed_at_local, ingested_at_utc, temperature_f, dew_point_f, wind_dir_deg, wind_speed_mph, pressure_mb, cloud_ceiling_ft, solar_radiation_wm2, qc_flag, raw_payload_hash, latency_seconds.
- `model_forecasts`: model_name, run_time_utc, valid_time_utc, forecast_high_f, temperature_f, percentile, bucket, raw_payload_hash.
- `intraday_features`: market_ticker, snapshot_time_local, temp_f, warming_rate_f_per_hr, dew_point_f, wind_dir_deg, wind_speed_mph, pressure_mb, cloud_trend, intraday_max_f, yesterday_error_f, marine_layer_cleared_before_10am.
- `historical_bias`: model_name, regime_tag, sample_count, mean_error_f, p50_error_f, p90_abs_error_f, period_start, period_end.
- `market_probabilities`: market_ticker, captured_at_utc, bucket, bid_price, ask_price, mid_price, implied_probability.
- `hypotheses`: market_ticker, generated_at_utc, estimated_high_f, lower_f, upper_f, bucket, probability, confidence_label, stale_data_flag, rule_verified_flag.
- `source_polls`: source, polled_at_utc, status_code, success, records_returned, newest_observation_at_utc, error_message.
- `audit_log`: event_at_utc, actor, event_type, entity_type, entity_id, old_value, new_value, reason.
