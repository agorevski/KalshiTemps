from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
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
    disk_free_status,
    safe_restore_preflight,
    validate_backup_source,
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


def test_access_posture_summary_classifies_binding_risk() -> None:
    loopback = access_posture_summary("127.0.0.1", 8000)
    broad = access_posture_summary("0.0.0.0", 8000)
    tailnet = access_posture_summary("100.64.1.2", 8000)

    assert loopback["posture"] == "loopback"
    assert broad["posture"] == "broad-bind"
    assert tailnet["posture"] == "tailscale-ip"
    assert broad["tailscale_docs"] == "docs/tailscale-remote-access.md"
    assert "not implemented" in broad["auth"]
