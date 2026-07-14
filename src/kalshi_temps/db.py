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

            CREATE TABLE IF NOT EXISTS model_probability_buckets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_run_id INTEGER NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
                temperature_bucket TEXT NOT NULL,
                probability REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(model_run_id, temperature_bucket)
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

            CREATE INDEX IF NOT EXISTS idx_observations_observed_at ON observations(observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_observations_source ON observations(source_id);
            CREATE INDEX IF NOT EXISTS idx_forecast_discussions_issued ON forecast_discussions(issued_at DESC);
            CREATE INDEX IF NOT EXISTS idx_model_runs_target ON model_runs(target_date, model_name);
            CREATE INDEX IF NOT EXISTS idx_market_snapshots_bucket ON market_snapshots(temperature_bucket, captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_probability_buckets_run ON model_probability_buckets(model_run_id);
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
