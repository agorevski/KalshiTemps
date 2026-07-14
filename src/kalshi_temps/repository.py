from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .fusion import compare_bucket_probabilities, evaluate_freshness, generate_risk_guards
from .quality import validate_forecast, validate_observation


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
        source_type: str = "weather",
        source_url: str | None = None,
        source_notes: str | None = None,
    ) -> dict[str, Any]:
        source = self.upsert_source(
            source_name,
            source_type=source_type,
            url=source_url,
            notes=source_notes,
            last_seen_at=observed_at,
        )
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

    def save_forecast_discussion(
        self,
        source_name: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        _require_fields(
            record,
            "product_id",
            "ingest_at",
            "text",
            "text_hash",
            "raw_payload_hash",
            "parser_status",
        )
        source = self.upsert_source(
            source_name,
            source_type="forecast_discussion",
            url=record.get("source_url"),
            notes=record.get("parser_notes"),
            last_seen_at=record.get("issued_at") or record.get("ingest_at"),
        )
        self.conn.execute(
            """
            INSERT INTO forecast_discussions (
                source_id, product_id, issued_at, ingest_at, source_url, text,
                text_hash, raw_payload_hash, parser_status, parser_notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id, ingest_at, text_hash) DO UPDATE SET
                source_id = excluded.source_id,
                issued_at = excluded.issued_at,
                source_url = excluded.source_url,
                text = excluded.text,
                raw_payload_hash = excluded.raw_payload_hash,
                parser_status = excluded.parser_status,
                parser_notes = excluded.parser_notes
            """,
            (
                source["id"],
                record["product_id"],
                record.get("issued_at"),
                record["ingest_at"],
                record.get("source_url"),
                record["text"],
                record["text_hash"],
                record["raw_payload_hash"],
                record["parser_status"],
                record.get("parser_notes"),
            ),
        )
        row = self.conn.execute(
            """
            SELECT fd.*, s.name AS source_name
            FROM forecast_discussions fd
            LEFT JOIN data_sources s ON s.id = fd.source_id
            WHERE fd.product_id = ? AND fd.ingest_at = ? AND fd.text_hash = ?
            """,
            (record["product_id"], record["ingest_at"], record["text_hash"]),
        ).fetchone()
        return _row_to_dict(row)

    def list_forecast_discussions(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT fd.*, s.name AS source_name
            FROM forecast_discussions fd
            LEFT JOIN data_sources s ON s.id = fd.source_id
            ORDER BY COALESCE(fd.issued_at, fd.ingest_at) DESC, fd.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def save_observation_record(self, source_name: str, record: dict[str, Any]) -> dict[str, Any]:
        _require_fields(record, "station", "observed_at", "temperature_f")
        source_url = record.get("source_url")
        raw_payload = {
            "raw_payload": record.get("raw_payload"),
            "hash": record.get("hash"),
            "raw_payload_hash": record.get("raw_payload_hash"),
            "ingest_at": record.get("ingest_at"),
            "parser_status": record.get("parser_status"),
            "parser_notes": record.get("parser_notes"),
            "source_url": source_url,
        }
        return self.add_observation(
            source_name,
            record["station"],
            record["observed_at"],
            record["temperature_f"],
            dew_point_f=record.get("dew_point_f"),
            wind_direction_deg=record.get("wind_direction_deg"),
            wind_speed_mph=record.get("wind_speed_mph"),
            pressure_mb=record.get("pressure_mb"),
            cloud_ceiling_ft=record.get("cloud_ceiling_ft"),
            raw_payload=raw_payload,
            source_type="weather_observation",
            source_url=source_url,
            source_notes=record.get("parser_notes"),
        )

    def save_model_high_record(self, record: dict[str, Any]) -> dict[str, Any]:
        _require_fields(record, "run_at", "model_name", "target_date", "predicted_high_f")
        self.conn.execute(
            """
            INSERT INTO model_runs (
                run_at, model_name, model_cycle, valid_date, target_date,
                predicted_high_f, source_url, provenance, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["run_at"],
                record["model_name"],
                record.get("model_cycle"),
                record.get("valid_date"),
                record["target_date"],
                record["predicted_high_f"],
                record.get("source_url"),
                record.get("provenance") or record.get("provenance_hash"),
                record.get("notes") or "Normalized placeholder model record; evidence only.",
            ),
        )
        row = self.conn.execute("SELECT * FROM model_runs WHERE id = last_insert_rowid()").fetchone()
        return _row_to_dict(row)

    def save_market_snapshot_record(self, record: dict[str, Any]) -> dict[str, Any]:
        _require_fields(record, "ticker", "captured_at")
        raw_payload = json.dumps(record, sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO market_snapshots (
                market_ticker, temperature_bucket, captured_at, yes_bid_cents,
                yes_ask_cents, no_bid_cents, no_ask_cents, last_price_cents,
                implied_probability, settlement_source_note, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["ticker"],
                record.get("bucket"),
                record["captured_at"],
                record.get("yes_bid"),
                record.get("yes_ask"),
                record.get("no_bid"),
                record.get("no_ask"),
                record.get("last"),
                record.get("implied_probability"),
                record.get("source_note") or "Normalized placeholder market record; not a trade recommendation.",
                raw_payload,
            ),
        )
        row = self.conn.execute("SELECT * FROM market_snapshots WHERE id = last_insert_rowid()").fetchone()
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

    def latest_model_bucket_probabilities(self) -> dict[str, float]:
        rows = self.conn.execute(
            """
            SELECT mpb.temperature_bucket, AVG(mpb.probability) AS probability
            FROM model_probability_buckets mpb
            JOIN model_runs mr ON mr.id = mpb.model_run_id
            WHERE mr.target_date = (SELECT MAX(target_date) FROM model_runs)
            GROUP BY mpb.temperature_bucket
            ORDER BY mpb.temperature_bucket
            """
        ).fetchall()
        return {row["temperature_bucket"]: row["probability"] for row in rows if row["probability"] is not None}

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

    def latest_market_bucket_probabilities(self) -> dict[str, float]:
        rows = self.conn.execute(
            """
            SELECT ms.temperature_bucket, ms.implied_probability
            FROM market_snapshots ms
            JOIN (
                SELECT temperature_bucket, MAX(captured_at) AS captured_at
                FROM market_snapshots
                WHERE temperature_bucket IS NOT NULL AND implied_probability IS NOT NULL
                GROUP BY temperature_bucket
            ) latest
              ON latest.temperature_bucket = ms.temperature_bucket
             AND latest.captured_at = ms.captured_at
            WHERE ms.implied_probability IS NOT NULL
            ORDER BY ms.temperature_bucket, ms.id DESC
            """
        ).fetchall()
        probabilities: dict[str, float] = {}
        for row in rows:
            probabilities.setdefault(row["temperature_bucket"], row["implied_probability"])
        return probabilities

    def source_freshness_summaries(self, *, max_age_minutes: float = 180) -> list[dict[str, Any]]:
        evaluated_at = utc_now_iso()
        summaries = []
        for source in self.list_sources():
            latest_at = source.get("latest_observation_at") or source.get("last_seen_at")
            status = evaluate_freshness(
                latest_at,
                evaluated_at=evaluated_at,
                max_age_minutes=max_age_minutes,
            )
            summaries.append(
                {
                    "source_name": source["name"],
                    "source_type": source["source_type"],
                    "url": source.get("url"),
                    "latest_at": latest_at,
                    "age_minutes": status.age_minutes,
                    "max_age_minutes": status.max_age_minutes,
                    "is_fresh": status.is_fresh,
                    "is_stale": status.is_stale,
                    "label": status.label,
                }
            )
        return summaries

    def risk_guard_status(self, *, freshness_max_age_minutes: float = 180) -> list[dict[str, Any]]:
        freshness = self.source_freshness_summaries(max_age_minutes=freshness_max_age_minutes)
        spread = self.latest_model_spread()
        guards = generate_risk_guards(
            settlement_source_verified=False,
            is_stale=any(item["is_stale"] for item in freshness),
            model_spread_f=spread["spread_f"] if spread else None,
            high_spread_threshold_f=4,
            proxy_only_observations=True,
        )
        return [
            {
                "key": guard.key,
                "label": guard.label,
                "severity": guard.severity,
                "active": guard.active,
            }
            for guard in guards
        ]

    def observation_quality_summaries(self, *, limit: int = 50, max_age_minutes: float = 180) -> list[dict[str, Any]]:
        observations = self.list_observations(limit=limit)
        evaluated_at = utc_now_iso()
        return [
            {
                "observation_id": observation["id"],
                "source_name": observation["source_name"],
                "station": observation["station"],
                "observed_at": observation["observed_at"],
                **validate_observation(
                    observation,
                    evaluated_at=evaluated_at,
                    max_age_minutes=max_age_minutes,
                    context_observations=observations,
                ).as_dict(),
            }
            for observation in observations
        ]

    def forecast_quality_summaries(self, *, limit: int = 50, max_age_minutes: float = 24 * 60) -> list[dict[str, Any]]:
        evaluated_at = utc_now_iso()
        return [
            {
                "model_run_id": forecast["id"],
                "model_name": forecast["model_name"],
                "run_at": forecast["run_at"],
                "target_date": forecast["target_date"],
                **validate_forecast(
                    forecast,
                    evaluated_at=evaluated_at,
                    max_age_minutes=max_age_minutes,
                ).as_dict(),
            }
            for forecast in self.list_model_runs(limit=limit)
        ]

    def bucket_probability_deltas(self) -> list[dict[str, Any]]:
        deltas = compare_bucket_probabilities(
            self.latest_model_bucket_probabilities(),
            self.latest_market_bucket_probabilities(),
        )
        return [
            {
                "bucket": delta.bucket,
                "model_probability": delta.model_probability,
                "market_probability": delta.market_probability,
                "probability_delta": delta.probability_delta,
                "expected_edge_cents": delta.expected_edge_cents,
                "note": "Descriptive model-vs-market difference only; not a trade recommendation.",
            }
            for delta in deltas
        ]

    def product_status(self) -> dict[str, Any]:
        freshness = self.source_freshness_summaries()
        guards = self.risk_guard_status()
        active_guards = [guard for guard in guards if guard["active"]]
        status = "needs-review" if active_guards else "research-populated"
        return {
            "status": status,
            "label": "Research view needs review" if active_guards else "Research view populated",
            "summary": "Evidence-only dashboard; verify official market rules and source freshness before interpreting probabilities.",
            "source_count": len(freshness),
            "stale_source_count": sum(1 for item in freshness if item["is_stale"]),
            "active_guard_count": len(active_guards),
        }

    def fusion_summary(self) -> dict[str, Any]:
        return {
            "daily_high": self.daily_high(),
            "model_spread": self.latest_model_spread(),
            "source_freshness": self.source_freshness_summaries(),
            "risk_guards": self.risk_guard_status(),
            "bucket_deltas": self.bucket_probability_deltas(),
            "observation_quality": self.observation_quality_summaries(),
            "forecast_quality": self.forecast_quality_summaries(),
            "product_status": self.product_status(),
        }

    def list_events(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM app_events ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]


def _require_fields(record: dict[str, Any], *fields: str) -> None:
    for field in fields:
        if field not in record or record[field] is None or record[field] == "":
            raise ValueError(f"{field} is required")
