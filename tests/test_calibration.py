from __future__ import annotations

import math
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.calibration import (  # noqa: E402
    bucket_brier_score,
    bucket_contains_temperature,
    bucket_log_loss,
    chronological_split_date,
    generate_calibration_report,
    forecast_error,
    grouped_bias_summary,
    leakage_safe_date_split,
    reliability_bins,
)
from kalshi_temps import cli  # noqa: E402
from kalshi_temps.db import connection, initialize_database  # noqa: E402
from kalshi_temps.repository import WeatherRepository  # noqa: E402


def _project_temp_db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def test_forecast_error_and_grouped_bias_math() -> None:
    error = forecast_error(78, 75.5)
    assert error.error_f == 2.5
    assert error.absolute_error_f == 2.5
    assert error.squared_error_f == 6.25

    summaries = grouped_bias_summary(
        [
            {"model_name": "A", "regime": "marine", "station": "KSEA", "predicted_high_f": 78, "actual_high_f": 76},
            {"model_name": "A", "regime": "marine", "station": "KSEA", "predicted_high_f": 74, "actual_high_f": 76},
            {"model_name": "B", "regime": "clear", "station": "KSEA", "predicted_high_f": None, "actual_high_f": 76},
        ]
    )

    assert len(summaries) == 1
    assert summaries[0]["sample_count"] == 2
    assert summaries[0]["mean_error_f"] == 0
    assert summaries[0]["mean_absolute_error_f"] == 2
    assert summaries[0]["rmse_f"] == 2
    assert summaries[0]["warm_bias_count"] == 1
    assert summaries[0]["cool_bias_count"] == 1


def test_brier_reliability_bucket_and_empty_edges() -> None:
    records = [
        {"probability": 0.8, "outcome": 1},
        {"probability": 0.2, "outcome": 0},
        {"probability": 50, "outcome": True},
        {"probability": None, "outcome": 1},
    ]

    assert round(bucket_brier_score(records), 6) == round(((0.2**2) + (0.2**2) + (0.5**2)) / 3, 6)
    bins = reliability_bins(records, bin_count=2, include_empty=True)
    assert len(bins) == 2
    assert bins[0]["sample_count"] == 1
    assert bins[1]["sample_count"] == 2
    assert bucket_brier_score([]) is None
    assert reliability_bins([], bin_count=2) == []
    assert bucket_contains_temperature("<73°F", 72.9)
    assert bucket_contains_temperature("73-74°F", 74)
    assert bucket_contains_temperature("77°F+", 77)
    assert not bucket_contains_temperature("75-76°F", 77)
    assert round(bucket_log_loss([{"probability": 0.8, "outcome": 1}]), 6) == round(-math.log(0.8), 6)


def test_leakage_safe_date_split_helpers() -> None:
    records = [
        {"target_date": "2026-07-01", "value": "train"},
        {"target_date": "2026-07-02", "value": "gap"},
        {"target_date": "2026-07-03", "value": "test"},
    ]

    split = leakage_safe_date_split(records, split_date="2026-07-03", gap_days=1)
    assert [record["value"] for record in split["train"]] == ["train"]
    assert [record["value"] for record in split["test"]] == ["test"]
    assert chronological_split_date([record["target_date"] for record in records], test_fraction=0.34).isoformat() == "2026-07-02"


def test_generate_calibration_report_metrics_missingness_and_empty_data() -> None:
    report = generate_calibration_report(
        [
            {
                "model_name": "A",
                "regime": "marine",
                "station": "KSEA",
                "snapshot_at": "2026-07-01T12:00:00+00:00",
                "target_date": "2026-07-01",
                "predicted_high_f": 76,
                "actual_high_f": 75,
                "temperature_bucket": "75-76°F",
                "probability": 0.8,
            },
            {
                "model_name": "A",
                "station": "KSEA",
                "snapshot_at": "2026-07-02T18:00:00+00:00",
                "target_date": "2026-07-02",
                "predicted_high_f": 72,
            },
        ],
        bin_count=5,
        split_date="2026-07-02",
    )

    assert report["sample_sizes"]["prediction_count"] == 2
    assert report["sample_sizes"]["matched_outcome_count"] == 1
    assert report["bucket_metrics"][0]["brier_score"] == (0.8 - 1) ** 2
    assert report["mae"]
    assert report["missingness"]["fields"]["actual_high_f"]["missing_count"] == 1
    assert report["leakage_safe_split"]["valid"] is False

    empty = generate_calibration_report([])
    assert empty["sample_sizes"]["prediction_count"] == 0
    assert empty["bucket_metrics"] == []


