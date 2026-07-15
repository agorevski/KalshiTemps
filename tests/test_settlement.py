from __future__ import annotations

from pathlib import Path
import json
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps import cli  # noqa: E402
from kalshi_temps.db import connection, initialize_database  # noqa: E402
from kalshi_temps.repository import WeatherRepository  # noqa: E402
from kalshi_temps.settlement import (  # noqa: E402
    apply_rounding,
    local_day_check,
    normalize_temperature_value,
    parse_temperature_bucket,
    replay_settlement,
)


def _db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def _rule(**overrides: object) -> dict[str, object]:
    rule: dict[str, object] = {
        "ticker": "KXHIGHSEA-26JUL14-B75",
        "title": "Seattle high temperature above 75°F on July 14, 2026",
        "settlement_rule_text": "Settles from the official daily high temperature reported for KSEA.",
        "official_source_name": "NOAA Daily Climate Report",
        "official_station_id": "KSEA",
        "product": "daily high temperature",
        "timezone": "America/Los_Angeles",
        "daily_cutoff": "23:59",
        "units": "fahrenheit",
        "rounding": "nearest whole degree per exchange rule",
        "fallback_policy": "Use exchange-published fallback if the official station report is unavailable.",
        "correction_policy": "Use final corrected official report if the exchange applies corrections.",
        "verification_status": "verified",
        "verified_by": "test-fixture",
        "verified_at": "2026-07-14T20:00:00+00:00",
        "source_url": "https://example.test/rules/kxhighsea",
        "notes": "Verification only; not a trade recommendation.",
    }
    rule.update(overrides)
    return rule


def test_temperature_bucket_boundaries_and_thresholds() -> None:
    closed = parse_temperature_bucket("75-76°F")
    above = parse_temperature_bucket("above 75°F")
    at_least = parse_temperature_bucket("77°F+")
    below = parse_temperature_bucket("below 70°F")

    assert closed.contains(75)
    assert closed.contains(76)
    assert not closed.contains(76.1)
    assert not above.contains(75)
    assert above.contains(75.1)
    assert at_least.contains(77)
    assert not below.contains(70)


def test_rounding_and_celsius_normalization() -> None:
    assert apply_rounding(75.5, "nearest whole degree per exchange rule") == 76
    assert apply_rounding(75.9, "floor") == 75
    assert apply_rounding(75.1, "ceiling") == 76
    assert normalize_temperature_value(25, from_units="celsius", to_units="fahrenheit") == 77


def test_local_day_cutoff_uses_market_timezone() -> None:
    valid = local_day_check(
        "2026-07-15T06:59:00+00:00",
        target_date="2026-07-14",
        timezone_name="America/Los_Angeles",
        daily_cutoff="23:59",
    )
    invalid = local_day_check(
        "2026-07-15T07:00:00+00:00",
        target_date="2026-07-14",
        timezone_name="America/Los_Angeles",
        daily_cutoff="23:59",
    )

    assert valid["date_matches"]
    assert valid["within_cutoff"]
    assert not invalid["date_matches"]


def test_replay_verified_rule_corrections_and_mismatches() -> None:
    matched = replay_settlement(
        _rule(),
        {
            "target_date": "2026-07-14",
            "first_published_high_temperature_f": 75,
            "corrected_high_temperature_f": 75.5,
            "observed_at": "2026-07-15T06:59:00+00:00",
            "source_name": "NOAA",
        },
    )
    unmatched = replay_settlement(
        _rule(verification_status="unverified", verified_by=None, verified_at=None),
        {
            "target_date": "2026-07-14",
            "high_temperature_f": 76,
            "observed_at": "2026-07-15T07:00:00+00:00",
            "source_name": "NOAA",
        },
    )

    assert matched["status"] == "matched"
    assert matched["correction_applied"]
    assert matched["first_published_value"] == 75
    assert matched["corrected_value"] == 75.5
    assert unmatched["status"] == "unmatched"
    assert "market-rule-not-verified" in unmatched["mismatch_reasons"]
    assert "local-day-mismatch" in unmatched["mismatch_reasons"]


def test_repository_persists_settlement_replay_idempotently() -> None:
    db_path = _db_path("test-settlement-repo")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            repo.upsert_market_rule(_rule())
            repo.save_official_outcome(
                station="KSEA",
                target_date="2026-07-14",
                high_temperature_f=76,
                source_name="NOAA",
                observed_at="2026-07-15T06:59:00+00:00",
                raw_payload={"station": "KSEA", "high": 76},
            )

            first = repo.replay_settlement(ticker="KXHIGHSEA-26JUL14-B75", target_date="2026-07-14")
            second = repo.replay_settlement(ticker="KXHIGHSEA-26JUL14-B75", target_date="2026-07-14")
            rows = repo.list_settlement_replays(ticker="KXHIGHSEA-26JUL14-B75")

        assert first["id"] == second["id"]
        assert first["status"] == "matched"
        assert first["raw_payload_hash"]
        assert json.loads(first["mismatch_reasons"]) == []
        assert len(rows) == 1
    finally:
        db_path.unlink(missing_ok=True)


def test_cli_replay_settlement_smoke(capsys) -> None:
    db_path = _db_path("test-settlement-cli")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            repo.upsert_market_rule(_rule())
            repo.save_official_outcome(
                station="KSEA",
                target_date="2026-07-14",
                high_temperature_f=76,
                observed_at="2026-07-15T06:59:00+00:00",
            )

        assert (
            cli.main(
                [
                    "--db",
                    str(db_path),
                    "replay-settlement",
                    "KXHIGHSEA-26JUL14-B75",
                    "--target-date",
                    "2026-07-14",
                ]
            )
            == 0
        )

        output = capsys.readouterr().out
        assert "Settlement replay KXHIGHSEA-26JUL14-B75 2026-07-14: matched" in output
        assert "not trading advice" in output
    finally:
        db_path.unlink(missing_ok=True)
