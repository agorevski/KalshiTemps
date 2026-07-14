from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


class WeatherRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_source(
        self,
        name: str,
        source_type: str = "weather",
        url: str | None = None,
        notes: str | None = None,
        last_seen_at: str | None = None,
    ) -> dict[str, Any]:
        self.conn.execute(
            """
            INSERT INTO data_sources (name, source_type, url, notes, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                source_type = excluded.source_type,
                url = COALESCE(excluded.url, data_sources.url),
                notes = COALESCE(excluded.notes, data_sources.notes),
                last_seen_at = COALESCE(excluded.last_seen_at, data_sources.last_seen_at)
            """,
            (name, source_type, url, notes, last_seen_at),
        )
        return self.get_source_by_name(name)

    def get_source_by_name(self, name: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM data_sources WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown data source: {name}")
        return _row_to_dict(row)

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT s.*,
                   COUNT(o.id) AS observation_count,
                   MAX(o.observed_at) AS latest_observation_at
            FROM data_sources s
            LEFT JOIN observations o ON o.source_id = s.id
            GROUP BY s.id
            ORDER BY COALESCE(MAX(o.observed_at), s.last_seen_at, s.created_at) DESC
            """
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def add_observation(
        self,
        source_name: str,
        station: str,
        observed_at: str,
        temperature_f: float,
        dew_point_f: float | None = None,
        wind_direction_deg: int | None = None,
        wind_speed_mph: float | None = None,
        pressure_mb: float | None = None,
        cloud_ceiling_ft: int | None = None,
        solar_radiation_wm2: float | None = None,
        raw_payload: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        source = self.upsert_source(source_name, last_seen_at=observed_at)
        payload = json.dumps(raw_payload, sort_keys=True) if isinstance(raw_payload, dict) else raw_payload
        self.conn.execute(
            """
            INSERT INTO observations (
                source_id, station, observed_at, temperature_f, dew_point_f,
                wind_direction_deg, wind_speed_mph, pressure_mb, cloud_ceiling_ft,
                solar_radiation_wm2, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, station, observed_at) DO UPDATE SET
                temperature_f = excluded.temperature_f,
                dew_point_f = excluded.dew_point_f,
                wind_direction_deg = excluded.wind_direction_deg,
                wind_speed_mph = excluded.wind_speed_mph,
                pressure_mb = excluded.pressure_mb,
                cloud_ceiling_ft = excluded.cloud_ceiling_ft,
                solar_radiation_wm2 = excluded.solar_radiation_wm2,
                raw_payload = excluded.raw_payload
            """,
            (
                source["id"],
                station,
                observed_at,
                temperature_f,
                dew_point_f,
                wind_direction_deg,
                wind_speed_mph,
                pressure_mb,
                cloud_ceiling_ft,
                solar_radiation_wm2,
                payload,
            ),
        )
        self.conn.execute(
            "UPDATE data_sources SET last_seen_at = MAX(COALESCE(last_seen_at, ''), ?) WHERE id = ?",
            (observed_at, source["id"]),
        )
        row = self.conn.execute(
            """
            SELECT o.*, s.name AS source_name
            FROM observations o
            JOIN data_sources s ON s.id = o.source_id
            WHERE o.source_id = ? AND o.station = ? AND o.observed_at = ?
            """,
            (source["id"], station, observed_at),
        ).fetchone()
        return _row_to_dict(row)

    def list_observations(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT o.*, s.name AS source_name, s.url AS source_url
            FROM observations o
            JOIN data_sources s ON s.id = o.source_id
            ORDER BY o.observed_at DESC, o.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def daily_high(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT date(observed_at) AS observed_date,
                   MAX(temperature_f) AS high_temperature_f,
                   COUNT(*) AS observation_count
            FROM observations
            WHERE date(observed_at) = (SELECT MAX(date(observed_at)) FROM observations)
            GROUP BY date(observed_at)
            """
        ).fetchone()
        return _row_to_dict(row) if row else None

    def list_model_runs(self, limit: int = 12) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT mr.*,
                   GROUP_CONCAT(mpb.temperature_bucket || ': ' || ROUND(mpb.probability * 100, 0) || '%', ', ')
                       AS probability_buckets
            FROM model_runs mr
            LEFT JOIN model_probability_buckets mpb ON mpb.model_run_id = mr.id
            GROUP BY mr.id
            ORDER BY mr.run_at DESC, mr.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def latest_model_spread(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM model_spread ORDER BY calculated_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return _row_to_dict(row) if row else None

    def list_marine_indicators(self, limit: int = 6) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT mli.*, s.name AS source_name
            FROM marine_layer_indicators mli
            LEFT JOIN data_sources s ON s.id = mli.source_id
            ORDER BY mli.observed_at DESC, mli.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_market_snapshots(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM market_snapshots ORDER BY captured_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_events(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM app_events ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
