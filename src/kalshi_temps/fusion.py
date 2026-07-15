from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ModelHighForecast:
    model_name: str
    high_f: float


@dataclass(frozen=True)
class ModelSpread:
    min_high_f: float | None
    max_high_f: float | None
    mean_high_f: float | None
    spread_f: float | None
    model_count: int
    min_model_name: str | None = None
    max_model_name: str | None = None


@dataclass(frozen=True)
class ModelRunChange:
    model_name: str
    target_date: str
    run_at: str
    previous_run_at: str
    predicted_high_f: float
    previous_predicted_high_f: float
    change_f: float


@dataclass(frozen=True)
class ProbabilityDelta:
    bucket: str
    model_probability: float
    market_probability: float
    probability_delta: float
    expected_edge_cents: float


@dataclass(frozen=True)
class FreshnessStatus:
    observed_at: datetime | None
    evaluated_at: datetime
    max_age_minutes: float
    age_minutes: float | None
    is_fresh: bool
    is_stale: bool
    label: str


@dataclass(frozen=True)
class RiskGuard:
    key: str
    label: str
    severity: str
    active: bool


def compute_model_spread(
    forecasts: Mapping[str, float | int | None] | Iterable[ModelHighForecast],
) -> ModelSpread:
    """Compute the high-temperature spread across available model forecasts."""
    normalized = _normalize_forecasts(forecasts)
    if not normalized:
        return ModelSpread(None, None, None, None, 0)

    min_forecast = min(normalized, key=lambda item: item.high_f)
    max_forecast = max(normalized, key=lambda item: item.high_f)
    mean_high = sum(item.high_f for item in normalized) / len(normalized)
    return ModelSpread(
        min_high_f=min_forecast.high_f,
        max_high_f=max_forecast.high_f,
        mean_high_f=mean_high,
        spread_f=max_forecast.high_f - min_forecast.high_f,
        model_count=len(normalized),
        min_model_name=min_forecast.model_name,
        max_model_name=max_forecast.model_name,
    )


def compute_model_run_changes(runs: Iterable[Mapping[str, Any]]) -> list[ModelRunChange]:
    """Return latest-vs-previous high-temperature changes per model and target date."""
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for run in runs:
        model_name = str(run.get("model_name") or "").strip()
        target_date = str(run.get("target_date") or run.get("valid_date") or "").strip()
        run_at = str(run.get("run_at") or "").strip()
        high = run.get("predicted_high_f", run.get("high_f"))
        if not model_name or not target_date or not run_at or high is None:
            continue
        try:
            parsed_high = float(high)
        except (TypeError, ValueError):
            continue
        if parsed_high != parsed_high:
            continue
        grouped.setdefault((model_name, target_date), []).append({**run, "predicted_high_f": parsed_high})

    changes: list[ModelRunChange] = []
    for (model_name, target_date), group in grouped.items():
        ordered = sorted(group, key=lambda item: str(item.get("run_at") or ""))
        if len(ordered) < 2:
            continue
        previous = ordered[-2]
        latest = ordered[-1]
        latest_high = float(latest["predicted_high_f"])
        previous_high = float(previous["predicted_high_f"])
        changes.append(
            ModelRunChange(
                model_name=model_name,
                target_date=target_date,
                run_at=str(latest["run_at"]),
                previous_run_at=str(previous["run_at"]),
                predicted_high_f=latest_high,
                previous_predicted_high_f=previous_high,
                change_f=latest_high - previous_high,
            )
        )
    return sorted(changes, key=lambda change: (change.target_date, change.model_name))


def implied_probability_from_market(
    *,
    yes_bid_cents: float | int | None = None,
    yes_ask_cents: float | int | None = None,
    mid_cents: float | int | None = None,
) -> float | None:
    """Return an implied probability from a yes-price midpoint when possible."""
    if mid_cents is not None:
        return _probability_from_cents(mid_cents)

    if yes_bid_cents is None or yes_ask_cents is None:
        return None

    bid = _clean_cents(yes_bid_cents)
    ask = _clean_cents(yes_ask_cents)
    if bid is None or ask is None or bid > ask:
        return None
    return ((bid + ask) / 2) / 100


