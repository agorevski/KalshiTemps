from __future__ import annotations

from pathlib import Path
import uuid
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.db import connection, initialize_database
from kalshi_temps.nowcast import generate_fixed_nowcast_snapshots
from kalshi_temps.repository import WeatherRepository
from kalshi_temps.weather_features import classify_marine_burnoff, normalize_cloud_feature


def _project_temp_db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def test_fixed_nowcast_snapshot_hours_and_trends() -> None:
    cloud = normalize_cloud_feature(
        {
            "source": "manual satellite proxy",
            "observed_at": "2026-07-14T16:00:00+00:00",
            "cloud_cover_pct": 30,
            "stratus_extent_pct": 15,
            "fog_present": False,
            "confidence": 0.7,
        }
    )
    snapshots = generate_fixed_nowcast_snapshots(
        [
            {
                "station": "KSEA",
                "observed_at": "2026-07-14T14:00:00+00:00",
                "temperature_f": 58,
                "dew_point_f": 55,
                "wind_direction_deg": 170,
                "wind_speed_mph": 4,
                "cloud_ceiling_ft": 1200,
                "visibility_miles": 6,
            },
            {
                "station": "KSEA",
                "observed_at": "2026-07-14T16:00:00+00:00",
                "temperature_f": 62,
                "dew_point_f": 56,
                "wind_direction_deg": 230,
                "wind_speed_mph": 10,
                "cloud_ceiling_ft": 3200,
                "visibility_miles": 10,
            },
            {
                "station": "KSEA",
                "observed_at": "2026-07-14T18:00:00+00:00",
                "temperature_f": 70,
                "dew_point_f": 57,
                "wind_direction_deg": 250,
                "wind_speed_mph": 12,
                "solar_radiation_wm2": 760,
            },
        ],
        target_date="2026-07-14",
        cloud_features=[cloud],
        model_spread={"spread_f": 5, "mean_high_f": 78},
    )

    assert [snapshot["snapshot_hour_local"] for snapshot in snapshots] == [7, 9, 11, 12]
    nine = snapshots[1]
    assert nine["warming_rate_f_per_hour"] == 2.0
    assert nine["wind_shift"]["detected"] is True
    assert nine["burnoff_status"] == "burned_off"
    assert nine["remaining_upside_distribution"]["placeholder"] is True
    assert "trade" in nine["remaining_upside_distribution"]["note"]


def test_missing_and_stale_nowcast_data_are_labeled() -> None:
    snapshots = generate_fixed_nowcast_snapshots(
        [
            {
                "station": "KSEA",
                "observed_at": "2026-07-14T14:00:00+00:00",
                "temperature_f": 58,
            }
        ],
        target_date="2026-07-14",
    )

    assert snapshots[0]["data_status"] == "fresh"
    assert snapshots[1]["data_status"] == "stale"
    assert snapshots[2]["data_status"] == "stale"


def test_marine_burnoff_classification() -> None:
    assert classify_marine_burnoff(cloud_cover_pct=20, stratus_extent_pct=10, fog_present=False) == "burned_off"
    assert classify_marine_burnoff(cloud_cover_pct=60, stratus_extent_pct=45, fog_present=False) == "partial_burnoff"
    assert classify_marine_burnoff(cloud_cover_pct=90, stratus_extent_pct=80, fog_present=True) == "persistent_marine_layer"
    assert classify_marine_burnoff() == "unknown"


def test_cloud_features_and_nowcast_persistence_round_trip() -> None:
    db_path = _project_temp_db_path("test-nowcast")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            cloud = repo.save_cloud_feature(
                normalize_cloud_feature(
                    {
                        "source": "manual satellite proxy",
                        "observed_at": "2026-07-14T16:00:00+00:00",
                        "cloud_cover_pct": 88,
                        "stratus_extent_pct": 75,
                        "fog_present": "true",
                        "source_hash": "abc123",
                    }
                )
            )
            assert cloud["fog_present"] is True
            assert repo.latest_cloud_feature()["burnoff_status"] == "persistent_marine_layer"

            snapshot = generate_fixed_nowcast_snapshots(
                [
                    {
                        "station": "KSEA",
                        "observed_at": "2026-07-14T16:00:00+00:00",
                        "temperature_f": 62,
                        "cloud_ceiling_ft": 1000,
                    }
                ],
                target_date="2026-07-14",
                cloud_features=[cloud],
            )[1]
            saved = repo.save_nowcast_snapshot(snapshot)
            listed = repo.list_nowcast_snapshots(target_date="2026-07-14")
            assert saved["raw_snapshot"]["remaining_upside_distribution"]["placeholder"] is True
            assert listed[0]["snapshot_hour_local"] == 9
    finally:
        db_path.unlink(missing_ok=True)
