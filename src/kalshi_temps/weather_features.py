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
    cloud_features: Iterable[Mapping[str, Any]] | None = None,
    model_spread: Mapping[str, Any] | None = None,
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
    cloud_proxy = _latest_cloud_feature(cloud_features, snapshot_dt, tz)
    source_ids = sorted({obs["source_id"] for obs in day_obs if obs.get("source_id") is not None})
    age_minutes = round((snapshot_dt - current["_observed_dt"]).total_seconds() / 60, 1)

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
        "visibility_miles": current.get("visibility_miles"),
        "solar_radiation_wm2": current.get("solar_radiation_wm2"),
        "solar_proxy": _solar_proxy(current, snapshot_local, cloud_proxy),
        "cloud_trend": cloud_trend,
        "ceiling_trend": cloud_trend,
        "wind_shift": _wind_shift(day_obs),
        "marine_push_indicator": _marine_push_indicator(day_obs, current),
        "cloud_feature_id": cloud_proxy.get("id") if cloud_proxy else None,
        "cloud_cover_pct": cloud_proxy.get("cloud_cover_pct") if cloud_proxy else None,
        "stratus_extent_pct": cloud_proxy.get("stratus_extent_pct") if cloud_proxy else None,
        "fog_present": cloud_proxy.get("fog_present") if cloud_proxy else None,
        "burnoff_status": cloud_proxy.get("burnoff_status") if cloud_proxy else None,
        "remaining_solar_window_proxy": _remaining_solar_window_proxy(snapshot_local, cloud_proxy),
        "remaining_upside_distribution": _remaining_upside_placeholder(model_spread),
        "marine_layer_cleared_before_10am": cleared,
        "observation_age_minutes": age_minutes,
        "data_status": "stale" if age_minutes > 90 else "fresh",
        "unresolved": ["remaining_upside_distribution_unmodeled"],
    }


