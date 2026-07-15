from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping


PASS = "pass"
WARN = "warn"
FAIL = "fail"
_UNSET = object()
KNOWN_MODEL_NAMES = {"HRRR", "NAM", "GFS", "NBM", "ECMWF", "GRAPHCAST", "GRAPHCAST/AI", "PLACEHOLDER BLEND"}


@dataclass(frozen=True)
class QualityCheck:
    severity: str
    code: str
    message: str
    status: str


@dataclass(frozen=True)
class QualityReport:
    status: str
    checks: tuple[QualityCheck, ...]

    @property
    def passed(self) -> bool:
        return self.status == PASS

    @property
    def warnings(self) -> tuple[QualityCheck, ...]:
        return tuple(check for check in self.checks if check.status == WARN)

    @property
    def failures(self) -> tuple[QualityCheck, ...]:
        return tuple(check for check in self.checks if check.status == FAIL)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [check.__dict__ for check in self.checks],
            "warning_count": len(self.warnings),
            "failure_count": len(self.failures),
        }


@dataclass(frozen=True)
class SourceQualityStatus:
    source_name: str
    observed_at: datetime | None
    evaluated_at: datetime
    age_minutes: float | None
    max_age_minutes: float
    status: str
    label: str


def validate_observation(
    observation: Mapping[str, Any],
    *,
    evaluated_at: datetime | str,
    max_age_minutes: float = 180,
    future_tolerance_minutes: float = 5,
    dew_point_tolerance_f: float = 0.5,
    context_observations: Iterable[Mapping[str, Any]] | None = None,
    station_metadata: Mapping[str, Any] | None | object = _UNSET,
) -> QualityReport:
    """Validate one Seattle-area temperature observation with deterministic checks."""
    checks: list[QualityCheck] = []
    station = _optional_text(observation, "station")
    observed_at = _optional_datetime(observation, "observed_at")
    temperature = _float_field(checks, observation, "temperature_f")

    _require_present(checks, "station", station, "Observation station is required")
    _require_present(checks, "observed_at", observed_at, "Observation timestamp is required")
    _require_present(checks, "temperature_f", temperature, "Observation temperature is required")

    if observed_at is not None:
        checks.extend(
            _timestamp_checks(
                observed_at,
                evaluated_at=evaluated_at,
                stale_code="observation-stale",
                future_code="observation-future",
                max_age_minutes=max_age_minutes,
                future_tolerance_minutes=future_tolerance_minutes,
            )
        )

    _range_check(checks, "temperature-plausible", temperature, 0, 115, "Observation temperature is plausible for Seattle")

    dew_point = _float_field(checks, observation, "dew_point_f")
    if temperature is not None and dew_point is not None:
        if dew_point <= temperature + float(dew_point_tolerance_f):
            checks.append(_pass("dew-point-le-temp", "Dew point is not above temperature beyond tolerance"))
        else:
            checks.append(_fail("dew-point-above-temp", "Dew point is above temperature beyond tolerance"))

    _range_check(checks, "wind-direction-range", _float_field(checks, observation, "wind_direction_deg"), 0, 360, "Wind direction is within 0-360 degrees")
    _range_check(checks, "wind-speed-range", _float_field(checks, observation, "wind_speed_mph"), 0, 120, "Wind speed is within expected range")
    _range_check(checks, "pressure-range", _float_field(checks, observation, "pressure_mb"), 850, 1100, "Pressure is within expected range")
    _range_check(checks, "cloud-ceiling-range", _float_field(checks, observation, "cloud_ceiling_ft"), 0, 60000, "Cloud ceiling is within expected range")
    _range_check(checks, "solar-radiation-range", _float_field(checks, observation, "solar_radiation_wm2"), 0, 1400, "Solar radiation is within expected range")

    if context_observations is not None and station and observed_at is not None and temperature is not None:
        checks.extend(_observation_context_checks(observation, context_observations, station, observed_at, temperature))

    if station is not None and station_metadata is not _UNSET:
        checks.extend(_station_metadata_checks(station, station_metadata, observed_at=observed_at))

    return _report(checks)


