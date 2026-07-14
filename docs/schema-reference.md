# SQLite Schema Reference

This reference documents the current SQLite schema and planned tables for the Kalshi Temps implementation. It is implementation-oriented: field names should map closely to repository methods, ingestion jobs, dashboard sections, and future migrations.

## Schema conventions

- Use `INTEGER PRIMARY KEY AUTOINCREMENT` for local row IDs unless a natural key is reliable.
- Store canonical timestamps as ISO-8601 text; prefer UTC for ingestion and add local-market fields where settlement-day logic requires them.
- Preserve source provenance through source IDs, URLs, raw payload text, or raw payload hashes.
- Use `INTEGER` for booleans in SQLite: `0` false, `1` true, `NULL` unknown.
- Keep raw evidence separate from derived records.
- Include verification and stale-data fields where a row could influence an actionable research conclusion.

## Current tables

### `data_sources`

Tracks weather, model, market, and manual data providers.

Current fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Local source ID. |
| `name` | TEXT UNIQUE | Human-readable source name such as `NOAA ASOS KSEA`. |
| `source_type` | TEXT | Defaults to `weather`; planned values include `weather`, `model`, `market`, `rules`, `manual`. |
| `url` | TEXT | Source homepage or endpoint. |
| `notes` | TEXT | Provenance or usage notes. |
| `last_seen_at` | TEXT | Latest source observation/poll time known to the app. |
| `created_at` | TEXT | Insert timestamp. |

Planned additions:

- `trust_tier`: `official`, `verified_settlement`, `proxy`, `context`, `demo`.
- `station_id`: canonical station identifier where applicable.
- `requires_license`: flag for restricted sources such as some model products.
- `active`: whether ingestion jobs should poll this source.

### `observations`

Stores station observations and current-day sensor evidence. This table supports Layer 3, KSEA verification, and intraday nowcasting.

Current fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Local observation ID. |
| `source_id` | INTEGER FK | References `data_sources(id)`. |
| `station` | TEXT | Station code or label, e.g. `KSEA`. |
| `observed_at` | TEXT | Observation timestamp. |
| `temperature_f` | REAL | Observed temperature. |
| `dew_point_f` | REAL | Dew point. |
| `wind_direction_deg` | INTEGER | Wind direction. |
| `wind_speed_mph` | REAL | Wind speed. |
| `pressure_mb` | REAL | Pressure. |
| `cloud_ceiling_ft` | INTEGER | Ceiling height. |
| `solar_radiation_wm2` | REAL | Solar radiation where available. |
| `raw_payload` | TEXT | Raw source payload or serialized subset. |
| `created_at` | TEXT | Insert timestamp. |

Current uniqueness: `(source_id, station, observed_at)`.

Planned additions:

- `observed_at_utc`, `observed_at_local`, `ingested_at_utc` for explicit settlement-day handling.
- `market_ticker` or bridge table to associate observations with a market/day.
- `qc_flag`, `qc_reason`, `latency_seconds`, `is_stale`.
- `temperature_high_so_far_f` for intraday max snapshots.
- `source_rank` or trust labels for verified station, KSEA, ASOS/AWOS, PWS, and context-only data.
- `raw_payload_hash` to avoid large repeated payloads while preserving auditability.

### `market_snapshots`

Stores market price snapshots and market-implied probability inputs for Layer 6.

Current fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Local snapshot ID. |
| `market_ticker` | TEXT | Kalshi market ticker. |
| `temperature_bucket` | TEXT | Bucket label from the contract. |
| `captured_at` | TEXT | Snapshot time. |
| `yes_bid_cents` | INTEGER | Yes bid in cents. |
| `yes_ask_cents` | INTEGER | Yes ask in cents. |
| `no_bid_cents` | INTEGER | No bid in cents. |
| `no_ask_cents` | INTEGER | No ask in cents. |
| `last_price_cents` | INTEGER | Last traded price. |
| `implied_probability` | REAL | Derived probability, usually from mid or selected price convention. |
| `settlement_source_note` | TEXT | Free-text settlement/source caveat. |
| `raw_payload` | TEXT | Raw market payload or serialized subset. |

Planned additions:

- `orderbook_depth`, `volume`, `open_interest`, `bid_ask_spread_cents`, `mid_price_cents`.
- `implied_probability_bid`, `implied_probability_ask`, `implied_probability_mid`.
- `distribution_set_id` to group all bucket snapshots captured at the same time.
- `rule_verified_flag` and `not_actionable_reason` to prevent unverified-source use.

### `model_runs`

Stores raw forecast-model output for Layer 1.

Current fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Local run ID. |
| `run_at` | TEXT | Ingestion or model run timestamp. |
| `model_name` | TEXT | HRRR, NAM, GFS, ECMWF, NBM, etc. |
| `model_cycle` | TEXT | Cycle such as `12z`. |
| `valid_date` | TEXT | Forecast valid date or time. |
| `target_date` | TEXT | Local date for forecast high. |
| `predicted_high_f` | REAL | Point forecast high. |
| `confidence` | REAL | Optional source confidence or internal score. |
| `source_url` | TEXT | Provenance URL. |
| `provenance` | TEXT | Provenance description. |
| `notes` | TEXT | Human or ingestion notes. |