def normalize_cloud_feature(record: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize manual/derived cloud satellite proxy payloads with provenance."""
    _require_record_fields(record, "source", "observed_at")
    cloud_cover = _optional_float(record.get("cloud_cover_pct"))
    stratus_extent = _optional_float(record.get("stratus_extent_pct"))
    confidence = _optional_float(record.get("confidence"))
    fog_present = _optional_bool(record.get("fog_present"))
    normalized = {
        "feature_type": "cloud_satellite_proxy",
        "source": str(record["source"]),
        "observed_at": _datetime_to_iso(_parse_datetime(record["observed_at"]) or datetime.now(LOCAL_TZ)),
        "cloud_cover_pct": _bounded_pct(cloud_cover, "cloud_cover_pct"),
        "stratus_extent_pct": _bounded_pct(stratus_extent, "stratus_extent_pct"),
        "fog_present": fog_present,
        "burnoff_status": record.get("burnoff_status")
        or classify_marine_burnoff(
            cloud_cover_pct=cloud_cover,
            stratus_extent_pct=stratus_extent,
            fog_present=fog_present,
        ),
        "burnoff_time": record.get("burnoff_time"),
        "confidence": _bounded_confidence(confidence),
        "source_url": record.get("source_url"),
        "source_hash": record.get("source_hash") or record.get("hash") or record.get("raw_payload_hash"),
        "notes": record.get("notes"),
    }
    return normalized


def classify_marine_burnoff(
    *,
    cloud_cover_pct: float | None = None,
    stratus_extent_pct: float | None = None,
    fog_present: bool | None = None,
) -> str:
    """Classify marine-layer burnoff from proxy fields without image processing."""
    if cloud_cover_pct is None and stratus_extent_pct is None and fog_present is None:
        return "unknown"
    cloud = 0.0 if cloud_cover_pct is None else float(cloud_cover_pct)
    stratus = 0.0 if stratus_extent_pct is None else float(stratus_extent_pct)
    if fog_present or stratus >= 70 or cloud >= 85:
        return "persistent_marine_layer"
    if stratus <= 20 and cloud <= 35:
        return "burned_off"
    return "partial_burnoff"


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
    for key in ("dew_point_f", "wind_speed_mph", "pressure_mb", "solar_radiation_wm2", "visibility_miles"):
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


def _latest_cloud_feature(
        cloud_features: Iterable[Mapping[str, Any]] | None,
        snapshot_dt: datetime,
        tz: ZoneInfo,
) -> dict[str, Any] | None:
        if not cloud_features:
            return None
        eligible = []
        for feature in cloud_features:
            observed = _parse_datetime(feature.get("observed_at"))
            if observed is None:
                continue
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=tz)
            if observed <= snapshot_dt:
                eligible.append((observed, dict(feature)))
        if not eligible:
            return None
        return sorted(eligible, key=lambda item: item[0])[-1][1]


def _wind_shift(day_obs: list[dict[str, Any]]) -> dict[str, Any]:
        dirs = [obs for obs in day_obs if obs.get("wind_direction_deg") is not None]
        if len(dirs) < 2:
            return {"detected": False, "degrees": None, "from_deg": None, "to_deg": None}
        start = dirs[0]["wind_direction_deg"]
        end = dirs[-1]["wind_direction_deg"]
        diff = abs((end - start + 180) % 360 - 180)
        return {"detected": diff >= 45, "degrees": diff, "from_deg": start, "to_deg": end}


def _marine_push_indicator(day_obs: list[dict[str, Any]], current: dict[str, Any]) -> str:
        direction = current.get("wind_direction_deg")
        speed = current.get("wind_speed_mph") or 0
        ceiling = current.get("cloud_ceiling_ft")
        dew = current.get("dew_point_f")
        temp = current.get("temperature_f")
        onshore = direction is not None and 180 <= direction <= 300 and speed >= 8
        low_cloud = ceiling is not None and ceiling <= 2500
        moist = dew is not None and temp is not None and temp - dew <= 5
        if onshore and (low_cloud or moist):
            return "likely"
        if onshore:
            return "possible"
        if len(day_obs) >= 2 and _wind_shift(day_obs)["detected"] and direction is not None and 180 <= direction <= 300:
            return "possible"
        return "not_indicated"


def _solar_proxy(current: dict[str, Any], snapshot_local: datetime, cloud_proxy: Mapping[str, Any] | None) -> float | None:
        if current.get("solar_radiation_wm2") is not None:
            return current["solar_radiation_wm2"]
        daylight_factor = max(0.0, min(1.0, (18 - snapshot_local.hour) / 11))
        if snapshot_local.hour < 6 or snapshot_local.hour > 18:
            return 0.0
        cloud_cover = cloud_proxy.get("cloud_cover_pct") if cloud_proxy else None
        cloud_factor = 1.0 - ((float(cloud_cover) / 100) if cloud_cover is not None else 0.5)
        return round(900 * daylight_factor * max(0.1, cloud_factor), 1)


def _remaining_solar_window_proxy(snapshot_local: datetime, cloud_proxy: Mapping[str, Any] | None) -> dict[str, Any]:
        hours = max(0.0, 18.0 - (snapshot_local.hour + snapshot_local.minute / 60))
        burnoff = cloud_proxy.get("burnoff_status") if cloud_proxy else None
        multiplier = 0.35 if burnoff == "persistent_marine_layer" else 0.7 if burnoff == "partial_burnoff" else 1.0
        return {"hours_remaining": round(hours, 2), "cloud_adjusted_hours": round(hours * multiplier, 2), "burnoff_status": burnoff}


def _remaining_upside_placeholder(model_spread: Mapping[str, Any] | None) -> dict[str, Any]:
        return {
            "placeholder": True,
            "model_spread_f": model_spread.get("spread_f") if model_spread else None,
            "mean_high_f": model_spread.get("mean_high_f") if model_spread else None,
            "note": "Distribution not modeled yet; uncertainty visible and not a deterministic trade call.",
        }


def _bounded_pct(value: float | None, field: str) -> float | None:
        if value is None:
            return None
        if not 0 <= value <= 100:
            raise ValueError(f"{field} must be between 0 and 100")
        return value


def _bounded_confidence(value: float | None) -> float | None:
        if value is None:
            return None
        if not 0 <= value <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


def _optional_float(value: Any) -> float | None:
        return None if value in (None, "") else float(value)


def _optional_bool(value: Any) -> bool | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _require_record_fields(record: Mapping[str, Any], *fields: str) -> None:
        for field in fields:
            if record.get(field) in (None, ""):
                raise ValueError(f"{field} is required")


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
