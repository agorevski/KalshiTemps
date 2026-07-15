from __future__ import annotations

import hashlib
import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .model_adapters import (
    fetch_model_forecast_records,
    load_model_forecast_records,
    normalize_model_forecast,
    parse_model_forecast_records,
)

from .official_sources import (
    DEFAULT_NWS_OBSERVATION_URL_TEMPLATE,
    collect_nws_station_observation,
    load_station_metadata,
    parse_climate_daily_summary_records,
    parse_nearby_asos_awos_stations,
    parse_nws_station_observation,
    parse_station_metadata_records,
)


_METAR_TIME_RE = re.compile(r"^(?P<day>\d{2})(?P<hour>\d{2})(?P<minute>\d{2})Z$")
_WIND_RE = re.compile(r"^(?P<direction>\d{3}|VRB)(?P<speed>\d{2,3})(G\d{2,3})?KT$")
_TEMP_DEW_RE = re.compile(r"^(?P<temp>M?\d{2})/(?P<dew>M?\d{2}|//)$")
_ALTIMETER_RE = re.compile(r"^A(?P<hundredths>\d{4})$")
_QNH_RE = re.compile(r"^Q(?P<mb>\d{4})$")
_CEILING_RE = re.compile(r"^(BKN|OVC|VV)(?P<hundreds>\d{3})")

DEFAULT_NWS_SEW_DISCUSSION_URL = (
    "https://forecast.weather.gov/product.php?site=SEW&issuedby=SEW&product=AFD&format=txt&version=1&glossary=0"
)
DEFAULT_AVIATION_WEATHER_METAR_URL_TEMPLATE = (
    "https://aviationweather.gov/api/data/metar?ids={station}&format=raw&taf=false"
)
TextFetcher = Callable[[str], str]
SUPPORTED_MANUAL_MODEL_NAMES = {"HRRR", "NAM", "GFS", "NBM", "ECMWF", "GraphCast", "GraphCast/AI"}


@dataclass(frozen=True)
class CollectorResult:
    source: str
    collector_name: str
    started_at: str
    finished_at: str
    status: str
    records: list[dict[str, Any]] = field(default_factory=list)
    records_returned: int = 0
    newest_observation_at: str | None = None
    latency_seconds: float | None = None
    error_message: str | None = None
    source_url: str | None = None
    payload_hash: str | None = None
    attempts: int = 1

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    def poll_record(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "collector_name": self.collector_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "records_returned": self.records_returned,
            "newest_observation_at": self.newest_observation_at,
            "latency_seconds": self.latency_seconds,
            "error_message": self.error_message,
            "source_url": self.source_url,
            "payload_hash": self.payload_hash,
        }


