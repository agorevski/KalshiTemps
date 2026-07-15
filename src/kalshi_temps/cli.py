from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from .db import connection
from .db import initialize_database
from .ingest import (
    DEFAULT_AVIATION_WEATHER_METAR_URL_TEMPLATE,
    DEFAULT_NWS_SEW_DISCUSSION_URL,
    TextFetcher,
    collect_forecast_discussion,
    collect_metar_observation,
    load_model_high_records,
    run_forecast_discussion_collector,
    run_metar_collector,
)
from .ops import backup_path, ops_status
from .repository import WeatherRepository
from .seed import seed_demo_data
from .weather_features import extract_discussion_features


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

    spread_parser = subparsers.add_parser("list-model-spread", help="List persisted model spread rows")
    spread_parser.add_argument("--target-date", help="Filter spread rows to one ISO target date")
    spread_parser.add_argument("--limit", type=int, default=10, help="Maximum spread rows to print")

    features_parser = subparsers.add_parser(
        "extract-weather-features",
        help="Extract deterministic regime features from latest discussion or a text file",
    )
    features_parser.add_argument("--file", help="Forecast discussion text file. Defaults to latest saved discussion.")

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


def compute_calibration(db_path: str | None, *, bins: int = 10) -> dict[str, object]:
    initialize_database(db_path)
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        bias = repo.compute_bias_summaries()
        metrics = repo.compute_calibration_metrics(bin_count=bins)
    return {"bias_summaries": bias, "calibration_metrics": metrics}


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

    if args.command == "import-model-highs":
        summary = import_and_save_model_highs(args.db, file_path=args.file)
        print(
            f"Imported {summary['imported_count']} model-high records; "
            f"updated {len(summary['model_spreads'])} spread row(s)"
        )
        return 0

    if args.command == "list-model-spread":
        initialize_database(args.db)
        with connection(args.db) as conn:
            rows = WeatherRepository(conn).list_model_spread(limit=args.limit, target_date=args.target_date)
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
        result = compute_calibration(args.db, bins=args.bins)
        print(
            "Computed "
            f"{len(result['bias_summaries'])} bias summaries and "
            f"{len(result['calibration_metrics'])} calibration metrics"
        )
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
