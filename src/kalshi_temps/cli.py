from __future__ import annotations

import argparse
import csv
import json
import sys

from pathlib import Path

from .backfill import run_backfill
from .calibration import export_report_json
from .db import connection
from .db import initialize_database
from .ingest import (
    DEFAULT_AVIATION_WEATHER_METAR_URL_TEMPLATE,
    DEFAULT_NWS_SEW_DISCUSSION_URL,
    DEFAULT_NWS_OBSERVATION_URL_TEMPLATE,
    TextFetcher,
    collect_forecast_discussion,
    collect_metar_observation,
    collect_model_high_records,
    collect_nws_station_observation,
    load_model_high_records,
    load_station_metadata,
    parse_climate_daily_summary_records,
    run_forecast_discussion_collector,
    run_metar_collector,
)
from .ops import backup_path, ops_status
from .paper_live import (
    close_run as close_paper_live_run,
    list_runs as list_paper_live_runs,
    record_checklist as record_paper_live_checklist,
    record_postmortem as record_paper_live_postmortem,
    record_prediction_note as record_paper_live_prediction_note,
    record_soak_metric as record_paper_live_soak_metric,
    start_run as start_paper_live_run,
)
from .repository import WeatherRepository
from .seed import seed_demo_data
from .nowcast import generate_fixed_nowcast_snapshots
from .weather_features import extract_discussion_features, normalize_cloud_feature


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the local Kalshi Temps SQLite dashboard.")
    parser.add_argument("--db", help="SQLite database path. Defaults to KALSHI_TEMPS_DB or data/kalshi_temps.sqlite3")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init-db", help="Create or migrate the SQLite database")
    init_parser.add_argument("--seed", action="store_true", help="Insert demo Seattle observations after initialization")

    subparsers.add_parser("seed-demo", help="Initialize the database and insert demo observations")

    nws_parser = subparsers.add_parser("collect-nws-discussion", help="Collect public NWS Seattle forecast discussion")
    nws_parser.add_argument("--url", default=DEFAULT_NWS_SEW_DISCUSSION_URL, help="Text forecast discussion URL")
    nws_parser.add_argument("--source-name", default="NWS Seattle Forecast Discussion", help="SQLite source name")
    nws_parser.add_argument("--timeout", type=float, default=10, help="Collector request timeout in seconds")
    nws_parser.add_argument("--max-attempts", type=int, default=1, help="Retry-ready attempt count; no daemon is started")

    metar_parser = subparsers.add_parser("collect-metar", help="Collect public Aviation Weather METAR observation")
    metar_parser.add_argument("--station", default="KSEA", help="METAR station id")
    metar_parser.add_argument(
        "--url",
        help=(
            "Raw METAR URL. Defaults to "
            f"{DEFAULT_AVIATION_WEATHER_METAR_URL_TEMPLATE.replace('{station}', '<station>')}"
        ),
    )
    metar_parser.add_argument("--source-name", default="Aviation Weather METAR", help="SQLite source name")
    metar_parser.add_argument("--timeout", type=float, default=10, help="Collector request timeout in seconds")
    metar_parser.add_argument("--max-attempts", type=int, default=1, help="Retry-ready attempt count; no daemon is started")

    nws_obs_parser = subparsers.add_parser("collect-nws-observation", help="Collect public api.weather.gov station observation")
    nws_obs_parser.add_argument("--station", default="KSEA", help="NOAA/NWS station id")
    nws_obs_parser.add_argument(
        "--url",
        help=f"NWS observation URL. Defaults to {DEFAULT_NWS_OBSERVATION_URL_TEMPLATE.replace('{station}', '<station>')}",
    )
    nws_obs_parser.add_argument("--source-name", default="NOAA/NWS Station Observation", help="SQLite source name")

    import_stations = subparsers.add_parser("import-stations", help="Import station metadata from JSON or CSV")
    import_stations.add_argument("file", help="Station metadata fixture file")

    list_stations = subparsers.add_parser("list-stations", help="List imported station metadata")
    list_stations.add_argument("--network", help="Optional network filter, e.g. ASOS or AWOS")
    list_stations.add_argument("--limit", type=int, default=100)

    import_daily = subparsers.add_parser(
        "import-climate-daily-summaries",
        help="Import public climate daily-summary JSON/CSV fixtures as official outcomes",
    )
    import_daily.add_argument("file", help="Climate daily-summary fixture file")

    list_official_obs = subparsers.add_parser("list-official-observations", help="List persisted official observations")
    list_official_obs.add_argument("--limit", type=int, default=50)

    run_parser = subparsers.add_parser("run-collectors", help="Run NWS and METAR collectors once with poll records")
    run_parser.add_argument("--nws-url", default=DEFAULT_NWS_SEW_DISCUSSION_URL, help="Text forecast discussion URL")
    run_parser.add_argument("--metar-station", default="KSEA", help="METAR station id")
    run_parser.add_argument("--metar-url", help="Raw METAR URL")
    run_parser.add_argument("--timeout", type=float, default=10, help="Collector request timeout in seconds")
    run_parser.add_argument("--max-attempts", type=int, default=1, help="Retry-ready attempt count; no daemon is started")

    runs_parser = subparsers.add_parser("collector-runs", help="List persisted collector poll runs")
    runs_parser.add_argument("--limit", type=int, default=20, help="Maximum runs to print")

    health_parser = subparsers.add_parser("collector-health", help="Summarize collector freshness and failures")
    health_parser.add_argument("--max-age-minutes", type=float, default=180, help="Freshness threshold in minutes")

    import_models = subparsers.add_parser(
        "import-model-highs",
        help="Import manual HRRR/NAM/GFS/NBM-style model-high records from JSON or CSV",
    )
    import_models.add_argument("file", help="JSON or CSV file of model-high records")

    import_forecasts = subparsers.add_parser(
        "import-model-forecasts",
        help="Import supported HRRR/NAM/GFS/NBM-style model forecast records from JSON or CSV",
    )
    import_forecasts.add_argument("file", help="JSON or CSV file of model forecast records")

    fetch_forecasts = subparsers.add_parser(
        "fetch-model-forecasts",
        help="Fetch supported JSON/CSV model forecast payloads from a URL and import them; no live API contract is implied",
    )
    fetch_forecasts.add_argument("url", help="URL returning a supported JSON or CSV payload")
    fetch_forecasts.add_argument("--timeout", type=float, default=10, help="Fetcher request timeout in seconds")

    spread_parser = subparsers.add_parser("list-model-spread", help="List persisted model spread rows")
    spread_parser.add_argument("--target-date", help="Filter spread rows to one ISO target date")
    spread_parser.add_argument("--limit", type=int, default=10, help="Maximum spread rows to print")

    deltas_parser = subparsers.add_parser("list-model-deltas", help="List persisted run-to-run model deltas")
    deltas_parser.add_argument("--target-date", help="Filter delta rows to one ISO target date")
    deltas_parser.add_argument("--limit", type=int, default=20, help="Maximum delta rows to print")

    features_parser = subparsers.add_parser(
        "extract-weather-features",
        help="Extract deterministic regime features from latest discussion or a text file",
    )
    features_parser.add_argument("--file", help="Forecast discussion text file. Defaults to latest saved discussion.")

    import_cloud_parser = subparsers.add_parser(
        "import-cloud-features",
        help="Import manual/derived cloud satellite proxy records from JSON or CSV",
    )
    import_cloud_parser.add_argument("file", help="JSON or CSV cloud feature records")

    list_cloud_parser = subparsers.add_parser("list-cloud-features", help="List cloud satellite proxy records")
    list_cloud_parser.add_argument("--limit", type=int, default=20)

    nowcast_parser = subparsers.add_parser(
        "generate-nowcast-snapshots",
        help="Generate fixed 7/9/11/noon evidence-only nowcast snapshots from stored observations",
    )
    nowcast_parser.add_argument("--target-date", help="Local target date YYYY-MM-DD; defaults to latest observation date")
    nowcast_parser.add_argument("--limit-observations", type=int, default=100)

    list_nowcast_parser = subparsers.add_parser("list-nowcast-snapshots", help="List persisted nowcast snapshots")
    list_nowcast_parser.add_argument("--target-date")
    list_nowcast_parser.add_argument("--limit", type=int, default=20)

    ops_parser = subparsers.add_parser("ops-status", help="Print local database, disk, and access posture status")
    ops_parser.add_argument("--host", default="127.0.0.1", help="Intended app bind host for access posture guidance")
    ops_parser.add_argument("--port", default=8000, type=int, help="Intended app port for access posture guidance")

    backup_parser = subparsers.add_parser("backup-path", help="Print the next timestamped SQLite backup path")
    backup_parser.add_argument("--backup-dir", default="data/backups", help="Directory where backups are stored")

    add_rule_parser = subparsers.add_parser("add-market-rule", help="Add or update explicit market rule metadata")
    _add_market_rule_arguments(add_rule_parser)
    add_rule_parser.add_argument("--json", dest="json_path", help="JSON file containing market rule fields")

    verify_rule_parser = subparsers.add_parser("verify-market-rule", help="Mark a complete market rule as verified")
    verify_rule_parser.add_argument("ticker", help="Market ticker to verify")
    verify_rule_parser.add_argument("--verified-by", required=True, help="Person or process that verified the rule")
    verify_rule_parser.add_argument("--verified-at", help="ISO-8601 verification timestamp; defaults to now")
    verify_rule_parser.add_argument("--notes", help="Optional verification notes")

    list_rules_parser = subparsers.add_parser("list-market-rules", help="List stored market rule verification records")
    list_rules_parser.add_argument("--limit", type=int, default=50, help="Maximum number of rules to list")

    outcome_parser = subparsers.add_parser("record-official-outcome", help="Record an official daily high outcome")
    outcome_parser.add_argument("--station", default="KSEA", help="Official station id")
    outcome_parser.add_argument("--target-date", required=True, help="ISO target date, e.g. 2026-07-14")
    outcome_parser.add_argument("--high-temperature-f", required=True, type=float, help="Official high temperature")
    outcome_parser.add_argument("--source-name", default="manual", help="Outcome source name")
    outcome_parser.add_argument("--observed-at", help="Optional ISO observation timestamp")
    outcome_parser.add_argument("--notes", help="Optional notes")

    replay_parser = subparsers.add_parser("replay-settlement", help="Replay an official outcome against a verified market rule")
    replay_parser.add_argument("ticker", help="Market ticker with stored market rule metadata")
    replay_parser.add_argument("--target-date", help="ISO target date for a stored or explicit outcome")
    replay_parser.add_argument("--outcome-json", help="Inline JSON official outcome object")
    replay_parser.add_argument("--outcome-file", help="JSON file containing an official outcome object")
    replay_parser.add_argument("--no-persist", action="store_true", help="Replay without saving settlement_replays")
    replay_parser.add_argument("--json", action="store_true", help="Print the full replay JSON")

    prediction_parser = subparsers.add_parser("record-prediction-snapshot", help="Record a manual prediction snapshot")
    prediction_parser.add_argument("--model-name", required=True)
    prediction_parser.add_argument("--station", default="KSEA")
    prediction_parser.add_argument("--target-date", required=True)
    prediction_parser.add_argument("--snapshot-at")
    prediction_parser.add_argument("--regime")
    prediction_parser.add_argument("--predicted-high-f", type=float)
    prediction_parser.add_argument("--temperature-bucket")
    prediction_parser.add_argument("--probability", type=float)
    prediction_parser.add_argument("--hypothesis")
    prediction_parser.add_argument("--source-name")
    prediction_parser.add_argument("--notes")

    calibration_parser = subparsers.add_parser(
        "compute-calibration",
        help="Compute historical bias and bucket calibration metrics from stored local snapshots",
    )
    calibration_parser.add_argument("--bins", type=int, default=10, help="Reliability bin count")
    calibration_parser.add_argument("--export", help="Optional JSON path for a full calibration report")
    calibration_parser.add_argument("--split-date", help="Optional test split date for leakage-safe validation")
    calibration_parser.add_argument("--gap-days", type=int, default=0, help="Gap days to withhold before split date")

    backfill_parser = subparsers.add_parser("run-backfill", help="Replay frozen JSON/CSV fixture bundle into SQLite")
    backfill_parser.add_argument("source", help="Fixture directory or JSON/CSV fixture file")

    report_parser = subparsers.add_parser("calibration-report", help="Compute and export calibration report JSON")
    report_parser.add_argument("--bins", type=int, default=10, help="Reliability bin count")
    report_parser.add_argument("--output", "--export", required=True, help="JSON output path")
    report_parser.add_argument("--split-date", help="Optional test split date for leakage-safe validation")
    report_parser.add_argument("--gap-days", type=int, default=0, help="Gap days to withhold before split date")

    start_paper_parser = subparsers.add_parser("start-paper-live-run", help="Start an evidence-only paper-live run")
    start_paper_parser.add_argument("--name", required=True, help="Human-readable run name")
    start_paper_parser.add_argument("--station", default="KSEA", help="Station under review")
    start_paper_parser.add_argument("--target-date", help="Optional ISO target date")
    start_paper_parser.add_argument("--notes", help="Optional run notes")

    list_paper_parser = subparsers.add_parser("list-paper-live-runs", help="List paper-live runs")
    list_paper_parser.add_argument("--include-closed", action="store_true", help="Include closed runs")
    list_paper_parser.add_argument("--limit", type=int, default=20, help="Maximum runs to print")

    close_paper_parser = subparsers.add_parser("close-paper-live-run", help="Close a paper-live run")
    close_paper_parser.add_argument("run_id", type=int)
    close_paper_parser.add_argument("--notes", help="Closure or postmortem summary")

    checklist_parser = subparsers.add_parser("record-paper-live-checklist", help="Record a paper-live checklist entry")
    checklist_parser.add_argument("run_id", type=int)
    checklist_parser.add_argument("--item", required=True)
    checklist_parser.add_argument("--status", default="pending", choices=("pending", "done", "blocked"))
    checklist_parser.add_argument("--checklist-date")
    checklist_parser.add_argument("--notes")

    prediction_note_parser = subparsers.add_parser(
        "record-paper-live-prediction-note",
        help="Record a paper-live prediction note without placing trades",
    )
    prediction_note_parser.add_argument("run_id", type=int)
    prediction_note_parser.add_argument("--note", required=True)
    prediction_note_parser.add_argument("--target-date")
    prediction_note_parser.add_argument("--predicted-high-f", type=float)
    prediction_note_parser.add_argument("--probability-bucket")
    prediction_note_parser.add_argument("--confidence", type=float)

    postmortem_parser = subparsers.add_parser("record-paper-live-postmortem", help="Record postmortem/reconciliation notes")
    postmortem_parser.add_argument("run_id", type=int)
    postmortem_parser.add_argument("--note", required=True)
    postmortem_parser.add_argument("--note-type", default="postmortem", choices=("postmortem", "reconciliation"))
    postmortem_parser.add_argument("--target-date")

    soak_parser = subparsers.add_parser("record-paper-live-soak-metric", help="Record paper-live soak metrics")
    soak_parser.add_argument("run_id", type=int)
    soak_parser.add_argument("--uptime-status", default="not-measured")
    soak_parser.add_argument("--collector-success-count", type=int, default=0)
    soak_parser.add_argument("--collector-failure-count", type=int, default=0)
    soak_parser.add_argument("--backup-success", action="store_true")
    soak_parser.add_argument("--alert-count", type=int, default=0)
    soak_parser.add_argument("--notes")
    return parser


