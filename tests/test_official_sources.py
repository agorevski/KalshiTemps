from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.db import initialize_database  # noqa: E402
from kalshi_temps.official_sources import (  # noqa: E402
    collect_nws_station_observation,
    parse_climate_daily_summary_records,
    parse_nearby_asos_awos_stations,
    parse_nws_station_observation,
    parse_station_metadata_records,
)
from kalshi_temps.quality import WARN, validate_observation, validate_station_metadata  # noqa: E402
from kalshi_temps.repository import WeatherRepository  # noqa: E402


def test_station_metadata_json_csv_and_nearby_network_filters() -> None:
    records = parse_station_metadata_records(
        {
            "stations": [
                {
                    "station_id": "ksea",
                    "name": "Seattle Tacoma",
                    "network": "ASOS",
                    "lat": 47.45,
                    "lon": -122.31,
                    "elevation_m": 132,
                    "timezone": "America/Los_Angeles",
                    "source_class": "official",
                },
                {"station_id": "KBFI", "network": "OTHER"},
            ]
        }
    )
    assert records[0]["station_id"] == "KSEA"
    assert len(records[0]["metadata_hash"]) == 64
    assert validate_station_metadata(records[0]).failures == ()

    csv_records = parse_nearby_asos_awos_stations("station_id,name,network,lat,lon\nKPAE,Paine,AWOS,47.9,-122.3\nKXYZ,X,OTHER,0,0\n")
    assert [row["station_id"] for row in csv_records] == ["KPAE"]


def test_nws_station_observation_parser_and_injected_collector() -> None:
    payload = {
        "properties": {
            "station": "https://api.weather.gov/stations/KSEA",
            "timestamp": "2026-07-14T20:53:00+00:00",
            "temperature": {"value": 22.0, "unitCode": "wmoUnit:degC"},
            "dewpoint": {"value": 13.0},
            "windDirection": {"value": 240},
            "windSpeed": {"value": 12.0},
            "barometricPressure": {"value": 101320},
            "cloudLayers": [{"amount": "BKN", "base": {"value": 762}}],
        }
    }

    parsed = parse_nws_station_observation(payload, source_url="https://example.test/obs")
    assert parsed["station"] == "KSEA"
    assert parsed["temperature_f"] == 71.6
    assert parsed["wind_speed_mph"] == 7.5
    assert parsed["cloud_ceiling_ft"] == 2500

    collected = collect_nws_station_observation(
        "KSEA",
        url="https://example.test/obs",
        fetcher=lambda url: json.dumps(payload),
        ingest_at="2026-07-14T21:00:00Z",
    )
    assert collected["ingest_at"] == "2026-07-14T21:00:00+00:00"
    assert collected["parser_status"] == "ok"


def test_climate_daily_summary_parser_supports_json_and_csv() -> None:
    json_records = parse_climate_daily_summary_records(
        {"results": [{"STATION": "KSEA", "DATE": "2026-07-14", "TMAX": 222}]}
    )
    csv_records = parse_climate_daily_summary_records("station,date,high_temperature_f\nKSEA,2026-07-15,73\n")

    assert json_records[0]["high_temperature_f"] == 72.0
    assert csv_records[0]["target_date"] == "2026-07-15"
    assert len(json_records[0]["provenance_hash"]) == 64


def test_quality_checks_warn_for_missing_proxy_and_inactive_metadata() -> None:
    report = validate_observation(
        {"station": "KSEA", "observed_at": "2026-07-14T20:00:00Z", "temperature_f": 72},
        evaluated_at=datetime(2026, 7, 14, 21, tzinfo=timezone.utc),
        station_metadata=None,
    )
    assert report.status == WARN
    assert "station-metadata-missing" in {check.code for check in report.checks}

    proxy = {
        "station_id": "KSEA",
        "source_class": "proxy",
        "active_to": "2026-01-01",
        "metadata_hash": "abc",
    }
    proxy_report = validate_observation(
        {"station": "KSEA", "observed_at": "2026-07-14T20:00:00Z", "temperature_f": 72},
        evaluated_at=datetime(2026, 7, 14, 21, tzinfo=timezone.utc),
        station_metadata=proxy,
    )
    assert {"proxy-source-class", "proxy-distance-placeholder", "station-inactive-at-observation"} <= {
        check.code for check in proxy_report.checks
    }


def test_repository_persists_station_metadata_and_official_observation() -> None:
    db_path = Path("data") / "test-official-sources.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    db_path.unlink(missing_ok=True)
    initialize_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        repo = WeatherRepository(conn)
        repo.upsert_station_metadata({"station_id": "KSEA", "network": "ASOS", "source_class": "official"})
        saved = repo.save_official_observation_record(
            "NOAA/NWS",
            {
                "station": "KSEA",
                "observed_at": "2026-07-14T20:00:00+00:00",
                "temperature_f": 72.0,
                "source_url": "https://example.test/obs",
                "hash": "abc",
            },
        )
        conn.commit()
        assert saved["station"] == "KSEA"
        assert saved["qc_status"] in {"pass", "warn"}
        assert repo.list_official_observations()[0]["source_name"] == "NOAA/NWS"
    finally:
        conn.close()
        db_path.unlink(missing_ok=True)
