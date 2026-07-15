from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class ForecastError:
    predicted_f: float
    actual_f: float
    error_f: float
    absolute_error_f: float
    squared_error_f: float


def forecast_error(predicted_f: float | int, actual_f: float | int) -> ForecastError:
    """Return forecast error where positive means the forecast was too warm."""
    predicted = float(predicted_f)
    actual = float(actual_f)
    if not math.isfinite(predicted) or not math.isfinite(actual):
        raise ValueError("predicted_f and actual_f must be finite numbers")
    error = predicted - actual
    return ForecastError(
        predicted_f=predicted,
        actual_f=actual,
        error_f=error,
        absolute_error_f=abs(error),
        squared_error_f=error * error,
    )


def grouped_bias_summary(
    records: Iterable[Mapping[str, Any]],
    *,
    group_by: Sequence[str] = ("model_name", "regime", "station"),
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[ForecastError]] = {}
    for record in records:
        predicted = _first_present(record, "predicted_high_f", "predicted_f")
        actual = _first_present(record, "actual_high_f", "high_temperature_f", "actual_f")
        if predicted is None or actual is None:
            continue
        try:
            error = forecast_error(predicted, actual)
        except (TypeError, ValueError):
            continue
        key = tuple(record.get(field) for field in group_by)
        groups.setdefault(key, []).append(error)

    summaries: list[dict[str, Any]] = []
    for key, errors in groups.items():
        sample_count = len(errors)
        mean_error = sum(item.error_f for item in errors) / sample_count
        mean_absolute_error = sum(item.absolute_error_f for item in errors) / sample_count
        rmse = math.sqrt(sum(item.squared_error_f for item in errors) / sample_count)
        summary = {field: value for field, value in zip(group_by, key)}
        summary.update(
            {
                "sample_count": sample_count,
                "mean_error_f": mean_error,
                "mean_absolute_error_f": mean_absolute_error,
                "rmse_f": rmse,
                "warm_bias_count": sum(1 for item in errors if item.error_f > 0),
                "cool_bias_count": sum(1 for item in errors if item.error_f < 0),
                "exact_count": sum(1 for item in errors if item.error_f == 0),
            }
        )
        summaries.append(summary)
    return sorted(summaries, key=lambda item: tuple(str(item.get(field) or "") for field in group_by))


def bucket_brier_score(records: Iterable[Mapping[str, Any]]) -> float | None:
    squared_errors = []
    for record in records:
        probability = _clean_probability(_first_present(record, "probability", "predicted_probability"))
        outcome = _clean_outcome(_first_present(record, "outcome", "occurred", "actual_outcome"))
        if probability is None or outcome is None:
            continue
        squared_errors.append((probability - outcome) ** 2)
    if not squared_errors:
        return None
    return sum(squared_errors) / len(squared_errors)


def reliability_bins(
    records: Iterable[Mapping[str, Any]],
    *,
    bin_count: int = 10,
    include_empty: bool = False,
) -> list[dict[str, Any]]:
    if bin_count <= 0:
        raise ValueError("bin_count must be positive")

    bins: list[list[tuple[float, int]]] = [[] for _ in range(bin_count)]
    for record in records:
        probability = _clean_probability(_first_present(record, "probability", "predicted_probability"))
        outcome = _clean_outcome(_first_present(record, "outcome", "occurred", "actual_outcome"))
        if probability is None or outcome is None:
            continue
        index = min(int(probability * bin_count), bin_count - 1)
        bins[index].append((probability, outcome))

    summaries: list[dict[str, Any]] = []
    for index, values in enumerate(bins):
        if not values and not include_empty:
            continue
        lower = index / bin_count
        upper = (index + 1) / bin_count
        if values:
            mean_probability = sum(probability for probability, _ in values) / len(values)
            observed_frequency = sum(outcome for _, outcome in values) / len(values)
            brier = sum((probability - outcome) ** 2 for probability, outcome in values) / len(values)
        else:
            mean_probability = None
            observed_frequency = None
            brier = None
        summaries.append(
            {
                "bin_index": index,
                "lower_bound": lower,
                "upper_bound": upper,
                "sample_count": len(values),
                "mean_probability": mean_probability,
                "observed_frequency": observed_frequency,
                "brier_score": brier,
            }
        )
    return summaries


