from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.backfill import run_backfill  # noqa: E402
from kalshi_temps import cli  # noqa: E402
from kalshi_temps.db import connection, initialize_database  # noqa: E402
from kalshi_temps.repository import WeatherRepository  # noqa: E402


def _project_temp_db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def _project_fixture_dir(prefix: str) -> Path:
    path = Path("data") / f"{prefix}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_backfill_imports_fixture_bundle_idempotently() -> None:
    db_path = _project_temp_db_path("test-backfill")
    fixture_dir = _project_fixture_dir("fixture-backfill")
    try:
        (fixture_dir / "bundle.json").write_text(
            json.dumps(
                {
                    "observations": [
                        {"source_name": "fixture", "station": "KSEA", "observed_at": "2026-07-14T18:00:00+00:00", "temperature_f": 72}
                    ],
                    "model_runs": [
                        {"run_at": "2026-07-14T00:00:00+00:00", "model_name": "FixtureModel", "target_date": "2026-07-14", "predicted_high_f": 76}
                    ],
                    "market_snapshots": [
                        {"ticker": "KXSEA-26JUL14-T75", "captured_at": "2026-07-14T12:00:00+00:00", "temperature_bucket": "75-76°F", "implied_probability": 0.6}
                    ],
                    "official_outcomes": [
                        {"station": "KSEA", "target_date": "2026-07-14", "high_temperature_f": 76}
                    ],
                    "regime_tags": [
                        {"extracted_at": "2026-07-14T10:00:00+00:00", "regime_tags": ["marine_layer"], "evidence": ["clouds"]}
                    ],
                    "prediction_snapshots": [
                        {"snapshot_at": "2026-07-14T12:00:00+00:00", "model_name": "FixtureModel", "station": "KSEA", "target_date": "2026-07-14", "regime": "marine_layer", "predicted_high_f": 75, "temperature_bucket": "75-76°F", "probability": 0.7}
                    ],
                }
            ),
            encoding="utf-8",
        )

        first = run_backfill(str(db_path), fixture_dir)
        second = run_backfill(str(db_path), fixture_dir)

        assert first["status"] == "success"
        assert second["status"] == "success"
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            assert len(repo.list_observations()) == 1
            assert len(repo.list_model_runs()) == 1
            assert len(repo.list_market_snapshots()) == 1
            assert len(repo.list_official_outcomes()) == 1
            assert len(repo.list_weather_regime_features()) == 1
            assert len(repo.list_prediction_snapshots()) == 1
            assert len(repo.list_backfill_runs()) == 2
    finally:
        db_path.unlink(missing_ok=True)
        shutil.rmtree(fixture_dir, ignore_errors=True)


def test_backfill_reports_partial_failures() -> None:
    db_path = _project_temp_db_path("test-backfill-partial")
    fixture_dir = _project_fixture_dir("fixture-backfill-partial")
    try:
        (fixture_dir / "official_outcomes.csv").write_text(
            "station,target_date,high_temperature_f\nKSEA,2026-07-14,76\nKSEA,,77\n",
            encoding="utf-8",
        )
        result = run_backfill(str(db_path), fixture_dir)
        assert result["status"] == "partial_failure"
        assert result["counts"]["official_outcomes_imported"] == 1
        assert result["errors"]
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            assert WeatherRepository(conn).list_backfill_runs(limit=1)[0]["status"] == "partial_failure"
    finally:
        db_path.unlink(missing_ok=True)
        shutil.rmtree(fixture_dir, ignore_errors=True)


def test_cli_runs_backfill_and_exports_calibration_report(capsys) -> None:
    db_path = _project_temp_db_path("test-backfill-cli")
    fixture_dir = _project_fixture_dir("fixture-backfill-cli")
    output_path = Path("data") / f"calibration-report-{uuid.uuid4().hex}.json"
    try:
        (fixture_dir / "prediction_snapshots.json").write_text(
            json.dumps(
                [
                    {
                        "snapshot_at": "2026-07-14T12:00:00+00:00",
                        "model_name": "FixtureModel",
                        "station": "KSEA",
                        "target_date": "2026-07-14",
                        "predicted_high_f": 75,
                        "temperature_bucket": "75-76°F",
                        "probability": 0.7,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (fixture_dir / "official_outcomes.json").write_text(
            json.dumps([{"station": "KSEA", "target_date": "2026-07-14", "high_temperature_f": 76}]),
            encoding="utf-8",
        )

        assert cli.main(["--db", str(db_path), "run-backfill", str(fixture_dir)]) == 0
        assert cli.main(["--db", str(db_path), "calibration-report", "--output", str(output_path), "--bins", "4"]) == 0
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["sample_sizes"]["prediction_count"] == 1
        assert report["bucket_metrics"][0]["sample_count"] == 1
        output = capsys.readouterr().out
        assert "Backfill success" in output
        assert "Exported calibration report" in output
    finally:
        db_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        shutil.rmtree(fixture_dir, ignore_errors=True)