Planned additions:

- `market_ticker`, `station`, `lead_time_hours`, `run_at_utc`, `target_date_local`.
- `forecast_low_f`, hourly forecast fields in a child table, and percentile fields where available.
- `raw_payload_hash`, `source_id`, `ingested_at_utc`.
- `regime_tags` or child table for marine layer, offshore flow, heat wave, persistent clouds.

### `model_spread`

Stores explicit model disagreement summaries for Layer 1.

Current fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Local spread ID. |
| `target_date` | TEXT | Forecast local date. |
| `calculated_at` | TEXT | Calculation time. |
| `min_high_f` | REAL | Lowest model high. |
| `max_high_f` | REAL | Highest model high. |
| `mean_high_f` | REAL | Mean model high. |
| `spread_f` | REAL | `max_high_f - min_high_f`. |
| `model_count` | INTEGER | Number of included model runs. |
| `notes` | TEXT | Inclusion/caveat notes. |

Planned additions:

- `market_ticker`, `station`, `median_high_f`, `p25_high_f`, `p75_high_f`, `stddev_high_f`.
- `included_model_run_ids` or join table.
- `wide_spread_flag` and `review_required_flag`.
- Regime-specific spread notes, especially marine-layer disagreement.

### `marine_layer_indicators`

Stores marine-layer and cloud-evolution signals for Layer 2.

Current fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Local indicator ID. |
| `source_id` | INTEGER FK nullable | References `data_sources(id)`. |
| `observed_at` | TEXT | Observation or assessment time. |
| `cloud_cover_pct` | REAL | Cloud cover estimate. |
| `ceiling_ft` | INTEGER | Ceiling height. |
| `satellite_trend` | TEXT | Trend label or notes. |
| `marine_layer_cleared_before_10am` | INTEGER | Boolean/unknown flag. |
| `notes` | TEXT | Context and interpretation. |
| `created_at` | TEXT | Insert timestamp. |

Planned additions:

- `market_ticker`, `target_date_local`, `observed_at_utc`, `observed_at_local`.
- `fog_present`, `stratus_depth_ft`, `marine_push_flag`, `wind_shift_detected`.
- `burnoff_time_local`, `solar_radiation_wm2`, `dew_point_f`, `pressure_mb`.
- `regime_tag` and `confidence_label`.

### `model_probability_buckets`

Stores model-derived bucket probabilities for Layer 1 and the research distribution.

Current fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Local bucket row ID. |
| `model_run_id` | INTEGER FK | References `model_runs(id)`. |
| `temperature_bucket` | TEXT | Bucket label. |
| `probability` | REAL | Probability from 0 to 1. |
| `created_at` | TEXT | Insert timestamp. |

Current uniqueness: `(model_run_id, temperature_bucket)`.

Planned additions:

- `bucket_min_f`, `bucket_max_f`, `inclusive_min`, `inclusive_max`.
- `calibration_version`, `bias_adjusted_probability`.
- `source_probability_type`: raw model, calibrated model, ensemble, nowcast, or research blend.

### `app_events`

Stores operational and audit events.

Current fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Local event ID. |
| `event_type` | TEXT | Event name. |
| `message` | TEXT | Human-readable message. |
| `severity` | TEXT | Defaults to `info`. |
| `source_name` | TEXT | Optional source name. |
| `provenance_url` | TEXT | Optional source URL. |
| `is_stale` | INTEGER | Boolean stale flag. |
| `created_at` | TEXT | Event timestamp. |

Planned additions:

- `market_ticker`, `entity_type`, `entity_id`, `actor`, `old_value`, `new_value`, `reason`.
- `correlation_id` to connect a source poll, ingestion result, and dashboard warning.

## Planned tables

### `markets`

Tracks market metadata and settlement verification. This is required before any actionable output.

Planned fields:

| Field | Notes |
| --- | --- |
| `id`, `ticker`, `title` | Local ID and Kalshi identifiers. |
| `event_ticker` | Parent event where available. |
| `temperature_bucket`, `bucket_min_f`, `bucket_max_f` | Parsed contract bucket. |
| `settlement_rule_text` | Full copied rule text or hash plus provenance. |
| `official_source_name`, `official_station_id`, `official_product` | Exact source that settles the contract. |
| `timezone`, `daily_cutoff_local`, `rounding_rule`, `fallback_rule` | Local-day and rule mechanics. |
| `ksea_claim_status` | `unverified`, `confirmed`, `rejected`, `not_applicable`. |
| `verification_status`, `rule_verified_at`, `verified_by` | Actionability controls. |
| `notes`, `created_at`, `updated_at` | Audit notes. |

### `source_polls`

Records ingestion job attempts and source freshness.

Planned fields: `id`, `source_id`, `job_name`, `polled_at_utc`, `status_code`, `success`, `records_returned`, `newest_observation_at_utc`, `latency_seconds`, `error_message`, `raw_payload_hash`, `created_at`.

### `model_forecast_points`

