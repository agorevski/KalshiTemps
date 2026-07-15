from __future__ import annotations

import os
import sqlite3
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path("data/kalshi_temps.sqlite3")

EXPECTED_TABLES = frozenset(
    {
        "app_events",
        "alert_records",
        "backfill_plans",
        "backfill_runs",
        "calibration_metrics",
        "cloud_features",
        "data_sources",
        "forecast_discussions",
        "historical_bias",
        "intraday_features",
        "kalshi_market_candidates",
        "kalshi_market_selections",
        "marine_layer_indicators",
        "market_rules",
        "market_snapshots",
        "model_probability_buckets",
        "model_run_deltas",
        "model_run_extractions",
        "model_runs",
        "model_spread",
        "nowcast_snapshots",
        "observations",
        "official_observations",
        "official_outcomes",
        "paper_live_checklist_entries",
        "paper_live_prediction_notes",
        "paper_live_reconciliation_notes",
        "paper_live_runs",
        "paper_live_soak_metrics",
        "prediction_snapshots",
        "settlement_replays",
        "source_polls",
        "station_metadata",
        "weather_regime_features",
    }
)
EXPECTED_INDEXES = frozenset(
    {
        "idx_backfill_runs_source_hash",
        "idx_alert_records_key",
        "idx_alert_records_status",
        "idx_backfill_plans_station",
        "idx_backfill_runs_plan_hash",
        "idx_calibration_metrics_group",
        "idx_cloud_features_observed",
        "idx_forecast_discussions_issued",
        "idx_historical_bias_group",
        "idx_intraday_features_snapshot",
        "idx_kalshi_candidates_target",
        "idx_kalshi_candidates_ticker",
        "idx_kalshi_selections_target",
        "idx_market_rules_status",
        "idx_market_snapshots_bucket",
        "idx_model_deltas_target",
        "idx_model_runs_target",
        "idx_nowcast_snapshots_time",
        "idx_observations_observed_at",
        "idx_observations_source",
        "idx_official_observations_observed",
        "idx_official_outcomes_target",
        "idx_paper_live_checklist_run",
        "idx_paper_live_notes_run",
        "idx_paper_live_reconciliation_run",
        "idx_paper_live_runs_status",
        "idx_paper_live_soak_run",
        "idx_prediction_snapshots_target",
        "idx_probability_buckets_run",
        "idx_settlement_replays_ticker",
        "idx_source_polls_finished",
        "idx_source_polls_source_collector",
        "idx_station_metadata_network",
        "idx_weather_regime_features_extracted",
    }
)
EXPECTED_VIEWS = frozenset({"collector_runs"})
EXPECTED_SCHEMA_FINGERPRINT = hashlib.sha256(
    "\n".join(
        [f"index:{name}" for name in sorted(EXPECTED_INDEXES)]
        + [f"table:{name}" for name in sorted(EXPECTED_TABLES)]
        + [f"view:{name}" for name in sorted(EXPECTED_VIEWS)]
    ).encode("utf-8")
).hexdigest()


