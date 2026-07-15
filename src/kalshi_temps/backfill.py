from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from .db import connection, initialize_database
from .official_sources import parse_climate_daily_summary_records, parse_nws_station_observation_records, parse_public_observation_records
from .repository import WeatherRepository

TextFetcher = Callable[[str], str]

URL_TEMPLATES = {
    "noaa_daily": "https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries&stations={station}&startDate={date}&endDate={date}&format=json&units=standard",
    "nws_hourly": "https://api.weather.gov/stations/{station}/observations?start={date}T00:00:00Z&end={next_date}T00:00:00Z",
    "metar_hourly": "https://aviationweather.gov/api/data/metar?ids={station}&format=json&date={date}",
    "fixture": "{fixture_root}/{station}/{date}.json",
}

DATASET_ALIASES = {
    "observations": "observations",
    "observation": "observations",
    "model_runs": "model_runs",
    "model_highs": "model_runs",
    "models": "model_runs",
    "market_snapshots": "market_snapshots",
    "markets": "market_snapshots",
    "official_outcomes": "official_outcomes",
    "outcomes": "official_outcomes",
    "regime_tags": "regime_tags",
    "weather_regime_features": "regime_tags",
    "prediction_snapshots": "prediction_snapshots",
    "predictions": "prediction_snapshots",
    "station_metadata": "station_metadata",
    "stations": "station_metadata",
    "official_observations": "official_observations",
    "public_observations": "official_observations",
    "nws_observations": "official_observations",
    "metar_observations": "official_observations",
    "daily_summaries": "official_outcomes",
}


@dataclass(frozen=True)
class BackfillPlanItem:
    date: str
    source_kind: str
    url: str | None = None
    fixture_path: str | None = None


@dataclass(frozen=True)
class BackfillPlan:
    station: str
    start_date: str
    end_date: str
    source_kind: str
    items: list[BackfillPlanItem]
    plan_hash: str
    caveat: str = "Backfill foundation only; not proof of calibrated performance."

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["items"] = [asdict(item) for item in self.items]
        return data


def create_backfill_plan(
    *,
    station: str,
    start_date: str,
    end_date: str,
    source_kind: str = "noaa_daily",
    fixture_root: str | Path | None = None,
) -> dict[str, Any]:
    station_id = station.strip().upper()
    if not station_id:
        raise ValueError("station is required")
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    kind = source_kind.strip().lower()
    if kind not in URL_TEMPLATES:
        raise ValueError(f"unsupported source_kind: {source_kind}")
    root = str(fixture_root) if fixture_root is not None else None
    items: list[BackfillPlanItem] = []
    current = start
    while current <= end:
        next_day = current + timedelta(days=1)
        if kind == "fixture":
            fixture_path = URL_TEMPLATES[kind].format(fixture_root=root or ".", station=station_id, date=current.isoformat(), next_date=next_day.isoformat())
            items.append(BackfillPlanItem(date=current.isoformat(), source_kind=kind, fixture_path=fixture_path))
        else:
            url = URL_TEMPLATES[kind].format(station=station_id, date=current.isoformat(), next_date=next_day.isoformat(), fixture_root=root or ".")
            items.append(BackfillPlanItem(date=current.isoformat(), source_kind=kind, url=url))
        current = next_day
    payload = {
        "station": station_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "source_kind": kind,
        "items": [asdict(item) for item in items],
    }
    payload["plan_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return BackfillPlan(
        station=station_id,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        source_kind=kind,
        items=items,
        plan_hash=payload["plan_hash"],
    ).as_dict()


