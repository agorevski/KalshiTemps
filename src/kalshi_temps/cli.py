from __future__ import annotations

import argparse

from .db import connection
from .db import initialize_database
from .ingest import (
    DEFAULT_AVIATION_WEATHER_METAR_URL_TEMPLATE,
    DEFAULT_NWS_SEW_DISCUSSION_URL,
    TextFetcher,
    collect_forecast_discussion,
    collect_metar_observation,
)
from .repository import WeatherRepository
from .seed import seed_demo_data


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
    return parser


def collect_and_save_forecast_discussion(
    db_path: str | None,
    *,
    url: str = DEFAULT_NWS_SEW_DISCUSSION_URL,
    source_name: str = "NWS Seattle Forecast Discussion",
    fetcher: TextFetcher | None = None,
) -> dict[str, object]:
    initialize_database(db_path)
    record = collect_forecast_discussion(url=url, fetcher=fetcher)
    with connection(db_path) as conn:
        saved = WeatherRepository(conn).save_forecast_discussion(source_name, record)
    return saved


def collect_and_save_metar(
    db_path: str | None,
    *,
    station: str = "KSEA",
    url: str | None = None,
    source_name: str = "Aviation Weather METAR",
    fetcher: TextFetcher | None = None,
) -> dict[str, object]:
    initialize_database(db_path)
    record = collect_metar_observation(station=station, url=url, fetcher=fetcher)
    with connection(db_path) as conn:
        saved = WeatherRepository(conn).save_observation_record(source_name, record)
    return saved


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
        saved = collect_and_save_forecast_discussion(args.db, url=args.url, source_name=args.source_name)
        print(f"Collected forecast discussion {saved['product_id']} at {saved['ingest_at']}")
        return 0

    if args.command == "collect-metar":
        saved = collect_and_save_metar(args.db, station=args.station, url=args.url, source_name=args.source_name)
        print(f"Collected METAR {saved['station']} at {saved['observed_at']}")
        return 0

    parser.print_help()
    return 2