def database_path(path: str | os.PathLike[str] | None = None) -> Path:
    configured = path or os.getenv("KALSHI_TEMPS_DB") or DEFAULT_DB_PATH
    return Path(configured).expanduser()


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    db_path = database_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def connection(path: str | os.PathLike[str] | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database(path: str | os.PathLike[str] | None = None) -> Path:
    db_path = database_path(path)
    with connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL DEFAULT 'weather',
                url TEXT,
                notes TEXT,
                last_seen_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
                station_metadata_id INTEGER REFERENCES station_metadata(id) ON DELETE SET NULL,
                source_poll_id INTEGER REFERENCES source_polls(id) ON DELETE SET NULL,
                station TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                temperature_f REAL NOT NULL,
                dew_point_f REAL,
                wind_direction_deg INTEGER,
                wind_speed_mph REAL,
                pressure_mb REAL,
                cloud_ceiling_ft INTEGER,
                visibility_miles REAL,
                solar_radiation_wm2 REAL,
                raw_payload TEXT,
                provenance_hash TEXT,
                qc_status TEXT,
                qc_report TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source_id, station, observed_at)
            );

            CREATE TABLE IF NOT EXISTS station_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL UNIQUE,
                name TEXT,
                network TEXT,
                latitude REAL,
                longitude REAL,
                elevation_m REAL,
                timezone TEXT,
                source_class TEXT NOT NULL DEFAULT 'proxy',
                water_exposure TEXT,
                land_cover TEXT,
                active_from TEXT,
                active_to TEXT,
                metadata_hash TEXT NOT NULL,
                raw_payload TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS official_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
                station_metadata_id INTEGER REFERENCES station_metadata(id) ON DELETE SET NULL,
                source_poll_id INTEGER REFERENCES source_polls(id) ON DELETE SET NULL,
                station TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                temperature_f REAL NOT NULL,
                dew_point_f REAL,
                wind_direction_deg INTEGER,
                wind_speed_mph REAL,
                pressure_mb REAL,
                cloud_ceiling_ft INTEGER,
                source_url TEXT,
                provenance_hash TEXT,
                qc_status TEXT,
                qc_report TEXT,
                raw_payload TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(station, observed_at, source_id)
            );

            CREATE TABLE IF NOT EXISTS forecast_discussions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
                product_id TEXT NOT NULL,
                issued_at TEXT,
                ingest_at TEXT NOT NULL,
                source_url TEXT,
                text TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                raw_payload_hash TEXT NOT NULL,
                parser_status TEXT NOT NULL,
                parser_notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(product_id, ingest_at, text_hash)
            );

            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_ticker TEXT NOT NULL,
                temperature_bucket TEXT,
                captured_at TEXT NOT NULL DEFAULT (datetime('now')),
                yes_bid_cents INTEGER,
                yes_ask_cents INTEGER,
                no_bid_cents INTEGER,
                no_ask_cents INTEGER,
                last_price_cents INTEGER,
                implied_probability REAL,
                settlement_source_note TEXT,
                raw_payload TEXT
            );

            CREATE TABLE IF NOT EXISTS market_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                settlement_rule_text TEXT NOT NULL,
                official_source_name TEXT NOT NULL,
                official_station_id TEXT NOT NULL,
                product TEXT NOT NULL,
                timezone TEXT NOT NULL,
                daily_cutoff TEXT NOT NULL,
                units TEXT NOT NULL,
                rounding TEXT NOT NULL,
                fallback_policy TEXT NOT NULL,
                correction_policy TEXT NOT NULL,
                verification_status TEXT NOT NULL DEFAULT 'unverified',
                verified_by TEXT,
                verified_at TEXT,
                source_url TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS kalshi_market_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                event_ticker TEXT,
                title TEXT NOT NULL,
                subtitle TEXT,
                yes_sub_title TEXT,
                no_sub_title TEXT,
                status TEXT,
                market_type TEXT,
                open_time TEXT,
                close_time TEXT,
                expiration_time TEXT,
                rules_primary TEXT,
                rules_secondary TEXT,
                yes_bid_cents INTEGER,
                yes_ask_cents INTEGER,
                no_bid_cents INTEGER,
                no_ask_cents INTEGER,
                last_price_cents INTEGER,
                implied_probability REAL,
                rank_score INTEGER NOT NULL DEFAULT 0,
                rank_reasons TEXT NOT NULL DEFAULT '[]',
                seattle_match INTEGER NOT NULL DEFAULT 0,
                date_match INTEGER NOT NULL DEFAULT 0,
                temperature_language_match INTEGER NOT NULL DEFAULT 0,
                settlement_rule_presence INTEGER NOT NULL DEFAULT 0,
                source_url TEXT,
                captured_at TEXT NOT NULL,
                raw_payload_hash TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                selected INTEGER NOT NULL DEFAULT 0,
                selection_notes TEXT,
                selected_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(target_date, ticker)
            );

            CREATE TABLE IF NOT EXISTS kalshi_market_selections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_date TEXT NOT NULL UNIQUE,
                ticker TEXT NOT NULL,
                selected_at TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS model_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL DEFAULT (datetime('now')),
                model_name TEXT NOT NULL,
                model_cycle TEXT,
                valid_at TEXT,
                forecast_hour INTEGER,
                valid_date TEXT,
                target_date TEXT NOT NULL,
                extraction_lat REAL,
                extraction_lon REAL,
                extraction_station TEXT,
                extraction_gridpoint TEXT,
                predicted_high_f REAL,
                confidence REAL,
                source_url TEXT,
                provenance TEXT,
                hourly_temperatures TEXT,
                percentiles TEXT,
                raw_payload_hash TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS model_run_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_run_id INTEGER NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
                extraction_lat REAL,
                extraction_lon REAL,
                extraction_station TEXT,
                extraction_gridpoint TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(model_run_id)
            );

            CREATE TABLE IF NOT EXISTS model_run_deltas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_run_id INTEGER NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
                previous_model_run_id INTEGER REFERENCES model_runs(id) ON DELETE SET NULL,
                model_name TEXT NOT NULL,
                target_date TEXT NOT NULL,
                run_at TEXT NOT NULL,
                previous_run_at TEXT,
                predicted_high_f REAL,
                previous_predicted_high_f REAL,
                change_f REAL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(model_run_id)
            );

            CREATE TABLE IF NOT EXISTS model_spread (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_date TEXT NOT NULL,
                calculated_at TEXT NOT NULL DEFAULT (datetime('now')),
                min_high_f REAL,
                max_high_f REAL,
                mean_high_f REAL,
                spread_f REAL,
                model_count INTEGER NOT NULL DEFAULT 0,
                min_model_name TEXT,
                max_model_name TEXT,
                run_change_count INTEGER NOT NULL DEFAULT 0,
                mean_run_change_f REAL,
                max_abs_run_change_f REAL,
                run_change_details TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS marine_layer_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
                observed_at TEXT NOT NULL,
                cloud_cover_pct REAL,
                ceiling_ft INTEGER,
                satellite_trend TEXT,
                marine_layer_cleared_before_10am INTEGER,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS weather_regime_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                forecast_discussion_id INTEGER REFERENCES forecast_discussions(id) ON DELETE SET NULL,
                source_id INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
                product_id TEXT,
                issued_at TEXT,
                extracted_at TEXT NOT NULL,
                regime_tags TEXT NOT NULL,
                confidence_label TEXT NOT NULL,
                evidence TEXT NOT NULL,
                raw_features TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(forecast_discussion_id, extracted_at)
            );

            CREATE TABLE IF NOT EXISTS cloud_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                cloud_cover_pct REAL,
                stratus_extent_pct REAL,
                fog_present INTEGER,
                burnoff_status TEXT,
                burnoff_time TEXT,
                confidence REAL,
                source_url TEXT,
                source_hash TEXT,
                notes TEXT,
                raw_features TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source, observed_at, source_hash)
            );

            CREATE TABLE IF NOT EXISTS intraday_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
                station TEXT,
                snapshot_at TEXT NOT NULL,
                local_snapshot_time TEXT NOT NULL,
                day_of_year INTEGER NOT NULL,
                current_temp_f REAL,
                intraday_max_f REAL,
                warming_rate_f_per_hour REAL,
                dew_point_f REAL,
                wind_direction_deg INTEGER,
                wind_speed_mph REAL,
                pressure_mb REAL,
                cloud_ceiling_ft INTEGER,
                cloud_trend TEXT,
                marine_layer_cleared_before_10am INTEGER,
                raw_features TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(station, snapshot_at)
            );

            CREATE TABLE IF NOT EXISTS nowcast_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station TEXT,
                snapshot_at TEXT NOT NULL,
                local_snapshot_time TEXT NOT NULL,
                target_date TEXT NOT NULL,
                snapshot_hour_local INTEGER NOT NULL,
                current_temp_f REAL,
                intraday_max_f REAL,
                warming_rate_f_per_hour REAL,
                dew_point_f REAL,
                wind_direction_deg INTEGER,
                wind_speed_mph REAL,
                pressure_mb REAL,
                cloud_ceiling_ft INTEGER,
                visibility_miles REAL,
                solar_radiation_wm2 REAL,
                solar_proxy REAL,
                cloud_trend TEXT,
                ceiling_trend TEXT,
                wind_shift TEXT,
                marine_push_indicator TEXT,
                remaining_solar_window_proxy TEXT,
                remaining_upside_distribution TEXT,
                data_status TEXT,
                raw_snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(station, snapshot_at)
            );

            CREATE TABLE IF NOT EXISTS model_probability_buckets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_run_id INTEGER NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
                temperature_bucket TEXT NOT NULL,
                probability REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(model_run_id, temperature_bucket)
            );

            CREATE TABLE IF NOT EXISTS official_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station TEXT NOT NULL,
                target_date TEXT NOT NULL,
                high_temperature_f REAL NOT NULL,
                source_name TEXT NOT NULL DEFAULT 'manual',
                observed_at TEXT,
                notes TEXT,
                raw_payload TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(station, target_date)
            );

            CREATE TABLE IF NOT EXISTS settlement_replays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                target_date TEXT NOT NULL,
                official_outcome_id INTEGER REFERENCES official_outcomes(id) ON DELETE SET NULL,
                status TEXT NOT NULL,
                settlement_bucket TEXT,
                bucket_matched INTEGER NOT NULL DEFAULT 0,
                mismatch_reasons TEXT NOT NULL DEFAULT '[]',
                reconciliation_error TEXT,
                official_value REAL,
                official_units TEXT,
                normalized_value REAL,
                rounded_value REAL,
                evaluation_units TEXT,
                source_url TEXT,
                official_source_name TEXT,
                raw_payload_hash TEXT NOT NULL,
                raw_official_payload TEXT,
                first_published_value REAL,
                corrected_value REAL,
                correction_applied INTEGER NOT NULL DEFAULT 0,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                replayed_at TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                market_rule_verified INTEGER NOT NULL DEFAULT 0,
                replay_result_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(ticker, target_date, raw_payload_hash, rule_version)
            );

            CREATE TABLE IF NOT EXISTS prediction_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_at TEXT NOT NULL DEFAULT (datetime('now')),
                model_name TEXT NOT NULL,
                station TEXT NOT NULL DEFAULT 'KSEA',
                target_date TEXT NOT NULL,
                regime TEXT,
                predicted_high_f REAL,
                temperature_bucket TEXT,
                probability REAL,
                hypothesis TEXT,
                source_name TEXT,
                notes TEXT,
                raw_payload TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS backfill_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial_failure', 'failed')),
                plan_hash TEXT,
                plan_json TEXT,
                missing_dates_json TEXT NOT NULL DEFAULT '[]',
                payload_hashes_json TEXT NOT NULL DEFAULT '{}',
                idempotency_key TEXT,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                dry_run INTEGER NOT NULL DEFAULT 0,
                counts_json TEXT NOT NULL DEFAULT '{}',
                errors_json TEXT NOT NULL DEFAULT '[]',
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS backfill_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                plan_hash TEXT NOT NULL UNIQUE,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS historical_bias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                computed_at TEXT NOT NULL DEFAULT (datetime('now')),
                model_name TEXT,
                regime TEXT,
                station TEXT,
                sample_count INTEGER NOT NULL,
                mean_error_f REAL,
                mean_absolute_error_f REAL,
                rmse_f REAL,
                warm_bias_count INTEGER NOT NULL DEFAULT 0,
                cool_bias_count INTEGER NOT NULL DEFAULT 0,
                exact_count INTEGER NOT NULL DEFAULT 0,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS calibration_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                computed_at TEXT NOT NULL DEFAULT (datetime('now')),
                model_name TEXT,
                station TEXT,
                temperature_bucket TEXT,
                sample_count INTEGER NOT NULL,
                brier_score REAL,
                reliability_bins_json TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS app_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                source_name TEXT,
                provenance_url TEXT,
                is_stale INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS alert_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_key TEXT NOT NULL,
                alert_day TEXT NOT NULL,
                source_name TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL CHECK (severity IN ('info', 'warn', 'fail')),
                code TEXT NOT NULL,
                message TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                resolved_at TEXT,
                resolved_by TEXT,
                resolution_notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(alert_key, alert_day, source_name)
            );

            CREATE TABLE IF NOT EXISTS source_polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                collector_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
                records_returned INTEGER NOT NULL DEFAULT 0,
                newest_observation_at TEXT,
                latency_seconds REAL,
                error_message TEXT,
                source_url TEXT,
                payload_hash TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS paper_live_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_name TEXT NOT NULL,
                station TEXT NOT NULL DEFAULT 'KSEA',
                target_date TEXT,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                closed_at TEXT,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS paper_live_checklist_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES paper_live_runs(id) ON DELETE CASCADE,
                checklist_date TEXT NOT NULL,
                item TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'blocked')),
                notes TEXT,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS paper_live_prediction_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES paper_live_runs(id) ON DELETE CASCADE,
                target_date TEXT,
                predicted_high_f REAL,
                probability_bucket TEXT,
                confidence REAL,
                note TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS paper_live_reconciliation_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES paper_live_runs(id) ON DELETE CASCADE,
                note_type TEXT NOT NULL DEFAULT 'postmortem'
                    CHECK (note_type IN ('postmortem', 'reconciliation')),
                target_date TEXT,
                note TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS paper_live_soak_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES paper_live_runs(id) ON DELETE CASCADE,
                measured_at TEXT NOT NULL DEFAULT (datetime('now')),
                uptime_status TEXT NOT NULL DEFAULT 'not-measured',
                collector_success_count INTEGER NOT NULL DEFAULT 0,
                collector_failure_count INTEGER NOT NULL DEFAULT 0,
                backup_success INTEGER NOT NULL DEFAULT 0,
                alert_count INTEGER NOT NULL DEFAULT 0,
                notes TEXT
            );

            CREATE VIEW IF NOT EXISTS collector_runs AS
            SELECT * FROM source_polls;

            CREATE INDEX IF NOT EXISTS idx_observations_observed_at ON observations(observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_observations_source ON observations(source_id);
            CREATE INDEX IF NOT EXISTS idx_station_metadata_network ON station_metadata(network, station_id);
            CREATE INDEX IF NOT EXISTS idx_official_observations_observed ON official_observations(station, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_forecast_discussions_issued ON forecast_discussions(issued_at DESC);
            CREATE INDEX IF NOT EXISTS idx_model_runs_target ON model_runs(target_date, model_name);
            CREATE INDEX IF NOT EXISTS idx_market_snapshots_bucket ON market_snapshots(temperature_bucket, captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_market_rules_status ON market_rules(verification_status, ticker);
            CREATE INDEX IF NOT EXISTS idx_kalshi_candidates_target ON kalshi_market_candidates(target_date, rank_score DESC);
            CREATE INDEX IF NOT EXISTS idx_kalshi_candidates_ticker ON kalshi_market_candidates(ticker, captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_kalshi_selections_target ON kalshi_market_selections(target_date, selected_at DESC);
            CREATE INDEX IF NOT EXISTS idx_probability_buckets_run ON model_probability_buckets(model_run_id);
            CREATE INDEX IF NOT EXISTS idx_model_deltas_target ON model_run_deltas(target_date, model_name, run_at DESC);
            CREATE INDEX IF NOT EXISTS idx_official_outcomes_target ON official_outcomes(station, target_date);
            CREATE INDEX IF NOT EXISTS idx_settlement_replays_ticker
                ON settlement_replays(ticker, target_date, replayed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_prediction_snapshots_target ON prediction_snapshots(station, target_date, model_name);
            CREATE INDEX IF NOT EXISTS idx_backfill_runs_source_hash ON backfill_runs(source_hash, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_backfill_runs_plan_hash ON backfill_runs(plan_hash, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_backfill_plans_station ON backfill_plans(station, start_date, end_date);
            CREATE INDEX IF NOT EXISTS idx_historical_bias_group ON historical_bias(model_name, regime, station);
            CREATE INDEX IF NOT EXISTS idx_calibration_metrics_group ON calibration_metrics(model_name, station, temperature_bucket);
            CREATE INDEX IF NOT EXISTS idx_source_polls_finished ON source_polls(finished_at DESC);
            CREATE INDEX IF NOT EXISTS idx_source_polls_source_collector ON source_polls(source, collector_name, finished_at DESC);
            CREATE INDEX IF NOT EXISTS idx_alert_records_status ON alert_records(status, alert_day DESC, severity);
            CREATE INDEX IF NOT EXISTS idx_alert_records_key ON alert_records(alert_key, alert_day DESC, source_name);
            CREATE INDEX IF NOT EXISTS idx_paper_live_runs_status ON paper_live_runs(status, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_paper_live_checklist_run ON paper_live_checklist_entries(run_id, checklist_date DESC);
            CREATE INDEX IF NOT EXISTS idx_paper_live_notes_run ON paper_live_prediction_notes(run_id, recorded_at DESC);
            CREATE INDEX IF NOT EXISTS idx_paper_live_reconciliation_run ON paper_live_reconciliation_notes(run_id, recorded_at DESC);
            CREATE INDEX IF NOT EXISTS idx_paper_live_soak_run ON paper_live_soak_metrics(run_id, measured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_weather_regime_features_extracted
                ON weather_regime_features(extracted_at DESC);
            CREATE INDEX IF NOT EXISTS idx_intraday_features_snapshot
                ON intraday_features(snapshot_at DESC);
            CREATE INDEX IF NOT EXISTS idx_cloud_features_observed
                ON cloud_features(observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_nowcast_snapshots_time
                ON nowcast_snapshots(target_date DESC, snapshot_hour_local, snapshot_at DESC);
            """
        )
        _ensure_columns(
            conn,
            "observations",
            {
                "dew_point_f": "REAL",
                "wind_direction_deg": "INTEGER",
                "wind_speed_mph": "REAL",
                "pressure_mb": "REAL",
                "cloud_ceiling_ft": "INTEGER",
                "visibility_miles": "REAL",
                "solar_radiation_wm2": "REAL",
                "station_metadata_id": "INTEGER REFERENCES station_metadata(id) ON DELETE SET NULL",
                "source_poll_id": "INTEGER REFERENCES source_polls(id) ON DELETE SET NULL",
                "provenance_hash": "TEXT",
                "qc_status": "TEXT",
                "qc_report": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "market_snapshots",
            {
                "temperature_bucket": "TEXT",
                "no_bid_cents": "INTEGER",
                "no_ask_cents": "INTEGER",
                "implied_probability": "REAL",
                "settlement_source_note": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "model_runs",
            {
                "model_cycle": "TEXT",
                "valid_at": "TEXT",
                "forecast_hour": "INTEGER",
                "valid_date": "TEXT",
                "extraction_lat": "REAL",
                "extraction_lon": "REAL",
                "extraction_station": "TEXT",
                "extraction_gridpoint": "TEXT",
                "source_url": "TEXT",
                "provenance": "TEXT",
                "hourly_temperatures": "TEXT",
                "percentiles": "TEXT",
                "raw_payload_hash": "TEXT",
                "notes": "TEXT",
                "confidence": "REAL",
            },
        )
        _ensure_columns(
            conn,
            "model_spread",
            {
                "min_model_name": "TEXT",
                "max_model_name": "TEXT",
                "run_change_count": "INTEGER NOT NULL DEFAULT 0",
                "mean_run_change_f": "REAL",
                "max_abs_run_change_f": "REAL",
                "run_change_details": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "app_events",
            {
                "severity": "TEXT NOT NULL DEFAULT 'info'",
                "source_name": "TEXT",
                "provenance_url": "TEXT",
                "is_stale": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        _ensure_columns(
            conn,
            "source_polls",
            {
                "source": "TEXT NOT NULL DEFAULT 'unknown'",
                "collector_name": "TEXT NOT NULL DEFAULT 'unknown'",
                "started_at": "TEXT NOT NULL DEFAULT (datetime('now'))",
                "finished_at": "TEXT NOT NULL DEFAULT (datetime('now'))",
                "status": "TEXT NOT NULL DEFAULT 'failed'",
                "records_returned": "INTEGER NOT NULL DEFAULT 0",
                "newest_observation_at": "TEXT",
                "latency_seconds": "REAL",
                "error_message": "TEXT",
                "source_url": "TEXT",
                "payload_hash": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "backfill_runs",
            {
                "plan_hash": "TEXT",
                "plan_json": "TEXT",
                "missing_dates_json": "TEXT NOT NULL DEFAULT '[]'",
                "payload_hashes_json": "TEXT NOT NULL DEFAULT '{}'",
                "idempotency_key": "TEXT",
                "warnings_json": "TEXT NOT NULL DEFAULT '[]'",
                "dry_run": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        _ensure_columns(
            conn,
            "market_rules",
            {
                "title": "TEXT NOT NULL DEFAULT ''",
                "settlement_rule_text": "TEXT NOT NULL DEFAULT ''",
                "official_source_name": "TEXT NOT NULL DEFAULT ''",
                "official_station_id": "TEXT NOT NULL DEFAULT ''",
                "product": "TEXT NOT NULL DEFAULT ''",
                "timezone": "TEXT NOT NULL DEFAULT ''",
                "daily_cutoff": "TEXT NOT NULL DEFAULT ''",
                "units": "TEXT NOT NULL DEFAULT ''",
                "rounding": "TEXT NOT NULL DEFAULT ''",
                "fallback_policy": "TEXT NOT NULL DEFAULT ''",
                "correction_policy": "TEXT NOT NULL DEFAULT ''",
                "verification_status": "TEXT NOT NULL DEFAULT 'unverified'",
                "verified_by": "TEXT",
                "verified_at": "TEXT",
                "source_url": "TEXT NOT NULL DEFAULT ''",
                "notes": "TEXT",
                "updated_at": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "kalshi_market_candidates",
            {
                "event_ticker": "TEXT",
                "subtitle": "TEXT",
                "yes_sub_title": "TEXT",
                "no_sub_title": "TEXT",
                "status": "TEXT",
                "market_type": "TEXT",
                "open_time": "TEXT",
                "close_time": "TEXT",
                "expiration_time": "TEXT",
                "rules_primary": "TEXT",
                "rules_secondary": "TEXT",
                "yes_bid_cents": "INTEGER",
                "yes_ask_cents": "INTEGER",
                "no_bid_cents": "INTEGER",
                "no_ask_cents": "INTEGER",
                "last_price_cents": "INTEGER",
                "implied_probability": "REAL",
                "rank_score": "INTEGER NOT NULL DEFAULT 0",
                "rank_reasons": "TEXT NOT NULL DEFAULT '[]'",
                "seattle_match": "INTEGER NOT NULL DEFAULT 0",
                "date_match": "INTEGER NOT NULL DEFAULT 0",
                "temperature_language_match": "INTEGER NOT NULL DEFAULT 0",
                "settlement_rule_presence": "INTEGER NOT NULL DEFAULT 0",
                "source_url": "TEXT",
                "captured_at": "TEXT NOT NULL DEFAULT (datetime('now'))",
                "raw_payload_hash": "TEXT NOT NULL DEFAULT ''",
                "raw_payload": "TEXT NOT NULL DEFAULT '{}'",
                "selected": "INTEGER NOT NULL DEFAULT 0",
                "selection_notes": "TEXT",
                "selected_at": "TEXT",
                "updated_at": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "settlement_replays",
            {
                "ticker": "TEXT NOT NULL DEFAULT ''",
                "target_date": "TEXT NOT NULL DEFAULT ''",
                "official_outcome_id": "INTEGER",
                "status": "TEXT NOT NULL DEFAULT 'unmatched'",
                "settlement_bucket": "TEXT",
                "bucket_matched": "INTEGER NOT NULL DEFAULT 0",
                "mismatch_reasons": "TEXT NOT NULL DEFAULT '[]'",
                "reconciliation_error": "TEXT",
                "official_value": "REAL",
                "official_units": "TEXT",
                "normalized_value": "REAL",
                "rounded_value": "REAL",
                "evaluation_units": "TEXT",
                "source_url": "TEXT",
                "official_source_name": "TEXT",
                "raw_payload_hash": "TEXT NOT NULL DEFAULT ''",
                "raw_official_payload": "TEXT",
                "first_published_value": "REAL",
                "corrected_value": "REAL",
                "correction_applied": "INTEGER NOT NULL DEFAULT 0",
                "fallback_used": "INTEGER NOT NULL DEFAULT 0",
                "replayed_at": "TEXT",
                "rule_version": "TEXT NOT NULL DEFAULT ''",
                "market_rule_verified": "INTEGER NOT NULL DEFAULT 0",
                "replay_result_json": "TEXT NOT NULL DEFAULT '{}'",
                "updated_at": "TEXT",
            },
        )
        conn.execute(
            "INSERT INTO app_events (event_type, message) VALUES (?, ?)",
            ("database.initialized", f"Initialized database at {db_path}"),
        )
    return db_path


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