def run_backfill(
    db_path: str | None,
    source: str | Path | None = None,
    *,
    plan: dict[str, Any] | BackfillPlan | None = None,
    fetcher: TextFetcher | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_path = Path(source) if source is not None else None
    plan_dict = plan.as_dict() if isinstance(plan, BackfillPlan) else plan
    initialize_database(db_path)
    try:
        source_hash = hash_source(source_path) if source_path is not None else hash_plan(plan_dict)
        hash_error = None
    except Exception as exc:
        source_hash = hashlib.sha256(str(source_path or plan_dict).encode("utf-8")).hexdigest()
        hash_error = exc
    idempotency_key = hashlib.sha256(
        json.dumps({"source_hash": source_hash, "plan_hash": plan_dict.get("plan_hash") if plan_dict else None, "dry_run": dry_run}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        if plan_dict:
            repo.save_backfill_plan(plan_dict)
        existing = repo.get_backfill_run_by_idempotency_key(idempotency_key) if not dry_run else None
        if existing is not None:
            existing["idempotent_replay"] = True
            return existing
        run = repo.start_backfill_run(
            source_path=str(source_path) if source_path is not None else "<public-plan>",
            source_hash=source_hash,
            plan=plan_dict,
            idempotency_key=idempotency_key,
            dry_run=dry_run,
        )
        if hash_error is not None:
            return repo.finish_backfill_run(
                int(run["id"]),
                status="failed",
                counts={},
                errors=[{"source": str(source_path), "error": str(hash_error)}],
            )
        counts: Counter[str] = Counter()
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        missing_dates: list[str] = []
        payload_hashes: dict[str, str] = {}
        if dry_run:
            counts["planned_dates"] = len(plan_dict.get("items", [])) if plan_dict else 0
            counts["dry_run"] = 1
            return repo.finish_backfill_run(
                int(run["id"]),
                status="success",
                counts=dict(counts),
                errors=[],
                missing_dates=[],
                payload_hashes={},
                warnings=warnings,
            )
        try:
            items, fixture_warnings = load_fixture_bundle_with_warnings(source_path) if source_path is not None else ({}, [])
            warnings.extend(fixture_warnings)
            if plan_dict:
                planned_items, plan_warnings, plan_missing, plan_hashes = load_plan_payloads(plan_dict, fetcher=fetcher)
                warnings.extend(plan_warnings)
                missing_dates.extend(plan_missing)
                payload_hashes.update(plan_hashes)
                for dataset, records in planned_items.items():
                    items.setdefault(dataset, []).extend(records)
        except Exception as exc:
            return repo.finish_backfill_run(
                int(run["id"]),
                status="failed",
                counts={},
                errors=[{"source": str(source_path), "error": str(exc)}],
                warnings=warnings,
            )

        for dataset, records in items.items():
            counts[f"{dataset}_seen"] += len(records)
            for index, record in enumerate(records):
                try:
                    _save_record(repo, dataset, record)
                    counts[f"{dataset}_imported"] += 1
                except Exception as exc:
                    errors.append({"dataset": dataset, "index": index, "error": str(exc), "record": record})
        status = "success" if not errors else "partial_failure"
        if warnings or missing_dates:
            status = "partial_failure" if status == "success" else status
        if items and sum(counts[key] for key in counts if key.endswith("_imported")) == 0 and errors:
            status = "failed"
        return repo.finish_backfill_run(
            int(run["id"]),
            status=status,
            counts=dict(counts),
            errors=errors,
            missing_dates=missing_dates,
            payload_hashes=payload_hashes,
            warnings=warnings,
        )


def load_fixture_bundle(source: str | Path) -> dict[str, list[dict[str, Any]]]:
    bundle, _warnings = load_fixture_bundle_with_warnings(source)
    return bundle


def load_fixture_bundle_with_warnings(source: str | Path | None) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    if source is None:
        return {}, []
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)
    files = sorted(path.rglob("*")) if path.is_dir() else [path]
    bundle: dict[str, list[dict[str, Any]]] = {}
    warnings: list[dict[str, Any]] = []
    for file_path in files:
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in {".json", ".csv"}:
            warnings.append({"source": str(file_path), "warning": f"unsupported fixture extension: {file_path.suffix}"})
            continue
        try:
            loaded = _load_fixture_file(file_path)
        except ValueError as exc:
            warnings.append({"source": str(file_path), "warning": str(exc)})
            continue
        if not loaded:
            warnings.append({"source": str(file_path), "warning": "no supported datasets found"})
        for dataset, records in loaded.items():
            bundle.setdefault(dataset, []).extend(records)
    return bundle, warnings


def hash_source(source: str | Path) -> str:
    path = Path(source)
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]
    for file_path in files:
        digest.update(str(file_path.relative_to(path) if path.is_dir() else file_path.name).encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def hash_plan(plan: dict[str, Any] | None) -> str:
    return hashlib.sha256(json.dumps(plan or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_plan_payloads(
    plan: dict[str, Any],
    *,
    fetcher: TextFetcher | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[str], dict[str, str]]:
    bundle: dict[str, list[dict[str, Any]]] = {}
    warnings: list[dict[str, Any]] = []
    missing_dates: list[str] = []
    payload_hashes: dict[str, str] = {}
    station = str(plan["station"]).upper()
    for item in plan.get("items", []):
        item_date = str(item["date"])
        source_kind = str(item.get("source_kind") or plan["source_kind"]).lower()
        payload: str | None = None
        source_label = item.get("fixture_path") or item.get("url")
        if item.get("fixture_path"):
            path = Path(str(item["fixture_path"]))
            if not path.exists():
                missing_dates.append(item_date)
                warnings.append({"date": item_date, "source": str(path), "warning": "planned fixture missing"})
                continue
            payload = path.read_text(encoding="utf-8")
        elif item.get("url"):
            if fetcher is None:
                missing_dates.append(item_date)
                warnings.append({"date": item_date, "source": str(item["url"]), "warning": "no fetcher supplied; live network not attempted"})
                continue
            try:
                payload = fetcher(str(item["url"]))
            except Exception as exc:  # noqa: BLE001 - preserve per-date public backfill failure.
                missing_dates.append(item_date)
                warnings.append({"date": item_date, "source": str(item["url"]), "warning": f"fetch failed: {exc}"})
                continue
        else:
            missing_dates.append(item_date)
            warnings.append({"date": item_date, "warning": "plan item has neither fixture_path nor url"})
            continue
        payload_hashes[item_date] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        try:
            parsed = _parse_planned_payload(payload, source_kind=source_kind, station=station, source_url=str(source_label or ""))
        except Exception as exc:  # noqa: BLE001 - preserve per-date parser failure.
            missing_dates.append(item_date)
            warnings.append({"date": item_date, "source": str(source_label or ""), "warning": f"parse failed: {exc}"})
            continue
        for dataset, records in parsed.items():
            bundle.setdefault(dataset, []).extend(records)
    return bundle, warnings, missing_dates, payload_hashes


def _parse_planned_payload(payload: str, *, source_kind: str, station: str, source_url: str) -> dict[str, list[dict[str, Any]]]:
    if source_kind == "noaa_daily":
        return {"official_outcomes": parse_climate_daily_summary_records(payload)}
    if source_kind == "nws_hourly":
        return {"official_observations": parse_nws_station_observation_records(payload, station=station, source_url=source_url)}
    if source_kind in {"metar_hourly", "fixture"}:
        return {"official_observations": parse_public_observation_records(payload, station=station, source_url=source_url)}
    raise ValueError(f"unsupported source_kind: {source_kind}")


def _load_fixture_file(path: Path) -> dict[str, list[dict[str, Any]]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _records_from_json_payload(payload, _dataset_from_name(path.stem))
    if path.suffix.lower() == ".csv":
        dataset = _dataset_from_name(path.stem)
        if dataset is None:
            raise ValueError(f"cannot infer dataset type from CSV filename: {path.name}")
        with path.open(newline="", encoding="utf-8") as handle:
            return {dataset: [_coerce_record(row) for row in csv.DictReader(handle)]}
    raise ValueError(f"unsupported fixture extension: {path.suffix}")


def _records_from_json_payload(payload: Any, fallback_dataset: str | None) -> dict[str, list[dict[str, Any]]]:
    if isinstance(payload, list):
        if fallback_dataset is None:
            raise ValueError("JSON list fixtures require a dataset-like filename")
        return {fallback_dataset: [_coerce_record(item) for item in payload]}
    if not isinstance(payload, dict):
        raise ValueError("JSON fixture must be an object or list")
    if "records" in payload and fallback_dataset:
        return {fallback_dataset: [_coerce_record(item) for item in _ensure_list(payload["records"])]}
    result: dict[str, list[dict[str, Any]]] = {}
    for key, value in payload.items():
        dataset = DATASET_ALIASES.get(key)
        if dataset is None:
            continue
        result.setdefault(dataset, []).extend(_coerce_record(item) for item in _ensure_list(value))
    if not result and fallback_dataset:
        result[fallback_dataset] = [_coerce_record(payload)]
    return result


def _save_record(repo: WeatherRepository, dataset: str, record: dict[str, Any]) -> dict[str, Any]:
    if dataset == "observations":
        source_name = str(record.get("source_name") or record.get("source") or "backfill")
        normalized = _aliases(record, {"temperature_f": ("temp_f", "temperature", "value")})
        return repo.save_observation_record(source_name, normalized)
    if dataset == "model_runs":
        return repo.save_model_high_record(record)
    if dataset == "market_snapshots":
        return repo.save_market_snapshot_record(_aliases(record, {"ticker": ("market_ticker",), "captured_at": ("snapshot_at",)}))
    if dataset == "official_outcomes":
        normalized = _aliases(record, {"high_temperature_f": ("actual_high_f", "high_f", "temperature_f")})
        return repo.save_official_outcome(
            station=normalized.get("station") or "KSEA",
            target_date=normalized["target_date"],
            high_temperature_f=float(normalized["high_temperature_f"]),
            source_name=normalized.get("source_name") or normalized.get("source") or "backfill",
            observed_at=normalized.get("observed_at"),
            notes=normalized.get("notes"),
            raw_payload=record,
        )
    if dataset == "official_observations":
        source_name = str(record.get("source_name") or record.get("source") or "public official observation")
        return repo.save_official_observation_record(source_name, record)
    if dataset == "station_metadata":
        return repo.upsert_station_metadata(record)
    if dataset == "regime_tags":
        normalized = _aliases(record, {"extracted_at": ("snapshot_at", "issued_at"), "regime_tags": ("tags", "regimes")})
        normalized.setdefault("confidence_label", "backfill")
        normalized.setdefault("evidence", [])
        return repo.save_weather_regime_features(normalized)
    if dataset == "prediction_snapshots":
        return repo.save_prediction_snapshot(record)
    raise ValueError(f"unknown fixture dataset: {dataset}")


def _dataset_from_name(name: str) -> str | None:
    normalized = name.lower().replace("-", "_")
    if normalized in DATASET_ALIASES:
        return DATASET_ALIASES[normalized]
    for key, dataset in DATASET_ALIASES.items():
        if key in normalized:
            return dataset
    return None


def _coerce_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("fixture records must be objects")
    return {key: _coerce_value(value) for key, value in record.items()}


def _coerce_value(value: Any) -> Any:
    if value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        for caster in (int, float):
            try:
                return caster(text)
            except ValueError:
                continue
    return value


def _aliases(record: dict[str, Any], aliases: dict[str, Iterable[str]]) -> dict[str, Any]:
    normalized = dict(record)
    for target, source_names in aliases.items():
        if normalized.get(target) is not None:
            continue
        for source in source_names:
            if normalized.get(source) is not None:
                normalized[target] = normalized[source]
                break
    return normalized


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
