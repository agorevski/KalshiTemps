# SQLite Schema Reference

This reference summarizes the current SQLite schema for the local Kalshi Temps implementation and the concise extensions still planned for production-depth operation. Field names map to repository methods, ingestion jobs, dashboard sections, and future migrations.

## Schema conventions

- Use `INTEGER PRIMARY KEY AUTOINCREMENT` for local row IDs unless a natural key is reliable.
- Store canonical timestamps as ISO-8601 text; prefer UTC for ingestion and add local-market fields where settlement-day logic requires them.
- Preserve source provenance through source IDs, URLs, raw payload text, or raw payload hashes.
- Use `INTEGER` for booleans in SQLite: `0` false, `1` true, `NULL` unknown.
- Keep raw evidence separate from derived records.
- Include verification and stale-data fields where a row could influence a research conclusion.

## Current tables and views

### `data_sources`

Tracks weather, model, market, and manual providers.

Current fields: `id`, `name`, `source_type`, `url`, `notes`, `last_seen_at`, `created_at`.
Useful extensions: `trust_tier`, `requires_license`, and stronger active/permission status fields.

### `observations`

Stores station observations and current-day sensor evidence for KSEA/proxy verification and intraday nowcasting.

Current fields: `id`, `source_id`, `station`, `observed_at`, `temperature_f`, `dew_point_f`, `wind_direction_deg`, `wind_speed_mph`, `pressure_mb`, `cloud_ceiling_ft`, `solar_radiation_wm2`, `raw_payload`, `created_at`.
Current uniqueness: `(source_id, station, observed_at)`.
Useful extensions: explicit UTC/local timestamps, market bridge, QC/stale flags, source rank, payload hash.

### `station_metadata`

Stores imported station metadata for official-vs-proxy discipline.

Current fields: `id`, `station_id`, `name`, `network`, `latitude`, `longitude`, `elevation_m`, `timezone`, `source_class`, `water_exposure`, `land_cover`, `active_from`, `active_to`, `metadata_hash`, `raw_payload`, `created_at`, `updated_at`.
Current uniqueness: `station_id`.
Useful extensions: authoritative station-history source, move/maintenance events, sensor type, source-license fields, and quality tier.

### `official_observations`

Stores public official-source station observations imported or collected for settlement/source research.

Current fields: `id`, `source_id`, `station_metadata_id`, `source_poll_id`, `station`, `observed_at`, `temperature_f`, `dew_point_f`, `wind_direction_deg`, `wind_speed_mph`, `pressure_mb`, `cloud_ceiling_ft`, `source_url`, `provenance_hash`, `qc_status`, `qc_report`, `raw_payload`, `created_at`.
Current uniqueness: `(station, observed_at, source_id)`.
Useful extensions: market ticker, official product family, release/correction timestamp, and source-specific QC flags.

### `forecast_discussions`

Stores collected public NWS forecast-discussion text and parser metadata.

Current fields: `id`, `source_id`, `product_id`, `issued_at`, `ingest_at`, `source_url`, `text`, `text_hash`, `raw_payload_hash`, `parser_status`, `parser_notes`, `created_at`.
Current uniqueness: `(product_id, ingest_at, text_hash)`.

### `source_polls` / `collector_runs` view

Records one-shot collector attempts and powers collector health. `collector_runs` is a compatibility view over `source_polls`.

Current fields: `id`, `source`, `collector_name`, `started_at`, `finished_at`, `status`, `records_returned`, `newest_observation_at`, `latency_seconds`, `error_message`, `source_url`, `payload_hash`, `created_at`.
Useful extensions: scheduler run IDs, retry count, HTTP status, alert state, and operator acknowledgement.

### `market_rules`

Stores market-specific settlement metadata and verification state.

Current fields: `id`, `ticker`, `title`, `settlement_rule_text`, `official_source_name`, `official_station_id`, `product`, `timezone`, `daily_cutoff`, `units`, `rounding`, `fallback_policy`, `correction_policy`, `verification_status`, `verified_by`, `verified_at`, `source_url`, `notes`, `created_at`, `updated_at`.
Rules are research inputs only until complete and verified per ticker by the user or another trusted process; they do not imply trading approval.

### `market_snapshots`

Stores market price snapshots and market-implied probability inputs.

Current fields: `id`, `market_ticker`, `temperature_bucket`, `captured_at`, `yes_bid_cents`, `yes_ask_cents`, `no_bid_cents`, `no_ask_cents`, `last_price_cents`, `implied_probability`, `settlement_source_note`, `raw_payload`.
Useful extensions: permitted live Kalshi metadata, order-book depth, volume/open interest, spread fields, distribution set IDs, source/license provenance, and explicit stale/liquidity warnings.

### `model_runs`

Stores manual or adapter-normalized forecast-model high records for HRRR/NAM/GFS/NBM-style research inputs.

Current fields: `id`, `run_at`, `model_name`, `model_cycle`, `valid_at`, `forecast_hour`, `valid_date`, `target_date`, `extraction_lat`, `extraction_lon`, `extraction_station`, `extraction_gridpoint`, `predicted_high_f`, `confidence`, `source_url`, `provenance`, `hourly_temperatures`, `percentiles`, `raw_payload_hash`, `notes`.
Useful extensions: market linkage, source-specific product IDs, ensemble-member details, license/permission status, and richer hourly/percentile child records.

### `model_run_extractions`

Stores extraction metadata for model runs.

Current fields: `id`, `model_run_id`, `extraction_lat`, `extraction_lon`, `extraction_station`, `extraction_gridpoint`, `metadata_json`, `created_at`.
Current uniqueness: `model_run_id`.

### `model_run_deltas`

Stores run-to-run model forecast changes.

Current fields: `id`, `model_run_id`, `previous_model_run_id`, `model_name`, `target_date`, `run_at`, `previous_run_at`, `predicted_high_f`, `previous_predicted_high_f`, `change_f`, `created_at`.
Current uniqueness: `model_run_id`.

### `model_probability_buckets`

Stores model-derived bucket probabilities.

Current fields: `id`, `model_run_id`, `temperature_bucket`, `probability`, `created_at`.
Current uniqueness: `(model_run_id, temperature_bucket)`.
Useful extensions: bucket bounds, inclusivity flags, calibration version, and source probability type.

### `model_spread`

Stores model disagreement summaries.

Current fields: `id`, `target_date`, `calculated_at`, `min_high_f`, `max_high_f`, `mean_high_f`, `spread_f`, `model_count`, `min_model_name`, `max_model_name`, `run_change_count`, `mean_run_change_f`, `max_abs_run_change_f`, `run_change_details`, `notes`.
Useful extensions: station/market linkage, percentiles, standard deviation, included-run references, and review-required flags.

### `marine_layer_indicators`

Stores marine-layer and cloud-evolution signals.

Current fields: `id`, `source_id`, `observed_at`, `cloud_cover_pct`, `ceiling_ft`, `satellite_trend`, `marine_layer_cleared_before_10am`, `notes`, `created_at`.
Useful extensions: UTC/local fields, target date, fog/stratus depth, wind shift, burn-off time, solar radiation, regime tag, and confidence label.

### `cloud_features`

Stores imported manual/derived cloud satellite proxy records. This is not actual satellite image processing.

Current fields: `id`, `source`, `observed_at`, `cloud_cover_pct`, `stratus_extent_pct`, `fog_present`, `burnoff_status`, `burnoff_time`, `confidence`, `source_url`, `source_hash`, `notes`, `raw_features`, `created_at`.
Current uniqueness: `(source, observed_at, source_hash)`.
Useful extensions: image asset references, processing algorithm/version, geospatial extent, and license metadata once actual image processing is implemented.

### `weather_regime_features`

Stores deterministic regime features extracted from saved or supplied forecast discussions.

Current fields: `id`, `forecast_discussion_id`, `source_id`, `product_id`, `issued_at`, `extracted_at`, `regime_tags`, `confidence_label`, `evidence`, `raw_features`, `created_at`.
Current uniqueness: `(forecast_discussion_id, extracted_at)`.

### `intraday_features`

Stores intraday nowcasting feature snapshots.

Current fields: `id`, `source_id`, `station`, `snapshot_at`, `local_snapshot_time`, `day_of_year`, `current_temp_f`, `intraday_max_f`, `warming_rate_f_per_hour`, `dew_point_f`, `wind_direction_deg`, `wind_speed_mph`, `pressure_mb`, `cloud_ceiling_ft`, `cloud_trend`, `marine_layer_cleared_before_10am`, `raw_features`, `created_at`.
Current uniqueness: `(station, snapshot_at)`.
Useful extensions: market ticker, sunrise/solar fields, previous-day error, remaining-upside estimate, and stale flags.

### `nowcast_snapshots`

Stores fixed-hour evidence-only nowcast signals.

Current fields: `id`, `station`, `snapshot_at`, `local_snapshot_time`, `target_date`, `snapshot_hour_local`, `current_temp_f`, `intraday_max_f`, `warming_rate_f_per_hour`, `dew_point_f`, `wind_direction_deg`, `wind_speed_mph`, `pressure_mb`, `cloud_ceiling_ft`, `visibility_miles`, `solar_radiation_wm2`, `solar_proxy`, `cloud_trend`, `ceiling_trend`, `wind_shift`, `marine_push_indicator`, `remaining_solar_window_proxy`, `remaining_upside_distribution`, `data_status`, `raw_snapshot`, `created_at`.
Current uniqueness: `(station, snapshot_at)`.
Useful extensions: calibrated remaining-upside distributions, source completeness metrics, and model-nowcast ensemble linkage.

### `official_outcomes`

Stores manual official daily high outcomes for later reconciliation and calibration.

Current fields: `id`, `station`, `target_date`, `high_temperature_f`, `source_name`, `observed_at`, `notes`, `raw_payload`, `created_at`.
Current uniqueness: `(station, target_date)`.
Useful extensions: market ticker, official product, release timestamp, rounding/correction metadata, and payload hash.

### `settlement_replays`

Stores deterministic replays of official outcomes against market rules.

Current fields: `id`, `ticker`, `target_date`, `official_outcome_id`, `status`, `settlement_bucket`, `bucket_matched`, `mismatch_reasons`, `reconciliation_error`, `official_value`, `official_units`, `normalized_value`, `rounded_value`, `evaluation_units`, `source_url`, `official_source_name`, `raw_payload_hash`, `raw_official_payload`, `first_published_value`, `corrected_value`, `correction_applied`, `fallback_used`, `replayed_at`, `rule_version`, `market_rule_verified`, `replay_result_json`, `created_at`, `updated_at`.
Current uniqueness: `(ticker, target_date, raw_payload_hash, rule_version)`.
Useful extensions: immutable market-rule version table, explicit review/approval workflow, and correction-window lifecycle state.

### `prediction_snapshots`

Stores manual prediction or hypothesis snapshots used by calibration summaries.

Current fields: `id`, `snapshot_at`, `model_name`, `station`, `target_date`, `regime`, `predicted_high_f`, `temperature_bucket`, `probability`, `hypothesis`, `source_name`, `notes`, `raw_payload`, `created_at`.
Useful extensions: market ticker, research distribution ID, source mix, rule/stale flags, and append-only review status.

### `backfill_runs`

Stores frozen fixture replay/backfill attempts.

Current fields: `id`, `source_path`, `source_hash`, `status`, `counts_json`, `errors_json`, `started_at`, `finished_at`, `created_at`.
Useful extensions: fixture manifest version, data coverage summary, train/test split markers, and reproducibility metadata.

### `historical_bias`

Stores computed local bias summaries from saved prediction snapshots and official outcomes.

Current fields: `id`, `computed_at`, `model_name`, `regime`, `station`, `sample_count`, `mean_error_f`, `mean_absolute_error_f`, `rmse_f`, `warm_bias_count`, `cool_bias_count`, `exact_count`, `notes`.
These summaries are scaffolding until sufficient historical backfill exists.

