from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

SEVERITIES = ("info", "warn", "fail")


@dataclass(frozen=True)
class MonitoringCheck:
    code: str
    severity: str
    message: str
    alert_key: str
    source_name: str | None = None
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "alert_key": self.alert_key,
            "source_name": self.source_name,
            "details": self.details or {},
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def monitoring_day(evaluated_at: str | None = None) -> str:
    if evaluated_at:
        return evaluated_at[:10]
    return datetime.now(timezone.utc).date().isoformat()


def evaluate_monitoring_checks(summary: dict[str, Any], *, high_spread_threshold_f: float = 4.0) -> list[dict[str, Any]]:
    """Evaluate pure local monitoring checks from repository summary dictionaries."""
    checks: list[MonitoringCheck] = []

    freshness = list(summary.get("source_health") or summary.get("source_freshness") or [])
    if not freshness:
        checks.append(
            MonitoringCheck(
                code="missing_sources",
                severity="warn",
                alert_key="missing-sources",
                message="No data sources are recorded; collector/source health cannot be assessed.",
                details={"source_count": 0},
            )
        )
    for source in freshness:
        if source.get("is_stale"):
            name = str(source.get("source_name") or source.get("source") or "unknown")
            checks.append(
                MonitoringCheck(
                    code="stale_source",
                    severity="warn",
                    alert_key=f"stale-source:{name}",
                    source_name=name,
                    message=f"Source {name} is stale ({source.get('label') or 'stale'}).",
                    details=dict(source),
                )
            )

    collector_health = list(summary.get("collector_health") or [])
    for collector in collector_health:
        status = collector.get("status")
        if status == "failed" or collector.get("is_stale"):
            source = str(collector.get("source") or collector.get("source_name") or "unknown")
            name = str(collector.get("collector_name") or "collector")
            code = "collector_failure" if status == "failed" else "stale_collector"
            checks.append(
                MonitoringCheck(
                    code=code,
                    severity="fail" if status == "failed" else "warn",
                    alert_key=f"{code}:{source}:{name}",
                    source_name=source,
                    message=f"Collector {name} for {source} needs attention ({collector.get('label') or status}).",
                    details=dict(collector),
                )
            )

    observations = list(summary.get("latest_observations") or [])
    if not observations:
        checks.append(
            MonitoringCheck(
                code="missing_observations",
                severity="fail",
                alert_key="missing-observations",
                message="No latest observations are available for reporting or nowcast checks.",
                details={"observation_count": 0},
            )
        )

    spread = summary.get("model_spread") or {}
    spread_f = spread.get("spread_f") if isinstance(spread, dict) else None
    if spread_f is None:
        checks.append(
            MonitoringCheck(
                code="missing_model_spread",
                severity="info",
                alert_key="missing-model-spread",
                message="No model spread row is available yet.",
                details={},
            )
        )
    elif float(spread_f) >= high_spread_threshold_f:
        checks.append(
            MonitoringCheck(
                code="high_model_spread",
                severity="warn",
                alert_key=f"high-model-spread:{spread.get('target_date') or 'latest'}",
                message=f"Latest model spread is {float(spread_f):.1f}°F, at or above {high_spread_threshold_f:.1f}°F.",
                details=dict(spread),
            )
        )

    verification = summary.get("market_verification") or {}
    if not verification.get("is_actionable"):
        ticker = verification.get("ticker")
        severity = "fail" if ticker else "warn"
        checks.append(
            MonitoringCheck(
                code="unverified_selected_market" if ticker else "missing_selected_market",
                severity=severity,
                alert_key=f"unverified-market:{ticker or 'none'}",
                source_name=str(ticker) if ticker else None,
                message=verification.get("reason") or "Selected market is not verified/actionable.",
                details=dict(verification),
            )
        )

    paper = summary.get("paper_live_status") or {}
    latest_soak = paper.get("latest_soak_metric") if isinstance(paper, dict) else None
    if isinstance(latest_soak, dict) and latest_soak.get("backup_success") in {0, False}:
        checks.append(
            MonitoringCheck(
                code="backup_failure",
                severity="fail",
                alert_key=f"backup-failure:{paper.get('run_id') or 'latest'}",
                message="Latest paper-live soak metric did not mark backup success.",
                details={"paper_live_status": paper},
            )
        )

    calibration = summary.get("calibration_status") or {}
    if not calibration.get("metric_count"):
        checks.append(
            MonitoringCheck(
                code="calibration_drift_placeholder",
                severity="info",
                alert_key="calibration-drift-placeholder",
                message="Calibration drift monitoring placeholder: no calibration metrics computed yet.",
                details=dict(calibration),
            )
        )

    if not any(check.severity in {"warn", "fail"} for check in checks):
        checks.append(
            MonitoringCheck(
                code="monitoring_ok",
                severity="info",
                alert_key="monitoring-ok",
                message="Monitoring checks completed with no warning or failure alerts.",
                details={"check_count": len(checks)},
            )
        )
    return [check.as_dict() for check in checks]