def validate_station_metadata(metadata: Mapping[str, Any]) -> QualityReport:
    """Validate official/proxy weather station metadata completeness."""
    checks: list[QualityCheck] = []
    station = _optional_text(metadata, "station_id") or _optional_text(metadata, "station")
    _require_present(checks, "station-metadata-station-id", station, "Station metadata id is required")
    _presence_warning(checks, metadata, "name", "Station metadata name is missing")
    _presence_warning(checks, metadata, "network", "Station metadata network is missing")
    _range_check(checks, "station-latitude-range", _optional_float(metadata, "latitude"), -90, 90, "Station latitude is valid")
    _range_check(checks, "station-longitude-range", _optional_float(metadata, "longitude"), -180, 180, "Station longitude is valid")
    source_class = (_optional_text(metadata, "source_class") or "").lower()
    if not source_class:
        checks.append(_warn("station-source-class-missing", "Station source_class is missing"))
    elif source_class in {"official", "primary_official", "noaa", "nws", "asos_awos"}:
        checks.append(_pass("station-source-class-official", "Station is marked as an official source class"))
    elif source_class in {"proxy", "nearby_proxy", "unofficial"}:
        checks.append(_warn("station-source-class-proxy", "Station is marked as a proxy source class"))
    else:
        checks.append(_warn("station-source-class-unknown", f"Station source_class is not recognized: {source_class}"))
    _presence_warning(checks, metadata, "timezone", "Station timezone is missing")
    _presence_warning(checks, metadata, "metadata_hash", "Station metadata hash is missing")
    return _report(checks)


def validate_official_observation(
    observation: Mapping[str, Any],
    *,
    evaluated_at: datetime | str,
    station_metadata: Mapping[str, Any] | None = None,
    max_age_minutes: float = 180,
) -> QualityReport:
    return validate_observation(
        observation,
        evaluated_at=evaluated_at,
        max_age_minutes=max_age_minutes,
        station_metadata=station_metadata,
    )