def leakage_safe_date_split(
    records: Iterable[Mapping[str, Any]],
    *,
    split_date: date | datetime | str,
    date_field: str = "target_date",
    gap_days: int = 0,
) -> dict[str, list[Mapping[str, Any]]]:
    """Split chronologically; records in the gap before split_date are withheld."""
    if gap_days < 0:
        raise ValueError("gap_days must be non-negative")
    cutoff = _parse_date(split_date)
    train_before = cutoff - timedelta(days=gap_days)
    train: list[Mapping[str, Any]] = []
    test: list[Mapping[str, Any]] = []
    for record in records:
        record_date = _parse_date(record.get(date_field))
        if record_date < train_before:
            train.append(record)
        elif record_date >= cutoff:
            test.append(record)
    return {"train": train, "test": test}


def chronological_split_date(
    dates: Iterable[date | datetime | str],
    *,
    test_fraction: float = 0.2,
    min_train_size: int = 1,
) -> date:
    unique_dates = sorted({_parse_date(value) for value in dates})
    if not unique_dates:
        raise ValueError("at least one date is required")
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between 0 and 1")
    split_index = max(min_train_size, int(len(unique_dates) * (1 - test_fraction)))
    split_index = min(split_index, len(unique_dates) - 1)
    return unique_dates[split_index]


def bucket_contains_temperature(bucket: str, temperature_f: float | int) -> bool:
    value = float(temperature_f)
    text = bucket.strip().replace("°", "").replace("F", "")
    range_match = re.search(r"(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)", text)
    if range_match:
        lower = float(range_match.group(1))
        upper = float(range_match.group(2))
        return lower <= value <= upper
    numbers = [float(match) for match in re.findall(r"-?\d+(?:\.\d+)?", text)]
    if not numbers:
        return False
    if text.startswith("<="):
        return value <= numbers[0]
    if text.startswith("<"):
        return value < numbers[0]
    if text.endswith("+") or text.startswith(">="):
        return value >= numbers[0]
    if text.startswith(">"):
        return value > numbers[0]
    if len(numbers) >= 2:
        return numbers[0] <= value <= numbers[1]
    return round(value) == round(numbers[0])


def bucket_log_loss(records: Iterable[Mapping[str, Any]], *, epsilon: float = 1e-15) -> float | None:
    losses = []
    for record in records:
        probability = _clean_probability(_first_present(record, "probability", "predicted_probability"))
        outcome = _clean_outcome(_first_present(record, "outcome", "occurred", "actual_outcome"))
        if probability is None or outcome is None:
            continue
        clipped = min(max(probability, epsilon), 1 - epsilon)
        losses.append(-(outcome * math.log(clipped) + (1 - outcome) * math.log(1 - clipped)))
    if not losses:
        return None
    return sum(losses) / len(losses)