def daily_report(summary: dict[str, Any], alerts: list[dict[str, Any]], *, report_date: str | None = None) -> dict[str, Any]:
    return {
        "report_date": report_date or monitoring_day(),
        "source_health": summary.get("source_health") or summary.get("source_freshness") or [],
        "selected_market_verification": summary.get("market_verification") or {},
        "latest_observations": summary.get("latest_observations") or [],
        "model_spread": summary.get("model_spread"),
        "nowcast_status": summary.get("nowcast_status") or {},
        "paper_live_status": summary.get("paper_live_status") or {},
        "unresolved_alerts": [alert for alert in alerts if alert.get("status") != "resolved"],
        "caveats": [
            "Local monitoring/reporting only; no external notifications are sent.",
            "Evidence-only dashboard output is not a trade recommendation.",
            "Calibration drift checks are placeholders until enough settled outcomes exist.",
        ],
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    lines = [f"# Kalshi Temps Daily Report - {report['report_date']}", ""]
    lines.extend(["## Source health", ""])
    sources = report.get("source_health") or []
    if sources:
        for source in sources:
            name = source.get("source_name") or source.get("source") or "unknown"
            label = source.get("label") or ("stale" if source.get("is_stale") else "fresh")
            latest = source.get("latest_at") or source.get("newest_observation_at") or source.get("last_finished_at") or "unknown"
            lines.append(f"- {name}: {label} (latest {latest})")
    else:
        lines.append("- No source health records available.")

    verification = report.get("selected_market_verification") or {}
    lines.extend(["", "## Selected market verification", ""])
    lines.append(f"- Ticker: {verification.get('ticker') or 'none'}")
    lines.append(f"- Status: {verification.get('verification_status') or 'not verified'}")
    lines.append(f"- Reason: {verification.get('reason') or 'n/a'}")

    lines.extend(["", "## Latest observations", ""])
    observations = report.get("latest_observations") or []
    if observations:
        for obs in observations[:10]:
            lines.append(f"- {obs.get('station')} {obs.get('observed_at')}: {obs.get('temperature_f')}°F from {obs.get('source_name')}")
    else:
        lines.append("- No observations available.")

    spread = report.get("model_spread") or {}
    lines.extend(["", "## Model spread", ""])
    if spread:
        lines.append(
            f"- {spread.get('target_date')}: {spread.get('spread_f')}°F "
            f"across {spread.get('model_count')} model(s)."
        )
    else:
        lines.append("- No model spread available.")

    lines.extend(["", "## Nowcast and paper-live status", ""])
    lines.append(f"- Nowcast: {json.dumps(report.get('nowcast_status') or {}, sort_keys=True)}")
    lines.append(f"- Paper-live: {json.dumps(report.get('paper_live_status') or {}, sort_keys=True)}")

    lines.extend(["", "## Unresolved alerts", ""])
    alerts = report.get("unresolved_alerts") or []
    if alerts:
        for alert in alerts:
            lines.append(f"- [{alert.get('severity')}] {alert.get('code')}: {alert.get('message')}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Caveats", ""])
    for caveat in report.get("caveats") or []:
        lines.append(f"- {caveat}")
    lines.append("")
    return "\n".join(lines)


def export_daily_report(report: dict[str, Any], output_path: str | Path, *, markdown: bool | None = None) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    as_markdown = markdown if markdown is not None else path.suffix.lower() in {".md", ".markdown"}
    if as_markdown:
        path.write_text(report_to_markdown(report), encoding="utf-8")
    else:
        path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path