Stores hourly or percentile model details separately from daily model run summaries.

Planned fields: `id`, `model_run_id`, `valid_at_utc`, `station`, `temperature_f`, `dew_point_f`, `wind_direction_deg`, `wind_speed_mph`, `cloud_cover_pct`, `ceiling_ft`, `percentile`, `created_at`.

### `intraday_features`

Stores Layer 5 nowcasting snapshots.

Planned fields: `id`, `market_ticker`, `snapshot_time_utc`, `snapshot_time_local`, `station`, `temp_f`, `dew_point_f`, `wind_dir_deg`, `wind_speed_mph`, `pressure_mb`, `cloud_ceiling_ft`, `solar_radiation_wm2`, `warming_rate_f_per_hr`, `intraday_max_f`, `yesterday_error_f`, `day_of_year`, `sunrise_time_local`, `cloud_trend`, `marine_layer_cleared_before_10am`, `remaining_upside_f`, `created_at`.

### `market_probability_buckets`

Stores grouped market-implied distributions by bucket. This can either extend `market_snapshots` or become the normalized target table.

Planned fields: `id`, `distribution_set_id`, `market_ticker`, `captured_at_utc`, `temperature_bucket`, `bucket_min_f`, `bucket_max_f`, `yes_bid_cents`, `yes_ask_cents`, `mid_price_cents`, `last_price_cents`, `implied_probability_bid`, `implied_probability_ask`, `implied_probability_mid`, `volume`, `open_interest`, `liquidity_warning`, `created_at`.

### `hypotheses`

Stores generated research hypotheses and probability distributions. This table should be append-only.

Planned fields: `id`, `market_ticker`, `generated_at_utc`, `target_date_local`, `estimated_high_f`, `lower_f`, `upper_f`, `confidence_label`, `research_distribution_id`, `model_spread_f`, `marine_layer_status`, `rule_verified_flag`, `stale_data_flag`, `not_actionable_reason`, `summary`, `created_at`.

### `hypothesis_probability_buckets`

Stores bucket-level probabilities for each hypothesis.

Planned fields: `id`, `hypothesis_id`, `temperature_bucket`, `bucket_min_f`, `bucket_max_f`, `probability`, `source_mix`, `bias_adjustment_f`, `created_at`.

### `risk_checks`

Stores explicit safety and actionability checks.

Planned fields: `id`, `market_ticker`, `checked_at_utc`, `check_name`, `status`, `severity`, `message`, `blocks_action`, `source_entity_type`, `source_entity_id`, `created_at`.

Required checks include settlement-source verified, KSEA claim verified/rejected, source freshness, model-spread width, market liquidity/spread, stale observations, and automated-betting disabled.

### `official_results`

Stores authoritative settlement or official daily high values after release.

Planned fields: `id`, `market_ticker`, `target_date_local`, `official_source_name`, `official_station_id`, `released_at_utc`, `official_high_f`, `rounding_applied`, `raw_payload_hash`, `correction_of_result_id`, `created_at`.

### `historical_bias`

Stores Layer 4 model error by model and weather regime.

Planned fields: `id`, `model_name`, `station`, `lead_time_hours`, `regime_tag`, `season`, `sample_count`, `mean_error_f`, `median_error_f`, `p90_abs_error_f`, `overestimate_rate`, `period_start`, `period_end`, `last_updated_at`, `notes`.

Important regimes: marine layer, late burn-off after 10 AM, persistent clouds, offshore flow, heat wave, weak mixing, and unknown.

### `historical_bias_observations`

Stores daily model-vs-official error records feeding `historical_bias`.

Planned fields: `id`, `market_ticker`, `target_date_local`, `model_run_id`, `official_result_id`, `predicted_high_f`, `official_high_f`, `error_f`, `absolute_error_f`, `regime_tags`, `created_at`.

### `audit_log`

Stores manual edits, corrections, and important derived-record changes.

Planned fields: `id`, `event_at_utc`, `actor`, `event_type`, `entity_type`, `entity_id`, `old_value`, `new_value`, `reason`, `created_at`.

## Relationship map

- `data_sources` owns many `observations`, `marine_layer_indicators`, and `source_polls`.
- `markets` owns many `market_snapshots`, `market_probability_buckets`, `intraday_features`, `hypotheses`, `risk_checks`, and `official_results`.
- `model_runs` owns many `model_probability_buckets` and `model_forecast_points`.
- `model_spread` summarizes multiple `model_runs` for a target date and, in the planned schema, a market/station.
- `hypotheses` owns many `hypothesis_probability_buckets` and should link to risk checks and events by market/time.
- `official_results` and `model_runs` feed `historical_bias_observations`, which aggregate into `historical_bias`.

## Migration priorities

1. Add `markets` and settlement verification fields before live market use.
2. Add `source_polls` and freshness/risk events before scheduled ingestion.
3. Normalize market and hypothesis probability buckets so market-implied and research distributions can be compared directly.
4. Add intraday features and marine-layer enhancements for nowcasting.
5. Add official results and historical-bias tables before ML or calibration claims.
6. Add audit log entries for manual overrides, corrections, and changed verification statuses.
