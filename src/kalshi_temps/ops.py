from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import shutil
import sqlite3

from .db import EXPECTED_INDEXES, EXPECTED_SCHEMA_FINGERPRINT, EXPECTED_TABLES, EXPECTED_VIEWS, database_path
from .auth import access_status

MIN_FREE_BYTES = 50 * 1024 * 1024
TAILSCALE_DOC = "docs/tailscale-remote-access.md"


class OpsError(ValueError):
    """Raised when an operations preflight check fails."""


@dataclass(frozen=True)
class PathCheck:
    path: str
    exists: bool
    is_file: bool
    is_dir: bool
    parent_exists: bool
    readable: bool
    writable: bool
    sqlite_header: str

    @property
    def ok(self) -> bool:
        return self.parent_exists and not self.is_dir and (not self.exists or self.is_file)

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "is_file": self.is_file,
            "is_dir": self.is_dir,
            "parent_exists": self.parent_exists,
            "readable": self.readable,
            "writable": self.writable,
            "sqlite_header": self.sqlite_header,
            "ok": self.ok,
        }


def check_db_path(path: str | os.PathLike[str] | None = None) -> PathCheck:
    db_path = database_path(path)
    exists = db_path.exists()
    is_file = db_path.is_file()
    is_dir = db_path.is_dir()
    parent_exists = db_path.parent.exists()
    readable = os.access(db_path, os.R_OK) if exists else False
    writable = os.access(db_path, os.W_OK) if exists else os.access(db_path.parent, os.W_OK)
    sqlite_header = "missing"
    if is_file and readable:
        with db_path.open("rb") as handle:
            sqlite_header = "ok" if handle.read(16) == b"SQLite format 3\0" else "unknown"
    return PathCheck(
        path=str(db_path),
        exists=exists,
        is_file=is_file,
        is_dir=is_dir,
        parent_exists=parent_exists,
        readable=readable,
        writable=writable,
        sqlite_header=sqlite_header,
    )


def _usage_anchor(path: Path) -> Path:
    candidate = path if path.exists() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def disk_free_status(
    path: str | os.PathLike[str] | None = None,
    *,
    min_free_bytes: int = MIN_FREE_BYTES,
) -> dict[str, object]:
    db_path = database_path(path)
    usage = shutil.disk_usage(_usage_anchor(db_path))
    return {
        "path": str(db_path),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "min_free_bytes": min_free_bytes,
        "ok": usage.free >= min_free_bytes,
    }


def backup_file_name(
    db_path: str | os.PathLike[str] | None = None,
    *,
    timestamp: datetime | None = None,
) -> str:
    path = database_path(db_path)
    stamp = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.stem).strip(".-") or "kalshi_temps"
    return f"{safe_stem}-{stamp}.sqlite3"


def backup_path(
    db_path: str | os.PathLike[str] | None = None,
    backup_dir: str | os.PathLike[str] = "data/backups",
    *,
    timestamp: datetime | None = None,
) -> Path:
    return Path(backup_dir).expanduser() / backup_file_name(db_path, timestamp=timestamp)


def _readonly_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def sqlite_check(path: str | os.PathLike[str] | None = None, *, quick: bool = True) -> dict[str, object]:
    db_path = database_path(path)
    check = check_db_path(db_path)
    errors: list[str] = []
    result: str | None = None
    pragma = "quick_check" if quick else "integrity_check"
    if not check.exists:
        errors.append("database file does not exist")
    elif not check.is_file:
        errors.append("database path is not a regular file")
    elif check.sqlite_header != "ok":
        errors.append("database file does not look like SQLite")
    else:
        try:
            with _readonly_connection(db_path) as conn:
                rows = conn.execute(f"PRAGMA {pragma}").fetchall()
            values = [str(row[0]) for row in rows]
            result = "; ".join(values)
            if values != ["ok"]:
                errors.append(f"{pragma} failed: {result}")
        except sqlite3.DatabaseError as exc:
            errors.append(f"{pragma} failed: {exc}")
    return {"ok": not errors, "errors": errors, "path": str(db_path), "check": pragma, "result": result}