### `calibration_metrics`

Stores bucket calibration metrics computed from local prediction snapshots and outcomes.

Current fields: `id`, `computed_at`, `model_name`, `station`, `temperature_bucket`, `sample_count`, `brier_score`, `reliability_bins_json`, `notes`.
These metrics should not be represented as production-calibrated ML without enough clean history and holdout evaluation.

### `paper_live_runs` and child tables

Store no-betting paper-live run records, checklists, notes, reconciliation/postmortems, and soak metrics.

- `paper_live_runs`: `id`, `run_name`, `station`, `target_date`, `started_at`, `closed_at`, `status`, `notes`, `created_at`, `updated_at`.
- `paper_live_checklist_entries`: `id`, `run_id`, `checklist_date`, `item`, `status`, `notes`, `recorded_at`.
- `paper_live_prediction_notes`: `id`, `run_id`, `target_date`, `predicted_high_f`, `probability_bucket`, `confidence`, `note`, `recorded_at`.
- `paper_live_reconciliation_notes`: `id`, `run_id`, `note_type`, `target_date`, `note`, `recorded_at`.
- `paper_live_soak_metrics`: `id`, `run_id`, `measured_at`, `uptime_status`, `collector_success_count`, `collector_failure_count`, `backup_success`, `alert_count`, `notes`.

These tables record research notes only; they do not enable betting or order entry.

### `app_events`

Stores operational and audit events.

Current fields: `id`, `event_type`, `message`, `severity`, `source_name`, `provenance_url`, `is_stale`, `created_at`.
Useful extensions: market ticker, entity references, actor, old/new values, reason, and correlation ID.

## Planned/normalized tables

These remain future schema work rather than current production capability:

- `markets`: normalized Kalshi market metadata and settlement rule bridge when live metadata ingestion is permitted.
- `market_probability_buckets`: grouped live market-implied distributions with liquidity/spread fields.
- `hypotheses` and `hypothesis_probability_buckets`: append-only research distributions, caveats, and bucket probabilities.
- `risk_checks`: explicit actionability blockers for rule verification, stale data, source mismatch, wide spread, liquidity, and automated-betting-disabled status.
- `historical_bias_observations`: daily model-vs-official error rows feeding deeper bias tables.
- `audit_log`: durable manual edit/correction history with actor and reason fields.
- Production auth/session/role tables only if the app moves beyond local env-token gating.

## Relationship map

- `data_sources` owns many `observations`, `official_observations`, `forecast_discussions`, `marine_layer_indicators`, `weather_regime_features`, and `source_polls`.
- `station_metadata` can link official observations to station/source context.
- `market_rules` and future `markets` gate actionability for `market_snapshots`, `settlement_replays`, probability comparisons, and risk checks.
- `model_runs` owns `model_probability_buckets`, `model_run_extractions`, and `model_run_deltas`; `model_spread` summarizes runs for a target date.
- `official_outcomes` and `prediction_snapshots` feed `historical_bias` and `calibration_metrics`.
- `backfill_runs` records fixture replay attempts that may populate observations, model runs, outcomes, snapshots, and calibration inputs.
- `paper_live_runs` owns paper-live checklist, prediction, reconciliation, and soak records.
- `app_events` records operational/audit facts until a richer `audit_log` exists.

## Migration priorities

1. Keep market-rule verification required before any actionable language or live market use.
2. Harden `source_polls`, freshness/risk events, backups, and paper-live soak records before scheduled ingestion.
3. Normalize market and research probability buckets so market-implied and model/research distributions can be compared directly.
4. Deepen intraday, marine-layer, cloud, and station-metadata features for nowcasting.
5. Add official-result, settlement-replay, and historical-bias detail before ML or calibration claims.
6. Add audit log entries for manual overrides, corrections, and changed verification statuses.
7. Add production-grade auth/deployment schema only if external deployment becomes an approved goal.
