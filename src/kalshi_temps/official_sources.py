from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

TextFetcher = Callable[[str], str]

DEFAULT_NWS_OBSERVATION_URL_TEMPLATE = "https://api.weather.gov/stations/{station}/observations/latest"
OFFICIAL_SOURCE_CLASSES = {"official", "primary_official", "noaa", "nws", "asos_awos"}
PROXY_SOURCE_CLASSES = {"proxy", "nearby_proxy", "unofficial"}


@dataclass(frozen=True)
class StationMetadata:
    station_id: str
    name: str | None = None
    network: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    timezone: str | None = None
    source_class: str = "proxy"
    water_exposure: str | None = None
    land_cover: str | None = None
    active_from: str | None = None
    active_to: str | None = None
    metadata_hash: str | None = None

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["metadata_hash"] = self.metadata_hash or station_metadata_hash(record)
        return record


def station_metadata_hash(record: Mapping[str, Any]) -> str:
    comparable = {key: value for key, value in record.items() if key not in {"metadata_hash", "created_at", "updated_at"}}
    return provenance_hash(comparable)


def provenance_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_station_metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize station metadata from public ASOS/AWOS/NOAA-style fixtures."""
    station_id = _required_text(record, "station_id", aliases=("id", "station", "icao", "sid")).upper()
    normalized = {
        "station_id": station_id,
        "name": _optional_text(record, "name", aliases=("station_name",)),
        "network": _optional_text(record, "network", aliases=("type", "station_type")),
        "latitude": _optional_float(record, "latitude", aliases=("lat",)),
        "longitude": _optional_float(record, "longitude", aliases=("lon", "lng")),
        "elevation_m": _optional_float(record, "elevation_m", aliases=("elevation", "elevation_meters")),
        "timezone": _optional_text(record, "timezone", aliases=("time_zone", "tz")),
        "source_class": (_optional_text(record, "source_class", aliases=("class",)) or "proxy").lower(),
        "water_exposure": _optional_text(record, "water_exposure"),
        "land_cover": _optional_text(record, "land_cover"),
        "active_from": _optional_date(record, "active_from", aliases=("begin", "start_date")),
        "active_to": _optional_date(record, "active_to", aliases=("end", "end_date")),
    }
    normalized["metadata_hash"] = station_metadata_hash(normalized)
    return normalized


def parse_station_metadata_records(payload: str | bytes | Mapping[str, Any] | list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = _coerce_records(payload, list_keys=("stations", "features", "records", "data"))
    return [normalize_station_metadata(_feature_properties(record)) for record in records]


def load_station_metadata(path: str | Path) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".csv":
        return parse_station_metadata_records(_csv_records(text))
    return parse_station_metadata_records(text)


def parse_nearby_asos_awos_stations(payload: str | bytes | Mapping[str, Any] | list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = parse_station_metadata_records(payload)
    return [row for row in records if (row.get("network") or "").upper() in {"ASOS", "AWOS", "ASOS/AWOS"}]


def collect_nws_station_observation(
    station: str,
    *,
    url: str | None = None,
    fetcher: TextFetcher,
    ingest_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Collect a public api.weather.gov latest-observation payload using an injected fetcher."""
    station_id = station.strip().upper()
    if not station_id:
        raise ValueError("station is required")
    source_url = url or DEFAULT_NWS_OBSERVATION_URL_TEMPLATE.format(station=station_id)
    raw_text = fetcher(source_url)
    record = parse_nws_station_observation(raw_text, station=station_id, source_url=source_url)
    record["ingest_at"] = _datetime_to_iso(_parse_optional_datetime(ingest_at) or datetime.now(timezone.utc))
    record["raw_payload_hash"] = provenance_hash(raw_text)
    record["parser_status"] = "ok"
    record["parser_notes"] = "Parsed public api.weather.gov station observation."
    return record