def compare_bucket_probabilities(
    model_probabilities: Mapping[str, float | int | None],
    market_probabilities: Mapping[str, float | int | None],
) -> list[ProbabilityDelta]:
    """Compare model probabilities with market-implied probabilities by bucket.

    Positive deltas mean the model probability is higher than the market-implied
    probability; negative deltas mean it is lower. This is only a descriptive
    edge metric and is not a trade recommendation.
    """
    deltas: list[ProbabilityDelta] = []
    for bucket in sorted(set(model_probabilities) & set(market_probabilities)):
        model_probability = _clean_probability(model_probabilities[bucket])
        market_probability = _clean_probability(market_probabilities[bucket])
        if model_probability is None or market_probability is None:
            continue
        probability_delta = round(model_probability - market_probability, 10)
        deltas.append(
            ProbabilityDelta(
                bucket=bucket,
                model_probability=model_probability,
                market_probability=market_probability,
                probability_delta=probability_delta,
                expected_edge_cents=probability_delta * 100,
            )
        )
    return deltas


def evaluate_freshness(
    observed_at: datetime | str | None,
    *,
    evaluated_at: datetime | str,
    max_age_minutes: float = 60,
) -> FreshnessStatus:
    """Evaluate whether a timestamped source record is fresh enough to use."""
    checked_at = _as_utc(_require_datetime(evaluated_at, "evaluated_at"))
    max_age = float(max_age_minutes)
    parsed_observed_at = _parse_datetime(observed_at)

    if parsed_observed_at is None or max_age < 0:
        return FreshnessStatus(
            observed_at=parsed_observed_at,
            evaluated_at=checked_at,
            max_age_minutes=max_age,
            age_minutes=None,
            is_fresh=False,
            is_stale=True,
            label="missing timestamp" if parsed_observed_at is None else "invalid freshness threshold",
        )

    parsed_observed_at = _as_utc(parsed_observed_at)
    age_minutes = (checked_at - parsed_observed_at).total_seconds() / 60
    is_fresh = 0 <= age_minutes <= max_age
    return FreshnessStatus(
        observed_at=parsed_observed_at,
        evaluated_at=checked_at,
        max_age_minutes=max_age,
        age_minutes=age_minutes,
        is_fresh=is_fresh,
        is_stale=not is_fresh,
        label="fresh" if is_fresh else "stale",
    )


def generate_risk_guards(
    *,
    settlement_source_verified: bool,
    is_stale: bool,
    model_spread_f: float | int | None = None,
    high_spread_threshold_f: float = 4,
    proxy_only_observations: bool = False,
) -> list[RiskGuard]:
    """Generate cautious data-quality guard labels for the fusion workflow."""
    spread = float(model_spread_f) if model_spread_f is not None else None
    high_spread = spread is not None and spread >= float(high_spread_threshold_f)
    return [
        RiskGuard(
            key="unverified-settlement-source",
            label="Settlement source is not independently verified",
            severity="warning",
            active=not settlement_source_verified,
        ),
        RiskGuard(
            key="stale-data",
            label="One or more source records are stale",
            severity="warning",
            active=is_stale,
        ),
        RiskGuard(
            key="high-model-spread",
            label="Model high-temperature spread is elevated",
            severity="caution",
            active=high_spread,
        ),
        RiskGuard(
            key="proxy-only-observations",
            label="Observation set is proxy-only, not a direct settlement source",
            severity="caution",
            active=proxy_only_observations,
        ),
    ]


def active_risk_guards(guards: Iterable[RiskGuard]) -> list[RiskGuard]:
    return [guard for guard in guards if guard.active]


def _normalize_forecasts(
    forecasts: Mapping[str, float | int | None] | Iterable[ModelHighForecast],
) -> list[ModelHighForecast]:
    if isinstance(forecasts, Mapping):
        items = (ModelHighForecast(str(name), float(value)) for name, value in forecasts.items() if value is not None)
    else:
        items = forecasts
    return [forecast for forecast in items if forecast.high_f == forecast.high_f]


def _clean_cents(value: float | int | None) -> float | None:
    if value is None:
        return None
    cents = float(value)
    if cents != cents or cents < 0 or cents > 100:
        return None
    return cents


def _probability_from_cents(value: float | int | None) -> float | None:
    cents = _clean_cents(value)
    if cents is None:
        return None
    return cents / 100


def _clean_probability(value: float | int | None) -> float | None:
    if value is None:
        return None
    probability = float(value)
    if probability != probability:
        return None
    if 0 <= probability <= 1:
        return probability
    if 1 < probability <= 100:
        return probability / 100
    return None


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _require_datetime(value: datetime | str, field_name: str) -> datetime:
    parsed = _parse_datetime(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be a datetime or ISO-8601 timestamp")
    return parsed


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
