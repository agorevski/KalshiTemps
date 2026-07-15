from __future__ import annotations

from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps import cli  # noqa: E402
from kalshi_temps.db import connection, initialize_database  # noqa: E402
from kalshi_temps.repository import WeatherRepository  # noqa: E402
from kalshi_temps.weather_features import build_intraday_feature_snapshot, extract_discussion_features  # noqa: E402


def _project_temp_db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def test_discussion_keyword_extraction_returns_tags_snippets_and_confidence() -> None:
    features = extract_discussion_features(
        """
        A shallow marine layer will keep low stratus near Puget Sound early.
        Clouds should burn off before 10 AM with hotter 80s this afternoon.
        Confidence is low on the exact timing of the wind shift.
        """,
        extracted_at="2026-07-14T16:00:00-07:00",
    )

    assert {
        "marine_layer",
        "stratus",
        "burn_off_timing",
        "heat",
        "low_confidence",
        "wind_shift",
    } <= set(features["regime_tags"])
    assert features["confidence_label"] == "high"
    assert any(item["tag"] == "marine_layer" and "marine layer" in item["snippet"] for item in features["evidence"])
    assert features["unresolved"] == ["satellite_cloud_extraction"]


def test_discussion_extraction_avoids_negated_false_positives() -> None:
    features = extract_discussion_features(
        "Fog is not expected and stratus is unlikely today. Offshore flow develops tonight.",
        extracted_at="2026-07-14T16:00:00-07:00",
    )

    assert "fog" not in features["regime_tags"]
    assert "stratus" not in features["regime_tags"]
    assert features["regime_tags"] == ["offshore_flow"]


def test_intraday_snapshot_calculates_temperature_and_cloud_features() -> None:
    snapshot = build_intraday_feature_snapshot(
        [
            {
                "station": "KSEA",
                "observed_at": "2026-07-14T14:30:00+00:00",
                "temperature_f": 58,
                "dew_point_f": 54,
                "wind_direction_deg": 190,
                "wind_speed_mph": 5,
                "pressure_mb": 1014.2,
                "cloud_ceiling_ft": 1200,
            },
            {
                "station": "KSEA",
                "observed_at": "2026-07-14T16:30:00+00:00",
                "temperature_f": 62,
                "dew_point_f": 55,
                "wind_direction_deg": 210,
                "wind_speed_mph": 7,
                "pressure_mb": 1013.8,
                "cloud_ceiling_ft": None,
            },
            {
                "station": "KSEA",
                "observed_at": "2026-07-14T18:30:00+00:00",
                "temperature_f": 70,
                "dew_point_f": 56,
                "wind_direction_deg": 240,
                "wind_speed_mph": 9,
                "pressure_mb": 1012.9,
                "cloud_ceiling_ft": None,
            },
        ],
        snapshot_at="2026-07-14T18:30:00+00:00",
    )

    assert snapshot["current_temp_f"] == 70
    assert snapshot["intraday_max_f"] == 70
    assert snapshot["warming_rate_f_per_hour"] == 4.0
    assert snapshot["day_of_year"] == 195
    assert snapshot["local_snapshot_time"].startswith("2026-07-14T11:30:00")
    assert snapshot["cloud_trend"] == "clear_or_unreported"
    assert snapshot["marine_layer_cleared_before_10am"] is True
    assert snapshot["wind_direction_deg"] == 240


def test_weather_feature_persistence_round_trips_json_and_latest_methods() -> None:
    db_path = _project_temp_db_path("test-weather-features")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            discussion = repo.save_forecast_discussion(
                "NWS Seattle Forecast Discussion",
                {
                    "product_id": "AFDSEW",
                    "issued_at": "2026-07-14T15:30:00+00:00",
                    "ingest_at": "2026-07-14T16:00:00+00:00",
                    "source_url": "https://example.test/afd",
                    "text": "Marine layer with low clouds should burn off before 10 AM.",
                    "text_hash": "weather-feature-text",
                    "raw_payload_hash": "weather-feature-raw",
                    "parser_status": "ok",
                },
            )
            regime = extract_discussion_features(
                discussion["text"],
                extracted_at="2026-07-14T16:05:00+00:00",
            )
            regime.update(
                {
                    "forecast_discussion_id": discussion["id"],
                    "source_id": discussion["source_id"],
                    "product_id": discussion["product_id"],
                    "issued_at": discussion["issued_at"],
                }
            )
            saved_regime = repo.save_weather_regime_features(regime)
            intraday = build_intraday_feature_snapshot(
                [
                    {
                        "source_id": discussion["source_id"],
                        "station": "KSEA",
                        "observed_at": "2026-07-14T16:00:00+00:00",
                        "temperature_f": 61,
                        "cloud_ceiling_ft": 1500,
                    },
                    {
                        "source_id": discussion["source_id"],
                        "station": "KSEA",
                        "observed_at": "2026-07-14T16:30:00+00:00",
                        "temperature_f": 65,
                        "cloud_ceiling_ft": 3500,
                    },
                ]
            )
            saved_intraday = repo.save_intraday_features(intraday)

            assert saved_regime["regime_tags"] == ["burn_off_timing", "marine_layer", "stratus"]
            assert saved_regime["evidence"][0]["snippet"]
            assert repo.latest_weather_regime_features()["id"] == saved_regime["id"]
            assert repo.list_weather_regime_features()[0]["raw_features"]["unresolved"] == [
                "satellite_cloud_extraction"
            ]
            assert saved_intraday["marine_layer_cleared_before_10am"] is True
            assert repo.latest_intraday_features()["id"] == saved_intraday["id"]
    finally:
        db_path.unlink(missing_ok=True)


def test_cli_weather_feature_extraction_reports_missing_discussion(capsys) -> None:
    db_path = _project_temp_db_path("test-weather-features-missing")
    try:
        assert cli.main(["--db", str(db_path), "extract-weather-features"]) == 1
        assert "pass --file or collect one first" in capsys.readouterr().err
    finally:
        db_path.unlink(missing_ok=True)