def parse_nws_station_observation(
    payload: str | bytes | Mapping[str, Any],
    *,
    station: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    data = _json_payload(payload)
    props = data.get("properties", data) if isinstance(data, Mapping) else {}
    if not isinstance(props, Mapping):
        raise ValueError("NWS observation payload must contain properties")
    station_id = (station or _station_from_url(_optional_text(props, "station")) or _optional_text(props, "stationIdentifier") or "").upper()
    if not station_id:
        raise ValueError("station is required")
    observed_at = _datetime_to_iso(_parse_datetime_required(props.get("timestamp"), "timestamp"))
    temp_c = _unit_value(props.get("temperature"))
    if temp_c is None:
        raise ValueError("NWS observation temperature is required")
    record = {
        "station": station_id,
        "observed_at": observed_at,
        "temperature_f": _c_to_f(temp_c),
        "dew_point_f": _c_to_f(_unit_value(props.get("dewpoint"))) if _unit_value(props.get("dewpoint")) is not None else None,
        "wind_direction_deg": _optional_int_value(props.get("windDirection")),
        "wind_speed_mph": _kmh_to_mph(_unit_value(props.get("windSpeed"))) if _unit_value(props.get("windSpeed")) is not None else None,
        "pressure_mb": _pa_to_mb(_unit_value(props.get("barometricPressure"))) if _unit_value(props.get("barometricPressure")) is not None else None,
        "cloud_ceiling_ft": _cloud_ceiling_ft(props.get("cloudLayers")),
        "source_url": source_url,
        "raw_payload": data,
    }
    record["hash"] = provenance_hash(record)
    return record


def parse_climate_daily_summary_records(payload: str | bytes | Mapping[str, Any] | list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize public daily-summary fixtures (NOAA JSON/CSV-like payloads)."""
    records = _coerce_records(payload, list_keys=("results", "records", "data", "summaries"))
    return [normalize_climate_daily_summary(record) for record in records]


def normalize_climate_daily_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    station = _required_text(record, "station", aliases=("station_id", "STATION", "id")).upper()
    target_date = _optional_date(record, "target_date", aliases=("date", "DATE"))
    if target_date is None:
        raise ValueError("daily summary date is required")
    high_f = _optional_float(record, "high_temperature_f", aliases=("tmax_f", "temp_max_f"))
    if high_f is None:
        tmax_c = _optional_float(record, "TMAX", aliases=("tmax", "temperature_max_c"))
        if tmax_c is not None:
            high_f = _c_to_f(tmax_c / 10 if abs(tmax_c) > 80 else tmax_c)
    if high_f is None:
        raise ValueError("daily summary high temperature is required")
    normalized = {
        "station": station,
        "target_date": target_date,
        "high_temperature_f": high_f,
        "source_name": _optional_text(record, "source_name") or "NOAA daily summary",
        "observed_at": _optional_datetime_iso(record, "observed_at"),
        "source_url": _optional_text(record, "source_url"),
        "raw_payload": dict(record),
    }
    normalized["provenance_hash"] = provenance_hash(normalized)
    return normalized


def _coerce_records(payload: Any, *, list_keys: tuple[str, ...]) -> list[Mapping[str, Any]]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            raise ValueError("payload is empty")
        if stripped.startswith(("{", "[")):
            return _coerce_records(json.loads(stripped), list_keys=list_keys)
        return _csv_records(stripped)
    if isinstance(payload, Mapping):
        for key in list_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return _coerce_records(value, list_keys=list_keys)
        return [payload]
    if isinstance(payload, list) and all(isinstance(item, Mapping) for item in payload):
        return payload
    raise ValueError("payload must be JSON, CSV, a mapping, or a list of mappings")


def _csv_records(text: str) -> list[Mapping[str, Any]]:
    rows = [dict(row) for row in csv.DictReader(text.splitlines())]
    if not rows:
        raise ValueError("CSV payload did not contain records")
    return rows


def _feature_properties(record: Mapping[str, Any]) -> Mapping[str, Any]:
    props = record.get("properties")
    if isinstance(props, Mapping):
        geometry = record.get("geometry")
        merged = dict(props)
        if isinstance(geometry, Mapping) and isinstance(geometry.get("coordinates"), list):
            coords = geometry["coordinates"]
            if len(coords) >= 2:
                merged.setdefault("longitude", coords[0])
                merged.setdefault("latitude", coords[1])
            if len(coords) >= 3:
                merged.setdefault("elevation_m", coords[2])
        return merged
    return record


def _json_payload(payload: str | bytes | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        loaded = json.loads(payload)
        if not isinstance(loaded, Mapping):
            raise ValueError("JSON payload must be an object")
        return loaded
    if isinstance(payload, Mapping):
        return payload
    raise ValueError("payload must be JSON text or mapping")


def _required_text(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> str:
    value = _first(record, key, aliases)
    if value is None or str(value).strip() == "":
        raise ValueError(f"{key} is required")
    return str(value).strip()


def _optional_text(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> str | None:
    value = _first(record, key, aliases)
    return None if value is None or str(value).strip() == "" else str(value).strip()


def _optional_float(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> float | None:
    value = _first(record, key, aliases)
    if value is None or value == "":
        return None
    return float(value)


def _optional_date(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> str | None:
    value = _first(record, key, aliases)
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)[:10]).isoformat()


def _optional_datetime_iso(record: Mapping[str, Any], key: str) -> str | None:
    value = record.get(key)
    return _datetime_to_iso(_parse_datetime_required(value, key)) if value not in (None, "") else None


def _first(record: Mapping[str, Any], key: str, aliases: tuple[str, ...]) -> Any:
    for candidate in (key, *aliases):
        if candidate in record:
            return record[candidate]
    return None


def _unit_value(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("value")
    if value in (None, ""):
        return None
    return float(value)


def _optional_int_value(value: Any) -> int | None:
    parsed = _unit_value(value)
    return None if parsed is None else int(round(parsed))


def _cloud_ceiling_ft(layers: Any) -> int | None:
    if not isinstance(layers, list):
        return None
    ceilings: list[int] = []
    for layer in layers:
        if not isinstance(layer, Mapping):
            continue
        if str(layer.get("amount", "")).upper() not in {"BKN", "OVC", "VV"}:
            continue
        meters = _unit_value(layer.get("base"))
        if meters is not None:
            ceilings.append(int(round(meters * 3.28084)))
    return min(ceilings) if ceilings else None


def _parse_optional_datetime(value: datetime | str | None) -> datetime | None:
    if value in (None, ""):
        return None
    return _parse_datetime_required(value, "ingest_at")


def _parse_datetime_required(value: datetime | str | None, field: str) -> datetime:
    if value in (None, ""):
        raise ValueError(f"{field} is required")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"{field} must be a datetime or ISO timestamp")


def _datetime_to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _station_from_url(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/").split("/")[-1]


def _c_to_f(value: float) -> float:
    return round(value * 9 / 5 + 32, 1)


def _kmh_to_mph(value: float) -> float:
    return round(value * 0.621371, 1)


def _pa_to_mb(value: float) -> float:
    return round(value / 100, 1)
