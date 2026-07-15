from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .ingest import normalize_market_snapshot, provenance_hash

PRODUCTION_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
DEMO_BASE_URL = "https://external-api.demo.kalshi.co/trade-api/v2"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_ENV_PATH = ".env"


@dataclass(frozen=True)
class KalshiConfig:
    base_url: str = PRODUCTION_BASE_URL
    api_key_id: str | None = None
    private_key_path: Path | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key_id and self.private_key_path)


Transport = Callable[[str, str, Mapping[str, str], float], Mapping[str, Any]]


class KalshiClient:
    def __init__(self, config: KalshiConfig, *, transport: Transport | None = None):
        self.config = config
        self._transport = transport
        self._private_key: rsa.RSAPrivateKey | None = None

    def list_markets(
        self,
        *,
        status: str | None = "open",
        limit: int = 100,
        cursor: str | None = None,
        series_ticker: str | None = None,
        event_ticker: str | None = None,
        min_close_ts: int | None = None,
        max_close_ts: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {"limit": _bounded_limit(limit)}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if min_close_ts is not None:
            params["min_close_ts"] = min_close_ts
        if max_close_ts is not None:
            params["max_close_ts"] = max_close_ts
        return self._request("GET", "/markets", params=params)

    def get_market(self, ticker: str) -> dict[str, Any]:
        ticker = ticker.strip().upper()
        if not ticker:
            raise ValueError("ticker is required")
        return self._request("GET", f"/markets/{ticker}")

    def iter_markets(self, **kwargs: Any) -> list[dict[str, Any]]:
        cursor = kwargs.pop("cursor", None)
        markets: list[dict[str, Any]] = []
        while True:
            payload = self.list_markets(cursor=cursor, **kwargs)
            batch = payload.get("markets", [])
            if not isinstance(batch, list):
                raise ValueError("Kalshi markets response must contain a markets list")
            markets.extend(market for market in batch if isinstance(market, dict))
            cursor = payload.get("cursor")
            if not cursor:
                return markets

    def _request(self, method: str, path: str, *, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request_path = f"{path}{query}"
        headers = self._headers(method, request_path)
        if self._transport is not None:
            payload = self._transport(method, request_path, headers, self.config.timeout_seconds)
        else:
            url = self.config.base_url.rstrip("/") + request_path
            try:
                response = httpx.request(method, url, headers=headers, timeout=self.config.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                raise ValueError(f"Kalshi API returned HTTP {exc.response.status_code} for {path}") from exc
            except httpx.HTTPError as exc:
                raise ValueError(f"Kalshi API request failed for {path}: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise ValueError(f"Kalshi API returned non-JSON payload for {path}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("Kalshi API response must be a JSON object")
        return dict(payload)

    def _headers(self, method: str, path: str) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "kalshi-temps/0.1"}
        if not self.config.has_credentials:
            return headers
        timestamp = str(int(time.time() * 1000))
        path_without_query = path.split("?", 1)[0]
        signature = sign_pss_text(self._load_private_key(), timestamp + method.upper() + path_without_query)
        headers.update(
            {
                "KALSHI-ACCESS-KEY": self.config.api_key_id or "",
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "KALSHI-ACCESS-SIGNATURE": signature,
            }
        )
        return headers

    def _load_private_key(self) -> rsa.RSAPrivateKey:
        if self._private_key is not None:
            return self._private_key
        if self.config.private_key_path is None:
            raise ValueError("KALSHI_API_PRIVATE_KEY_PATH is required for signed Kalshi requests")
        key_path = self.config.private_key_path.expanduser()
        try:
            loaded = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        except OSError as exc:
            raise ValueError("Kalshi private key file could not be read") from exc
        if not isinstance(loaded, rsa.RSAPrivateKey):
            raise ValueError("Kalshi private key must be an RSA private key")
        self._private_key = loaded
        return loaded


def load_env_file(path: str | os.PathLike[str] = DEFAULT_ENV_PATH, *, override: bool = False) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    loaded: dict[str, str] = {}
    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise ValueError(f"Invalid .env line {line_number}: expected KEY=value")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid .env key on line {line_number}")
        parsed = _unquote_env_value(value.strip())
        loaded[key] = parsed
        if override or key not in os.environ:
            os.environ[key] = parsed
    return loaded


def kalshi_config_from_env(*, env_path: str | os.PathLike[str] | None = DEFAULT_ENV_PATH) -> KalshiConfig:
    if env_path is not None:
        load_env_file(env_path)
    base_url = os.getenv("KALSHI_API_BASE_URL", PRODUCTION_BASE_URL).strip().rstrip("/")
    if not base_url.startswith(("https://", "http://")):
        raise ValueError("KALSHI_API_BASE_URL must be an http(s) URL")
    timeout_value = os.getenv("KALSHI_API_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout = float(timeout_value)
    except ValueError as exc:
        raise ValueError("KALSHI_API_TIMEOUT_SECONDS must be numeric") from exc
    if timeout <= 0:
        raise ValueError("KALSHI_API_TIMEOUT_SECONDS must be positive")
    key_path = os.getenv("KALSHI_API_PRIVATE_KEY_PATH")
    return KalshiConfig(
        base_url=base_url,
        api_key_id=os.getenv("KALSHI_API_KEY_ID"),
        private_key_path=Path(key_path).expanduser() if key_path else None,
        timeout_seconds=timeout,
    )


def sign_pss_text(private_key: rsa.RSAPrivateKey, text: str) -> str:
    signature = private_key.sign(
        text.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def find_seattle_temperature_candidates(
    markets: list[Mapping[str, Any]],
    *,
    target_date: str,
    captured_at: str | None = None,
) -> list[dict[str, Any]]:
    target = date.fromisoformat(target_date).isoformat()
    captured = captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    candidates = [normalize_kalshi_market_candidate(market, target_date=target, captured_at=captured) for market in markets]
    filtered = [
        candidate
        for candidate in candidates
        if candidate["rank_score"] > 0 and candidate["seattle_match"] and candidate["temperature_language_match"]
    ]
    return sorted(filtered, key=lambda item: (-item["rank_score"], item["ticker"]))


def normalize_kalshi_market_candidate(
    market: Mapping[str, Any],
    *,
    target_date: str,
    captured_at: str | None = None,
) -> dict[str, Any]:
    ticker = _required_text(market, "ticker").upper()
    title = _text(market.get("title")) or _text(market.get("yes_sub_title")) or ticker
    subtitle = _text(market.get("subtitle")) or _text(market.get("yes_sub_title"))
    rules_primary = _text(market.get("rules_primary"))
    rules_secondary = _text(market.get("rules_secondary"))
    text = " ".join(value for value in (ticker, title, subtitle, rules_primary, rules_secondary) if value).lower()
    target = date.fromisoformat(target_date).isoformat()
    target_tokens = _target_date_tokens(target)
    reasons: list[str] = []
    score = 0
    seattle_match = any(token in text for token in ("seattle", "seatac", "sea-tac", "ksea"))
    temperature_language_match = any(
        token in text for token in ("temperature", "high temp", "daily high", "weather", "climate")
    )
    date_match = any(token.lower() in text for token in target_tokens)
    if seattle_match:
        score += 45
        reasons.append("Seattle/KSEA language matched")
    if temperature_language_match:
        score += 30
        reasons.append("temperature/climate language matched")
    if date_match:
        score += 25
        reasons.append("target date language matched")
    close_time = _text(market.get("close_time"))
    if close_time and close_time.startswith(target):
        score += 10
        reasons.append("close_time falls on target date")
    if rules_primary or rules_secondary:
        score += 5
        reasons.append("settlement rules present")
    if _text(market.get("status")) in {"active", "open"}:
        score += 5
        reasons.append("market is active/open")
    if score == 0:
        reasons.append("no Seattle temperature/date match")
    captured = captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    price_snapshot = kalshi_market_to_snapshot(market, captured_at=captured)
    return {
        "target_date": target,
        "ticker": ticker,
        "event_ticker": _text(market.get("event_ticker")),
        "title": title,
        "subtitle": subtitle,
        "yes_sub_title": _text(market.get("yes_sub_title")),
        "no_sub_title": _text(market.get("no_sub_title")),
        "status": _text(market.get("status")),
        "market_type": _text(market.get("market_type")),
        "open_time": _text(market.get("open_time")),
        "close_time": close_time,
        "expiration_time": _text(market.get("expected_expiration_time")) or _text(market.get("latest_expiration_time")),
        "rules_primary": rules_primary,
        "rules_secondary": rules_secondary,
        "yes_bid_cents": price_snapshot.get("yes_bid"),
        "yes_ask_cents": price_snapshot.get("yes_ask"),
        "no_bid_cents": price_snapshot.get("no_bid"),
        "no_ask_cents": price_snapshot.get("no_ask"),
        "last_price_cents": price_snapshot.get("last"),
        "implied_probability": price_snapshot.get("implied_probability"),
        "rank_score": score,
        "rank_reasons": reasons,
        "source_url": f"https://kalshi.com/markets/{ticker}",
        "captured_at": captured,
        "raw_payload": dict(market),
        "raw_payload_hash": provenance_hash(market),
        "seattle_match": seattle_match,
        "date_match": date_match,
        "temperature_language_match": temperature_language_match,
        "settlement_rule_presence": bool(rules_primary or rules_secondary),
    }


def kalshi_market_to_snapshot(market: Mapping[str, Any], *, captured_at: str | None = None) -> dict[str, Any]:
    record = {
        "ticker": _required_text(market, "ticker").upper(),
        "bucket": _text(market.get("yes_sub_title")) or _text(market.get("title")),
        "captured_at": captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "yes_bid": _dollars_to_cents(market.get("yes_bid_dollars")),
        "yes_ask": _dollars_to_cents(market.get("yes_ask_dollars")),
        "no_bid": _dollars_to_cents(market.get("no_bid_dollars")),
        "no_ask": _dollars_to_cents(market.get("no_ask_dollars")),
        "last": _dollars_to_cents(market.get("last_price_dollars")),
        "source_note": "Read-only Kalshi market data snapshot; not a trade recommendation.",
    }
    return normalize_market_snapshot(record)


def market_rule_draft_from_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    rules = "\n\n".join(
        value
        for value in (_text(candidate.get("rules_primary")), _text(candidate.get("rules_secondary")))
        if value
    )
    return {
        "ticker": _required_text(candidate, "ticker").upper(),
        "title": _required_text(candidate, "title"),
        "settlement_rule_text": rules or "Review Kalshi market rules before verification.",
        "official_source_name": "Review Kalshi settlement rule",
        "official_station_id": "Review required station",
        "product": "Review required product",
        "timezone": "America/Los_Angeles",
        "daily_cutoff": "23:59",
        "units": "fahrenheit",
        "rounding": "Review Kalshi settlement rule",
        "fallback_policy": "Review Kalshi settlement rule",
        "correction_policy": "Review Kalshi settlement rule",
        "verification_status": "unverified",
        "source_url": _text(candidate.get("source_url")) or f"https://kalshi.com/markets/{candidate['ticker']}",
        "notes": "Drafted from read-only Kalshi metadata; manually verify every field before relying on it.",
    }


def _bounded_limit(limit: int) -> int:
    parsed = int(limit)
    if parsed < 1 or parsed > 1000:
        raise ValueError("limit must be between 1 and 1000")
    return parsed


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _required_text(record: Mapping[str, Any], key: str) -> str:
    value = _text(record.get(key))
    if value is None:
        raise ValueError(f"Kalshi market {key} is required")
    return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dollars_to_cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    cents = round(float(value) * 100)
    if cents < 0 or cents > 100:
        raise ValueError("Kalshi price must be between $0 and $1")
    return cents


def _target_date_tokens(target_date: str) -> tuple[str, ...]:
    parsed = date.fromisoformat(target_date)
    return (
        parsed.isoformat(),
        parsed.strftime("%b %-d"),
        parsed.strftime("%B %-d"),
        parsed.strftime("%b %d"),
        parsed.strftime("%B %d"),
        parsed.strftime("%y%b%d").upper(),
        parsed.strftime("%d%b%y").upper(),
    )
