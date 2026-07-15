from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import hashlib
import json
import math
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .market_rules import market_rule_actionability


@dataclass(frozen=True)
class TemperatureBucket:
    label: str
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    units: str = "fahrenheit"

    def contains(self, value: float) -> bool:
        if self.lower is not None:
            if value < self.lower or (value == self.lower and not self.lower_inclusive):
                return False
        if self.upper is not None:
            if value > self.upper or (value == self.upper and not self.upper_inclusive):
                return False
        return True


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_temperature_bucket(text: str, *, units: str = "fahrenheit") -> TemperatureBucket:
    """Parse common exchange temperature bucket language without inferring unknown rules."""
    if not text or not text.strip():
        raise ValueError("temperature bucket text is required")
    original = text.strip()
    normalized = (
        original.lower()
        .replace("degrees", "")
        .replace("degree", "")
        .replace("°", "")
        .replace("fahrenheit", "f")
        .replace("celsius", "c")
    )
    unit = "celsius" if re.search(r"\bc\b", normalized) else units.lower()

    range_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:-|to|through)\s*(-?\d+(?:\.\d+)?)", normalized)
    if range_match:
        lower, upper = sorted((float(range_match.group(1)), float(range_match.group(2))))
        return TemperatureBucket(original, lower, upper, True, True, unit)

    between_match = re.search(
        r"(?:between|from)\s+(-?\d+(?:\.\d+)?)\s+(?:and|to)\s+(-?\d+(?:\.\d+)?)",
        normalized,
    )
    if between_match:
        lower, upper = sorted((float(between_match.group(1)), float(between_match.group(2))))
        return TemperatureBucket(original, lower, upper, True, True, unit)

    numbers = [float(match) for match in re.findall(r"-?\d+(?:\.\d+)?", normalized)]
    if not numbers:
        raise ValueError(f"could not parse temperature bucket from: {original}")
    threshold = numbers[0]

    if re.search(r"(?:^|\s)(?:>|above|over|greater than|warmer than)\s*-?\d", normalized):
        return TemperatureBucket(original, lower=threshold, lower_inclusive=False, units=unit)
    if re.search(r"(?:^|\s)(?:>=|at least|or above|or higher|and above|\+)", normalized) or normalized.rstrip().endswith(
        "+"
    ):
        return TemperatureBucket(original, lower=threshold, lower_inclusive=True, units=unit)
    if re.search(r"(?:^|\s)(?:<|below|under|less than|cooler than)\s*-?\d", normalized):
        return TemperatureBucket(original, upper=threshold, upper_inclusive=False, units=unit)
    if re.search(r"(?:^|\s)(?:<=|at most|or below|or lower|and below)", normalized):
        return TemperatureBucket(original, upper=threshold, upper_inclusive=True, units=unit)

    return TemperatureBucket(original, lower=threshold, upper=threshold, units=unit)


def bucket_from_market_rule(rule: Mapping[str, Any]) -> TemperatureBucket:
    units = str(rule.get("units") or "fahrenheit").lower()
    candidates = [
        rule.get("temperature_bucket"),
        rule.get("bucket"),
        rule.get("title"),
        rule.get("settlement_rule_text"),
        rule.get("ticker"),
    ]
    errors: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return parse_temperature_bucket(str(candidate), units=units)
        except ValueError as exc:
            errors.append(str(exc))
    raise ValueError("could not determine settlement bucket from verified market rule")


def normalize_temperature_value(value: Any, *, from_units: str, to_units: str = "fahrenheit") -> float:
    temperature = float(value)
    if not math.isfinite(temperature):
        raise ValueError("temperature must be finite")
    source = from_units.lower()
    target = to_units.lower()
    if source == target:
        return temperature
    if source in {"fahrenheit", "f"} and target in {"celsius", "c"}:
        return (temperature - 32.0) * 5.0 / 9.0
    if source in {"celsius", "c"} and target in {"fahrenheit", "f"}:
        return temperature * 9.0 / 5.0 + 32.0
    raise ValueError("temperature units must be fahrenheit or celsius")


