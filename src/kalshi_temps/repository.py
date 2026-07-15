from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .calibration import bucket_brier_score, bucket_contains_temperature, grouped_bias_summary, reliability_bins
from .fusion import ModelHighForecast, compare_bucket_probabilities, compute_model_spread, evaluate_freshness, generate_risk_guards
from .market_rules import market_rule_actionability, normalize_market_rule, validate_market_rule
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

    def record_collector_run(self, record: dict[str, Any]) -> dict[str, Any]:
        _require_fields(record, "source", "collector_name", "started_at", "finished_at", "status")
        status = record["status"]
        if status not in {"success", "failed"}:
            raise ValueError("status must be success or failed")
        self.conn.execute(
            """
            INSERT INTO source_polls (
                source, collector_name, started_at, finished_at, status,
                records_returned, newest_observation_at, latency_seconds,
                error_message, source_url, payload_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["source"],
                record["collector_name"],
                record["started_at"],
                record["finished_at"],
                status,
                int(record.get("records_returned") or 0),
                record.get("newest_observation_at"),
                record.get("latency_seconds"),
                record.get("error_message"),
                record.get("source_url"),
                record.get("payload_hash"),
            ),
        )
        row = self.conn.execute("SELECT * FROM source_polls WHERE id = last_insert_rowid()").fetchone()
        return _row_to_dict(row)

    def list_collector_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM source_polls
            ORDER BY finished_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def collector_health_summaries(self, *, max_age_minutes: float = 180) -> list[dict[str, Any]]:
        evaluated_at = utc_now_iso()
        rows = self.conn.execute(
            """
            SELECT sp.*
            FROM source_polls sp
            JOIN (
                SELECT source, collector_name, MAX(finished_at) AS finished_at
                FROM source_polls
                GROUP BY source, collector_name
            ) latest
              ON latest.source = sp.source
             AND latest.collector_name = sp.collector_name
             AND latest.finished_at = sp.finished_at
            ORDER BY sp.finished_at DESC, sp.id DESC
            """
        ).fetchall()
        summaries = []
        for row in rows:
            poll = _row_to_dict(row)
            latest_at = poll.get("newest_observation_at") or poll.get("finished_at")
            freshness = evaluate_freshness(
                latest_at,
                evaluated_at=evaluated_at,
                max_age_minutes=max_age_minutes,
            )
            summaries.append(
                {
                    "source": poll["source"],
                    "collector_name": poll["collector_name"],
                    "status": poll["status"],
                    "last_finished_at": poll["finished_at"],
                    "records_returned": poll["records_returned"],
                    "newest_observation_at": poll.get("newest_observation_at"),
                    "latency_seconds": poll.get("latency_seconds"),
                    "error_message": poll.get("error_message"),
                    "source_url": poll.get("source_url"),
                    "age_minutes": freshness.age_minutes,
                    "max_age_minutes": freshness.max_age_minutes,
                    "is_fresh": freshness.is_fresh and poll["status"] == "success",
                    "is_stale": freshness.is_stale or poll["status"] != "success",
                    "label": "failed" if poll["status"] != "success" else freshness.label,
                }
            )
        return summaries

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

    def latest_forecast_discussion(self) -> dict[str, Any] | None:
        rows = self.list_forecast_discussions(limit=1)
        return rows[0] if rows else None

    def save_weather_regime_features(self, record: dict[str, Any]) -> dict[str, Any]:
        _require_fields(record, "extracted_at", "regime_tags", "evidence", "confidence_label")
        regime_tags = json.dumps(record["regime_tags"], sort_keys=True)
        evidence = json.dumps(record["evidence"], sort_keys=True)
        raw_features = json.dumps(record, sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO weather_regime_features (
                forecast_discussion_id, source_id, product_id, issued_at, extracted_at,
                regime_tags, confidence_label, evidence, raw_features
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(forecast_discussion_id, extracted_at) DO UPDATE SET
                source_id = excluded.source_id,
                product_id = excluded.product_id,
                issued_at = excluded.issued_at,
                regime_tags = excluded.regime_tags,
                confidence_label = excluded.confidence_label,
                evidence = excluded.evidence,
                raw_features = excluded.raw_features
            """,
            (
                record.get("forecast_discussion_id"),
                record.get("source_id"),
                record.get("product_id"),
                record.get("issued_at"),
                record["extracted_at"],
                regime_tags,
                record["confidence_label"],
                evidence,
                raw_features,
            ),
        )
        row = self.conn.execute(
            """
            SELECT wrf.*, fd.product_id AS discussion_product_id
            FROM weather_regime_features wrf
            LEFT JOIN forecast_discussions fd ON fd.id = wrf.forecast_discussion_id
            WHERE wrf.extracted_at = ?
              AND COALESCE(wrf.forecast_discussion_id, -1) = COALESCE(?, -1)
            ORDER BY wrf.id DESC
            LIMIT 1
            """,
            (record["extracted_at"], record.get("forecast_discussion_id")),
        ).fetchone()
        return _feature_row_to_dict(row)

    def list_weather_regime_features(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT wrf.*, fd.product_id AS discussion_product_id
            FROM weather_regime_features wrf
            LEFT JOIN forecast_discussions fd ON fd.id = wrf.forecast_discussion_id
            ORDER BY wrf.extracted_at DESC, wrf.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_feature_row_to_dict(row) for row in rows]

    def latest_weather_regime_features(self) -> dict[str, Any] | None:
        rows = self.list_weather_regime_features(limit=1)
        return rows[0] if rows else None

    def save_intraday_features(self, record: dict[str, Any]) -> dict[str, Any]:
        _require_fields(record, "snapshot_at", "local_snapshot_time", "day_of_year")
        raw_features = json.dumps(record, sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO intraday_features (
                source_id, station, snapshot_at, local_snapshot_time, day_of_year,
                current_temp_f, intraday_max_f, warming_rate_f_per_hour, dew_point_f,
                wind_direction_deg, wind_speed_mph, pressure_mb, cloud_ceiling_ft,
                cloud_trend, marine_layer_cleared_before_10am, raw_features
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(station, snapshot_at) DO UPDATE SET
                source_id = excluded.source_id,
                local_snapshot_time = excluded.local_snapshot_time,
                day_of_year = excluded.day_of_year,
                current_temp_f = excluded.current_temp_f,
                intraday_max_f = excluded.intraday_max_f,
                warming_rate_f_per_hour = excluded.warming_rate_f_per_hour,
                dew_point_f = excluded.dew_point_f,
                wind_direction_deg = excluded.wind_direction_deg,
                wind_speed_mph = excluded.wind_speed_mph,
                pressure_mb = excluded.pressure_mb,
                cloud_ceiling_ft = excluded.cloud_ceiling_ft,
                cloud_trend = excluded.cloud_trend,
                marine_layer_cleared_before_10am = excluded.marine_layer_cleared_before_10am,
                raw_features = excluded.raw_features
            """,
            (
                record.get("source_id"),
                record.get("station"),
                record["snapshot_at"],
                record["local_snapshot_time"],
                record["day_of_year"],
                record.get("current_temp_f"),
                record.get("intraday_max_f"),
                record.get("warming_rate_f_per_hour"),
                record.get("dew_point_f"),
                record.get("wind_direction_deg"),
                record.get("wind_speed_mph"),
                record.get("pressure_mb"),
                record.get("cloud_ceiling_ft"),
                record.get("cloud_trend"),
                _bool_to_int(record.get("marine_layer_cleared_before_10am")),
                raw_features,
            ),
        )
        row = self.conn.execute(
            """
            SELECT * FROM intraday_features
            WHERE COALESCE(station, '') = COALESCE(?, '') AND snapshot_at = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (record.get("station"), record["snapshot_at"]),
        ).fetchone()
        return _feature_row_to_dict(row)

    def list_intraday_features(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM intraday_features ORDER BY snapshot_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_feature_row_to_dict(row) for row in rows]

    def latest_intraday_features(self) -> dict[str, Any] | None:
        rows = self.list_intraday_features(limit=1)
        return rows[0] if rows else None

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
        report = validate_forecast(record, evaluated_at=utc_now_iso())
        if report.failures:
            failures = ", ".join(check.code for check in report.failures)
            raise ValueError(f"model high record failed validation: {failures}")

        existing = self._find_model_run(record)
        if existing is None:
            cursor = self.conn.execute(
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
                    record.get("notes") or "Manually imported model-high record; evidence only.",
                ),
            )
            model_run_id = cursor.lastrowid
        else:
            model_run_id = existing["id"]
            self.conn.execute(
                """
                UPDATE model_runs
                SET valid_date = ?, predicted_high_f = ?, source_url = ?,
                    provenance = ?, notes = ?
                WHERE id = ?
                """,
                (
                    record.get("valid_date"),
                    record["predicted_high_f"],
                    record.get("source_url"),
                    record.get("provenance") or record.get("provenance_hash"),
                    record.get("notes") or existing.get("notes") or "Manually imported model-high record; evidence only.",
                    model_run_id,
                ),
            )
        if "probability_buckets" in record:
            self._replace_model_probability_buckets(model_run_id, record.get("probability_buckets") or [])
        row = self.conn.execute("SELECT * FROM model_runs WHERE id = ?", (model_run_id,)).fetchone()
        return _row_to_dict(row)

    def import_model_high_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        saved = [self.save_model_high_record(record) for record in records]
        spreads = [self.recalculate_model_spread(target_date) for target_date in sorted({row["target_date"] for row in saved})]
        return {
            "imported_count": len(saved),
            "model_runs": saved,
            "model_spreads": [spread for spread in spreads if spread is not None],
        }

    def _find_model_run(self, record: dict[str, Any]) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT *
            FROM model_runs
            WHERE run_at = ?
              AND model_name = ?
              AND target_date = ?
              AND COALESCE(model_cycle, '') = COALESCE(?, '')
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                record["run_at"],
                record["model_name"],
                record["target_date"],
                record.get("model_cycle"),
            ),
        ).fetchone()
        return _row_to_dict(row) if row else None

    def _replace_model_probability_buckets(self, model_run_id: int, buckets: list[dict[str, Any]]) -> None:
        self.conn.execute("DELETE FROM model_probability_buckets WHERE model_run_id = ?", (model_run_id,))
        for bucket in buckets:
            self.conn.execute(
                """
                INSERT INTO model_probability_buckets (model_run_id, temperature_bucket, probability)
                VALUES (?, ?, ?)
                """,
                (model_run_id, bucket["temperature_bucket"], bucket["probability"]),
            )

    def recalculate_model_spread(self, target_date: str) -> dict[str, Any] | None:
        latest_runs = self._latest_model_runs_for_target(target_date)
        spread = compute_model_spread(
            ModelHighForecast(row["model_name"], row["predicted_high_f"])
            for row in latest_runs
            if row["predicted_high_f"] is not None
        )
        if spread.model_count == 0:
            return None
        latest_run_at = max(row["run_at"] for row in latest_runs)
        changes = self._run_to_run_changes(latest_runs)
        mean_change = (
            sum(change["change_f"] for change in changes) / len(changes)
            if changes
            else None
        )
        max_abs_change = max((abs(change["change_f"]) for change in changes), default=None)
        payload = (
            target_date,
            latest_run_at,
            spread.min_high_f,
            spread.max_high_f,
            spread.mean_high_f,
            spread.spread_f,
            spread.model_count,
            spread.min_model_name,
            spread.max_model_name,
            len(changes),
            mean_change,
            max_abs_change,
            json.dumps(changes, sort_keys=True),
            "Latest manual model guidance spread by target date.",
        )
        existing = self.conn.execute(
            "SELECT id FROM model_spread WHERE target_date = ? AND calculated_at = ?",
            (target_date, latest_run_at),
        ).fetchone()
        if existing:
            self.conn.execute(
                """
                UPDATE model_spread
                SET min_high_f = ?, max_high_f = ?, mean_high_f = ?, spread_f = ?,
                    model_count = ?, min_model_name = ?, max_model_name = ?,
                    run_change_count = ?, mean_run_change_f = ?, max_abs_run_change_f = ?,
                    run_change_details = ?, notes = ?
                WHERE id = ?
                """,
                (*payload[2:], existing["id"]),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO model_spread (
                    target_date, calculated_at, min_high_f, max_high_f, mean_high_f,
                    spread_f, model_count, min_model_name, max_model_name,
                    run_change_count, mean_run_change_f, max_abs_run_change_f,
                    run_change_details, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
        row = self.conn.execute(
            "SELECT * FROM model_spread WHERE target_date = ? AND calculated_at = ?",
            (target_date, latest_run_at),
        ).fetchone()
        return _row_to_dict(row) if row else None

    def _latest_model_runs_for_target(self, target_date: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT mr.*
            FROM model_runs mr
            WHERE mr.target_date = ?
              AND mr.predicted_high_f IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM model_runs newer
                  WHERE newer.target_date = mr.target_date
                    AND newer.model_name = mr.model_name
                    AND (newer.run_at > mr.run_at OR (newer.run_at = mr.run_at AND newer.id > mr.id))
              )
            ORDER BY mr.model_name, mr.model_cycle
            """,
            (target_date,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def _run_to_run_changes(self, latest_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for row in latest_runs:
            previous = self.conn.execute(
                """
                SELECT *
                FROM model_runs
                WHERE target_date = ?
                  AND model_name = ?
                  AND predicted_high_f IS NOT NULL
                  AND (run_at < ? OR (run_at = ? AND id < ?))
                ORDER BY run_at DESC, id DESC
                LIMIT 1
                """,
                (row["target_date"], row["model_name"], row["run_at"], row["run_at"], row["id"]),
            ).fetchone()
            if previous is None:
                continue
            change = float(row["predicted_high_f"]) - float(previous["predicted_high_f"])
            changes.append(
                {
                    "model_name": row["model_name"],
                    "model_cycle": row.get("model_cycle"),
                    "run_at": row["run_at"],
                    "previous_run_at": previous["run_at"],
                    "predicted_high_f": row["predicted_high_f"],
                    "previous_predicted_high_f": previous["predicted_high_f"],
                    "change_f": change,
                }
            )
        return changes

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

    def upsert_market_rule(self, record: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_market_rule(record)
        validation = validate_market_rule(normalized)
        if validation.missing_critical_fields or validation.errors:
            details = list(validation.errors)
            if validation.missing_critical_fields:
                details.append(f"missing critical fields: {', '.join(validation.missing_critical_fields)}")
            raise ValueError("; ".join(details))

        self.conn.execute(
            """
            INSERT INTO market_rules (
                ticker, title, settlement_rule_text, official_source_name,
                official_station_id, product, timezone, daily_cutoff, units,
                rounding, fallback_policy, correction_policy, verification_status,
                verified_by, verified_at, source_url, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                title = excluded.title,
                settlement_rule_text = excluded.settlement_rule_text,
                official_source_name = excluded.official_source_name,
                official_station_id = excluded.official_station_id,
                product = excluded.product,
                timezone = excluded.timezone,
                daily_cutoff = excluded.daily_cutoff,
                units = excluded.units,
                rounding = excluded.rounding,
                fallback_policy = excluded.fallback_policy,
                correction_policy = excluded.correction_policy,
                verification_status = excluded.verification_status,
                verified_by = excluded.verified_by,
                verified_at = excluded.verified_at,
                source_url = excluded.source_url,
                notes = excluded.notes,
                updated_at = datetime('now')
            """,
            (
                normalized["ticker"],
                normalized["title"],
                normalized["settlement_rule_text"],
                normalized["official_source_name"],
                normalized["official_station_id"],
                normalized["product"],
                normalized["timezone"],
                normalized["daily_cutoff"],
                normalized["units"],
                normalized["rounding"],
                normalized["fallback_policy"],
                normalized["correction_policy"],
                normalized["verification_status"],
                normalized.get("verified_by"),
                normalized.get("verified_at"),
                normalized["source_url"],
                normalized.get("notes"),
            ),
        )
        return self.get_market_rule(normalized["ticker"])

    def verify_market_rule(
        self,
        ticker: str,
        *,
        verified_by: str,
        verified_at: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_market_rule(ticker)
        if existing is None:
            raise KeyError(f"Unknown market rule: {ticker}")
        updated = {
            **existing,
            "verification_status": "verified",
            "verified_by": verified_by,
            "verified_at": verified_at or utc_now_iso(),
            "notes": notes if notes is not None else existing.get("notes"),
        }
        return self.upsert_market_rule(updated)

    def get_market_rule(self, ticker: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM market_rules WHERE ticker = ?",
            (ticker.upper(),),
        ).fetchone()
        return _row_to_dict(row) if row else None

    def list_market_rules(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM market_rules
            ORDER BY updated_at DESC, created_at DESC, ticker
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def market_rule_actionability(self, ticker: str) -> dict[str, Any]:
        rule = self.get_market_rule(ticker)
        actionability = market_rule_actionability(rule)
        return {
            "ticker": ticker.upper(),
            "is_actionable": actionability.is_actionable,
            "reason": actionability.reason,
        }

    def save_official_outcome(
        self,
        *,
        station: str,
        target_date: str,
        high_temperature_f: float,
        source_name: str = "manual",
        observed_at: str | None = None,
        notes: str | None = None,
        raw_payload: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        payload = json.dumps(raw_payload, sort_keys=True) if isinstance(raw_payload, dict) else raw_payload
        self.conn.execute(
            """
            INSERT INTO official_outcomes (
                station, target_date, high_temperature_f, source_name, observed_at, notes, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(station, target_date) DO UPDATE SET
                high_temperature_f = excluded.high_temperature_f,
                source_name = excluded.source_name,
                observed_at = excluded.observed_at,
                notes = excluded.notes,
                raw_payload = excluded.raw_payload
            """,
            (station, target_date, high_temperature_f, source_name, observed_at, notes, payload),
        )
        row = self.conn.execute(
            "SELECT * FROM official_outcomes WHERE station = ? AND target_date = ?",
            (station, target_date),
        ).fetchone()
        return _row_to_dict(row)

    def list_official_outcomes(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM official_outcomes ORDER BY target_date DESC, station, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def save_prediction_snapshot(self, record: dict[str, Any]) -> dict[str, Any]:
        _require_fields(record, "model_name", "target_date")
        if record.get("predicted_high_f") is None and (
            record.get("temperature_bucket") is None or record.get("probability") is None
        ):
            raise ValueError("prediction snapshot requires predicted_high_f or temperature_bucket with probability")
        raw_payload = record.get("raw_payload")
        payload = json.dumps(raw_payload, sort_keys=True) if isinstance(raw_payload, dict) else raw_payload
        self.conn.execute(
            """
            INSERT INTO prediction_snapshots (
                snapshot_at, model_name, station, target_date, regime, predicted_high_f,
                temperature_bucket, probability, hypothesis, source_name, notes, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("snapshot_at") or utc_now_iso(),
                record["model_name"],
                record.get("station") or "KSEA",
                record["target_date"],
                record.get("regime"),
                record.get("predicted_high_f"),
                record.get("temperature_bucket"),
                record.get("probability"),
                record.get("hypothesis"),
                record.get("source_name"),
                record.get("notes"),
                payload,
            ),
        )
        row = self.conn.execute("SELECT * FROM prediction_snapshots WHERE id = last_insert_rowid()").fetchone()
        return _row_to_dict(row)

    def list_prediction_snapshots(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM prediction_snapshots ORDER BY snapshot_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def compute_bias_summaries(self) -> list[dict[str, Any]]:
        records = self._prediction_outcome_rows(continuous_only=True)
        summaries = grouped_bias_summary(records)
        self.conn.execute("DELETE FROM historical_bias")
        for summary in summaries:
            self.conn.execute(
                """
                INSERT INTO historical_bias (
                    model_name, regime, station, sample_count, mean_error_f,
                    mean_absolute_error_f, rmse_f, warm_bias_count, cool_bias_count, exact_count, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.get("model_name"),
                    summary.get("regime"),
                    summary.get("station"),
                    summary["sample_count"],
                    summary["mean_error_f"],
                    summary["mean_absolute_error_f"],
                    summary["rmse_f"],
                    summary["warm_bias_count"],
                    summary["cool_bias_count"],
                    summary["exact_count"],
                    "Computed from local prediction_snapshots joined to official_outcomes; positive error is warm bias.",
                ),
            )
        return self.list_bias_summaries(limit=max(len(summaries), 1))

    def list_bias_summaries(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM historical_bias
            ORDER BY computed_at DESC, sample_count DESC, model_name, regime, station
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def compute_calibration_metrics(self, *, bin_count: int = 10) -> list[dict[str, Any]]:
        rows = self._prediction_outcome_rows(probability_only=True)
        grouped: dict[tuple[str | None, str | None, str | None], list[dict[str, Any]]] = {}
        for row in rows:
            bucket = row.get("temperature_bucket")
            actual = row.get("actual_high_f")
            if bucket is None or actual is None:
                continue
            grouped.setdefault((row.get("model_name"), row.get("station"), bucket), []).append(
                {
                    **row,
                    "outcome": 1 if bucket_contains_temperature(bucket, actual) else 0,
                }
            )

        self.conn.execute("DELETE FROM calibration_metrics")
        for (model_name, station, bucket), records in grouped.items():
            brier = bucket_brier_score(records)
            bins = reliability_bins(records, bin_count=bin_count)
            self.conn.execute(
                """
                INSERT INTO calibration_metrics (
                    model_name, station, temperature_bucket, sample_count,
                    brier_score, reliability_bins_json, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_name,
                    station,
                    bucket,
                    len(records),
                    brier,
                    json.dumps(bins, sort_keys=True),
                    "Computed from local probability snapshots joined to official outcomes.",
                ),
            )
        return self.list_calibration_metrics(limit=max(len(grouped), 1))

    def list_calibration_metrics(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM calibration_metrics
            ORDER BY computed_at DESC, sample_count DESC, model_name, station, temperature_bucket
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        metrics = [_row_to_dict(row) for row in rows]
        for metric in metrics:
            bins = metric.get("reliability_bins_json")
            if isinstance(bins, str):
                metric["reliability_bins"] = json.loads(bins)
        return metrics

    def _prediction_outcome_rows(
        self,
        *,
        continuous_only: bool = False,
        probability_only: bool = False,
    ) -> list[dict[str, Any]]:
        predicates = []
        if continuous_only:
            predicates.append("ps.predicted_high_f IS NOT NULL")
        if probability_only:
            predicates.append("ps.probability IS NOT NULL AND ps.temperature_bucket IS NOT NULL")
        where = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        rows = self.conn.execute(
            f"""
            SELECT ps.*, oo.high_temperature_f AS actual_high_f, oo.source_name AS outcome_source_name
            FROM prediction_snapshots ps
            JOIN official_outcomes oo
              ON oo.station = ps.station
             AND oo.target_date = ps.target_date
            {where}
            ORDER BY ps.target_date, ps.model_name, ps.snapshot_at, ps.id
            """
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

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

    def list_model_spread(self, limit: int = 10, target_date: str | None = None) -> list[dict[str, Any]]:
        if target_date:
            rows = self.conn.execute(
                """
                SELECT *
                FROM model_spread
                WHERE target_date = ?
                ORDER BY calculated_at DESC, id DESC
                LIMIT ?
                """,
                (target_date, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM model_spread ORDER BY calculated_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def latest_model_spread(self, target_date: str | None = None) -> dict[str, Any] | None:
        if target_date:
            row = self.conn.execute(
                """
                SELECT *
                FROM model_spread
                WHERE target_date = ?
                ORDER BY calculated_at DESC, id DESC
                LIMIT 1
                """,
                (target_date,),
            ).fetchone()
            return _row_to_dict(row) if row else None
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
        market_verification = self.market_verification_summary()
        guards = generate_risk_guards(
            settlement_source_verified=bool(market_verification.get("is_actionable")),
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
        market_verification = self.market_verification_summary()
        status = "needs-review" if active_guards else "research-populated"
        return {
            "status": status,
            "label": "Research view needs review" if active_guards else "Research view populated",
            "summary": "Evidence-only dashboard; market rule verification is not a trade recommendation.",
            "source_count": len(freshness),
            "stale_source_count": sum(1 for item in freshness if item["is_stale"]),
            "active_guard_count": len(active_guards),
            "market_rule_actionable": market_verification.get("is_actionable"),
            "market_rule_reason": market_verification.get("reason"),
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
            "market_verification": self.market_verification_summary(),
            "product_status": self.product_status(),
        }

    def market_verification_summary(self, ticker: str | None = None) -> dict[str, Any]:
        selected_ticker = ticker or self._latest_market_ticker()
        if selected_ticker is None:
            rules = self.list_market_rules(limit=1)
            selected_ticker = rules[0]["ticker"] if rules else None
        if selected_ticker is None:
            actionability = market_rule_actionability(None)
            return {
                "ticker": None,
                "verification_status": None,
                "is_actionable": False,
                "reason": actionability.reason,
            }

        rule = self.get_market_rule(selected_ticker)
        actionability = market_rule_actionability(rule)
        return {
            "ticker": selected_ticker.upper(),
            "verification_status": rule.get("verification_status") if rule else None,
            "official_source_name": rule.get("official_source_name") if rule else None,
            "official_station_id": rule.get("official_station_id") if rule else None,
            "is_actionable": actionability.is_actionable,
            "reason": actionability.reason,
        }

    def _latest_market_ticker(self) -> str | None:
        row = self.conn.execute(
            "SELECT market_ticker FROM market_snapshots ORDER BY captured_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return row["market_ticker"] if row else None

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


def _feature_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = _row_to_dict(row)
    for key in ("regime_tags", "evidence", "raw_features"):
        if key in data and isinstance(data[key], str):
            data[key] = json.loads(data[key])
    if "marine_layer_cleared_before_10am" in data and data["marine_layer_cleared_before_10am"] is not None:
        data["marine_layer_cleared_before_10am"] = bool(data["marine_layer_cleared_before_10am"])
    return data


def _bool_to_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0
