from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .db import connection, initialize_database
from .repository import WeatherRepository

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
}


def run_backfill(db_path: str | None, source: str | Path) -> dict[str, Any]:
    source_path = Path(source)
    initialize_database(db_path)
    try:
        source_hash = hash_source(source_path)
        hash_error = None
    except Exception as exc:
        source_hash = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()
        hash_error = exc
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        run = repo.start_backfill_run(source_path=str(source_path), source_hash=source_hash)
        if hash_error is not None:
            return repo.finish_backfill_run(
                int(run["id"]),
                status="failed",
                counts={},
                errors=[{"source": str(source_path), "error": str(hash_error)}],
            )
        counts: Counter[str] = Counter()
        errors: list[dict[str, Any]] = []
        try:
            items = load_fixture_bundle(source_path)
        except Exception as exc:
            return repo.finish_backfill_run(
                int(run["id"]),
                status="failed",
                counts={},
                errors=[{"source": str(source_path), "error": str(exc)}],
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
        if items and sum(counts[key] for key in counts if key.endswith("_imported")) == 0 and errors:
            status = "failed"
        return repo.finish_backfill_run(int(run["id"]), status=status, counts=dict(counts), errors=errors)


def load_fixture_bundle(source: str | Path) -> dict[str, list[dict[str, Any]]]:
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)
    files = sorted(path.rglob("*")) if path.is_dir() else [path]
    bundle: dict[str, list[dict[str, Any]]] = {}
    for file_path in files:
        if not file_path.is_file() or file_path.suffix.lower() not in {".json", ".csv"}:
            continue
        for dataset, records in _load_fixture_file(file_path).items():
            bundle.setdefault(dataset, []).extend(records)
    return bundle


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