def collect_and_save_forecast_discussion(
    db_path: str | None,
    *,
    url: str = DEFAULT_NWS_SEW_DISCUSSION_URL,
    source_name: str = "NWS Seattle Forecast Discussion",
    fetcher: TextFetcher | None = None,
    timeout: float = 10,
    max_attempts: int = 1,
) -> dict[str, object]:
    initialize_database(db_path)
    result = run_forecast_discussion_collector(
        source=source_name,
        url=url,
        fetcher=fetcher,
        timeout=timeout,
        max_attempts=max_attempts,
    )
    error_message = None
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        repo.record_collector_run(result.poll_record())
        if not result.succeeded:
            error_message = result.error_message or "NWS discussion collector failed"
            saved = None
        else:
            saved = repo.save_forecast_discussion(source_name, result.records[0])
    if error_message:
        raise RuntimeError(error_message)
    assert saved is not None
    return saved


def collect_and_save_metar(
    db_path: str | None,
    *,
    station: str = "KSEA",
    url: str | None = None,
    source_name: str = "Aviation Weather METAR",
    fetcher: TextFetcher | None = None,
    timeout: float = 10,
    max_attempts: int = 1,
) -> dict[str, object]:
    initialize_database(db_path)
    result = run_metar_collector(
        source=source_name,
        station=station,
        url=url,
        fetcher=fetcher,
        timeout=timeout,
        max_attempts=max_attempts,
    )
    error_message = None
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        repo.record_collector_run(result.poll_record())
        if not result.succeeded:
            error_message = result.error_message or "METAR collector failed"
            saved = None
        else:
            saved = repo.save_observation_record(source_name, result.records[0])
    if error_message:
        raise RuntimeError(error_message)
    assert saved is not None
    return saved