def validate_forecast(
    forecast: Mapping[str, Any],
    *,
    evaluated_at: datetime | str,
    max_age_minutes: float = 24 * 60,
    future_tolerance_minutes: float = 15,
) -> QualityReport:
    """Validate one deterministic forecast-high record."""
    checks: list[QualityCheck] = []
    model_name = _optional_text(forecast, "model_name")
    run_at = _optional_datetime(forecast, "run_at")
    valid_at = _optional_datetime(forecast, "valid_at")
    target_date = _optional_date(forecast, "target_date") or _optional_date(forecast, "valid_date")
    predicted_high = _float_field(checks, forecast, "predicted_high_f", aliases=("high_f", "temperature_f"))
    forecast_hour = _optional_int_field(checks, forecast, "forecast_hour", aliases=("fhour", "fhr"))

    _require_present(checks, "model_name", model_name, "Forecast model name is required")
    _require_present(checks, "run_at", run_at, "Forecast run time is required")
    _require_present(checks, "target_date", target_date, "Forecast target date is required")
    _require_present(checks, "predicted_high_f", predicted_high, "Forecast predicted high is required")

    _range_check(checks, "forecast-high-plausible", predicted_high, 0, 115, "Forecast high is plausible for Seattle")

    if run_at is not None:
        checks.extend(
            _timestamp_checks(
                run_at,
                evaluated_at=evaluated_at,
                stale_code="forecast-too-old",
                future_code="forecast-run-future",
                max_age_minutes=max_age_minutes,
                future_tolerance_minutes=future_tolerance_minutes,
            )
        )
    if forecast_hour is None and valid_at is not None:
        checks.append(_warn("forecast_hour-missing", "Forecast hour is missing"))
    elif forecast_hour is not None:
        if 0 <= forecast_hour <= 384:
            checks.append(_pass("forecast_hour-range", "Forecast hour is within supported range"))
        else:
            checks.append(_fail("forecast_hour-range", "Forecast hour must be between 0 and 384"))

    if run_at is not None and valid_at is not None and forecast_hour is not None:
        aligned_hours = (_as_utc(valid_at) - _as_utc(run_at)).total_seconds() / 3600
        if abs(aligned_hours - forecast_hour) <= 0.01:
            checks.append(_pass("forecast-hour-aligned", "Forecast hour aligns run_at and valid_at"))
        else:
            checks.append(_fail("forecast-hour-misaligned", "Forecast hour does not align run_at and valid_at"))

    if model_name and model_name.upper() not in KNOWN_MODEL_NAMES:
        checks.append(_warn("unsupported-model-name", f"Forecast model {model_name} is not in the supported model warning allow-list"))
    elif model_name:
        checks.append(_pass("model-name-supported", "Forecast model name is supported or recognized"))

    _presence_warning(checks, forecast, "model_cycle", "Forecast model cycle is missing")
    _presence_warning(checks, forecast, "source_url", "Forecast source URL is missing")
    _presence_warning(checks, forecast, "provenance", "Forecast provenance is missing")
    if _has_extraction_metadata(forecast):
        checks.append(_pass("extraction-metadata-present", "Forecast extraction metadata is present"))
    elif any(key in forecast for key in ("extraction_station", "extraction_gridpoint", "extraction_lat", "extraction_lon", "station", "gridpoint", "lat", "lon", "latitude", "longitude")):
        checks.append(_warn("extraction-metadata-missing", "Forecast extraction metadata is missing"))
    return _report(checks)


def evaluate_source_quality(
    *,
    source_name: str,
    observed_at: datetime | str | None,
    evaluated_at: datetime | str,
    max_age_minutes: float,
    future_tolerance_minutes: float = 5,
) -> SourceQualityStatus:
    """Return a compact freshness status for source summaries and guard inputs."""
    name = source_name.strip()
    if not name:
        raise ValueError("source_name is required")
    checked = _as_utc(_require_datetime(evaluated_at, "evaluated_at"))
    observed = _optional_datetime({"observed_at": observed_at}, "observed_at")
    max_age = float(max_age_minutes)
    if max_age < 0:
        raise ValueError("max_age_minutes must be non-negative")
    if observed is None:
        return SourceQualityStatus(name, None, checked, None, max_age, FAIL, "missing timestamp")

    observed_utc = _as_utc(observed)
    age = (checked - observed_utc).total_seconds() / 60
    if age < -float(future_tolerance_minutes):
        return SourceQualityStatus(name, observed_utc, checked, age, max_age, FAIL, "future timestamp")
    if age > max_age:
        return SourceQualityStatus(name, observed_utc, checked, age, max_age, WARN, "stale")
    return SourceQualityStatus(name, observed_utc, checked, age, max_age, PASS, "fresh")


def validate_source_freshness(
    *,
    source_name: str,
    observed_at: datetime | str | None,
    evaluated_at: datetime | str,
    max_age_minutes: float,
    future_tolerance_minutes: float = 5,
) -> QualityReport:
    status = evaluate_source_quality(
        source_name=source_name,
        observed_at=observed_at,
        evaluated_at=evaluated_at,
        max_age_minutes=max_age_minutes,
        future_tolerance_minutes=future_tolerance_minutes,
    )
    if status.status == PASS:
        check = _pass("source-fresh", f"{source_name} source timestamp is fresh")
    elif status.label == "stale":
        check = _warn("source-stale", f"{source_name} source timestamp is stale")
    else:
        check = _fail("source-timestamp-invalid", f"{source_name} source timestamp is {status.label}")
    return _report([check])


