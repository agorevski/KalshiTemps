from __future__ import annotations

from typing import Any

from .db import connection, initialize_database
from .repository import WeatherRepository


def start_run(
    db_path: str | None,
    *,
    run_name: str,
    station: str = "KSEA",
    target_date: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).start_paper_live_run(
            run_name=run_name,
            station=station,
            target_date=target_date,
            notes=notes,
        )


def list_runs(db_path: str | None, *, include_closed: bool = False, limit: int = 20) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).list_paper_live_runs(include_closed=include_closed, limit=limit)


def close_run(db_path: str | None, *, run_id: int, notes: str | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).close_paper_live_run(run_id, notes=notes)


def record_checklist(
    db_path: str | None,
    *,
    run_id: int,
    item: str,
    status: str = "pending",
    checklist_date: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).add_paper_live_checklist_entry(
            run_id,
            item=item,
            status=status,
            checklist_date=checklist_date,
            notes=notes,
        )


def record_prediction_note(db_path: str | None, *, run_id: int, record: dict[str, Any]) -> dict[str, Any]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).add_paper_live_prediction_note(run_id, record)


def record_postmortem(
    db_path: str | None,
    *,
    run_id: int,
    note: str,
    note_type: str = "postmortem",
    target_date: str | None = None,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).add_paper_live_reconciliation_note(
            run_id,
            note=note,
            note_type=note_type,
            target_date=target_date,
        )


def record_soak_metric(db_path: str | None, *, run_id: int, record: dict[str, Any]) -> dict[str, Any]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).add_paper_live_soak_metric(run_id, record)
