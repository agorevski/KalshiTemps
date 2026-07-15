from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


VERIFICATION_STATUSES = {"unverified", "verified", "rejected"}
CRITICAL_FIELDS = (
    "ticker",
    "title",
    "settlement_rule_text",
    "official_source_name",
    "official_station_id",
    "product",
    "timezone",
    "daily_cutoff",
    "units",
    "rounding",
    "fallback_policy",
    "correction_policy",
    "source_url",
)


@dataclass(frozen=True)
class MarketRuleValidation:
    is_valid: bool
    errors: tuple[str, ...]
    missing_critical_fields: tuple[str, ...]


@dataclass(frozen=True)
class MarketRuleActionability:
    is_actionable: bool
    reason: str


def normalize_market_rule(record: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize an explicit manual market-rule record without guessing semantics."""
    normalized: dict[str, Any] = {}
    for field in CRITICAL_FIELDS + ("verification_status", "verified_by", "verified_at", "notes"):
        value = record.get(field)
        if isinstance(value, str):
            value = value.strip()
        normalized[field] = value

    ticker = normalized.get("ticker")
    if ticker:
        normalized["ticker"] = str(ticker).upper()

    status = normalized.get("verification_status") or "unverified"
    normalized["verification_status"] = str(status).lower()
    if normalized.get("verified_at") is None and normalized["verification_status"] == "verified":
        normalized["verified_at"] = utc_now_iso()
    return normalized


def validate_market_rule(record: Mapping[str, Any]) -> MarketRuleValidation:
    missing = tuple(field for field in CRITICAL_FIELDS if _blank(record.get(field)))
    errors: list[str] = []

    ticker = record.get("ticker")
    if not _blank(ticker) and not str(ticker).isupper():
        errors.append("ticker must be uppercase after normalization")

    status = str(record.get("verification_status") or "unverified").lower()
    if status not in VERIFICATION_STATUSES:
        errors.append(f"verification_status must be one of {sorted(VERIFICATION_STATUSES)}")

    if status == "verified":
        if _blank(record.get("verified_by")):
            errors.append("verified_by is required when verification_status is verified")
        if _blank(record.get("verified_at")):
            errors.append("verified_at is required when verification_status is verified")
        elif _parse_iso_datetime(str(record["verified_at"])) is None:
            errors.append("verified_at must be an ISO-8601 timestamp")

    if not _blank(record.get("timezone")):
        try:
            ZoneInfo(str(record["timezone"]))
        except ZoneInfoNotFoundError:
            errors.append("timezone must be a valid IANA timezone")

    if not _blank(record.get("daily_cutoff")) and not _is_hh_mm(str(record["daily_cutoff"])):
        errors.append("daily_cutoff must use HH:MM 24-hour format")

    units = str(record.get("units") or "").lower()
    if units and units not in {"fahrenheit", "celsius"}:
        errors.append("units must be fahrenheit or celsius")

    if not _blank(record.get("source_url")) and not _is_http_url(str(record["source_url"])):
        errors.append("source_url must be an http(s) URL")

    return MarketRuleValidation(
        is_valid=not missing and not errors,
        errors=tuple(errors),
        missing_critical_fields=missing,
    )


def market_rule_actionability(record: Mapping[str, Any] | None) -> MarketRuleActionability:
    if record is None:
        return MarketRuleActionability(False, "No market rule record has been entered.")

    validation = validate_market_rule(record)
    if validation.missing_critical_fields:
        fields = ", ".join(validation.missing_critical_fields)
        return MarketRuleActionability(False, f"Missing critical market rule fields: {fields}.")
    if validation.errors:
        return MarketRuleActionability(False, "; ".join(validation.errors))
    if record.get("verification_status") != "verified":
        return MarketRuleActionability(False, "Market rule has not been manually verified.")
    return MarketRuleActionability(
        True,
        "Market rule is complete and manually verified; this is evidence hygiene, not a trade recommendation.",
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _is_hh_mm(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return False
    hour, minute = (int(part) for part in parts)
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