def _observation_context_checks(
    observation: Mapping[str, Any],
    context: Iterable[Mapping[str, Any]],
    station: str,
    observed_at: datetime,
    temperature: float,
) -> list[QualityCheck]:
    comparable = [item for item in context if _optional_text(item, "station") == station]
    duplicate_count = sum(
        1
        for item in comparable
        if item is not observation and _optional_datetime(item, "observed_at") == observed_at
    )
    checks: list[QualityCheck] = []
    if duplicate_count:
        checks.append(_warn("observation-duplicate-hint", "Another observation has the same station and timestamp"))
    else:
        checks.append(_pass("observation-duplicate-hint", "No same-station duplicate timestamp hint found"))

    temps_by_time = {
        _as_utc(parsed_at): _optional_float(item, "temperature_f")
        for item in comparable
        if (parsed_at := _optional_datetime(item, "observed_at")) is not None
    }
    same_temp_times = [observed for observed, temp in temps_by_time.items() if temp == temperature]
    if len(temps_by_time) >= 3 and len(same_temp_times) >= 3:
        checks.append(_warn("observation-frozen-value-hint", "At least three same-station observations repeat the same temperature"))
    elif len(temps_by_time) >= 3:
        checks.append(_pass("observation-frozen-value-hint", "No frozen-temperature hint found"))
    return checks


def _station_metadata_checks(
    station: str,
    metadata: Mapping[str, Any] | None,
    *,
    observed_at: datetime | None,
) -> list[QualityCheck]:
    checks: list[QualityCheck] = []
    if metadata is None:
        return [_warn("station-metadata-missing", f"Station metadata is missing for {station}")]
    metadata_station = (_optional_text(metadata, "station_id") or _optional_text(metadata, "station") or "").upper()
    if metadata_station and metadata_station != station.upper():
        checks.append(_warn("station-metadata-mismatch", f"Station metadata id {metadata_station} does not match {station}"))
    else:
        checks.append(_pass("station-metadata-present", f"Station metadata is present for {station}"))

    source_class = (_optional_text(metadata, "source_class") or "").lower()
    if source_class in {"official", "primary_official", "noaa", "nws", "asos_awos"}:
        checks.append(_pass("official-source-class", "Observation station is an official source"))
    elif source_class:
        checks.append(_warn("proxy-source-class", "Observation station is a proxy rather than an official source"))
    else:
        checks.append(_warn("station-source-class-missing", "Observation station source_class is missing"))

    if observed_at is not None:
        active_from = _optional_date(metadata, "active_from")
        active_to = _optional_date(metadata, "active_to")
        obs_date = _as_utc(observed_at).date()
        if active_from is not None and obs_date < active_from:
            checks.append(_warn("station-inactive-at-observation", "Observation predates station active_from"))
        elif active_to is not None and obs_date > active_to:
            checks.append(_warn("station-inactive-at-observation", "Observation is after station active_to"))
        else:
            checks.append(_pass("station-active-at-observation", "Station is active at observation time"))

    if source_class and source_class not in {"official", "primary_official", "noaa", "nws", "asos_awos"}:
        if _optional_float(metadata, "proxy_distance_km") is None:
            checks.append(_warn("proxy-distance-placeholder", "Proxy station distance is not yet quantified"))
        if _optional_float(metadata, "proxy_elevation_delta_m") is None:
            checks.append(_warn("proxy-elevation-placeholder", "Proxy station elevation delta is not yet quantified"))
    return checks


def _timestamp_checks(
    value: datetime,
    *,
    evaluated_at: datetime | str,
    stale_code: str,
    future_code: str,
    max_age_minutes: float,
    future_tolerance_minutes: float,
) -> list[QualityCheck]:
    checked = _as_utc(_require_datetime(evaluated_at, "evaluated_at"))
    observed = _as_utc(value)
    max_age = float(max_age_minutes)
    if max_age < 0:
        raise ValueError("max_age_minutes must be non-negative")
    age_minutes = (checked - observed).total_seconds() / 60
    if age_minutes < -float(future_tolerance_minutes):
        return [_fail(future_code, "Timestamp is too far in the future")]
    if age_minutes > max_age:
        return [_warn(stale_code, "Timestamp is older than the freshness threshold")]
    return [_pass("timestamp-fresh", "Timestamp is within freshness bounds")]


