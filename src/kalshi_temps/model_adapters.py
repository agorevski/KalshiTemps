from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

TextFetcher = Callable[[str], str]
SUPPORTED_MODEL_NAMES = {"HRRR", "NAM", "GFS", "NBM"}
KNOWN_MODEL_NAMES = SUPPORTED_MODEL_NAMES | {"ECMWF", "GRAPHCAST", "GRAPHCAST/AI", "PLACEHOLDER BLEND"}


def normalize_model_forecast(record: Mapping[str, Any], *, source_url: str | None = None) -> dict[str, Any]:
    """Normalize one supported-payload model forecast record.

    This is an adapter foundation for fixture/file/fetcher supplied HRRR/NAM/GFS/NBM-style
    JSON or CSV payloads. It does not implement live vendor/model APIs.
    """
    if not isinstance(record, Mapping):
        raise ValueError("model forecast record must be a mapping")

    model_name = _required_str(record, "model_name", aliases=("model", "source_model"))
    run_at_dt = _parse_datetime_required(_first_present(record, "run_at", ("run_time", "cycle_time")), "run_at")
    forecast_hour = _optional_int(record, "forecast_hour", aliases=("fhour", "fhr", "hour"))
    valid_value = _first_present(record, "valid_at", ("valid_time", "valid_datetime"))
    valid_at_dt = _parse_datetime_required(valid_value, "valid_at") if valid_value not in (None, "") else None

    if forecast_hour is None and valid_at_dt is not None:
        hours = (_as_utc(valid_at_dt) - _as_utc(run_at_dt)).total_seconds() / 3600
        if abs(hours - round(hours)) > 1e-6:
            raise ValueError("forecast_hour alignment must be whole hours")
        forecast_hour = int(round(hours))
    if valid_at_dt is None and forecast_hour is not None:
        valid_at_dt = _as_utc(run_at_dt) + timedelta(hours=forecast_hour)

    target_value = _first_present(record, "target_date", ("valid_date", "date"))
    if target_value in (None, ""):
        if valid_at_dt is None:
            raise ValueError("model forecast target_date or valid_at is required")
        target_value = valid_at_dt.date()

    predicted = _optional_float(record, "predicted_high_f", aliases=("high_f", "temperature_f", "max_temp_f"))
    hourly = _normalize_hourly_temperatures(_first_present(record, "hourly_temperatures", ("hourly_temps", "temperatures")))
    if predicted is None and hourly:
        predicted = max(float(item["temperature_f"]) for item in hourly)
    if predicted is None:
        raise ValueError("predicted_high_f is required")

    valid_date_value = _first_present(record, "valid_date", ("target_date", "date"))
    if valid_date_value in (None, ""):
        valid_date_value = target_value

    normalized: dict[str, Any] = {
        "model_name": model_name,
        "model_cycle": _optional_str(record, "model_cycle", aliases=("cycle", "cycle_label")),
        "cycle": _optional_str(record, "cycle", aliases=("model_cycle", "cycle_label")),
        "run_at": _datetime_to_iso(run_at_dt),
        "valid_at": _datetime_to_iso(valid_at_dt) if valid_at_dt is not None else None,
        "forecast_hour": forecast_hour,
        "valid_date": _date_to_iso(valid_date_value, "valid_date"),
        "target_date": _date_to_iso(target_value, "target_date"),
        "extraction_lat": _optional_float(record, "extraction_lat", aliases=("lat", "latitude")),
        "extraction_lon": _optional_float(record, "extraction_lon", aliases=("lon", "longitude")),
        "extraction_station": _optional_str(record, "extraction_station", aliases=("station", "station_id")),
        "extraction_gridpoint": _optional_str(record, "extraction_gridpoint", aliases=("gridpoint", "grid_point")),
        "predicted_high_f": predicted,
        "source_url": _optional_str(record, "source_url", aliases=("url",)) or source_url,
        "provenance": record.get("provenance"),
        "raw_payload": dict(record),
    }
    if not normalized["model_cycle"] and normalized["cycle"]:
        normalized["model_cycle"] = normalized["cycle"]
    if not normalized["cycle"] and normalized["model_cycle"]:
        normalized["cycle"] = normalized["model_cycle"]
    if hourly:
        normalized["hourly_temperatures"] = hourly
    percentiles = _normalize_percentiles(_first_present(record, "percentiles", ("quantiles",)))
    if percentiles:
        normalized["percentiles"] = percentiles
    buckets = _normalize_probability_buckets(_first_present(record, "probability_buckets", ("probabilities", "buckets")))
    if buckets:
        normalized["probability_buckets"] = buckets

    normalized["raw_payload_hash"] = stable_hash(record)
    normalized["provenance_hash"] = stable_hash({key: value for key, value in normalized.items() if key != "provenance"})
    if normalized["provenance"] is None:
        normalized["provenance"] = normalized["provenance_hash"]
    return normalized


def parse_model_forecast_records(payload: str | bytes | Mapping[str, Any] | list[Mapping[str, Any]], *, source_url: str | None = None) -> list[dict[str, Any]]:
    return [normalize_model_forecast(record, source_url=source_url) for record in _coerce_records(payload)]


def load_model_forecast_records(path: str | Path) -> list[dict[str, Any]]:
    record_path = Path(path)
    text = record_path.read_text(encoding="utf-8")
    return parse_model_forecast_records(text, source_url=record_path.as_posix())


def fetch_model_forecast_records(url: str, *, fetcher: TextFetcher | None = None, timeout: float = 10) -> list[dict[str, Any]]:
    if fetcher is None:
        from .ingest import fetch_text

        raw = fetch_text(url, timeout=timeout)
    else:
        raw = fetcher(url)
    return parse_model_forecast_records(raw, source_url=url)


