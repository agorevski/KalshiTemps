from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.db import initialize_database
from kalshi_temps.ops import (
    OpsError,
    access_posture_summary,
    backup_file_name,
    backup_path,
    check_db_path,
    db_check,
    disk_free_status,
    paper_live_readiness,
    paper_live_run_status,
    prune_backups,
    safe_restore_preflight,
    validate_backup_source,
    verify_backup_file,
)


def _db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def test_db_path_and_disk_checks_for_sqlite_database() -> None:
    db_path = _db_path("test-ops-check")
    try:
        initialize_database(str(db_path))
        check = check_db_path(db_path)
        assert check.ok
        assert check.exists
        assert check.sqlite_header == "ok"

        disk = disk_free_status(db_path, min_free_bytes=1)
        assert disk["ok"] is True
        assert disk["free_bytes"] > 0
    finally:
        db_path.unlink(missing_ok=True)


def test_db_check_detects_healthy_database_schema() -> None:
    db_path = _db_path("test-ops-healthy")
    try:
        initialize_database(str(db_path))
        result = db_check(db_path)
        assert result["ok"] is True
        assert result["integrity"]["result"] == "ok"
        assert result["schema"]["missing_tables"] == []
        assert result["schema"]["missing_indexes"] == []
    finally:
        db_path.unlink(missing_ok=True)


def test_db_check_detects_missing_expected_table() -> None:
    db_path = _db_path("test-ops-missing-table")
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE data_sources (id INTEGER PRIMARY KEY)")
        result = db_check(db_path)
        assert result["ok"] is False
        assert "observations" in result["schema"]["missing_tables"]
        assert any("missing expected tables" in error for error in result["errors"])
    finally:
        db_path.unlink(missing_ok=True)


def test_backup_file_name_and_path_are_timestamped_and_sanitized() -> None:
    stamp = datetime(2026, 7, 14, 23, 46, tzinfo=timezone.utc)
    assert backup_file_name("data/kalshi temps.sqlite3", timestamp=stamp) == "kalshi-temps-20260714T234600Z.sqlite3"
    assert backup_path("data/kalshi temps.sqlite3", "data/backups", timestamp=stamp) == Path(
        "data/backups/kalshi-temps-20260714T234600Z.sqlite3"
    )


def test_restore_preflight_requires_force_for_existing_target() -> None:
    backup = _db_path("test-ops-backup")
    target = _db_path("test-ops-target")
    try:
        initialize_database(str(backup))
        initialize_database(str(target))
        assert validate_backup_source(backup)["ok"] is True

        with pytest.raises(OpsError, match="--force"):
            safe_restore_preflight(backup, target)

        result = safe_restore_preflight(backup, target, force=True)
        assert result["ok"] is True
        assert result["target_exists"] is True
    finally:
        backup.unlink(missing_ok=True)
        target.unlink(missing_ok=True)


def test_verify_backup_rejects_corrupt_non_sqlite_backup() -> None:
    backup = _db_path("test-ops-bad-backup")
    try:
        backup.write_text("not sqlite", encoding="utf-8")
        result = verify_backup_file(backup)
        assert result["ok"] is False
        assert "backup file does not look like SQLite" in result["errors"]
        with pytest.raises(OpsError, match="does not look like SQLite"):
            safe_restore_preflight(backup, _db_path("test-ops-target-bad"), dry_run=True)
    finally:
        backup.unlink(missing_ok=True)


def test_prune_backups_dry_run_and_min_keep_guard() -> None:
    backup_dir = Path("data") / f"test-backups-{uuid.uuid4().hex}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        files = []
        for index in range(4):
            path = backup_dir / f"backup-{index}.sqlite3"
            initialize_database(path)
            old_time = datetime(2026, 1, index + 1, tzinfo=timezone.utc).timestamp()
            os.utime(path, (old_time, old_time))
            files.append(path)

        result = prune_backups(backup_dir, older_than_days=1, keep=2, min_keep=2, dry_run=True)
        assert result["candidate_count"] == 2
        assert result["deleted"] == []
        assert all(path.exists() for path in files)

        with pytest.raises(OpsError, match="keep must be at least min_keep"):
            prune_backups(backup_dir, older_than_days=1, keep=1, min_keep=2, dry_run=True)
    finally:
        for path in backup_dir.glob("*"):
            path.unlink(missing_ok=True)
        backup_dir.rmdir()


def test_access_posture_summary_classifies_binding_risk() -> None:
    loopback = access_posture_summary("127.0.0.1", 8000)
    broad = access_posture_summary("0.0.0.0", 8000)
    tailnet = access_posture_summary("100.64.1.2", 8000)

    assert loopback["posture"] == "loopback"
    assert broad["posture"] == "broad-bind"
    assert tailnet["posture"] == "tailscale-ip"
    assert broad["tailscale_docs"] == "docs/tailscale-remote-access.md"
    assert broad["auth"]["mode"] in {"open-local-dev", "env-token"}


def test_paper_live_ops_helpers_summarize_readiness_and_run_status() -> None:
    readiness = paper_live_readiness(
        active_runs=[{"id": 1}],
        collector_health=[{"collector_name": "metar", "status": "success", "is_stale": False}],
        backup_success=True,
    )
    assert readiness["ready"] is True
    assert readiness["note"].startswith("Readiness")

    blocked = paper_live_readiness(active_runs=[], collector_health=[{"status": "failed"}], backup_success=False)
    assert blocked["ready"] is False
    assert "no active paper-live run" in blocked["blockers"]

    status = paper_live_run_status(
        {
            "id": 7,
            "status": "active",
            "checklist": [{"status": "pending"}, {"status": "done"}],
            "prediction_notes": [{"id": 1}],
            "reconciliation_notes": [],
            "soak_metrics": [{"alert_count": 0}],
        }
    )
    assert status["is_active"] is True
    assert status["open_checklist_count"] == 1
    assert status["no_automated_betting"] is True