def import_and_save_model_highs(db_path: str | None, *, file_path: str) -> dict[str, object]:
    initialize_database(db_path)
    records = load_model_high_records(file_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).import_model_high_records(records)


def fetch_and_save_model_highs(
    db_path: str | None,
    *,
    url: str,
    fetcher: TextFetcher | None = None,
    timeout: float = 10,
) -> dict[str, object]:
    initialize_database(db_path)
    records = collect_model_high_records(url, fetcher=fetcher, timeout=timeout)
    with connection(db_path) as conn:
        return WeatherRepository(conn).import_model_high_records(records)


def import_and_save_stations(db_path: str | None, *, file_path: str) -> dict[str, object]:
    initialize_database(db_path)
    records = load_station_metadata(file_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).import_station_metadata(records)


def collect_and_save_nws_observation(
    db_path: str | None,
    *,
    station: str = "KSEA",
    url: str | None = None,
    source_name: str = "NOAA/NWS Station Observation",
    fetcher: TextFetcher | None = None,
) -> dict[str, object]:
    if fetcher is None:
        from .ingest import fetch_text

        fetcher = fetch_text
    initialize_database(db_path)
    record = collect_nws_station_observation(station, url=url, fetcher=fetcher)
    with connection(db_path) as conn:
        return WeatherRepository(conn).save_official_observation_record(source_name, record)