def adapt_hrrr_payload(payload: Any, *, source_url: str | None = None) -> list[dict[str, Any]]:
    return _adapt_named_payload("HRRR", payload, source_url=source_url)


def adapt_nam_payload(payload: Any, *, source_url: str | None = None) -> list[dict[str, Any]]:
    return _adapt_named_payload("NAM", payload, source_url=source_url)


def adapt_gfs_payload(payload: Any, *, source_url: str | None = None) -> list[dict[str, Any]]:
    return _adapt_named_payload("GFS", payload, source_url=source_url)


def adapt_nbm_payload(payload: Any, *, source_url: str | None = None) -> list[dict[str, Any]]:
    return _adapt_named_payload("NBM", payload, source_url=source_url)


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _adapt_named_payload(model_name: str, payload: Any, *, source_url: str | None) -> list[dict[str, Any]]:
    records = []
    for record in _coerce_records(payload):
        with_name = dict(record)
        with_name.setdefault("model_name", model_name)
        records.append(normalize_model_forecast(with_name, source_url=source_url))
    return records


def _coerce_records(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            raise ValueError("model forecast payload is empty")
        if stripped.startswith(("{", "[")):
            try:
                return _coerce_records(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"model forecast JSON payload is invalid: {exc.msg}") from exc
        return _csv_records(stripped)
    if isinstance(payload, Mapping):
        for key in ("records", "forecasts", "model_forecasts", "model_highs", "model_runs", "data"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return _coerce_records(nested)
        return [payload]
    if isinstance(payload, list):
        if not all(isinstance(item, Mapping) for item in payload):
            raise ValueError("model forecast records must be mappings")
        return payload
    raise ValueError("model forecast payload must be JSON, CSV text, a mapping, or a list of mappings")


def _csv_records(text: str) -> list[Mapping[str, Any]]:
    rows = [dict(row) for row in csv.DictReader(text.splitlines())]
    if not rows:
        raise ValueError("model forecast CSV payload did not contain records")
    return rows


def _normalize_probability_buckets(value: Any) -> list[dict[str, float | str]]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("probability_buckets must be JSON when supplied as text") from exc
    if isinstance(value, Mapping):
        items = [{"temperature_bucket": str(bucket), "probability": probability} for bucket, probability in value.items()]
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError("probability_buckets must be a mapping or list")
    normalized = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("probability bucket entries must be mappings")
        bucket = _optional_str(item, "temperature_bucket", aliases=("bucket", "label"))
        if bucket is None:
            raise ValueError("probability bucket temperature_bucket is required")
        probability = _required_float(item, "probability", aliases=("prob", "p"))
        if 1 < probability <= 100:
            probability = probability / 100
        if probability < 0 or probability > 1:
            raise ValueError("probability bucket probability must be between 0 and 1")
        normalized.append({"temperature_bucket": bucket, "probability": probability})
    return normalized


def _normalize_percentiles(value: Any) -> dict[str, float]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("percentiles must be JSON when supplied as text") from exc
    if not isinstance(value, Mapping):
        raise ValueError("percentiles must be a mapping")
    return {str(key): _to_float(val, f"percentiles.{key}") for key, val in value.items()}


def _normalize_hourly_temperatures(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("hourly_temperatures must be JSON when supplied as text") from exc
    if isinstance(value, Mapping):
        items = [{"valid_at": key, "temperature_f": val} for key, val in value.items()]
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError("hourly_temperatures must be a mapping or list")
    normalized = []
    for item in items:
        if isinstance(item, Mapping):
            temp = _required_float(item, "temperature_f", aliases=("temp_f", "temperature", "value"))
            normalized.append(
                {
                    "valid_at": _datetime_to_iso(_parse_datetime_required(_first_present(item, "valid_at", ("time", "timestamp")), "valid_at"))
                    if _first_present(item, "valid_at", ("time", "timestamp")) not in (None, "")
                    else None,
                    "forecast_hour": _optional_int(item, "forecast_hour", aliases=("fhour", "fhr", "hour")),
                    "temperature_f": temp,
                }
            )
        else:
            raise ValueError("hourly temperature entries must be mappings")
    return normalized


def _required_str(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> str:
    value = _first_present(record, key, aliases)
    if value is None or str(value).strip() == "":
        raise ValueError(f"{key} is required")
    return str(value).strip()


def _optional_str(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> str | None:
    value = _first_present(record, key, aliases)
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip()


def _required_float(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> float:
    value = _first_present(record, key, aliases)
    if value is None or value == "":
        raise ValueError(f"{key} is required")
    return _to_float(value, key)


def _optional_float(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> float | None:
    value = _first_present(record, key, aliases)
    return None if value is None or value == "" else _to_float(value, key)


def _optional_int(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> int | None:
    value = _first_present(record, key, aliases)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _first_present(record: Mapping[str, Any], key: str, aliases: tuple[str, ...]) -> Any:
    for candidate in (key, *aliases):
        if candidate in record:
            return record[candidate]
    return None


def _to_float(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if parsed != parsed:
        raise ValueError(f"{field} must not be NaN")
    return parsed


def _parse_datetime_required(value: datetime | str | None, field: str) -> datetime:
    if value is None or value == "":
        raise ValueError(f"{field} is required")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO datetime") from exc
    raise ValueError(f"{field} must be a datetime or ISO datetime string")


def _date_to_iso(value: Any, field: str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO date") from exc
    raise ValueError(f"{field} is required")


def _datetime_to_iso(value: datetime) -> str:
    return _as_utc(value).replace(microsecond=0).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