def normalize_forecast_discussion(
    record: str | Mapping[str, Any],
    *,
    product_id: str | None = None,
    issued_at: datetime | str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Normalize a NOAA/NWS forecast discussion text product."""
    if isinstance(record, Mapping):
        text = _required_str(record, "text")
        product = product_id or _optional_str(record, "product_id") or _infer_product_id(text)
        issued = issued_at or record.get("issued_at") or _infer_discussion_issued_at(text)
        url = source_url or _optional_str(record, "source_url")
    elif isinstance(record, str):
        text = record.strip()
        product = product_id or _infer_product_id(text)
        issued = issued_at or _infer_discussion_issued_at(text)
        url = source_url
    else:
        raise ValueError("forecast discussion record must be text or a mapping")

    if not text:
        raise ValueError("forecast discussion text is required")
    if not product:
        raise ValueError("forecast discussion product_id is required")

    issued_iso = _datetime_to_iso(_parse_datetime_required(issued, "issued_at")) if issued else None
    payload = {
        "product_id": product,
        "issued_at": issued_iso,
        "source_url": url,
        "text": text,
    }
    payload["hash"] = provenance_hash(payload)
    return payload


def normalize_observation(
    record: str | Mapping[str, Any],
    *,
    reference_date: date | datetime | str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Normalize a simple METAR-like observation string or dictionary."""
    if isinstance(record, str):
        normalized = _parse_metar_string(record, reference_date=reference_date)
        raw: Any = record.strip()
    elif isinstance(record, Mapping):
        normalized = _parse_observation_mapping(record)
        raw = dict(record)
    else:
        raise ValueError("observation record must be a METAR-like string or mapping")

    normalized["source_url"] = source_url or normalized.get("source_url")
    normalized["raw_payload"] = raw
    normalized["hash"] = provenance_hash(normalized)
    return normalized


def normalize_model_high(record: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a forecast model high-temperature record.

    Backward-compatible wrapper over the HRRR/NAM/GFS/NBM-style adapter foundation.
    """
    return normalize_model_forecast(record)


def parse_model_high_records(payload: str | bytes | Mapping[str, Any] | list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize supplied model-high records from supported JSON/CSV payloads.

    This intentionally supports file/fetcher supplied HRRR/NAM/GFS/NBM-style
    records only; it does not collect from paid/private model APIs.
    """
    return parse_model_forecast_records(payload)


def load_model_high_records(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSON or CSV file of model-high/model-forecast records and normalize them."""
    return load_model_forecast_records(path)


def collect_model_high_records(
    url: str,
    *,
    fetcher: TextFetcher | None = None,
    timeout: float = 10,
) -> list[dict[str, Any]]:
    """Fetch supported JSON/CSV model payloads with an injectable fetcher; no API integration implied."""
    return fetch_model_forecast_records(url, fetcher=fetcher, timeout=timeout)

def normalize_market_snapshot(record: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a market price snapshot into implied-probability friendly fields."""
    if not isinstance(record, Mapping):
        raise ValueError("market snapshot must be a mapping")

    ticker = _required_str(record, "ticker", aliases=("market_ticker",))
    captured_at = _datetime_to_iso(_parse_datetime_required(record.get("captured_at"), "captured_at"))
    normalized = {
        "ticker": ticker,
        "bucket": _optional_str(record, "bucket", aliases=("temperature_bucket",)),
        "yes_bid": _optional_cents(record, "yes_bid", aliases=("yes_bid_cents",)),
        "yes_ask": _optional_cents(record, "yes_ask", aliases=("yes_ask_cents",)),
        "no_bid": _optional_cents(record, "no_bid", aliases=("no_bid_cents",)),
        "no_ask": _optional_cents(record, "no_ask", aliases=("no_ask_cents",)),
        "last": _optional_cents(record, "last", aliases=("last_price", "last_price_cents")),
        "captured_at": captured_at,
        "source_note": _optional_str(record, "source_note", aliases=("settlement_source_note", "source")),
    }
    normalized["implied_probability"] = _market_probability(normalized)
    normalized["provenance_hash"] = provenance_hash(normalized)
    return normalized


def collect_forecast_discussion(
    url: str = DEFAULT_NWS_SEW_DISCUSSION_URL,
    *,
    fetcher: TextFetcher | None = None,
    timeout: float = 10,
    ingest_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Fetch and normalize a public NWS forecast discussion with provenance."""
    raw_text = _fetch_with_optional_fetcher(url, fetcher=fetcher, timeout=timeout)
    normalized = normalize_forecast_discussion(raw_text, source_url=url)
    collected_at = _datetime_to_iso(_parse_optional_datetime(ingest_at) or datetime.now(timezone.utc))
    normalized.update(
        {
            "ingest_at": collected_at,
            "raw_payload_hash": provenance_hash(raw_text),
            "text_hash": provenance_hash(normalized["text"]),
            "parser_status": "ok",
            "parser_notes": "Parsed NWS text forecast discussion.",
        }
    )
    return normalized


def collect_metar_observation(
    station: str = "KSEA",
    *,
    url: str | None = None,
    fetcher: TextFetcher | None = None,
    timeout: float = 10,
    reference_date: date | datetime | str | None = None,
    ingest_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Fetch and normalize a public Aviation Weather METAR observation."""
    station_id = station.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,4}", station_id):
        raise ValueError("station must be a 3-4 character METAR station id")
    source_url = url or DEFAULT_AVIATION_WEATHER_METAR_URL_TEMPLATE.format(station=station_id)
    raw_text = _fetch_with_optional_fetcher(source_url, fetcher=fetcher, timeout=timeout)
    metar = _select_metar_line(raw_text, station_id)
    collected = _parse_optional_datetime(ingest_at) or datetime.now(timezone.utc)
    normalized = normalize_observation(
        metar,
        reference_date=reference_date or collected.date(),
        source_url=source_url,
    )
    normalized.update(
        {
            "ingest_at": _datetime_to_iso(collected),
            "raw_payload_hash": provenance_hash(raw_text),
            "parser_status": "ok",
            "parser_notes": "Parsed Aviation Weather raw METAR.",
        }
    )
    return normalized


def run_forecast_discussion_collector(
    *,
    source: str = "NWS Seattle Forecast Discussion",
    url: str = DEFAULT_NWS_SEW_DISCUSSION_URL,
    fetcher: TextFetcher | None = None,
    timeout: float = 10,
    ingest_at: datetime | str | None = None,
    max_attempts: int = 1,
) -> CollectorResult:
    """Run the NWS discussion collector and return a persistable poll result."""
    attempts = _validated_attempts(max_attempts)
    started = datetime.now(timezone.utc)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            record = collect_forecast_discussion(url=url, fetcher=fetcher, timeout=timeout, ingest_at=ingest_at)
            finished = datetime.now(timezone.utc)
            return CollectorResult(
                source=source,
                collector_name="nws_discussion",
                started_at=_datetime_to_iso(started),
                finished_at=_datetime_to_iso(finished),
                status="success",
                records=[record],
                records_returned=1,
                newest_observation_at=record.get("issued_at") or record.get("ingest_at"),
                latency_seconds=round((finished - started).total_seconds(), 3),
                source_url=url,
                payload_hash=record.get("raw_payload_hash") or record.get("text_hash"),
                attempts=attempt,
            )
        except Exception as exc:  # noqa: BLE001 - result captures collector failures for persistence.
            last_error = exc
    return _failed_collector_result(
        source=source,
        collector_name="nws_discussion",
        started=started,
        source_url=url,
        error=last_error,
        attempts=attempts,
    )


def run_metar_collector(
    *,
    source: str = "Aviation Weather METAR",
    station: str = "KSEA",
    url: str | None = None,
    fetcher: TextFetcher | None = None,
    timeout: float = 10,
    reference_date: date | datetime | str | None = None,
    ingest_at: datetime | str | None = None,
    max_attempts: int = 1,
) -> CollectorResult:
    """Run the METAR collector and return a persistable poll result."""
    attempts = _validated_attempts(max_attempts)
    station_id = station.strip().upper()
    source_url = url or DEFAULT_AVIATION_WEATHER_METAR_URL_TEMPLATE.format(station=station_id)
    started = datetime.now(timezone.utc)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            record = collect_metar_observation(
                station=station_id,
                url=source_url,
                fetcher=fetcher,
                timeout=timeout,
                reference_date=reference_date,
                ingest_at=ingest_at,
            )
            finished = datetime.now(timezone.utc)
            return CollectorResult(
                source=source,
                collector_name="metar",
                started_at=_datetime_to_iso(started),
                finished_at=_datetime_to_iso(finished),
                status="success",
                records=[record],
                records_returned=1,
                newest_observation_at=record.get("observed_at") or record.get("ingest_at"),
                latency_seconds=round((finished - started).total_seconds(), 3),
                source_url=source_url,
                payload_hash=record.get("raw_payload_hash") or record.get("hash"),
                attempts=attempt,
            )
        except Exception as exc:  # noqa: BLE001 - result captures collector failures for persistence.
            last_error = exc
    return _failed_collector_result(
        source=source,
        collector_name="metar",
        started=started,
        source_url=source_url,
        error=last_error,
        attempts=attempts,
    )


def source_freshness_metadata(
    *,
    source_name: str,
    observed_at: datetime | str,
    checked_at: datetime | str,
    max_age_minutes: float,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Return deterministic freshness metadata for a timestamped source record."""
    name = source_name.strip()
    if not name:
        raise ValueError("source_name is required")
    observed = _parse_datetime_required(observed_at, "observed_at")
    checked = _parse_datetime_required(checked_at, "checked_at")
    max_age = float(max_age_minutes)
    if max_age < 0:
        raise ValueError("max_age_minutes must be non-negative")

    age_minutes = (_as_utc(checked) - _as_utc(observed)).total_seconds() / 60
    metadata = {
        "source_name": name,
        "source_url": source_url,
        "observed_at": _datetime_to_iso(observed),
        "checked_at": _datetime_to_iso(checked),
        "max_age_minutes": max_age,
        "age_minutes": age_minutes,
        "is_fresh": 0 <= age_minutes <= max_age,
    }
    metadata["provenance_hash"] = provenance_hash(metadata)
    return metadata


def provenance_hash(value: Any) -> str:
    """Return a stable SHA-256 hash for provenance and deduplication."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fetch_text(url: str, *, timeout: float = 10, user_agent: str = "kalshi-temps/0.1") -> str:
    """Fetch text for future NOAA/NWS/Kalshi collectors without test-time network needs."""
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError("url must be an http(s) URL")
    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - caller supplies trusted collector URLs.
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise ValueError(f"fetch failed for {url}: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"fetch failed for {url}: {exc.reason}") from exc


def fetch_noaa_forecast_discussion(url: str, *, timeout: float = 10) -> dict[str, Any]:
    """Fetch and normalize a NOAA/NWS forecast discussion text product."""
    return collect_forecast_discussion(url, timeout=timeout)


def fetch_kalshi_market_snapshot(url: str, *, timeout: float = 10) -> str:
    """Documented stub for future Kalshi collection; callers parse authenticated payloads later."""
    return fetch_text(url, timeout=timeout)


def _fetch_with_optional_fetcher(url: str, *, fetcher: TextFetcher | None, timeout: float) -> str:
    if fetcher is None:
        return fetch_text(url, timeout=timeout)
    try:
        return fetcher(url)
    except Exception as exc:
        raise ValueError(f"fetch failed for {url}: {exc}") from exc


def _validated_attempts(max_attempts: int) -> int:
    try:
        attempts = int(max_attempts)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_attempts must be a positive integer") from exc
    if attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    return attempts


def _failed_collector_result(
    *,
    source: str,
    collector_name: str,
    started: datetime,
    source_url: str | None,
    error: Exception | None,
    attempts: int,
) -> CollectorResult:
    finished = datetime.now(timezone.utc)
    message = str(error) if error else "collector failed"
    return CollectorResult(
        source=source,
        collector_name=collector_name,
        started_at=_datetime_to_iso(started),
        finished_at=_datetime_to_iso(finished),
        status="failed",
        records=[],
        records_returned=0,
        latency_seconds=round((finished - started).total_seconds(), 3),
        error_message=message,
        source_url=source_url,
        payload_hash=provenance_hash({"source_url": source_url, "error": message, "attempts": attempts}),
        attempts=attempts,
    )


def _select_metar_line(raw_text: str, station: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("METAR response did not contain any observations")
    for line in lines:
        tokens = line.split()
        if tokens and tokens[0] in {"METAR", "SPECI"}:
            tokens = tokens[1:]
        if tokens and tokens[0].upper() == station:
            return line
    raise ValueError(f"METAR response did not contain station {station}")


def _coerce_model_high_records(payload: str | bytes | Mapping[str, Any] | list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            raise ValueError("model high payload is empty")
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"model high JSON payload is invalid: {exc.msg}") from exc
            return _coerce_model_high_records(decoded)
        return _csv_records(stripped)
    if isinstance(payload, Mapping):
        for key in ("records", "model_highs", "model_runs", "data"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return _coerce_model_high_records(nested)
        return [payload]
    if isinstance(payload, list):
        if not all(isinstance(item, Mapping) for item in payload):
            raise ValueError("model high records must be mappings")
        return payload
    raise ValueError("model high payload must be JSON, CSV text, a mapping, or a list of mappings")


def _csv_records(text: str) -> list[Mapping[str, Any]]:
    rows = [dict(row) for row in csv.DictReader(text.splitlines())]
    if not rows:
        raise ValueError("model high CSV payload did not contain records")
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

    normalized: list[dict[str, float | str]] = []
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


def _parse_metar_string(record: str, *, reference_date: date | datetime | str | None) -> dict[str, Any]:
    tokens = record.strip().split()
    if len(tokens) < 3:
        raise ValueError("METAR-like observation must include station, observed time, and weather fields")
    if tokens[0] in {"METAR", "SPECI"}:
        tokens = tokens[1:]
    station = tokens[0].upper()
    if not re.fullmatch(r"[A-Z0-9]{3,4}", station):
        raise ValueError("METAR station is invalid")

    time_match = _METAR_TIME_RE.match(tokens[1])
    if not time_match:
        raise ValueError("METAR observed time must look like DDHHMMZ")
    if reference_date is None:
        raise ValueError("reference_date is required for METAR DDHHMMZ timestamps")
    observed_at = _metar_time_to_datetime(time_match, reference_date)

    normalized: dict[str, Any] = {
        "station": station,
        "observed_at": _datetime_to_iso(observed_at),
        "temperature_f": None,
        "dew_point_f": None,
        "wind_direction_deg": None,
        "wind_speed_mph": None,
        "pressure_mb": None,
        "cloud_ceiling_ft": None,
    }
    for token in tokens[2:]:
        if wind := _WIND_RE.match(token):
            normalized["wind_direction_deg"] = None if wind.group("direction") == "VRB" else int(wind.group("direction"))
            normalized["wind_speed_mph"] = round(int(wind.group("speed")) * 1.15078, 1)
        elif temp_dew := _TEMP_DEW_RE.match(token):
            normalized["temperature_f"] = _c_to_f(_metar_signed_int(temp_dew.group("temp")))
            if temp_dew.group("dew") != "//":
                normalized["dew_point_f"] = _c_to_f(_metar_signed_int(temp_dew.group("dew")))
        elif altimeter := _ALTIMETER_RE.match(token):
            normalized["pressure_mb"] = round(int(altimeter.group("hundredths")) / 100 * 33.8639, 1)
        elif qnh := _QNH_RE.match(token):
            normalized["pressure_mb"] = float(qnh.group("mb"))
        elif ceiling := _CEILING_RE.match(token):
            height = int(ceiling.group("hundreds")) * 100
            current = normalized["cloud_ceiling_ft"]
            normalized["cloud_ceiling_ft"] = height if current is None else min(current, height)

    if normalized["temperature_f"] is None:
        raise ValueError("METAR temperature/dew point group is required")
    return normalized


def _parse_observation_mapping(record: Mapping[str, Any]) -> dict[str, Any]:
    station = _required_str(record, "station").upper()
    observed_at = _datetime_to_iso(_parse_datetime_required(record.get("observed_at"), "observed_at"))
    temperature = _required_float(record, "temperature_f", aliases=("temp_f", "temperature"))
    return {
        "station": station,
        "observed_at": observed_at,
        "temperature_f": temperature,
        "dew_point_f": _optional_float(record, "dew_point_f", aliases=("dew_f", "dewpoint_f")),
        "wind_direction_deg": _optional_int(record, "wind_direction_deg", aliases=("wind_dir_deg",)),
        "wind_speed_mph": _optional_float(record, "wind_speed_mph", aliases=("wind_mph",)),
        "pressure_mb": _optional_float(record, "pressure_mb", aliases=("altimeter_mb",)),
        "cloud_ceiling_ft": _optional_int(record, "cloud_ceiling_ft", aliases=("ceiling_ft",)),
        "source_url": _optional_str(record, "source_url"),
    }


def _infer_product_id(text: str) -> str | None:
    for line in text.splitlines():
        candidate = line.strip()
        if re.fullmatch(r"[A-Z]{3,6}[A-Z0-9]{0,3}", candidate):
            return candidate
    return None


def _infer_discussion_issued_at(text: str) -> datetime | None:
    for line in text.splitlines():
        stripped = line.strip()
        try:
            parsed = parsedate_to_datetime(stripped)
        except (TypeError, ValueError, IndexError):
            continue
        if parsed:
            return parsed
    return None


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
    if value is None:
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


def _optional_cents(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> int | None:
    value = _first_present(record, key, aliases)
    if value is None or value == "":
        return None
    cents = _optional_int({key: value}, key)
    if cents is None or cents < 0 or cents > 100:
        raise ValueError(f"{key} must be between 0 and 100 cents")
    return cents


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


def _parse_optional_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    return _parse_datetime_required(value, "ingest_at")


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


def _metar_time_to_datetime(match: re.Match[str], reference_date: date | datetime | str) -> datetime:
    if isinstance(reference_date, str):
        base = date.fromisoformat(reference_date)
    elif isinstance(reference_date, datetime):
        base = reference_date.date()
    else:
        base = reference_date
    return datetime.combine(
        base.replace(day=int(match.group("day"))),
        time(int(match.group("hour")), int(match.group("minute")), tzinfo=timezone.utc),
    )


def _metar_signed_int(value: str) -> int:
    return -int(value[1:]) if value.startswith("M") else int(value)


def _c_to_f(value: int) -> float:
    return round(value * 9 / 5 + 32, 1)


def _market_probability(snapshot: Mapping[str, Any]) -> float | None:
    if snapshot.get("last") is not None:
        return snapshot["last"] / 100
    if snapshot.get("yes_bid") is None or snapshot.get("yes_ask") is None:
        return None
    if snapshot["yes_bid"] > snapshot["yes_ask"]:
        raise ValueError("yes_bid must be less than or equal to yes_ask")
    return round(((snapshot["yes_bid"] + snapshot["yes_ask"]) / 2) / 100, 4)
