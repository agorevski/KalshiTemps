from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.fusion import (  # noqa: E402
    ModelHighForecast,
    active_risk_guards,
    compare_bucket_probabilities,
    compute_model_run_changes,
    compute_model_spread,
    evaluate_freshness,
    generate_risk_guards,
    implied_probability_from_market,
)


def test_compute_model_spread_from_model_highs() -> None:
    spread = compute_model_spread({"HRRR": 75, "GFS": 72.5, "ECMWF": 77.5, "NAM": None})

    assert spread.model_count == 3
    assert spread.min_high_f == 72.5
    assert spread.max_high_f == 77.5
    assert spread.mean_high_f == 75
    assert spread.spread_f == 5
    assert spread.min_model_name == "GFS"
    assert spread.max_model_name == "ECMWF"


def test_compute_model_spread_accepts_dataclasses_and_empty_inputs() -> None:
    spread = compute_model_spread(
        [ModelHighForecast("A", 70.0), ModelHighForecast("B", 73.25)]
    )

    assert spread.spread_f == 3.25
    assert compute_model_spread({}).model_count == 0
    assert compute_model_spread({}).spread_f is None


def test_compute_model_run_changes_compares_latest_to_previous_per_model() -> None:
    changes = compute_model_run_changes(
        [
            {"model_name": "HRRR", "target_date": "2026-07-15", "run_at": "2026-07-14T12:00:00Z", "high_f": 75},
            {"model_name": "HRRR", "target_date": "2026-07-15", "run_at": "2026-07-14T18:00:00Z", "high_f": 77.5},
            {"model_name": "GFS", "target_date": "2026-07-15", "run_at": "2026-07-14T18:00:00Z", "high_f": 74},
        ]
    )

    assert len(changes) == 1
    assert changes[0].model_name == "HRRR"
    assert changes[0].change_f == 2.5


def test_implied_probability_from_mid_or_bid_ask_cents() -> None:
    assert implied_probability_from_market(mid_cents=42) == 0.42
    assert implied_probability_from_market(yes_bid_cents=39, yes_ask_cents=43) == 0.41


def test_implied_probability_returns_none_when_market_price_unusable() -> None:
    assert implied_probability_from_market(yes_bid_cents=40) is None
    assert implied_probability_from_market(yes_bid_cents=44, yes_ask_cents=41) is None
    assert implied_probability_from_market(mid_cents=101) is None


def test_compare_bucket_probabilities_returns_descriptive_edge_deltas() -> None:
    deltas = compare_bucket_probabilities(
        {"70-74": 0.35, "75-79": 0.55, "80+": None},
        {"70-74": 41, "75-79": 0.45, "80+": 10, "under-70": 0.04},
    )

    assert [delta.bucket for delta in deltas] == ["70-74", "75-79"]
    assert deltas[0].probability_delta == -0.06
    assert deltas[0].expected_edge_cents == -6
    assert deltas[1].probability_delta == 0.10
    assert deltas[1].expected_edge_cents == 10


def test_evaluate_freshness_for_fresh_stale_and_missing_records() -> None:
    evaluated_at = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)

    fresh = evaluate_freshness(
        "2026-07-14T19:30:00+00:00",
        evaluated_at=evaluated_at,
        max_age_minutes=45,
    )
    stale = evaluate_freshness(
        "2026-07-14T18:00:00+00:00",
        evaluated_at=evaluated_at,
        max_age_minutes=45,
    )
    missing = evaluate_freshness(None, evaluated_at=evaluated_at)

    assert fresh.is_fresh is True
    assert fresh.age_minutes == 30
    assert stale.is_stale is True
    assert stale.label == "stale"
    assert missing.is_stale is True
    assert missing.label == "missing timestamp"


def test_generate_risk_guards_labels_active_data_quality_flags() -> None:
    guards = generate_risk_guards(
        settlement_source_verified=False,
        is_stale=True,
        model_spread_f=5,
        high_spread_threshold_f=4,
        proxy_only_observations=True,
    )

    active = active_risk_guards(guards)
    assert {guard.key for guard in active} == {
        "unverified-settlement-source",
        "stale-data",
        "high-model-spread",
        "proxy-only-observations",
    }
    assert all("trade" not in guard.label.lower() for guard in guards)


def test_generate_risk_guards_can_return_inactive_guards() -> None:
    guards = generate_risk_guards(
        settlement_source_verified=True,
        is_stale=False,
        model_spread_f=2,
        proxy_only_observations=False,
    )

    assert active_risk_guards(guards) == []
