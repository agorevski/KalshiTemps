from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .db import database_path, initialize_database, connection
from .ingest import (
    DEFAULT_AVIATION_WEATHER_METAR_URL_TEMPLATE,
    DEFAULT_NWS_SEW_DISCUSSION_URL,
    CollectorResult,
    run_forecast_discussion_collector,
    run_metar_collector,
)
from .repository import WeatherRepository

DEFAULT_LOCKFILE = Path("data/scheduler/collectors.lock")
DEFAULT_LOCK_STALE_SECONDS = 60 * 60
DEFAULT_COLLECTORS = ("nws_discussion", "metar")


class SchedulerLockError(RuntimeError):
    """Raised when a scheduler lock cannot be acquired safely."""


@dataclass(frozen=True)
class SchedulerLock:
    path: Path
    token: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CollectorSpec:
    name: str
    source: str
    run: Callable[..., CollectorResult]
    persist_kind: str


COLLECTOR_SPECS: dict[str, CollectorSpec] = {
    "nws_discussion": CollectorSpec(
        name="nws_discussion",
        source="NWS Seattle Forecast Discussion",
        run=run_forecast_discussion_collector,
        persist_kind="forecast_discussion",
    ),
    "metar": CollectorSpec(
        name="metar",
        source="Aviation Weather METAR",
        run=run_metar_collector,
        persist_kind="observation",
    ),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_collectors(collectors: str | Sequence[str] | None) -> list[str]:
    if collectors is None:
        return list(DEFAULT_COLLECTORS)
    raw: list[str] = []
    if isinstance(collectors, str):
        raw.extend(part.strip() for part in collectors.split(","))
    else:
        for item in collectors:
            raw.extend(part.strip() for part in str(item).split(","))
    selected = [item for item in raw if item]
    if not selected or selected == ["all"]:
        return list(DEFAULT_COLLECTORS)
    unknown = sorted(set(selected) - set(COLLECTOR_SPECS))
    if unknown:
        raise ValueError(f"Unknown scheduled collector(s): {', '.join(unknown)}")
    return selected


def parse_timeout_overrides(values: Sequence[str] | None) -> dict[str, float]:
    overrides: dict[str, float] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError("collector timeout overrides must use NAME=SECONDS")
        name, raw_seconds = value.split("=", 1)
        name = name.strip()
        if name not in COLLECTOR_SPECS:
            raise ValueError(f"Unknown collector timeout override: {name}")
        seconds = float(raw_seconds)
        if seconds <= 0:
            raise ValueError("collector timeout seconds must be positive")
        overrides[name] = seconds
    return overrides


def lock_status(lockfile: str | os.PathLike[str] | None = None, *, stale_after_seconds: float = DEFAULT_LOCK_STALE_SECONDS) -> dict[str, Any]:
    path = Path(lockfile or DEFAULT_LOCKFILE)
    if not path.exists():
        return {"locked": False, "path": str(path), "stale": False, "metadata": None}
    metadata = _read_lock_metadata(path)
    age_seconds = _lock_age_seconds(path, metadata)
    stale = age_seconds >= stale_after_seconds
    return {
        "locked": True,
        "path": str(path),
        "stale": stale,
        "age_seconds": age_seconds,
        "stale_after_seconds": stale_after_seconds,
        "metadata": metadata,
    }


def acquire_lock(
    lockfile: str | os.PathLike[str] | None = None,
    *,
    stale_after_seconds: float = DEFAULT_LOCK_STALE_SECONDS,
    metadata: Mapping[str, Any] | None = None,
) -> SchedulerLock:
    path = Path(lockfile or DEFAULT_LOCKFILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}:{datetime.now(timezone.utc).timestamp()}"
    payload = {
        "pid": os.getpid(),
        "created_at": utc_now_iso(),
        "token": token,
        **dict(metadata or {}),
    }
    data = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        existing = lock_status(path, stale_after_seconds=stale_after_seconds)
        if not existing["stale"]:
            raise SchedulerLockError(f"Scheduler lock is already held: {path}") from exc
        path.unlink()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.write(b"\n")
    return SchedulerLock(path=path, token=token, metadata=payload)


def release_lock(lock: SchedulerLock) -> None:
    if not lock.path.exists():
        return
    metadata = _read_lock_metadata(lock.path)
    if metadata.get("token") != lock.token:
        raise SchedulerLockError(f"Refusing to release lock not owned by this process: {lock.path}")
    lock.path.unlink()


def run_scheduled_collectors(
    db_path: str | os.PathLike[str] | None = None,
    *,
    collectors: str | Sequence[str] | None = None,
    lockfile: str | os.PathLike[str] | None = None,
    stale_after_seconds: float = DEFAULT_LOCK_STALE_SECONDS,
    dry_run: bool = False,
    timeout: float = 10,
    timeout_overrides: Mapping[str, float] | None = None,
    max_attempts: int = 1,
    metar_station: str = "KSEA",
    nws_url: str = DEFAULT_NWS_SEW_DISCUSSION_URL,
    metar_url: str | None = None,
) -> dict[str, Any]:
    selected = normalize_collectors(collectors)
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    overrides = dict(timeout_overrides or {})
    for name, seconds in overrides.items():
        if name not in COLLECTOR_SPECS:
            raise ValueError(f"Unknown collector timeout override: {name}")
        if seconds <= 0:
            raise ValueError("collector timeout seconds must be positive")

    lock = acquire_lock(
        lockfile,
        stale_after_seconds=stale_after_seconds,
        metadata={"command": "run_scheduled_collectors", "collectors": selected, "dry_run": dry_run},
    )
    started_at = utc_now_iso()
    try:
        if dry_run:
            results = [_planned_result(name, timeout=overrides.get(name, timeout)) for name in selected]
        else:
            initialize_database(db_path)
            results = []
            with connection(db_path) as conn:
                repo = WeatherRepository(conn)
                for name in selected:
                    result = _run_one(
                        name,
                        timeout=overrides.get(name, timeout),
                        max_attempts=max_attempts,
                        metar_station=metar_station,
                        nws_url=nws_url,
                        metar_url=metar_url,
                    )
                    _persist_result(repo, result)
                    results.append(_result_summary(result, timeout=overrides.get(name, timeout), dry_run=False))
        finished_at = utc_now_iso()
        success_count = sum(1 for item in results if item["status"] == "success")
        failure_count = sum(1 for item in results if item["status"] == "failed")
        return {
            "status": "success" if failure_count == 0 else "failed",
            "dry_run": dry_run,
            "started_at": started_at,
            "finished_at": finished_at,
            "db_path": str(database_path(db_path)),
            "lockfile": str(lock.path),
            "collector_count": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
            "collectors": results,
        }
    finally:
        release_lock(lock)


def scheduler_status(
    db_path: str | os.PathLike[str] | None = None,
    *,
    lockfile: str | os.PathLike[str] | None = None,
    stale_after_seconds: float = DEFAULT_LOCK_STALE_SECONDS,
    max_age_minutes: float = 180,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        health = WeatherRepository(conn).collector_health_summaries(max_age_minutes=max_age_minutes)
    return {
        "db_path": str(database_path(db_path)),
        "lock": lock_status(lockfile, stale_after_seconds=stale_after_seconds),
        "collector_health": health,
    }


def _run_one(
    name: str,
    *,
    timeout: float,
    max_attempts: int,
    metar_station: str,
    nws_url: str,
    metar_url: str | None,
) -> CollectorResult:
    spec = COLLECTOR_SPECS[name]
    if name == "nws_discussion":
        return spec.run(source=spec.source, url=nws_url, timeout=timeout, max_attempts=max_attempts)
    if name == "metar":
        return spec.run(source=spec.source, station=metar_station, url=metar_url, timeout=timeout, max_attempts=max_attempts)
    raise ValueError(f"Unknown scheduled collector: {name}")


def _persist_result(repo: WeatherRepository, result: CollectorResult) -> None:
    repo.record_collector_run(result.poll_record())
    if not result.succeeded:
        return
    if result.collector_name == "nws_discussion":
        repo.save_forecast_discussion(result.source, result.records[0])
    elif result.collector_name == "metar":
        repo.save_observation_record(result.source, result.records[0])
    else:
        raise ValueError(f"No persistence handler for collector: {result.collector_name}")


def _planned_result(name: str, *, timeout: float) -> dict[str, Any]:
    spec = COLLECTOR_SPECS[name]
    source_url = DEFAULT_NWS_SEW_DISCUSSION_URL if name == "nws_discussion" else DEFAULT_AVIATION_WEATHER_METAR_URL_TEMPLATE
    return {
        "collector_name": name,
        "source": spec.source,
        "status": "planned",
        "records_returned": 0,
        "timeout_seconds": timeout,
        "attempts": 0,
        "source_url": source_url,
        "error_message": None,
        "dry_run": True,
    }


def _result_summary(result: CollectorResult, *, timeout: float, dry_run: bool) -> dict[str, Any]:
    return {
        "collector_name": result.collector_name,
        "source": result.source,
        "status": result.status,
        "records_returned": result.records_returned,
        "timeout_seconds": timeout,
        "attempts": result.attempts,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "latency_seconds": result.latency_seconds,
        "newest_observation_at": result.newest_observation_at,
        "source_url": result.source_url,
        "error_message": result.error_message,
        "dry_run": dry_run,
    }


def _read_lock_metadata(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchedulerLockError(f"Scheduler lock contains invalid JSON: {path}") from exc
    except OSError as exc:
        raise SchedulerLockError(f"Unable to read scheduler lock: {path}") from exc
    if not isinstance(data, dict):
        raise SchedulerLockError(f"Scheduler lock metadata must be a JSON object: {path}")
    return data


def _lock_age_seconds(path: Path, metadata: Mapping[str, Any]) -> float:
    created_at = metadata.get("created_at")
    if isinstance(created_at, str):
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            created = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    else:
        created = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds())
