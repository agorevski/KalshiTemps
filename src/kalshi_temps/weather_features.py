from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

_NEGATION_RE = re.compile(
    r"\b(no|not|without|little|lack(?:ing)?|unlikely|isn['’]?t|aren['’]?t|won['’]?t|not expected|not expecting)\b",
    re.IGNORECASE,
)
_POST_NEGATION_RE = re.compile(
    r"\b(is|are|was|were|looks|remain(?:s)?)?\s*(not|unlikely|not expected|not forecast|not anticipated)\b",
    re.IGNORECASE,
)

_REGIME_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "marine_layer": (
        re.compile(r"\bmarine layer\b", re.IGNORECASE),
        re.compile(r"\bmarine push\b", re.IGNORECASE),
        re.compile(r"\bonshore flow\b", re.IGNORECASE),
    ),
    "stratus": (
        re.compile(r"\bstratus\b", re.IGNORECASE),
        re.compile(r"\blow clouds?\b", re.IGNORECASE),
        re.compile(r"\blow stratus\b", re.IGNORECASE),
    ),
    "fog": (
        re.compile(r"\bfog\b|\bfoggy\b", re.IGNORECASE),
        re.compile(r"\bmist\b", re.IGNORECASE),
    ),
    "offshore_flow": (
        re.compile(r"\boffshore flow\b", re.IGNORECASE),
        re.compile(r"\boffshore winds?\b", re.IGNORECASE),
        re.compile(r"\beasterly winds?\b", re.IGNORECASE),
    ),
    "heat": (
        re.compile(r"\bheat(?:wave| advisory| warning)?\b", re.IGNORECASE),
        re.compile(r"\bhot(?:ter)?\b", re.IGNORECASE),
        re.compile(r"\bwell above normal\b", re.IGNORECASE),
        re.compile(r"\b(?:80s|90s|triple digits)\b", re.IGNORECASE),
    ),
    "wind_shift": (
        re.compile(r"\bwind shift\b", re.IGNORECASE),
        re.compile(r"\bshift(?:ing)? winds?\b", re.IGNORECASE),
        re.compile(r"\bturn(?:ing)? (?:onshore|offshore|northerly|southerly|westerly|easterly)\b", re.IGNORECASE),
    ),
    "persistent_cloud": (
        re.compile(r"\bpersistent (?:clouds?|stratus|marine layer)\b", re.IGNORECASE),
        re.compile(r"\bclouds? (?:linger|persist|remain|stubborn)\b", re.IGNORECASE),
        re.compile(r"\bstubborn (?:clouds?|stratus|marine layer)\b", re.IGNORECASE),
    ),
    "low_confidence": (
        re.compile(r"\blow confidence\b", re.IGNORECASE),
        re.compile(r"\buncertain(?:ty)?\b", re.IGNORECASE),
        re.compile(r"\bconfidence (?:is )?(?:low|below average)\b", re.IGNORECASE),
    ),
    "burn_off_timing": (
        re.compile(r"\bburn(?:ing)? off\b", re.IGNORECASE),
        re.compile(r"\bclear(?:ing)? (?:by|before|late|early|around|after|through)\b", re.IGNORECASE),
        re.compile(r"\b(?:by|before|after|around) (?:9|10|11|noon|midday|morning)\b", re.IGNORECASE),
    ),
}