def import_and_save_climate_daily_summaries(db_path: str | None, *, file_path: str) -> dict[str, object]:
    initialize_database(db_path)
    text = Path(file_path).read_text(encoding="utf-8")
    records = parse_climate_daily_summary_records(text)
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        saved = [
            repo.save_official_outcome(
                station=record["station"],
                target_date=record["target_date"],
                high_temperature_f=record["high_temperature_f"],
                source_name=record.get("source_name") or "NOAA daily summary",
                observed_at=record.get("observed_at"),
                notes="Imported public climate daily-summary fixture.",
                raw_payload=record,
            )
            for record in records
        ]
    return {"imported_count": len(saved), "official_outcomes": saved}


def extract_and_save_weather_features(db_path: str | None, *, text_file: str | None = None) -> dict[str, object]:
    initialize_database(db_path)
    discussion: dict[str, object] | None = None
    if text_file:
        text = Path(text_file).read_text(encoding="utf-8")
    else:
        with connection(db_path) as conn:
            discussion = WeatherRepository(conn).latest_forecast_discussion()
        if discussion is None:
            raise RuntimeError("No forecast discussion found; pass --file or collect one first.")
        text = str(discussion["text"])

    features = extract_discussion_features(text)
    if discussion:
        features.update(
            {
                "forecast_discussion_id": discussion["id"],
                "source_id": discussion.get("source_id"),
                "product_id": discussion.get("product_id"),
                "issued_at": discussion.get("issued_at"),
            }
        )

    with connection(db_path) as conn:
        return WeatherRepository(conn).save_weather_regime_features(features)


