from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path("data/kalshi_temps.sqlite3")


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
                station TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                temperature_f REAL NOT NULL,
                dew_point_f REAL,
                wind_direction_deg INTEGER,
                wind_speed_mph REAL,
                pressure_mb REAL,
                cloud_ceiling_ft INTEGER,
                solar_radiation_wm2 REAL,
                raw_payload TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source_id, station, observed_at)
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

            CREATE TABLE IF NOT EXISTS model_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL DEFAULT (datetime('now')),
                model_name TEXT NOT NULL,
                model_cycle TEXT,
                valid_date TEXT,
                target_date TEXT NOT NULL,
                predicted_high_f REAL,
                confidence REAL,
                source_url TEXT,
                provenance TEXT,
                notes TEXT
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

            CREATE VIEW IF NOT EXISTS collector_runs AS
            SELECT * FROM source_polls;

            CREATE INDEX IF NOT EXISTS idx_observations_observed_at ON observations(observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_observations_source ON observations(source_id);
            CREATE INDEX IF NOT EXISTS idx_forecast_discussions_issued ON forecast_discussions(issued_at DESC);
            CREATE INDEX IF NOT EXISTS idx_model_runs_target ON model_runs(target_date, model_name);
            CREATE INDEX IF NOT EXISTS idx_market_snapshots_bucket ON market_snapshots(temperature_bucket, captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_market_rules_status ON market_rules(verification_status, ticker);
            CREATE INDEX IF NOT EXISTS idx_probability_buckets_run ON model_probability_buckets(model_run_id);
            CREATE INDEX IF NOT EXISTS idx_official_outcomes_target ON official_outcomes(station, target_date);
            CREATE INDEX IF NOT EXISTS idx_prediction_snapshots_target ON prediction_snapshots(station, target_date, model_name);
            CREATE INDEX IF NOT EXISTS idx_historical_bias_group ON historical_bias(model_name, regime, station);
            CREATE INDEX IF NOT EXISTS idx_calibration_metrics_group ON calibration_metrics(model_name, station, temperature_bucket);
            CREATE INDEX IF NOT EXISTS idx_source_polls_finished ON source_polls(finished_at DESC);
            CREATE INDEX IF NOT EXISTS idx_source_polls_source_collector ON source_polls(source, collector_name, finished_at DESC);
            CREATE INDEX IF NOT EXISTS idx_weather_regime_features_extracted
                ON weather_regime_features(extracted_at DESC);
            CREATE INDEX IF NOT EXISTS idx_intraday_features_snapshot
                ON intraday_features(snapshot_at DESC);
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
                "solar_radiation_wm2": "REAL",
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
                "valid_date": "TEXT",
                "source_url": "TEXT",
                "provenance": "TEXT",
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
