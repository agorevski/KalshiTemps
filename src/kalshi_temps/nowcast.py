from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from .weather_features import build_intraday_feature_snapshot

FIXED_LOCAL_SNAPSHOT_HOURS = (7, 9, 11, 12)
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def generate_fixed_nowcast_snapshots(
    observations: Iterable[Mapping[str, Any]],
    *,
    target_date: date | str | None = None,
    cloud_features: Iterable[Mapping[str, Any]] | None = None,
    model_spread: Mapping[str, Any] | None = None,
    local_tz: str = "America/Los_Angeles",
) -> list[dict[str, Any]]:
    """Generate evidence-only nowcast snapshots at 7/9/11/noon local time."""
    tz = ZoneInfo(local_tz)
    obs = list(observations)
    if target_date is None:
        parsed_dates = [_parse_datetime(item.get("observed_at") or item.get("snapshot_at"), tz).astimezone(tz).date() for item in obs]
        if not parsed_dates:
            raise ValueError("target_date is required when observations are empty")
        local_date = max(parsed_dates)
    elif isinstance(target_date, date):
        local_date = target_date
    else:
        local_date = date.fromisoformat(str(target_date))

    snapshots: list[dict[str, Any]] = []
    for hour in FIXED_LOCAL_SNAPSHOT_HOURS:
        snapshot_local = datetime.combine(local_date, time(hour=hour), tzinfo=tz)
        snapshot_at = snapshot_local.isoformat()
        eligible = [item for item in obs if _parse_datetime(item.get("observed_at") or item.get("snapshot_at"), tz) <= snapshot_local]
        eligible = [item for item in eligible if _parse_datetime(item.get("observed_at") or item.get("snapshot_at"), tz).astimezone(tz).date() == local_date]
        if not eligible:
            snapshots.append(_missing_snapshot(snapshot_local))
            continue
        snapshot = build_intraday_feature_snapshot(
            eligible,
            snapshot_at=snapshot_at,
            local_tz=local_tz,
            cloud_features=cloud_features,
            model_spread=model_spread,
        )
        snapshot["feature_type"] = "nowcast_snapshot"
        snapshot["snapshot_hour_local"] = hour
        snapshot["target_date"] = local_date.isoformat()
        snapshots.append(snapshot)
    return snapshots


def build_nowcast_snapshot(
    observations: Iterable[Mapping[str, Any]],
    *,
    snapshot_at: datetime | str | None = None,
    cloud_features: Iterable[Mapping[str, Any]] | None = None,
    model_spread: Mapping[str, Any] | None = None,
    local_tz: str = "America/Los_Angeles",
) -> dict[str, Any]:
    snapshot = build_intraday_feature_snapshot(
        observations,
        snapshot_at=snapshot_at,
        local_tz=local_tz,
        cloud_features=cloud_features,
        model_spread=model_spread,
    )
    snapshot["feature_type"] = "nowcast_snapshot"
    snapshot["target_date"] = snapshot["local_snapshot_time"][:10]
    snapshot["snapshot_hour_local"] = datetime.fromisoformat(snapshot["local_snapshot_time"]).hour
    return snapshot


def _missing_snapshot(snapshot_local: datetime) -> dict[str, Any]:
    return {
        "feature_type": "nowcast_snapshot",
        "snapshot_at": snapshot_local.isoformat(),
        "local_snapshot_time": snapshot_local.isoformat(),
        "target_date": snapshot_local.date().isoformat(),
        "snapshot_hour_local": snapshot_local.hour,
        "data_status": "missing_observations",
        "unresolved": ["missing_observations", "remaining_upside_distribution_unmodeled"],
        "remaining_upside_distribution": {"placeholder": True, "note": "Insufficient nowcast inputs; no trade call."},
    }


def _parse_datetime(value: Any, tz: ZoneInfo) -> datetime:
    if value is None:
        raise ValueError("observation observed_at is required")
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed
