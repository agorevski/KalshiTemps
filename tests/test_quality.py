from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.quality import (  # noqa: E402
    FAIL,
    PASS,
    WARN,
    evaluate_source_quality,
    validate_forecast,
    validate_observation,
    validate_source_freshness,
)


EVALUATED_AT = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)


def _codes(report) -> set[str]:
    return {check.code for check in report.checks}


def test_validate_observation_happy_path_passes_with_structured_checks() -> None:
    report = validate_observation(
        {
            "station": "KSEA",
            "observed_at": "2026-07-14T19:30:00Z",
            "temperature_f": 74.2,
            "dew_point_f": 53.5,
            "wind_direction_deg": 250,
            "wind_speed_mph": 8.5,
            "pressure_mb": 1015.1,
            "cloud_ceiling_ft": 2500,
            "solar_radiation_wm2": 680,
        },
        evaluated_at=EVALUATED_AT,
        max_age_minutes=60,
    )

    assert report.status == PASS
    assert report.as_dict()["failure_count"] == 0
    assert {"station-present", "timestamp-fresh", "temperature-plausible"} <= _codes(report)
    assert all(check.severity and check.message and check.status in {PASS, WARN, FAIL} for check in report.checks)


def test_validate_observation_flags_required_ranges_dewpoint_stale_and_future() -> None:
    stale = validate_observation(
        {
            "station": "",
            "observed_at": "2026-07-14T16:00:00Z",
            "temperature_f": 130,
            "dew_point_f": 131,
            "wind_direction_deg": 361,
            "wind_speed_mph": -1,
            "pressure_mb": 700,
            "cloud_ceiling_ft": 70000,
            "solar_radiation_wm2": 1600,
        },
        evaluated_at=EVALUATED_AT,
        max_age_minutes=60,
    )
    future = validate_observation(
        {"station": "KSEA", "observed_at": "2026-07-14T20:30:00Z", "temperature_f": 72},
        evaluated_at=EVALUATED_AT,
        future_tolerance_minutes=5,
    )

    assert stale.status == FAIL
    assert {
        "station-missing",
        "observation-stale",
        "temperature-plausible",
        "dew-point-above-temp",
        "wind-direction-range",
        "wind-speed-range",
        "pressure-range",
        "cloud-ceiling-range",
        "solar-radiation-range",
    } <= _codes(stale)
    assert future.status == FAIL
    assert "observation-future" in _codes(future)


def test_validate_observation_detects_duplicate_and_frozen_value_hints_when_context_is_supplied() -> None:
    observations = [
        {"station": "KSEA", "observed_at": "2026-07-14T17:00:00Z", "temperature_f": 72},
        {"station": "KSEA", "observed_at": "2026-07-14T18:00:00Z", "temperature_f": 72},
        {"station": "KSEA", "observed_at": "2026-07-14T19:00:00Z", "temperature_f": 72},
        {"station": "KSEA", "observed_at": "2026-07-14T19:00:00Z", "temperature_f": 72},
    ]

    report = validate_observation(
        observations[-1],
        evaluated_at=EVALUATED_AT,
        context_observations=observations,
        max_age_minutes=240,
    )

    assert report.status == WARN
    assert {"observation-duplicate-hint", "observation-frozen-value-hint"} <= _codes(report)


def test_validate_forecast_happy_path_and_missing_provenance_warnings() -> None:
    report = validate_forecast(
        {
            "model_name": "HRRR",
            "model_cycle": "18z",
            "run_at": "2026-07-14T18:00:00Z",
            "target_date": "2026-07-15",
            "predicted_high_f": 78.4,
            "source_url": "https://example.test/hrrr",
            "provenance": "fixture",
        },
        evaluated_at=EVALUATED_AT,
    )
    warning = validate_forecast(
        {
            "model_name": "GFS",
            "run_at": "2026-07-14T18:00:00Z",
            "target_date": "2026-07-15",
            "predicted_high_f": 78,
        },
        evaluated_at=EVALUATED_AT,
    )

    assert report.status == PASS
    assert warning.status == WARN
    assert {"model_cycle-missing", "source_url-missing", "provenance-missing"} <= _codes(warning)


def test_validate_forecast_flags_required_fields_bad_high_old_and_future_runs() -> None:
    old = validate_forecast(
        {
            "model_name": "",
            "run_at": "2026-07-12T18:00:00Z",
            "target_date": "",
            "predicted_high_f": -20,
        },
        evaluated_at=EVALUATED_AT,
        max_age_minutes=60,
    )
    future = validate_forecast(
        {
            "model_name": "HRRR",
            "run_at": "2026-07-14T21:00:00Z",
            "target_date": "2026-07-15",
            "predicted_high_f": 78,
        },
        evaluated_at=EVALUATED_AT,
        future_tolerance_minutes=15,
    )

    assert old.status == FAIL
    assert {"model_name-missing", "target_date-missing", "forecast-high-plausible", "forecast-too-old"} <= _codes(old)
    assert future.status == FAIL
    assert "forecast-run-future" in _codes(future)


def test_source_quality_status_and_report_cover_fresh_stale_future_and_missing() -> None:
    fresh = evaluate_source_quality(
        source_name="NOAA",
        observed_at="2026-07-14T19:30:00Z",
        evaluated_at=EVALUATED_AT,
        max_age_minutes=60,
    )
    stale_report = validate_source_freshness(
        source_name="NOAA",
        observed_at="2026-07-14T18:00:00Z",
        evaluated_at=EVALUATED_AT,
        max_age_minutes=60,
    )
    future = evaluate_source_quality(
        source_name="NOAA",
        observed_at="2026-07-14T20:30:00Z",
        evaluated_at=EVALUATED_AT,
        max_age_minutes=60,
    )
    missing = validate_source_freshness(
        source_name="NOAA",
        observed_at=None,
        evaluated_at=EVALUATED_AT,
        max_age_minutes=60,
    )

    assert fresh.status == PASS
    assert fresh.age_minutes == 30
    assert stale_report.status == WARN
    assert future.status == FAIL
    assert future.label == "future timestamp"
    assert missing.status == FAIL
