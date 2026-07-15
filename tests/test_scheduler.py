from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from kalshi_temps import cli, scheduler
from kalshi_temps.db import connection, initialize_database
from kalshi_temps.ingest import CollectorResult
from kalshi_temps.repository import WeatherRepository


def _project_path(prefix: str, suffix: str) -> Path:
    path = Path("data") / f"{prefix}-{uuid.uuid4().hex}{suffix}"
    path.parent.mkdir(exist_ok=True)
    return path


def _collector_result(name: str, *, status: str = "success") -> CollectorResult:
    return CollectorResult(
        source="Fixture Source",
        collector_name=name,
        started_at="2026-07-14T20:00:00+00:00",
        finished_at="2026-07-14T20:00:01+00:00",
        status=status,
        records=[
            {
                "product_id": "AFDSEW",
                "issued_at": "2026-07-14T19:30:00+00:00",
                "ingest_at": "2026-07-14T20:00:00+00:00",
                "source_url": "https://example.test/afd",
                "text": "AFDSEW\nMarine layer clearing late.",
                "text_hash": "text-hash",
                "raw_payload_hash": "raw-hash",
                "parser_status": "ok",
            }
        ],
        records_returned=1 if status == "success" else 0,
        newest_observation_at="2026-07-14T19:30:00+00:00",
        latency_seconds=1.0,
        error_message=None if status == "success" else "fixture failure",
        source_url="https://example.test/afd",
        payload_hash="raw-hash",
        attempts=1,
    )


def test_scheduler_lock_blocks_overlap_and_recovers_stale_lock() -> None:
    lock_path = _project_path("scheduler-lock", ".lock")
    try:
        held = scheduler.acquire_lock(lock_path, metadata={"test": True})
        with pytest.raises(scheduler.SchedulerLockError, match="already held"):
            scheduler.acquire_lock(lock_path, stale_after_seconds=3600)
        scheduler.release_lock(held)

        lock_path.write_text('{"created_at":"2000-01-01T00:00:00+00:00","token":"stale"}\n', encoding="utf-8")
        recovered = scheduler.acquire_lock(lock_path, stale_after_seconds=1)
        assert recovered.metadata["token"] != "stale"
        scheduler.release_lock(recovered)
        assert not lock_path.exists()
    finally:
        lock_path.unlink(missing_ok=True)


def test_dry_run_plans_selected_collectors_without_database_writes() -> None:
    db_path = _project_path("scheduler-dry-run", ".sqlite3")
    lock_path = _project_path("scheduler-dry-run", ".lock")
    try:
        summary = scheduler.run_scheduled_collectors(
            str(db_path),
            collectors=["metar"],
            lockfile=lock_path,
            dry_run=True,
            timeout=7,
            timeout_overrides={"metar": 3},
        )
        assert summary["status"] == "success"
        assert summary["dry_run"] is True
        assert [item["collector_name"] for item in summary["collectors"]] == ["metar"]
        assert summary["collectors"][0]["status"] == "planned"
        assert summary["collectors"][0]["timeout_seconds"] == 3
        assert not db_path.exists()
        assert not lock_path.exists()
    finally:
        db_path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)


def test_selected_collector_failure_summary_is_persisted(monkeypatch) -> None:
    db_path = _project_path("scheduler-failure", ".sqlite3")
    lock_path = _project_path("scheduler-failure", ".lock")
    original = scheduler.COLLECTOR_SPECS["nws_discussion"]
    spec = scheduler.CollectorSpec(
        name=original.name,
        source=original.source,
        persist_kind=original.persist_kind,
        run=lambda **kwargs: _collector_result("nws_discussion", status="failed"),
    )
    monkeypatch.setitem(scheduler.COLLECTOR_SPECS, "nws_discussion", spec)
    try:
        summary = scheduler.run_scheduled_collectors(
            str(db_path),
            collectors="nws_discussion",
            lockfile=lock_path,
        )
        assert summary["status"] == "failed"
        assert summary["failure_count"] == 1
        assert summary["collectors"][0]["error_message"] == "fixture failure"
        with connection(str(db_path)) as conn:
            runs = WeatherRepository(conn).list_collector_runs(limit=1)
        assert runs[0]["status"] == "failed"
        assert runs[0]["collector_name"] == "nws_discussion"
    finally:
        db_path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)


def test_scheduler_status_reports_lock_and_health() -> None:
    db_path = _project_path("scheduler-status", ".sqlite3")
    lock_path = _project_path("scheduler-status", ".lock")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            WeatherRepository(conn).record_collector_run(_collector_result("nws_discussion").poll_record())
        held = scheduler.acquire_lock(lock_path, metadata={"test": True})
        try:
            status = scheduler.scheduler_status(str(db_path), lockfile=lock_path, max_age_minutes=10_000_000)
        finally:
            scheduler.release_lock(held)
        assert status["lock"]["locked"] is True
        assert status["lock"]["stale"] is False
        assert status["collector_health"][0]["collector_name"] == "nws_discussion"
    finally:
        db_path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)


def test_cli_scheduled_collectors_dry_run_and_script_syntax(capsys) -> None:
    db_path = _project_path("scheduler-cli", ".sqlite3")
    lock_path = _project_path("scheduler-cli", ".lock")
    try:
        exit_code = cli.main(
            [
                "--db",
                str(db_path),
                "run-scheduled-collectors",
                "--collector",
                "metar",
                "--collector-timeout",
                "metar=2",
                "--lockfile",
                str(lock_path),
                "--dry-run",
            ]
        )
        assert exit_code == 0
        output = capsys.readouterr().out
        assert '"collector_name": "metar"' in output
        assert '"timeout_seconds": 2.0' in output
        subprocess.run(["bash", "-n", "scripts/run_collectors_once.sh"], check=True)
    finally:
        db_path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)
