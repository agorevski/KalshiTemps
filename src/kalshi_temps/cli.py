from __future__ import annotations

import argparse

from .db import initialize_database
from .seed import seed_demo_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the local Kalshi Temps SQLite dashboard.")
    parser.add_argument("--db", help="SQLite database path. Defaults to KALSHI_TEMPS_DB or data/kalshi_temps.sqlite3")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init-db", help="Create or migrate the SQLite database")
    init_parser.add_argument("--seed", action="store_true", help="Insert demo Seattle observations after initialization")

    subparsers.add_parser("seed-demo", help="Initialize the database and insert demo observations")
    return parser


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

    parser.print_help()
    return 2