def import_and_save_cloud_features(db_path: str | None, *, file_path: str) -> dict[str, object]:
    initialize_database(db_path)
    records = _load_records_file(file_path)
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        saved = [repo.save_cloud_feature(normalize_cloud_feature(record)) for record in records]
    return {"imported_count": len(saved), "cloud_features": saved}


def generate_and_save_nowcast_snapshots(
    db_path: str | None,
    *,
    target_date: str | None = None,
    limit_observations: int = 100,
) -> dict[str, object]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        observations = repo.list_observations(limit=limit_observations)
        cloud_features = repo.list_cloud_features(limit=20)
        model_spread = repo.latest_model_spread(target_date)
        snapshots = generate_fixed_nowcast_snapshots(
            observations,
            target_date=target_date,
            cloud_features=cloud_features,
            model_spread=model_spread,
        )
        saved = [repo.save_nowcast_snapshot(snapshot) for snapshot in snapshots]
    return {"saved_count": len(saved), "nowcast_snapshots": saved}


def add_or_update_market_rule(db_path: str | None, record: dict[str, object]) -> dict[str, object]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).upsert_market_rule(record)


def verify_market_rule(
    db_path: str | None,
    *,
    ticker: str,
    verified_by: str,
    verified_at: str | None = None,
    notes: str | None = None,
) -> dict[str, object]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).verify_market_rule(
            ticker,
            verified_by=verified_by,
            verified_at=verified_at,
            notes=notes,
        )


def record_official_outcome(
    db_path: str | None,
    *,
    station: str,
    target_date: str,
    high_temperature_f: float,
    source_name: str = "manual",
    observed_at: str | None = None,
    notes: str | None = None,
) -> dict[str, object]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).save_official_outcome(
            station=station,
            target_date=target_date,
            high_temperature_f=high_temperature_f,
            source_name=source_name,
            observed_at=observed_at,
            notes=notes,
        )


def record_prediction_snapshot(db_path: str | None, record: dict[str, object]) -> dict[str, object]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        return WeatherRepository(conn).save_prediction_snapshot(record)


def compute_calibration(
    db_path: str | None,
    *,
    bins: int = 10,
    export_path: str | None = None,
    split_date: str | None = None,
    gap_days: int = 0,
) -> dict[str, object]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        bias = repo.compute_bias_summaries()
        metrics = repo.compute_calibration_metrics(bin_count=bins)
        report = repo.calibration_report(bin_count=bins, split_date=split_date, gap_days=gap_days)
    if export_path:
        export_report_json(report, export_path)
    return {"bias_summaries": bias, "calibration_metrics": metrics, "report": report}


def compute_and_export_calibration_report(
    db_path: str | None,
    *,
    output_path: str,
    bins: int = 10,
    split_date: str | None = None,
    gap_days: int = 0,
) -> dict[str, object]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        report = WeatherRepository(conn).calibration_report(bin_count=bins, split_date=split_date, gap_days=gap_days)
    export_report_json(report, output_path)
    return report


