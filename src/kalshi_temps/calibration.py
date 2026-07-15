from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
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
