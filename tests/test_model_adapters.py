from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.model_adapters import (  # noqa: E402
    adapt_hrrr_payload,
    fetch_model_forecast_records,
    parse_model_forecast_records,
)
from kalshi_temps.quality import validate_forecast  # noqa: E402


def _codes(report) -> set[str]:
    return {check.code for check in report.checks}


def test_json_payload_normalizes_forecast_hour_metadata_hourly_percentiles_and_buckets() -> None:
    records = parse_model_forecast_records(
        {
            "records": [
                {
                    "model_name": "HRRR",
                    "cycle": "18z",
                    "run_at": "2026-07-14T18:00:00Z",
                    "forecast_hour": 18,
                    "station": "KSEA",
                    "gridpoint": "hrrr:45,72",
                    "target_date": "2026-07-15",
                    "hourly_temperatures": [
                        {"forecast_hour": 17, "temperature_f": 76.0},
                        {"forecast_hour": 18, "temperature_f": 79.2},
                    ],
                    "percentiles": {"p10": 74, "p90": 83},
                    "probabilities": {"78-79°F": 55, "80°F+": 0.25},
                }
            ]
        }
    )

    record = records[0]
    assert record["model_name"] == "HRRR"
    assert record["model_cycle"] == "18z"
    assert record["valid_at"] == "2026-07-15T12:00:00+00:00"
    assert record["forecast_hour"] == 18
    assert record["predicted_high_f"] == 79.2
    assert record["extraction_station"] == "KSEA"
    assert record["probability_buckets"][0] == {"temperature_bucket": "78-79°F", "probability": 0.55}
    assert record["percentiles"] == {"p10": 74.0, "p90": 83.0}


def test_csv_payload_and_fetcher_are_supported_without_live_network() -> None:
    csv_payload = (
        "model_name,run_at,valid_at,lat,lon,high_f,probabilities\n"
        'GFS,2026-07-14T12:00:00Z,2026-07-15T00:00:00Z,47.45,-122.31,75.5,"{""75°F+"": 0.7}"\n'
    )

    fetched = fetch_model_forecast_records("https://example.test/gfs.csv", fetcher=lambda url: csv_payload)

    assert fetched[0]["forecast_hour"] == 12
    assert fetched[0]["source_url"] == "https://example.test/gfs.csv"
    assert fetched[0]["extraction_lat"] == 47.45
    assert fetched[0]["probability_buckets"] == [{"temperature_bucket": "75°F+", "probability": 0.7}]


def test_named_adapter_supplies_model_name_and_invalid_payloads_fail() -> None:
    records = adapt_hrrr_payload(
        [{"run_at": "2026-07-14T18:00:00Z", "forecast_hour": 3, "target_date": "2026-07-14", "high_f": 72}]
    )
    assert records[0]["model_name"] == "HRRR"

    with pytest.raises(ValueError, match="model forecast JSON payload is invalid"):
        parse_model_forecast_records("{")
    with pytest.raises(ValueError, match="forecast_hour alignment"):
        parse_model_forecast_records(
            [{"model_name": "NAM", "run_at": "2026-07-14T00:00:00Z", "valid_at": "2026-07-14T01:30:00Z", "high_f": 70}]
        )


def test_quality_checks_forecast_hour_extraction_metadata_and_unsupported_model_warning() -> None:
    report = validate_forecast(
        {
            "model_name": "ExperimentalModel",
            "run_at": "2026-07-14T18:00:00Z",
            "valid_at": "2026-07-15T00:00:00Z",
            "forecast_hour": 7,
            "target_date": "2026-07-15",
            "predicted_high_f": 76,
            "provenance": "fixture",
            "source_url": "file://fixture",
            "model_cycle": "18z",
            "extraction_lat": 47.45,
        },
        evaluated_at="2026-07-14T20:00:00Z",
    )

    assert report.status == "fail"
    assert {"forecast-hour-misaligned", "extraction-metadata-missing", "unsupported-model-name"} <= _codes(report)