def _range_check(
    checks: list[QualityCheck],
    code: str,
    value: float | None,
    minimum: float,
    maximum: float,
    message: str,
) -> None:
    if value is None:
        return
    if minimum <= value <= maximum:
        checks.append(_pass(code, message))
    else:
        checks.append(_fail(code, f"{message}; got {value:g}, expected {minimum:g}-{maximum:g}"))


def _require_present(checks: list[QualityCheck], code: str, value: Any, message: str) -> None:
    checks.append(_pass(f"{code}-present", message) if value is not None else _fail(f"{code}-missing", message))


def _presence_warning(checks: list[QualityCheck], record: Mapping[str, Any], key: str, message: str) -> None:
    if _optional_text(record, key) is None:
        checks.append(_warn(f"{key}-missing", message))
    else:
        checks.append(_pass(f"{key}-present", message.replace("missing", "present")))


def _report(checks: list[QualityCheck]) -> QualityReport:
    if any(check.status == FAIL for check in checks):
        status = FAIL
    elif any(check.status == WARN for check in checks):
        status = WARN
    else:
        status = PASS
    return QualityReport(status=status, checks=tuple(checks))


def _pass(code: str, message: str) -> QualityCheck:
    return QualityCheck("info", code, message, PASS)


def _warn(code: str, message: str) -> QualityCheck:
    return QualityCheck("warning", code, message, WARN)


def _fail(code: str, message: str) -> QualityCheck:
    return QualityCheck("error", code, message, FAIL)


def _optional_text(record: Mapping[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip()


def _optional_float(record: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> float | None:
    value = _first_present(record, key, aliases)
    if value is None or value == "":
        return None
    parsed = float(value)
    if parsed != parsed:
        return None
    return parsed


def _float_field(
    checks: list[QualityCheck],
    record: Mapping[str, Any],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
) -> float | None:
    value = _first_present(record, key, aliases)
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        checks.append(_fail(f"{key}-invalid", f"{key} must be numeric"))
        return None
    if parsed != parsed:
        checks.append(_fail(f"{key}-invalid", f"{key} must not be NaN"))
        return None
    return parsed


def _optional_int_field(
    checks: list[QualityCheck],
    record: Mapping[str, Any],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
) -> int | None:
    value = _first_present(record, key, aliases)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        checks.append(_fail(f"{key}-invalid", f"{key} must be an integer"))
        return None


def _optional_datetime(record: Mapping[str, Any], key: str) -> datetime | None:
    value = record.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _optional_date(record: Mapping[str, Any], key: str) -> date | None:
    value = record.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _first_present(record: Mapping[str, Any], key: str, aliases: tuple[str, ...]) -> Any:
    for candidate in (key, *aliases):
        if candidate in record:
            return record[candidate]
    return None


def _has_extraction_metadata(record: Mapping[str, Any]) -> bool:
    if _optional_text(record, "extraction_station") or _optional_text(record, "station"):
        return True
    if _optional_text(record, "extraction_gridpoint") or _optional_text(record, "gridpoint"):
        return True
    return _optional_float(record, "extraction_lat", aliases=("lat", "latitude")) is not None and _optional_float(
        record, "extraction_lon", aliases=("lon", "longitude")
    ) is not None


def _require_datetime(value: datetime | str, field_name: str) -> datetime:
    parsed = _optional_datetime({field_name: value}, field_name)
    if parsed is None:
        raise ValueError(f"{field_name} must be a datetime or ISO-8601 timestamp")
    return parsed


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
