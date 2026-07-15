from __future__ import annotations

from pathlib import Path
import sys
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps import cli  # noqa: E402
from kalshi_temps.db import connection, initialize_database  # noqa: E402
from kalshi_temps.kalshi import (  # noqa: E402
    KalshiClient,
    KalshiConfig,
    find_seattle_temperature_candidates,
    kalshi_config_from_env,
    kalshi_market_to_snapshot,
)
from kalshi_temps.repository import WeatherRepository  # noqa: E402


def _db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def _market(**overrides: object) -> dict[str, object]:
    market: dict[str, object] = {
        "ticker": "KXHIGHTEMPSEA-26JUL15-B75",
        "event_ticker": "KXHIGHTEMPSEA-26JUL15",
        "market_type": "binary",
        "title": "Will Seattle's high temperature be above 75°F on July 15?",
        "yes_sub_title": "Above 75°F",
        "no_sub_title": "75°F or below",
        "status": "active",
        "open_time": "2026-07-14T12:00:00Z",
        "close_time": "2026-07-15T23:59:00Z",
        "latest_expiration_time": "2026-07-16T02:00:00Z",
        "rules_primary": "This market settles based on the official high temperature in Seattle.",
        "rules_secondary": "Review station and rounding rules on Kalshi.",
        "yes_bid_dollars": "0.42",
        "yes_ask_dollars": "0.48",
        "no_bid_dollars": "0.52",
        "no_ask_dollars": "0.58",
        "last_price_dollars": "0.45",
    }
    market.update(overrides)
    return market


def test_kalshi_env_file_loading(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "KALSHI_API_BASE_URL=https://external-api.demo.kalshi.co/trade-api/v2",
                "KALSHI_API_KEY_ID='key-id'",
                "KALSHI_API_PRIVATE_KEY_PATH=/tmp/kalshi-private.pem",
                "KALSHI_API_TIMEOUT_SECONDS=3.5",
            ]
        ),
        encoding="utf-8",
    )
    for key in (
        "KALSHI_API_BASE_URL",
        "KALSHI_API_KEY_ID",
        "KALSHI_API_PRIVATE_KEY_PATH",
        "KALSHI_API_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)

    config = kalshi_config_from_env(env_path=env_file)

    assert config.base_url == "https://external-api.demo.kalshi.co/trade-api/v2"
    assert config.api_key_id == "key-id"
    assert config.private_key_path == Path("/tmp/kalshi-private.pem")
    assert config.timeout_seconds == 3.5


def test_kalshi_client_signs_path_without_query(monkeypatch, tmp_path) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr("time.time", lambda: 1234.567)
    calls: list[tuple[str, str, dict[str, str], float]] = []

    def transport(method, path, headers, timeout):
        calls.append((method, path, dict(headers), timeout))
        return {"markets": [], "cursor": ""}

    client = KalshiClient(
        KalshiConfig(api_key_id="key-id", private_key_path=key_path, timeout_seconds=2),
        transport=transport,
    )

    client.list_markets(status="open", limit=5)

    assert calls[0][1] == "/markets?limit=5&status=open"
    assert calls[0][2]["KALSHI-ACCESS-KEY"] == "key-id"
    assert calls[0][2]["KALSHI-ACCESS-TIMESTAMP"] == "1234567"
    assert calls[0][2]["KALSHI-ACCESS-SIGNATURE"]


def test_candidate_ranking_and_snapshot_normalization() -> None:
    candidates = find_seattle_temperature_candidates(
        [
            _market(),
            _market(
                ticker="KXRAINNYC-26JUL15",
                title="Will it rain in New York on July 15?",
                rules_primary="This market settles based on New York precipitation.",
                rules_secondary="Review official rain rules on Kalshi.",
            ),
        ],
        target_date="2026-07-15",
        captured_at="2026-07-14T20:00:00+00:00",
    )
    snapshot = kalshi_market_to_snapshot(_market(), captured_at="2026-07-14T20:00:00+00:00")

    assert [candidate["ticker"] for candidate in candidates] == ["KXHIGHTEMPSEA-26JUL15-B75"]
    assert candidates[0]["rank_score"] >= 100
    assert snapshot["yes_bid"] == 42
    assert snapshot["yes_ask"] == 48
    assert snapshot["implied_probability"] == 0.45


def test_repository_persists_candidates_selection_and_snapshot() -> None:
    db_path = _db_path("test-kalshi")
    try:
        initialize_database(str(db_path))
        candidate = find_seattle_temperature_candidates(
            [_market()],
            target_date="2026-07-15",
            captured_at="2026-07-14T20:00:00+00:00",
        )[0]
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            saved = repo.save_kalshi_market_candidate(candidate)
            selected = repo.select_kalshi_market_candidate(
                target_date="2026-07-15",
                ticker=saved["ticker"],
                notes="manual selection",
            )
            snapshot = repo.save_kalshi_market_snapshot_from_payload(_market())

            assert saved["rank_reasons"]
            assert selected["selected"] is True
            assert repo.selected_kalshi_market("2026-07-15")["ticker"] == saved["ticker"]
            assert snapshot["market_ticker"] == saved["ticker"]
    finally:
        db_path.unlink(missing_ok=True)


def test_cli_kalshi_commands_with_mocked_client(monkeypatch, capsys) -> None:
    db_path = _db_path("test-kalshi-cli")

    class FakeClient:
        def iter_markets(self, **kwargs):
            return [_market()]

        def get_market(self, ticker):
            return {"market": _market(ticker=ticker)}

    monkeypatch.setattr(cli, "KalshiClient", lambda config: FakeClient())
    monkeypatch.setattr(cli, "kalshi_config_from_env", lambda: object())
    try:
        assert cli.main(["--db", str(db_path), "find-kalshi-markets", "--target-date", "2026-07-15"]) == 0
        assert (
            cli.main(
                [
                    "--db",
                    str(db_path),
                    "select-kalshi-market",
                    "--target-date",
                    "2026-07-15",
                    "--ticker",
                    "KXHIGHTEMPSEA-26JUL15-B75",
                ]
            )
            == 0
        )
        assert (
            cli.main(["--db", str(db_path), "collect-selected-kalshi-market", "--target-date", "2026-07-15"])
            == 0
        )

        output = capsys.readouterr().out
        assert "research-only, no bet placed" in output
        assert "not settlement verification" in output
        assert "no bet placed" in output
    finally:
        db_path.unlink(missing_ok=True)
