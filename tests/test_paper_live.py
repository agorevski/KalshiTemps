from __future__ import annotations

from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps import cli
from kalshi_temps.db import connection, initialize_database
from kalshi_temps.repository import WeatherRepository


def _db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def test_paper_live_repository_persists_run_workflow() -> None:
    db_path = _db_path("test-paper-live-repo")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            run = repo.start_paper_live_run(run_name="July soak", target_date="2026-07-15", notes="evidence only")
            checklist = repo.add_paper_live_checklist_entry(run["id"], item="Collectors checked", status="done")
            prediction = repo.add_paper_live_prediction_note(
                run["id"],
                {"target_date": "2026-07-15", "predicted_high_f": 75, "note": "Morning blend note"},
            )
            postmortem = repo.add_paper_live_reconciliation_note(run["id"], note="No trade was placed")
            soak = repo.add_paper_live_soak_metric(
                run["id"],
                {"uptime_status": "placeholder", "collector_success_count": 2, "backup_success": True, "alert_count": 0},
            )
            detail = repo.paper_live_run_detail(run["id"])
            closed = repo.close_paper_live_run(run["id"], notes="closed cleanly")

        assert checklist["status"] == "done"
        assert prediction["note"] == "Morning blend note"
        assert postmortem["note_type"] == "postmortem"
        assert soak["backup_success"] == 1
        assert len(detail["checklist"]) == 1
        assert len(detail["prediction_notes"]) == 1
        assert closed["status"] == "closed"
    finally:
        db_path.unlink(missing_ok=True)


def test_paper_live_cli_commands_persist_and_print(capsys) -> None:
    db_path = _db_path("test-paper-live-cli")
    try:
        assert cli.main(["--db", str(db_path), "start-paper-live-run", "--name", "CLI soak", "--target-date", "2026-07-15"]) == 0
        with connection(str(db_path)) as conn:
            run_id = WeatherRepository(conn).list_paper_live_runs()[0]["id"]

        assert cli.main(["--db", str(db_path), "record-paper-live-checklist", str(run_id), "--item", "Backup checked", "--status", "done"]) == 0
        assert cli.main(["--db", str(db_path), "record-paper-live-prediction-note", str(run_id), "--note", "Paper prediction only"]) == 0
        assert cli.main(["--db", str(db_path), "record-paper-live-soak-metric", str(run_id), "--backup-success", "--alert-count", "1"]) == 0
        assert cli.main(["--db", str(db_path), "record-paper-live-postmortem", str(run_id), "--note", "Reconciled manually"]) == 0
        assert cli.main(["--db", str(db_path), "list-paper-live-runs", "--include-closed"]) == 0
        assert cli.main(["--db", str(db_path), "close-paper-live-run", str(run_id), "--notes", "done"]) == 0

        output = capsys.readouterr().out
        assert "Started paper-live run" in output
        assert "no automated betting" in output
        assert "Paper prediction only" not in output

        with connection(str(db_path)) as conn:
            detail = WeatherRepository(conn).paper_live_run_detail(run_id)
        assert detail["status"] == "closed"
        assert detail["soak_metrics"][0]["alert_count"] == 1
    finally:
        db_path.unlink(missing_ok=True)