def apply_rounding(value: float, rounding: str | None) -> float:
    mode = (rounding or "none").strip().lower()
    decimal_value = Decimal(str(value))
    if mode in {"", "none", "exact", "no rounding", "no-rounding"}:
        return float(decimal_value)
    if "nearest" in mode or "whole" in mode or "round" in mode:
        return float(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if "floor" in mode or "down" in mode or "truncate" in mode:
        return float(decimal_value.to_integral_value(rounding=ROUND_FLOOR))
    if "ceil" in mode or "up" in mode:
        return float(decimal_value.to_integral_value(rounding=ROUND_CEILING))
    if "tenth" in mode or "0.1" in mode:
        return float(decimal_value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    raise ValueError(f"unsupported rounding mode: {rounding}")


def local_day_check(
    observed_at: str | None,
    *,
    target_date: str,
    timezone_name: str,
    daily_cutoff: str,
) -> dict[str, Any]:
    if not target_date:
        return {"checked": False, "reason": "target_date not provided"}
    if not observed_at:
        return {"checked": False, "reason": "observed_at not provided"}
    moment = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(timezone_name))
    local = moment.astimezone(ZoneInfo(timezone_name))
    cutoff_hour, cutoff_minute = (int(part) for part in daily_cutoff.split(":", 1))
    cutoff = time(cutoff_hour, cutoff_minute)
    target = date.fromisoformat(target_date)
    return {
        "checked": True,
        "local_observed_at": local.isoformat(),
        "local_date": local.date().isoformat(),
        "target_date": target.isoformat(),
        "daily_cutoff": daily_cutoff,
        "date_matches": local.date() == target,
        "within_cutoff": local.timetz().replace(tzinfo=None) <= cutoff,
    }


def replay_settlement(
    rule: Mapping[str, Any],
    official_outcome: Mapping[str, Any],
    *,
    replayed_at: str | None = None,
) -> dict[str, Any]:
    """Replay an official outcome for audit support; this is not trading advice."""
    mismatch_reasons: list[str] = []
    reconciliation_error: str | None = None
    actionability = market_rule_actionability(rule)
    if not actionability.is_actionable:
        mismatch_reasons.append("market-rule-not-verified")

    try:
        bucket = bucket_from_market_rule(rule)
        bucket_error = None
    except ValueError as exc:
        bucket = None
        bucket_error = str(exc)
        mismatch_reasons.append("bucket-unparseable")

    try:
        value, source_units, first_value, corrected_value, correction_applied = _official_temperature_for_rule(
            official_outcome,
            rule,
        )
        normalized = normalize_temperature_value(value, from_units=source_units, to_units=bucket.units if bucket else rule["units"])
        rounded = apply_rounding(normalized, str(rule.get("rounding") or "none"))
    except (KeyError, TypeError, ValueError) as exc:
        value = normalized = rounded = None
        source_units = str(rule.get("units") or "fahrenheit")
        first_value = corrected_value = None
        correction_applied = False
        reconciliation_error = str(exc)
        mismatch_reasons.append("official-value-invalid")

    local_check = local_day_check(
        _optional_str(official_outcome.get("observed_at")),
        target_date=str(official_outcome.get("target_date") or _target_date_from_rule(rule)),
        timezone_name=str(rule.get("timezone") or "UTC"),
        daily_cutoff=str(rule.get("daily_cutoff") or "23:59"),
    )
    if local_check.get("checked"):
        if not local_check.get("date_matches"):
            mismatch_reasons.append("local-day-mismatch")
        if not local_check.get("within_cutoff"):
            mismatch_reasons.append("local-cutoff-mismatch")

    bucket_matched = bool(bucket and rounded is not None and bucket.contains(float(rounded)))
    if bucket and rounded is not None and not bucket_matched:
        mismatch_reasons.append("official-value-outside-bucket")

    expected = _first_present(official_outcome, "settlement_bucket", "official_settlement_bucket", "market_bucket")
    expected_matches = None
    if expected and bucket:
        try:
            expected_bucket = parse_temperature_bucket(str(expected), units=bucket.units)
            expected_matches = expected_bucket == bucket or expected_bucket.contains(float(rounded))
            if not expected_matches:
                mismatch_reasons.append("reported-settlement-bucket-mismatch")
        except ValueError:
            expected_matches = False
            mismatch_reasons.append("reported-settlement-bucket-unparseable")

    fallback_used = bool(_first_present(official_outcome, "fallback_used", "used_fallback"))
    if fallback_used:
        mismatch_reasons.append("fallback-used")

    return {
        "ticker": str(rule.get("ticker") or "").upper(),
        "target_date": str(official_outcome.get("target_date") or _target_date_from_rule(rule) or ""),
        "status": "matched" if not mismatch_reasons and bucket_matched else "unmatched",
        "settlement_bucket": bucket.label if bucket else None,
        "bucket_matched": bucket_matched,
        "mismatch_reasons": sorted(set(mismatch_reasons)),
        "reconciliation_error": reconciliation_error or bucket_error,
        "official_value": value,
        "official_units": source_units,
        "normalized_value": normalized,
        "rounded_value": rounded,
        "evaluation_units": bucket.units if bucket else str(rule.get("units") or "fahrenheit"),
        "rounding": rule.get("rounding"),
        "local_day": local_check,
        "market_rule_verified": actionability.is_actionable,
        "market_rule_actionability_reason": actionability.reason,
        "rule_version": _rule_version(rule),
        "source_url": _first_present(official_outcome, "source_url", "url") or rule.get("source_url"),
        "official_source_name": _first_present(official_outcome, "source_name", "official_source_name")
        or rule.get("official_source_name"),
        "first_published_value": first_value,
        "corrected_value": corrected_value,
        "correction_applied": correction_applied,
        "correction_policy": rule.get("correction_policy"),
        "fallback_used": fallback_used,
        "fallback_policy": rule.get("fallback_policy"),
        "expected_bucket": expected,
        "expected_bucket_matches": expected_matches,
        "raw_payload_hash": canonical_json_hash(official_outcome),
        "replayed_at": replayed_at,
        "audit_note": "Settlement replay is audit support only and is not trading advice.",
    }


def validate_official_observation(*args: Any, **kwargs: Any) -> Any:
    """Compatibility wrapper for official observation quality checks."""
    from .quality import validate_official_observation as _validate_official_observation

    return _validate_official_observation(*args, **kwargs)


def _official_temperature_for_rule(
    outcome: Mapping[str, Any],
    rule: Mapping[str, Any],
) -> tuple[float, str, float | None, float | None, bool]:
    rule_units = str(rule.get("units") or "fahrenheit").lower()
    first = _first_present(outcome, "first_published_high_temperature_f", "first_published_temperature_f")
    corrected = _first_present(outcome, "corrected_high_temperature_f", "corrected_temperature_f")
    if first is None:
        first = _first_present(outcome, "first_published_high_temperature_c", "first_published_temperature_c")
    if corrected is None:
        corrected = _first_present(outcome, "corrected_high_temperature_c", "corrected_temperature_c")
    policy = str(rule.get("correction_policy") or "").lower()
    if corrected is not None and ("correct" in policy or outcome.get("is_corrected")):
        return float(corrected), _units_for_temperature_field(outcome, corrected, default=rule_units), _to_float(first), float(corrected), True

    for field, units in (
        ("high_temperature_f", "fahrenheit"),
        ("temperature_f", "fahrenheit"),
        ("high_temperature_c", "celsius"),
        ("temperature_c", "celsius"),
        ("high_temperature", str(outcome.get("units") or rule_units)),
        ("temperature", str(outcome.get("units") or rule_units)),
    ):
        if outcome.get(field) is not None:
            return float(outcome[field]), units, _to_float(first), _to_float(corrected), False
    raise ValueError("official outcome does not include a temperature value")


def _units_for_temperature_field(outcome: Mapping[str, Any], value: Any, *, default: str) -> str:
    del value
    if any(outcome.get(field) is not None for field in ("corrected_high_temperature_c", "corrected_temperature_c")):
        return "celsius"
    return str(outcome.get("units") or default)


def _first_present(record: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        if field in record and record[field] is not None:
            return record[field]
    return None


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _to_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _rule_version(rule: Mapping[str, Any]) -> str:
    return str(rule.get("updated_at") or rule.get("verified_at") or canonical_json_hash(dict(rule)))


def _target_date_from_rule(rule: Mapping[str, Any]) -> str | None:
    for value in (rule.get("target_date"), rule.get("title"), rule.get("ticker")):
        if not value:
            continue
        match = re.search(r"20\d{2}-\d{2}-\d{2}", str(value))
        if match:
            return match.group(0)
    return None
