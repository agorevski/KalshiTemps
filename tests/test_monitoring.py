from __future__ import annotations

import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps import cli  # noqa: E402
from kalshi_temps.db import connection, initialize_database  # noqa: E402
from kalshi_temps.monitoring import evaluate_monitoring_checks, report_to_markdown  # noqa: E402
from kalshi_temps.repository import WeatherRepository  # noqa: E402


def _db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def test_evaluate_monitoring_checks_severity_codes_and_empty_summary() -> None:
    checks = evaluate_monitoring_checks(
        {
            "source_health": [{"source_name": "METAR", "is_stale": True, "label": "stale"}],
            "collector_health": [{"source": "NWS", "collector_name": "discussion", "status": "failed"}],
            "latest_observations": [],
            "model_spread": {"target_date": "2026-07-14", "spread_f": 5.25, "model_count": 3},
            "market_verification": {"ticker": "KXHIGHSEA", "is_actionable": False, "reason": "unverified"},
            "paper_live_status": {"run_id": 7, "latest_soak_metric": {"backup_success": 0}},
            "calibration_status": {"metric_count": 0},
        },
        high_spread_threshold_f=4,
    )

    by_code = {check["code"]: check for check in checks}
    assert by_code["stale_source"]["severity"] == "warn"
    assert by_code["collector_failure"]["severity"] == "fail"
    assert by_code["missing_observations"]["severity"] == "fail"
    assert by_code["high_model_spread"]["severity"] == "warn"
    assert by_code["unverified_selected_market"]["severity"] == "fail"
    assert by_code["backup_failure"]["severity"] == "fail"
    assert by_code["calibration_drift_placeholder"]["severity"] == "info"


def test_alert_records_are_idempotent_and_resolvable() -> None:
    db_path = _db_path("test-monitoring-alerts")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            alert = {
                "alert_key": "stale-source:METAR",
                "severity": "warn",
                "code": "stale_source",
                "message": "METAR is stale",
                "source_name": "METAR",
                "details": {"age_minutes": 999},
            }
            first = repo.save_alert_record(alert, alert_day="2026-07-14")
            second = repo.save_alert_record({**alert, "message": "METAR remains stale"}, alert_day="2026-07-14")
            assert first["id"] == second["id"]
            assert len(repo.list_alert_records()) == 1
            assert repo.list_alert_records()[0]["message"] == "METAR remains stale"

            resolved = repo.resolve_alert_record(alert_id=first["id"], resolved_by="test", notes="fixed")
            assert resolved["status"] == "resolved"
            assert repo.list_alert_records() == []
            assert len(repo.list_alert_records(include_resolved=True)) == 1
    finally:
        db_path.unlink(missing_ok=True)


def test_run_monitoring_on_empty_db_records_expected_alerts() -> None:
    db_path = _db_path("test-monitoring-empty")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            result = repo.run_monitoring_checks(alert_day="2026-07-14")
            codes = {check["code"] for check in result["checks"]}
            assert {"missing_sources", "missing_observations", "missing_model_spread", "missing_selected_market"} <= codes
            assert any(check["severity"] == "fail" for check in result["checks"])

            second = repo.run_monitoring_checks(alert_day="2026-07-14")
            assert len(result["alerts"]) == len(second["alerts"])
            assert len(repo.list_alert_records(include_resolved=True)) == len(second["alerts"])
    finally:
        db_path.unlink(missing_ok=True)


def test_daily_report_contains_core_sections_and_exports_markdown_json() -> None:
    db_path = _db_path("test-monitoring-report")
    json_path = Path("data") / f"test-report-{uuid.uuid4().hex}.json"
    md_path = Path("data") / f"test-report-{uuid.uuid4().hex}.md"
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            repo.add_observation("METAR", "KSEA", "2026-07-14T19:00:00+00:00", 75.0)
            repo.import_model_high_records(
                [
                    {"model_name": "HRRR", "run_at": "2026-07-14T12:00:00+00:00", "target_date": "2026-07-14", "predicted_high_f": 75},
                    {"model_name": "GFS", "run_at": "2026-07-14T12:00:00+00:00", "target_date": "2026-07-14", "predicted_high_f": 80},
                ]
            )
            repo.save_alert_record(
                {
                    "alert_key": "high-model-spread:2026-07-14",
                    "severity": "warn",
                    "code": "high_model_spread",
                    "message": "Spread is high",
                },
                alert_day="2026-07-14",
            )
            report = repo.daily_monitoring_report(report_date="2026-07-14")

        markdown = report_to_markdown(report)
        assert report["latest_observations"][0]["station"] == "KSEA"
        assert report["model_spread"]["spread_f"] == 5
        assert report["unresolved_alerts"][0]["code"] == "high_model_spread"
        assert "## Source health" in markdown
        assert "## Unresolved alerts" in markdown

        assert cli.main(["--db", str(db_path), "export-daily-report", "--output", str(json_path), "--report-date", "2026-07-14"]) == 0
        assert cli.main(["--db", str(db_path), "export-daily-report", "--output", str(md_path), "--format", "markdown"]) == 0
        assert json.loads(json_path.read_text(encoding="utf-8"))["report_date"] == "2026-07-14"
        assert "Kalshi Temps Daily Report" in md_path.read_text(encoding="utf-8")
    finally:
        db_path.unlink(missing_ok=True)
        json_path.unlink(missing_ok=True)
        md_path.unlink(missing_ok=True)


def test_monitoring_cli_run_list_and_resolve(capsys) -> None:
    db_path = _db_path("test-monitoring-cli")
    try:
        assert cli.main(["--db", str(db_path), "run-monitoring-checks", "--alert-day", "2026-07-14"]) == 0
        assert cli.main(["--db", str(db_path), "list-alerts", "--severity", "fail"]) == 0
        output = capsys.readouterr().out
        assert "monitoring alert" in output
        assert "missing_observations" in output

        with connection(str(db_path)) as conn:
            alert = WeatherRepository(conn).list_alert_records(severity="fail", limit=1)[0]
        assert cli.main(["--db", str(db_path), "resolve-alert", "--id", str(alert["id"]), "--resolved-by", "test"]) == 0
        with connection(str(db_path)) as conn:
            assert WeatherRepository(conn).list_alert_records(include_resolved=True, severity="fail", limit=1)[0]["status"] == "resolved"
    finally:
        db_path.unlink(missing_ok=True)