def extract_discussion_features(text: str, *, extracted_at: datetime | str | None = None) -> dict[str, Any]:
    """Extract deterministic weather regime features from NWS discussion text."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("discussion text is required")

    evidence: list[dict[str, str]] = []
    for sentence in _sentences(text):
        for tag, patterns in _REGIME_PATTERNS.items():
            if any(pattern.search(sentence) for pattern in patterns) and not _is_negated(sentence, patterns):
                snippet = _clean_snippet(sentence)
                if not any(item["tag"] == tag and item["snippet"] == snippet for item in evidence):
                    evidence.append(
                        {
                            "tag": tag,
                            "snippet": snippet,
                            "confidence": _tag_confidence(tag, snippet),
                        }
                    )

    regime_tags = sorted({item["tag"] for item in evidence})
    extracted = _datetime_to_iso(_parse_datetime(extracted_at) or datetime.now(LOCAL_TZ))
    return {
        "feature_type": "weather_regime",
        "extracted_at": extracted,
        "regime_tags": regime_tags,
        "evidence": evidence,
        "confidence_label": _overall_confidence(evidence),
        "unresolved": ["satellite_cloud_extraction"],
    }


def build_intraday_feature_snapshot(
    observations: Iterable[Mapping[str, Any]],
    *,
    snapshot_at: datetime | str | None = None,
    local_tz: str = "America/Los_Angeles",
) -> dict[str, Any]:
    """Build an intraday feature snapshot from text/observation fields only."""
    tz = ZoneInfo(local_tz)
    parsed = sorted((_normalize_observation(obs, tz) for obs in observations), key=lambda item: item["_observed_dt"])
    if not parsed:
        raise ValueError("at least one observation is required")

    snapshot_dt = _parse_datetime(snapshot_at) if snapshot_at else parsed[-1]["_observed_dt"]
    if snapshot_dt.tzinfo is None:
        snapshot_dt = snapshot_dt.replace(tzinfo=tz)
    snapshot_local = snapshot_dt.astimezone(tz)
    day_obs = [
        obs
        for obs in parsed
        if obs["_observed_dt"].astimezone(tz).date() == snapshot_local.date()
        and obs["_observed_dt"] <= snapshot_dt
    ]
    if not day_obs:
        raise ValueError("no observations are available for the snapshot date")

    current = day_obs[-1]
    prior = day_obs[-2] if len(day_obs) > 1 else None
    warming_rate = _warming_rate(day_obs, current)
    cloud_trend = _cloud_trend(prior, current)
    cleared = _marine_layer_cleared_before_10am(day_obs, tz)
    source_ids = sorted({obs["source_id"] for obs in day_obs if obs.get("source_id") is not None})

    return {
        "feature_type": "intraday",
        "source_id": source_ids[-1] if len(source_ids) == 1 else None,
        "station": current.get("station"),
        "snapshot_at": _datetime_to_iso(snapshot_dt),
        "local_snapshot_time": snapshot_local.isoformat(),
        "day_of_year": snapshot_local.timetuple().tm_yday,
        "current_temp_f": current.get("temperature_f"),
        "intraday_max_f": max(obs["temperature_f"] for obs in day_obs if obs.get("temperature_f") is not None),
        "warming_rate_f_per_hour": warming_rate,
        "dew_point_f": current.get("dew_point_f"),
        "wind_direction_deg": current.get("wind_direction_deg"),
        "wind_speed_mph": current.get("wind_speed_mph"),
        "pressure_mb": current.get("pressure_mb"),
        "cloud_ceiling_ft": current.get("cloud_ceiling_ft"),
        "cloud_trend": cloud_trend,
        "marine_layer_cleared_before_10am": cleared,
        "unresolved": ["satellite_cloud_extraction"],
    }


def _sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.strip())
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", normalized) if part.strip()]


def _is_negated(sentence: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    for pattern in patterns:
        match = pattern.search(sentence)
        if not match:
            continue
        prefix = sentence[max(0, match.start() - 48) : match.start()]
        suffix = sentence[match.end() : match.end() + 48]
        if _NEGATION_RE.search(prefix) or _POST_NEGATION_RE.search(suffix):
            return True
    return False


def _clean_snippet(sentence: str, *, limit: int = 220) -> str:
    snippet = re.sub(r"\s+", " ", sentence).strip()
    return snippet if len(snippet) <= limit else f"{snippet[: limit - 1].rstrip()}…"


def _tag_confidence(tag: str, snippet: str) -> str:
    strong = {
        "marine_layer": "marine layer",
        "offshore_flow": "offshore flow",
        "low_confidence": "low confidence",
        "burn_off_timing": "burn",
    }
    if strong.get(tag) and strong[tag] in snippet.lower():
        return "high"
    return "medium"


def _overall_confidence(evidence: list[dict[str, str]]) -> str:
    if not evidence:
        return "low"
    if len(evidence) >= 3 or any(item["confidence"] == "high" for item in evidence):
        return "high"
    return "medium"


def _normalize_observation(obs: Mapping[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    observed_at = obs.get("observed_at") or obs.get("snapshot_at")
    if observed_at is None:
        raise ValueError("observation observed_at is required")
    observed_dt = _parse_datetime(observed_at)
    if observed_dt.tzinfo is None:
        observed_dt = observed_dt.replace(tzinfo=tz)
    normalized = dict(obs)
    normalized["_observed_dt"] = observed_dt
    if normalized.get("temperature_f") is None:
        raise ValueError("observation temperature_f is required")
    normalized["temperature_f"] = float(normalized["temperature_f"])
    for key in ("dew_point_f", "wind_speed_mph", "pressure_mb"):
        if normalized.get(key) is not None:
            normalized[key] = float(normalized[key])
    for key in ("source_id", "wind_direction_deg", "cloud_ceiling_ft"):
        if normalized.get(key) is not None:
            normalized[key] = int(normalized[key])
    return normalized


def _warming_rate(day_obs: list[dict[str, Any]], current: dict[str, Any]) -> float | None:
    current_dt = current["_observed_dt"]
    candidates = [
        obs
        for obs in day_obs[:-1]
        if 0 < (current_dt - obs["_observed_dt"]).total_seconds() <= 3 * 3600
        and obs.get("temperature_f") is not None
    ]
    if not candidates:
        return None
    baseline = candidates[0]
    hours = (current_dt - baseline["_observed_dt"]).total_seconds() / 3600
    if hours <= 0:
        return None
    return round((current["temperature_f"] - baseline["temperature_f"]) / hours, 2)


def _cloud_trend(prior: dict[str, Any] | None, current: dict[str, Any]) -> str:
    if prior is None:
        return "unknown"
    previous = prior.get("cloud_ceiling_ft")
    latest = current.get("cloud_ceiling_ft")
    if previous is None and latest is None:
        return "clear_or_unreported"
    if previous is not None and latest is None:
        return "clearing"
    if previous is None and latest is not None:
        return "lowering"
    if latest >= previous + 500:
        return "lifting"
    if latest <= previous - 500:
        return "lowering"
    return "steady"


def _marine_layer_cleared_before_10am(day_obs: list[dict[str, Any]], tz: ZoneInfo) -> bool | None:
    morning = [obs for obs in day_obs if obs["_observed_dt"].astimezone(tz).hour < 10]
    if len(morning) < 2:
        return None
    had_low_cloud = any((obs.get("cloud_ceiling_ft") or 99999) <= 2500 for obs in morning)
    cleared = any(obs.get("cloud_ceiling_ft") is None or (obs.get("cloud_ceiling_ft") or 0) >= 3000 for obs in morning)
    if had_low_cloud:
        return cleared
    return None


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def _datetime_to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)
    return value.replace(microsecond=0).isoformat()