def test_repository_persists_outcomes_predictions_bias_and_calibration() -> None:
    db_path = _project_temp_db_path("test-calibration-repo")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            assert repo.compute_bias_summaries() == []
            assert repo.compute_calibration_metrics() == []

            outcome = repo.save_official_outcome(
                station="KSEA",
                target_date="2026-07-14",
                high_temperature_f=76,
                source_name="Fixture official",
                raw_payload={"fixture": True},
            )
            repo.save_official_outcome(station="KSEA", target_date="2026-07-15", high_temperature_f=78)
            repo.save_prediction_snapshot(
                {
                    "snapshot_at": "2026-07-14T12:00:00+00:00",
                    "model_name": "FixtureModel",
                    "station": "KSEA",
                    "target_date": "2026-07-14",
                    "regime": "marine",
                    "predicted_high_f": 78,
                    "temperature_bucket": "75-76°F",
                    "probability": 0.7,
                    "hypothesis": "Marine layer clears by noon.",
                }
            )
            repo.save_prediction_snapshot(
                {
                    "snapshot_at": "2026-07-15T12:00:00+00:00",
                    "model_name": "FixtureModel",
                    "station": "KSEA",
                    "target_date": "2026-07-15",
                    "regime": "marine",
                    "predicted_high_f": 77,
                    "temperature_bucket": "77°F+",
                    "probability": 0.25,
                }
            )

            assert outcome["raw_payload"] == '{"fixture": true}'
            assert len(repo.list_official_outcomes()) == 2
            assert len(repo.list_prediction_snapshots()) == 2

            bias = repo.compute_bias_summaries()
            metrics = repo.compute_calibration_metrics(bin_count=5)

        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            persisted_bias = repo.list_bias_summaries()
            persisted_metrics = repo.list_calibration_metrics()

        assert bias == persisted_bias
        assert bias[0]["sample_count"] == 2
        assert bias[0]["mean_error_f"] == 0.5
        assert bias[0]["mean_absolute_error_f"] == 1.5
        assert persisted_metrics
        assert {metric["temperature_bucket"] for metric in metrics} == {"75-76°F", "77°F+"}
    finally:
        db_path.unlink(missing_ok=True)


def test_cli_records_outcome_prediction_and_computes_calibration(capsys) -> None:
    db_path = _project_temp_db_path("test-calibration-cli")
    try:
        assert cli.main(
            [
                "--db",
                str(db_path),
                "record-official-outcome",
                "--station",
                "KSEA",
                "--target-date",
                "2026-07-14",
                "--high-temperature-f",
                "76",
            ]
        ) == 0
        assert cli.main(
            [
                "--db",
                str(db_path),
                "record-prediction-snapshot",
                "--model-name",
                "ManualBaseline",
                "--station",
                "KSEA",
                "--target-date",
                "2026-07-14",
                "--predicted-high-f",
                "75",
                "--temperature-bucket",
                "75-76°F",
                "--probability",
                "0.6",
            ]
        ) == 0
        assert cli.main(["--db", str(db_path), "compute-calibration", "--bins", "4"]) == 0

        output = capsys.readouterr().out
        assert "Recorded official outcome KSEA 2026-07-14" in output
        assert "Computed 1 bias summaries and 1 calibration metrics" in output
    finally:
        db_path.unlink(missing_ok=True)