def schema_status(path: str | os.PathLike[str] | None = None) -> dict[str, object]:
    db_path = database_path(path)
    check = check_db_path(db_path)
    errors: list[str] = []
    tables: set[str] = set()
    indexes: set[str] = set()
    views: set[str] = set()
    fingerprint = ""
    if not check.exists:
        errors.append("database file does not exist")
    elif not check.is_file:
        errors.append("database path is not a regular file")
    elif check.sqlite_header != "ok":
        errors.append("database file does not look like SQLite")
    else:
        try:
            with _readonly_connection(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT type, name
                    FROM sqlite_schema
                    WHERE name NOT LIKE 'sqlite_%'
                    ORDER BY type, name
                    """
                ).fetchall()
            tables = {row["name"] for row in rows if row["type"] == "table"}
            indexes = {row["name"] for row in rows if row["type"] == "index"}
            views = {row["name"] for row in rows if row["type"] == "view"}
            fingerprint = _schema_fingerprint(tables, indexes, views)
        except sqlite3.DatabaseError as exc:
            errors.append(f"schema read failed: {exc}")
    missing_tables = sorted(EXPECTED_TABLES - tables)
    missing_indexes = sorted(EXPECTED_INDEXES - indexes)
    missing_views = sorted(EXPECTED_VIEWS - views)
    fingerprint_match = fingerprint == EXPECTED_SCHEMA_FINGERPRINT
    if missing_tables:
        errors.append(f"missing expected tables: {', '.join(missing_tables)}")
    if missing_indexes:
        errors.append(f"missing expected indexes: {', '.join(missing_indexes)}")
    if missing_views:
        errors.append(f"missing expected views: {', '.join(missing_views)}")
    if fingerprint and not fingerprint_match:
        errors.append("schema fingerprint differs from expected schema object set")
    return {
        "ok": not errors,
        "errors": errors,
        "path": str(db_path),
        "fingerprint": fingerprint,
        "expected_fingerprint": EXPECTED_SCHEMA_FINGERPRINT,
        "fingerprint_match": fingerprint_match,
        "missing_tables": missing_tables,
        "missing_indexes": missing_indexes,
        "missing_views": missing_views,
        "table_count": len(tables),
        "index_count": len(indexes),
        "view_count": len(views),
    }


def _schema_fingerprint(tables: set[str], indexes: set[str], views: set[str]) -> str:
    import hashlib

    payload = "\n".join(
        [f"index:{name}" for name in sorted(indexes)]
        + [f"table:{name}" for name in sorted(tables)]
        + [f"view:{name}" for name in sorted(views)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def db_check(path: str | os.PathLike[str] | None = None, *, quick: bool = True) -> dict[str, object]:
    disk = check_db_path(path).as_dict()
    integrity = sqlite_check(path, quick=quick)
    schema = schema_status(path)
    errors = [*integrity["errors"], *schema["errors"]]
    return {"ok": not errors, "errors": errors, "database": disk, "integrity": integrity, "schema": schema}


def verify_backup_file(path: str | os.PathLike[str]) -> dict[str, object]:
    backup_file = Path(path).expanduser()
    check = check_db_path(backup_file)
    errors: list[str] = []
    if not check.exists:
        errors.append("backup file does not exist")
    if check.is_dir:
        errors.append("backup path is a directory")
    if check.exists and check.is_file and backup_file.stat().st_size == 0:
        errors.append("backup file is empty")
    if check.exists and not check.readable:
        errors.append("backup file is not readable")
    if check.exists and check.sqlite_header != "ok":
        errors.append("backup file does not look like SQLite")
    quick = sqlite_check(backup_file, quick=True) if not errors else None
    if quick and not quick["ok"]:
        errors.extend(str(error) for error in quick["errors"])
    return {"ok": not errors, "errors": errors, "backup": check.as_dict(), "quick_check": quick}


def validate_backup_source(path: str | os.PathLike[str] | None = None) -> dict[str, object]:
    check = check_db_path(path)
    errors: list[str] = []
    if not check.exists:
        errors.append("database file does not exist")
    if check.is_dir:
        errors.append("database path is a directory")
    if check.exists and not check.readable:
        errors.append("database file is not readable")
    if check.exists and check.sqlite_header != "ok":
        errors.append("database file does not look like SQLite")
    quick = sqlite_check(path, quick=True) if not errors else None
    if quick and not quick["ok"]:
        errors.extend(str(error) for error in quick["errors"])
    return {"ok": not errors, "errors": errors, "database": check.as_dict(), "quick_check": quick}


def safe_restore_preflight(
    backup: str | os.PathLike[str],
    target: str | os.PathLike[str] | None = None,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    backup_file = Path(backup).expanduser()
    target_file = database_path(target)
    errors: list[str] = []
    backup_check = verify_backup_file(backup_file)
    if not backup_check["ok"]:
        errors.extend(str(error) for error in backup_check["errors"])
    if backup_file.exists() and target_file.exists() and backup_file.resolve() == target_file.resolve():
        errors.append("backup and target paths must differ")
    if target_file.exists() and target_file.is_dir():
        errors.append("target path is a directory")
    if target_file.exists() and not force:
        errors.append("target database exists; pass --force to overwrite")
    if not target_file.parent.exists():
        errors.append("target parent directory does not exist")
    elif not os.access(target_file.parent, os.W_OK):
        errors.append("target parent directory is not writable")
    if errors:
        raise OpsError("; ".join(errors))
    return {
        "ok": True,
        "backup": str(backup_file),
        "target": str(target_file),
        "target_exists": target_file.exists(),
        "force": force,
        "dry_run": dry_run,
        "backup_check": backup_check,
    }


def prune_backups(
    backup_dir: str | os.PathLike[str] = "data/backups",
    *,
    older_than_days: int = 30,
    keep: int = 5,
    min_keep: int = 1,
    dry_run: bool = True,
) -> dict[str, object]:
    if older_than_days < 0:
        raise OpsError("older_than_days must be non-negative")
    if min_keep < 1:
        raise OpsError("min_keep must be at least 1")
    if keep < min_keep:
        raise OpsError(f"keep must be at least min_keep ({min_keep})")
    directory = Path(backup_dir).expanduser()
    if not directory.exists():
        raise OpsError("backup directory does not exist")
    if not directory.is_dir():
        raise OpsError("backup path is not a directory")
    backups = sorted(
        [path for path in directory.iterdir() if path.is_file() and path.suffix in {".sqlite", ".sqlite3", ".db"}],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    protected = set(backups[:keep])
    candidates = [
        path
        for path in backups[keep:]
        if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff and path not in protected
    ]
    remaining = len(backups) - len(candidates)
    if remaining < min_keep:
        raise OpsError(f"prune would leave fewer than min_keep backups ({min_keep})")
    deleted: list[str] = []
    if not dry_run:
        for path in candidates:
            path.unlink()
            deleted.append(str(path))
    return {
        "ok": True,
        "backup_dir": str(directory),
        "dry_run": dry_run,
        "older_than_days": older_than_days,
        "keep": keep,
        "min_keep": min_keep,
        "candidate_count": len(candidates),
        "candidates": [str(path) for path in candidates],
        "deleted": deleted,
        "remaining_count": remaining,
    }


def access_posture_summary(host: str = "127.0.0.1", port: int = 8000) -> dict[str, object]:
    auth = access_status()
    if host in {"127.0.0.1", "::1", "localhost"}:
        posture = "loopback"
        guidance = "Safest local default; use SSH forwarding or Tailscale Serve for remote access."
    elif host == "0.0.0.0" or host == "::":
        posture = "broad-bind"
        guidance = "Exposes all interfaces; prefer loopback, a Tailscale IP, firewall scoping, and real auth before public use."
    elif host.startswith("100."):
        posture = "tailscale-ip"
        guidance = "Tailnet-scoped direct bind; confirm firewall rules and device membership."
    else:
        posture = "specific-host"
        guidance = "Confirm this interface is trusted and not publicly reachable without proper auth."
    return {
        "host": host,
        "port": port,
        "posture": posture,
        "guidance": guidance,
        "tailscale_docs": TAILSCALE_DOC,
        "auth": auth.as_dict(),
    }


def paper_live_readiness(
    *,
    active_runs: list[dict[str, object]] | None = None,
    collector_health: list[dict[str, object]] | None = None,
    backup_success: bool | None = None,
) -> dict[str, object]:
    active_runs = active_runs or []
    collector_health = collector_health or []
    stale_collectors = [item for item in collector_health if item.get("is_stale") or item.get("status") == "failed"]
    blockers: list[str] = []
    if not active_runs:
        blockers.append("no active paper-live run")
    if stale_collectors:
        blockers.append("collector health needs review")
    if backup_success is False:
        blockers.append("latest backup not marked successful")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "active_run_count": len(active_runs),
        "stale_collector_count": len(stale_collectors),
        "backup_success": backup_success,
        "note": "Readiness is an operational checklist only; it does not enable or recommend automated betting.",
    }


def paper_live_run_status(run: dict[str, object]) -> dict[str, object]:
    checklist = run.get("checklist") or []
    soak_metrics = run.get("soak_metrics") or []
    open_items = [item for item in checklist if isinstance(item, dict) and item.get("status") != "done"]
    latest_soak = soak_metrics[0] if soak_metrics else None
    return {
        "run_id": run.get("id"),
        "status": run.get("status"),
        "is_active": run.get("status") == "active",
        "open_checklist_count": len(open_items),
        "prediction_note_count": len(run.get("prediction_notes") or []),
        "reconciliation_note_count": len(run.get("reconciliation_notes") or []),
        "latest_soak_metric": latest_soak,
        "no_automated_betting": True,
    }


def ops_status(path: str | os.PathLike[str] | None = None, *, host: str = "127.0.0.1", port: int = 8000) -> dict[str, object]:
    return {
        "database": check_db_path(path).as_dict(),
        "disk": disk_free_status(path),
        "access": access_posture_summary(host, port),
    }