def replay_settlement_command(
    db_path: str | None,
    *,
    ticker: str,
    target_date: str | None = None,
    outcome_json: str | None = None,
    outcome_file: str | None = None,
    persist: bool = True,
) -> dict[str, object]:
    initialize_database(db_path)
    outcome = _load_outcome_argument(outcome_json=outcome_json, outcome_file=outcome_file)
    with connection(db_path) as conn:
        return WeatherRepository(conn).replay_settlement(
            ticker=ticker,
            official_outcome=outcome,
            target_date=target_date,
            persist=persist,
        )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "init-db"):
        db_path = initialize_database(args.db)
        if getattr(args, "seed", False):
            seed_demo_data(str(db_path))
        print(f"Initialized database: {db_path}")
        return 0

    if args.command == "seed-demo":
        seed_demo_data(args.db)
        print("Seeded demo observations")
        return 0

    if args.command == "collect-nws-discussion":
        try:
            saved = collect_and_save_forecast_discussion(args.db, url=args.url, source_name=args.source_name)
        except RuntimeError as exc:
            print(f"NWS discussion collector failed: {exc}", file=sys.stderr)
            return 1
        print(f"Collected forecast discussion {saved['product_id']} at {saved['ingest_at']}")
        return 0

    if args.command == "collect-metar":
        try:
            saved = collect_and_save_metar(args.db, station=args.station, url=args.url, source_name=args.source_name)
        except RuntimeError as exc:
            print(f"METAR collector failed: {exc}", file=sys.stderr)
            return 1
        print(f"Collected METAR {saved['station']} at {saved['observed_at']}")
        return 0

    if args.command == "collect-nws-observation":
        try:
            saved = collect_and_save_nws_observation(args.db, station=args.station, url=args.url, source_name=args.source_name)
        except Exception as exc:  # noqa: BLE001 - CLI reports collector failure.
            print(f"NWS observation collector failed: {exc}", file=sys.stderr)
            return 1
        print(f"Collected NWS observation {saved['station']} at {saved['observed_at']} ({saved['qc_status']})")
        return 0

    if args.command == "import-stations":
        summary = import_and_save_stations(args.db, file_path=args.file)
        print(f"Imported {summary['imported_count']} station metadata record(s)")
        return 0

    if args.command == "list-stations":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).list_station_metadata(network=args.network, limit=args.limit)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command == "import-climate-daily-summaries":
        summary = import_and_save_climate_daily_summaries(args.db, file_path=args.file)
        print(f"Imported {summary['imported_count']} climate daily summary record(s)")
        return 0

    if args.command == "list-official-observations":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).list_official_observations(limit=args.limit)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command == "run-collectors":
        initialize_database(args.db)
        results = [
            run_forecast_discussion_collector(
                url=args.nws_url,
                timeout=args.timeout,
                max_attempts=args.max_attempts,
            ),
            run_metar_collector(
                station=args.metar_station,
                url=args.metar_url,
                timeout=args.timeout,
                max_attempts=args.max_attempts,
            ),
        ]
        with connection(args.db) as conn:
            repo = WeatherRepository(conn)
            for result in results:
                repo.record_collector_run(result.poll_record())
                if result.succeeded and result.collector_name == "nws_discussion":
                    repo.save_forecast_discussion(result.source, result.records[0])
                elif result.succeeded and result.collector_name == "metar":
                    repo.save_observation_record(result.source, result.records[0])
        for result in results:
            print(f"{result.collector_name}\t{result.status}\t{result.records_returned}\t{result.error_message or ''}")
        return 0 if all(result.succeeded for result in results) else 1

    if args.command == "collector-runs":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).list_collector_runs(limit=args.limit)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command == "collector-health":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).collector_health_summaries(max_age_minutes=args.max_age_minutes)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command in {"import-model-highs", "import-model-forecasts"}:
        summary = import_and_save_model_highs(args.db, file_path=args.file)
        label = "model-high records" if args.command == "import-model-highs" else "model forecast record(s)"
        print(
            f"Imported {summary['imported_count']} {label}; "
            f"updated {len(summary['model_spreads'])} spread row(s)"
        )
        return 0

    if args.command == "fetch-model-forecasts":
        summary = fetch_and_save_model_highs(args.db, url=args.url, timeout=args.timeout)
        print(
            f"Fetched and imported {summary['imported_count']} model forecast record(s); "
            "supported payload adapter only, not a live model API implementation"
        )
        return 0

    if args.command == "list-model-spread":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).list_model_spread(limit=args.limit, target_date=args.target_date)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command == "list-model-deltas":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).list_model_run_deltas(limit=args.limit, target_date=args.target_date)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command == "extract-weather-features":
        try:
            saved = extract_and_save_weather_features(args.db, text_file=args.file)
        except RuntimeError as exc:
            print(f"Weather feature extraction failed: {exc}", file=sys.stderr)
            return 1
        tags = ", ".join(saved["regime_tags"]) if saved["regime_tags"] else "none"
        print(f"Extracted weather features ({saved['confidence_label']}): {tags}")
        return 0

    if args.command == "import-cloud-features":
        summary = import_and_save_cloud_features(args.db, file_path=args.file)
        print(f"Imported {summary['imported_count']} cloud feature record(s); proxy evidence only.")
        return 0

    if args.command == "list-cloud-features":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).list_cloud_features(limit=args.limit)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command == "generate-nowcast-snapshots":
        try:
            summary = generate_and_save_nowcast_snapshots(
                args.db,
                target_date=args.target_date,
                limit_observations=args.limit_observations,
            )
        except ValueError as exc:
            print(f"Nowcast snapshot generation failed: {exc}", file=sys.stderr)
            return 1
        print(f"Saved {summary['saved_count']} nowcast snapshot(s); uncertainty remains visible.")
        return 0

    if args.command == "list-nowcast-snapshots":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).list_nowcast_snapshots(limit=args.limit, target_date=args.target_date)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command == "ops-status":
        print(json.dumps(ops_status(args.db, host=args.host, port=args.port), indent=2, sort_keys=True))
        return 0

    if args.command == "backup-path":
        print(backup_path(args.db, args.backup_dir))
        return 0

    if args.command == "add-market-rule":
        saved = add_or_update_market_rule(args.db, _market_rule_record_from_args(args))
        print(f"Saved market rule {saved['ticker']} ({saved['verification_status']}); verification is not a trade recommendation.")
        return 0

    if args.command == "verify-market-rule":
        saved = verify_market_rule(
            args.db,
            ticker=args.ticker,
            verified_by=args.verified_by,
            verified_at=args.verified_at,
            notes=args.notes,
        )
        print(f"Verified market rule {saved['ticker']}; verification is not a trade recommendation.")
        return 0

    if args.command == "list-market-rules":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).list_market_rules(limit=args.limit)
        for row in rows:
            print(f"{row['ticker']}\t{row['verification_status']}\t{row['official_source_name']}\t{row['source_url']}")
        return 0

    if args.command == "record-official-outcome":
        saved = record_official_outcome(
            args.db,
            station=args.station,
            target_date=args.target_date,
            high_temperature_f=args.high_temperature_f,
            source_name=args.source_name,
            observed_at=args.observed_at,
            notes=args.notes,
        )
        print(f"Recorded official outcome {saved['station']} {saved['target_date']}: {saved['high_temperature_f']}°F")
        return 0

    if args.command == "replay-settlement":
        try:
            result = replay_settlement_command(
                args.db,
                ticker=args.ticker,
                target_date=args.target_date,
                outcome_json=args.outcome_json,
                outcome_file=args.outcome_file,
                persist=not args.no_persist,
            )
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            print(f"Settlement replay failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            printable = _decode_replay_row(result)
            print(json.dumps(printable, indent=2, sort_keys=True))
        else:
            raw_reasons = result.get("mismatch_reasons", [])
            reasons_list = json.loads(raw_reasons) if isinstance(raw_reasons, str) else raw_reasons
            reasons = ", ".join(str(reason) for reason in reasons_list)
            print(
                f"Settlement replay {result['ticker']} {result['target_date']}: "
                f"{result['status']} ({result.get('settlement_bucket')}); audit support only, not trading advice."
                + (f" Reasons: {reasons}" if reasons else "")
            )
        return 0

    if args.command == "record-prediction-snapshot":
        saved = record_prediction_snapshot(
            args.db,
            {
                "model_name": args.model_name,
                "station": args.station,
                "target_date": args.target_date,
                "snapshot_at": args.snapshot_at,
                "regime": args.regime,
                "predicted_high_f": args.predicted_high_f,
                "temperature_bucket": args.temperature_bucket,
                "probability": args.probability,
                "hypothesis": args.hypothesis,
                "source_name": args.source_name,
                "notes": args.notes,
            },
        )
        print(f"Recorded prediction snapshot {saved['model_name']} for {saved['station']} {saved['target_date']}")
        return 0

    if args.command == "compute-calibration":
        result = compute_calibration(
            args.db,
            bins=args.bins,
            export_path=args.export,
            split_date=args.split_date,
            gap_days=args.gap_days,
        )
        print(
            "Computed "
            f"{len(result['bias_summaries'])} bias summaries and "
            f"{len(result['calibration_metrics'])} calibration metrics"
        )
        if args.export:
            print(f"Exported calibration report to {args.export}")
        return 0

    if args.command == "run-backfill":
        result = run_backfill(args.db, args.source)
        print(
            f"Backfill {result['status']} from {result['source_path']}: "
            f"{json.dumps(result['counts'], sort_keys=True)}"
        )
        if result["errors"]:
            print(json.dumps(result["errors"], indent=2, sort_keys=True), file=sys.stderr)
        return 0 if result["status"] in {"success", "partial_failure"} else 1

    if args.command == "calibration-report":
        report = compute_and_export_calibration_report(
            args.db,
            output_path=args.output,
            bins=args.bins,
            split_date=args.split_date,
            gap_days=args.gap_days,
        )
        print(f"Exported calibration report to {args.output} ({report['sample_sizes']['prediction_count']} predictions)")
        return 0

    if args.command == "start-paper-live-run":
        saved = start_paper_live_run(
            args.db,
            run_name=args.name,
            station=args.station,
            target_date=args.target_date,
            notes=args.notes,
        )
        print(f"Started paper-live run {saved['id']}: {saved['run_name']} (no automated betting)")
        return 0

    if args.command == "list-paper-live-runs":
        rows = list_paper_live_runs(args.db, include_closed=args.include_closed, limit=args.limit)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command == "close-paper-live-run":
        saved = close_paper_live_run(args.db, run_id=args.run_id, notes=args.notes)
        print(f"Closed paper-live run {saved['id']}: {saved['run_name']}")
        return 0

    if args.command == "record-paper-live-checklist":
        saved = record_paper_live_checklist(
            args.db,
            run_id=args.run_id,
            item=args.item,
            status=args.status,
            checklist_date=args.checklist_date,
            notes=args.notes,
        )
        print(f"Recorded checklist entry {saved['id']} for paper-live run {saved['run_id']}")
        return 0

    if args.command == "record-paper-live-prediction-note":
        saved = record_paper_live_prediction_note(
            args.db,
            run_id=args.run_id,
            record={
                "note": args.note,
                "target_date": args.target_date,
                "predicted_high_f": args.predicted_high_f,
                "probability_bucket": args.probability_bucket,
                "confidence": args.confidence,
            },
        )
        print(f"Recorded prediction note {saved['id']} for paper-live run {saved['run_id']} (no trade placed)")
        return 0

    if args.command == "record-paper-live-postmortem":
        saved = record_paper_live_postmortem(
            args.db,
            run_id=args.run_id,
            note=args.note,
            note_type=args.note_type,
            target_date=args.target_date,
        )
        print(f"Recorded {saved['note_type']} note {saved['id']} for paper-live run {saved['run_id']}")
        return 0

    if args.command == "record-paper-live-soak-metric":
        saved = record_paper_live_soak_metric(
            args.db,
            run_id=args.run_id,
            record={
                "uptime_status": args.uptime_status,
                "collector_success_count": args.collector_success_count,
                "collector_failure_count": args.collector_failure_count,
                "backup_success": args.backup_success,
                "alert_count": args.alert_count,
                "notes": args.notes,
            },
        )
        print(f"Recorded soak metric {saved['id']} for paper-live run {saved['run_id']}")
        return 0

    parser.print_help()
    return 2


def _add_market_rule_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ticker")
    parser.add_argument("--title")
    parser.add_argument("--settlement-rule-text")
    parser.add_argument("--official-source-name")
    parser.add_argument("--official-station-id")
    parser.add_argument("--product")
    parser.add_argument("--timezone")
    parser.add_argument("--daily-cutoff")
    parser.add_argument("--units")
    parser.add_argument("--rounding")
    parser.add_argument("--fallback-policy")
    parser.add_argument("--correction-policy")
    parser.add_argument("--verification-status", default="unverified")
    parser.add_argument("--verified-by")
    parser.add_argument("--verified-at")
    parser.add_argument("--source-url")
    parser.add_argument("--notes")


def _market_rule_record_from_args(args: argparse.Namespace) -> dict[str, object]:
    record: dict[str, object] = {}
    if args.json_path:
        with open(args.json_path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("market rule JSON must contain an object")
        record.update(loaded)

    for field in (
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
        "verification_status",
        "verified_by",
        "verified_at",
        "source_url",
        "notes",
    ):
        value = getattr(args, field, None)
        if value is not None:
            record[field] = value
    return record


def _load_records_file(file_path: str) -> list[dict[str, object]]:
    path = Path(file_path)
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if isinstance(loaded, dict):
        if isinstance(loaded.get("records"), list):
            return loaded["records"]
        return [loaded]
    if isinstance(loaded, list):
        return loaded
    raise ValueError("records file must contain a JSON object, JSON array, or CSV rows")


def _load_outcome_argument(*, outcome_json: str | None, outcome_file: str | None) -> dict[str, object] | None:
    if outcome_json and outcome_file:
        raise ValueError("pass only one of --outcome-json or --outcome-file")
    if not outcome_json and not outcome_file:
        return None
    if outcome_file:
        loaded = json.loads(Path(outcome_file).read_text(encoding="utf-8"))
    else:
        loaded = json.loads(outcome_json or "{}")
    if not isinstance(loaded, dict):
        raise ValueError("official outcome JSON must contain an object")
    return loaded


def _decode_replay_row(row: dict[str, object]) -> dict[str, object]:
    decoded = dict(row)
    for field in ("mismatch_reasons", "replay_result_json"):
        value = decoded.get(field)
        if isinstance(value, str):
            try:
                decoded[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return decoded
