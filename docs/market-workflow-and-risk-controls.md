# Market Workflow and Risk Controls

This workflow supports analysis of Kalshi climate/temperature markets. It must not present early temperature reads as guaranteed arbitrage or automate betting by default.

## Pre-Market Checklist

- Read and save the full Kalshi settlement rule.
- Verify the exact source, station, product, time zone, rounding, and fallback rule; specifically verify any claim that Seattle markets settle using Weather Underground's KSEA station.
- Confirm NOAA/NWS, Weather Underground, model, satellite, and market-price data availability and latency.
- Identify temperature buckets and contract units.
- Define stale-data thresholds, human-review triggers, position-limit placeholders, and compliance checks.

## Intraday Data-Fusion Workflow

1. Ingest raw model guidance: HRRR hourly, NAM/GFS 6-hourly, ECMWF twice daily where licensed, GraphCast/AI where available, and NBM hourly/percentiles.
2. Measure model spread and run-to-run changes; treat disagreement as uncertainty signal.
3. Track marine-layer evolution using visible satellite, fog/stratus indicators, cloud ceiling, marine push, and 8-10 AM burn-off updates.
4. Poll actual sensors: verified settlement station, KSEA, ASOS/AWOS/METAR, nearby stations, and PWS as low-trust context.
5. Build 7 AM, 9 AM, and 11 AM snapshots: current temp, dew point, wind, pressure, warming rate, cloud trend, yesterday comparison, intraday max, and bucket probabilities.
6. Apply historical bias tables by regime: marine layer, offshore flow, heat wave, and persistent clouds.
7. Convert Kalshi bid/ask/mid prices to market-implied probability distributions by bucket.
8. Compare model distribution to market distribution using Bayesian updating and expected-value framing.
9. Present provenance, caveats, stale-data status, and risk checks for human review.

## Post-Official Workflow

- Ingest the official settlement source as a separate authoritative record.
- Reconcile official high with early hypotheses, market-implied probabilities, and model distributions.
- Record error drivers such as late marine-layer burn-off, HRRR overestimate after persistent clouds, station mismatch, or stale data.
- Update historical bias tables only after verifying the official result.
- Preserve audit history for all hypotheses, observations, market snapshots, and manual decisions.

## ML Roadmap

Start simple:

1. Rules and manually reviewed regime flags.
2. Bias/calibration tables by model and weather regime.
3. Clean historical feature set with daily forecasts, observations, market prices, and official outcomes.
4. Future optional gradient-boosted trees such as XGBoost or LightGBM.

Models should output probability for each temperature bucket, not only a point forecast. Prioritize calibration, out-of-sample evaluation, and feature quality over neural nets.

## Risk Controls

- **No guaranteed arbitrage language**: use probabilities, uncertainty ranges, and expected-value caveats.
- **No automated betting by default**: analysis should not place orders without explicit human approval and compliance review.
- **Settlement-source guard**: block actionable output if source/rule is unverified or the KSEA/Weather Underground claim is unconfirmed.
- **Stale-data guard**: block or downgrade signals when observations, forecasts, satellite features, or market prices exceed freshness limits.
- **Model-spread guard**: increase uncertainty and require review when HRRR/NAM/GFS/ECMWF/NBM disagree materially.
- **Source-mismatch guard**: warn when data are from proxy stations, PWS, or different products.
- **Human confirmation**: require review of source, timestamp, bucket, probability, proposed action, and compliance status.
- **Position limits**: configure placeholders for bankroll percentage, per-market exposure, daily loss, and correlated market exposure.
- **Auditability**: log inputs, transformations, hypothesis versions, user confirmations, and final outcomes.
- **Compliance checks**: review Kalshi terms, regulatory constraints, data licenses, and organizational policies before trading.

## SQLite Decision and Risk Fields

Recommended fields:

- `decision_snapshots`: market_ticker, created_at_utc, threshold_f, bucket, latest_official_obs_at_utc, running_high_f, estimated_final_high_f, probability_bucket, probability_ge_threshold, confidence_interval_low_f, confidence_interval_high_f, stale_data_flag, rule_verified_flag, source_mismatch_flag, model_spread_f.
- `daily_features`: market_ticker, date_local, hrrr_high_f, ecmwf_high_f, gfs_high_f, nam_high_f, nbm_high_f, nws_discussion_text_hash, sunrise_cloud_cover, sunrise_time_local, seven_am_temp_f, seven_am_dew_point_f, seven_am_wind_dir_deg, seven_am_wind_speed_mph, seven_am_pressure_mb, yesterday_error_f, ensemble_spread_f, marine_layer_cleared_before_10am, day_of_year.
- `forecast_update_history`: market_ticker, model_name, run_time_utc, forecast_high_f, bucket_probabilities_json, ingest_time_utc.
- `market_implied_probabilities`: market_ticker, captured_at_utc, bucket, bid_price, ask_price, mid_price, implied_probability.
- `risk_checks`: snapshot_id, check_name, status, severity, message, checked_at_utc.
- `human_confirmations`: snapshot_id, user_id, confirmed_at_utc, decision, notes.
- `position_limits`: market_ticker, bankroll_limit_pct, market_exposure_limit_usd, daily_loss_limit_usd, correlated_exposure_limit_usd, active_from_utc, active_to_utc.
- `outcomes`: market_ticker, official_value_f, official_source, official_released_at_utc, settled_at_utc, hypothesis_error_f, postmortem_notes.
