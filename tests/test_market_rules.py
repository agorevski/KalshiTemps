from __future__ import annotations

from pathlib import Path
import sys
import uuid

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps import cli  # noqa: E402
from kalshi_temps.db import connection, initialize_database  # noqa: E402
from kalshi_temps.market_rules import (  # noqa: E402
    market_rule_actionability,
    normalize_market_rule,
    validate_market_rule,
)
from kalshi_temps.repository import WeatherRepository  # noqa: E402


def _db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def _complete_rule(**overrides: object) -> dict[str, object]:
    rule: dict[str, object] = {
        "ticker": "kxhighsea-26jul14-b75",
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


def test_complete_verified_market_rule_is_actionable() -> None:
    rule = normalize_market_rule(_complete_rule())

    validation = validate_market_rule(rule)
    actionability = market_rule_actionability(rule)

    assert rule["ticker"] == "KXHIGHSEA-26JUL14-B75"
    assert validation.is_valid
    assert validation.errors == ()
    assert actionability.is_actionable
    assert "not a trade recommendation" in actionability.reason


def test_incomplete_or_unverified_market_rule_is_not_actionable() -> None:
    incomplete = normalize_market_rule(_complete_rule(settlement_rule_text="", verification_status="unverified"))
    unverified = normalize_market_rule(_complete_rule(verification_status="unverified", verified_by=None, verified_at=None))

    incomplete_actionability = market_rule_actionability(incomplete)
    unverified_actionability = market_rule_actionability(unverified)

    assert "settlement_rule_text" in incomplete_actionability.reason
    assert not incomplete_actionability.is_actionable
    assert not unverified_actionability.is_actionable
    assert "not been manually verified" in unverified_actionability.reason


def test_invalid_market_rule_fields_are_rejected() -> None:
    rule = normalize_market_rule(
        _complete_rule(
            timezone="Not/AZone",
            daily_cutoff="24:99",
            units="kelvin",
            source_url="ftp://example.test/rules",
        )
    )

    validation = validate_market_rule(rule)

    assert not validation.is_valid
    assert "timezone must be a valid IANA timezone" in validation.errors
    assert "daily_cutoff must use HH:MM 24-hour format" in validation.errors
    assert "units must be fahrenheit or celsius" in validation.errors
    assert "source_url must be an http(s) URL" in validation.errors


def test_repository_market_rule_persistence_and_idempotency() -> None:
    db_path = _db_path("test-market-rules")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            first = repo.upsert_market_rule(_complete_rule())
            second = repo.upsert_market_rule(_complete_rule(notes="updated verification note"))

            assert first["id"] == second["id"]
            assert second["notes"] == "updated verification note"
            assert repo.get_market_rule("kxhighsea-26jul14-b75")["verification_status"] == "verified"
            assert repo.market_rule_actionability("KXHIGHSEA-26JUL14-B75")["is_actionable"]
            assert len(repo.list_market_rules()) == 1
            assert repo.market_verification_summary("KXHIGHSEA-26JUL14-B75")["is_actionable"]

            with pytest.raises(ValueError):
                repo.upsert_market_rule(_complete_rule(source_url="not-a-url"))
    finally:
        db_path.unlink(missing_ok=True)


def test_cli_market_rule_commands_dispatch(monkeypatch, capsys) -> None:
    calls: list[tuple[str, object]] = []

    def fake_add(db_path, record):
        calls.append(("add", db_path, record["ticker"]))
        return {"ticker": record["ticker"], "verification_status": record["verification_status"]}

    def fake_verify(db_path, *, ticker, verified_by, verified_at=None, notes=None):
        calls.append(("verify", db_path, ticker, verified_by, verified_at, notes))
        return {"ticker": ticker.upper(), "verification_status": "verified"}

    class FakeRepo:
        def __init__(self, conn):
            self.conn = conn

        def list_market_rules(self, limit=50):
            calls.append(("list", limit))
            return [
                {
                    "ticker": "KXHIGHSEA-26JUL14-B75",
                    "verification_status": "verified",
                    "official_source_name": "NOAA",
                    "source_url": "https://example.test/rules",
                }
            ]

    monkeypatch.setattr(cli, "add_or_update_market_rule", fake_add)
    monkeypatch.setattr(cli, "verify_market_rule", fake_verify)
    monkeypatch.setattr(cli, "initialize_database", lambda db_path: Path(db_path or "data/fake.sqlite3"))
    monkeypatch.setattr(cli, "connection", lambda db_path: _NullContext(None))
    monkeypatch.setattr(cli, "WeatherRepository", FakeRepo)

    assert cli.main(["--db", "data/test.sqlite3", "add-market-rule", "--ticker", "KXHIGHSEA-26JUL14-B75"]) == 0
    assert (
        cli.main(
            [
                "--db",
                "data/test.sqlite3",
                "verify-market-rule",
                "KXHIGHSEA-26JUL14-B75",
                "--verified-by",
                "tester",
                "--verified-at",
                "2026-07-14T20:00:00+00:00",
            ]
        )
        == 0
    )
    assert cli.main(["--db", "data/test.sqlite3", "list-market-rules", "--limit", "1"]) == 0

    assert calls == [
        ("add", "data/test.sqlite3", "KXHIGHSEA-26JUL14-B75"),
        ("verify", "data/test.sqlite3", "KXHIGHSEA-26JUL14-B75", "tester", "2026-07-14T20:00:00+00:00", None),
        ("list", 1),
    ]
    output = capsys.readouterr().out
    assert "not a trade recommendation" in output
    assert "KXHIGHSEA-26JUL14-B75\tverified\tNOAA" in output


class _NullContext:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, exc_type, exc, traceback):
        return False