def generate_calibration_report(
    records: Iterable[Mapping[str, Any]],
    *,
    bin_count: int = 10,
    split_date: date | datetime | str | None = None,
    gap_days: int = 0,
) -> dict[str, Any]:
    rows = [dict(record) for record in records]
    scored_rows = [_with_outcomes(row) for row in rows]
    observed_rows = [row for row in scored_rows if row.get("actual_high_f") is not None]
    continuous_rows = [row for row in observed_rows if row.get("predicted_high_f") is not None]
    probability_rows = [row for row in observed_rows if row.get("probability") is not None and row.get("temperature_bucket")]

    mae_groups = []
    for group_by in (("model_name",), ("model_name", "regime"), ("model_name", "snapshot_hour")):
        for summary in grouped_bias_summary(continuous_rows, group_by=group_by):
            mae_groups.append({"group_by": list(group_by), **summary})

    bucket_groups: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    for row in probability_rows:
        bucket_groups.setdefault((row.get("model_name"), row.get("regime"), row.get("temperature_bucket")), []).append(row)
    bucket_metrics = []
    reliability_records = []
    for (model_name, regime, bucket), values in sorted(bucket_groups.items(), key=lambda item: tuple(str(part or "") for part in item[0])):
        bins = reliability_bins(values, bin_count=bin_count)
        metric = {
            "model_name": model_name,
            "regime": regime,
            "temperature_bucket": bucket,
            "sample_count": len(values),
            "brier_score": bucket_brier_score(values),
            "log_loss": bucket_log_loss(values),
            "reliability_bins": bins,
        }
        bucket_metrics.append(metric)
        for item in bins:
            reliability_records.append(
                {
                    "model_name": model_name,
                    "regime": regime,
                    "temperature_bucket": bucket,
                    **item,
                }
            )

    missingness = _missingness_summary(scored_rows)
    leakage = _leakage_validation(observed_rows, split_date=split_date, gap_days=gap_days)
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sample_sizes": {
            "prediction_count": len(rows),
            "matched_outcome_count": len(observed_rows),
            "continuous_count": len(continuous_rows),
            "probability_count": len(probability_rows),
        },
        "mae": mae_groups,
        "bucket_metrics": bucket_metrics,
        "reliability_bins": reliability_records,
        "missingness": missingness,
        "leakage_safe_split": leakage,
    }


def export_report_json(report: Mapping[str, Any], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _with_outcomes(record: dict[str, Any]) -> dict[str, Any]:
    row = dict(record)
    row["snapshot_hour"] = _snapshot_hour(row.get("snapshot_at"))
    actual = _first_present(row, "actual_high_f", "high_temperature_f", "actual_f")
    bucket = row.get("temperature_bucket")
    if actual is not None and bucket:
        row["outcome"] = 1 if bucket_contains_temperature(str(bucket), actual) else 0
    return row


def _missingness_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fields = ("actual_high_f", "predicted_high_f", "probability", "temperature_bucket", "regime", "snapshot_at")
    return {
        "total_count": len(records),
        "fields": {
            field: {
                "missing_count": sum(1 for record in records if record.get(field) in (None, "")),
                "present_count": sum(1 for record in records if record.get(field) not in (None, "")),
            }
            for field in fields
        },
    }


def _leakage_validation(
    records: Sequence[Mapping[str, Any]],
    *,
    split_date: date | datetime | str | None,
    gap_days: int,
) -> dict[str, Any]:
    dated = [record for record in records if record.get("target_date")]
    if not dated:
        return {"valid": True, "reason": "no dated matched outcomes", "train_count": 0, "test_count": 0, "gap_days": gap_days}
    selected_split = split_date or chronological_split_date([record["target_date"] for record in dated])
    split = leakage_safe_date_split(dated, split_date=selected_split, gap_days=gap_days)
    train_dates = [_parse_date(record["target_date"]) for record in split["train"]]
    test_dates = [_parse_date(record["target_date"]) for record in split["test"]]
    valid = bool(train_dates and test_dates and max(train_dates) < min(test_dates))
    return {
        "valid": valid,
        "split_date": _parse_date(selected_split).isoformat(),
        "gap_days": gap_days,
        "train_count": len(split["train"]),
        "test_count": len(split["test"]),
        "withheld_count": len(dated) - len(split["train"]) - len(split["test"]),
        "max_train_date": max(train_dates).isoformat() if train_dates else None,
        "min_test_date": min(test_dates).isoformat() if test_dates else None,
    }


def _snapshot_hour(value: Any) -> int | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.hour
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).hour
        except ValueError:
            return None
    return None


def _first_present(record: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        if field in record:
            return record[field]
    return None


def _clean_probability(value: Any) -> float | None:
    if value is None:
        return None
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(probability):
        return None
    if 0 <= probability <= 1:
        return probability
    if 1 < probability <= 100:
        return probability / 100
    return None


def _clean_outcome(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        outcome = int(value)
    except (TypeError, ValueError):
        return None
    return outcome if outcome in {0, 1} else None


def _parse_date(value: date | datetime | str | Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return date.fromisoformat(value)
    raise ValueError("date value must be a date, datetime, or ISO-8601 string")
