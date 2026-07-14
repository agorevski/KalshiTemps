from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import connection, initialize_database
from .repository import WeatherRepository


def seed_demo_data(db_path: str | None = None) -> None:
    initialize_database(db_path)
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    samples = [
        ("NOAA ASOS KSEA", "https://aviationweather.gov/", "KSEA", -5, 67.5, 51.0, 210, 8.0, 1016.2, 1800, None),
        ("NOAA ASOS KSEA", "https://aviationweather.gov/", "KSEA", -4, 70.0, 52.0, 220, 9.0, 1016.0, 2500, None),
        ("NOAA ASOS KSEA", "https://aviationweather.gov/", "KSEA", -3, 72.1, 52.5, 230, 10.0, 1015.7, 4000, None),
        ("NWS Seattle Forecast Office", "https://www.weather.gov/sew/", "Seattle Downtown", -2, 73.4, 53.0, 240, 7.5, 1015.3, None, 615.0),
        ("NWS Seattle Forecast Office", "https://www.weather.gov/sew/", "Seattle Downtown", -1, 74.2, 53.5, 250, 6.0, 1015.1, None, 680.0),
    ]
    with connection(db_path) as conn:
        repo = WeatherRepository(conn)
        for source_name, url, station, hours_ago, temp, dew_point, wind_dir, wind_speed, pressure, ceiling, solar in samples:
            repo.upsert_source(source_name, url=url, notes="Demo source for local dashboard development")
            observed_at = (base + timedelta(hours=hours_ago)).isoformat()
            repo.add_observation(
                source_name=source_name,
                station=station,
                observed_at=observed_at,
                temperature_f=temp,
                dew_point_f=dew_point,
                wind_direction_deg=wind_dir,
                wind_speed_mph=wind_speed,
                pressure_mb=pressure,
                cloud_ceiling_ft=ceiling,
                solar_radiation_wm2=solar,
                raw_payload={"demo": True, "temperature_f": temp},
            )
        forecast_source = repo.upsert_source(
            "Demo forecast model blend",
            source_type="forecast_model",
            url="https://example.invalid/demo-model-guidance",
            notes="Placeholder provenance for HRRR/NAM/GFS/ECMWF/GraphCast/NBM model fusion.",
            last_seen_at=base.isoformat(),
        )
        target_date = base.date().isoformat()
        model_runs = [
            ("HRRR", "18z", 75.0, 0.62, "Rapid-refresh hourly guidance"),
            ("NAM", "12z", 73.0, 0.55, "Mesoscale guidance with marine push sensitivity"),
            ("GFS", "12z", 76.0, 0.50, "Global deterministic guidance"),
            ("ECMWF", "00z", 74.0, 0.58, "Global deterministic guidance"),
            ("GraphCast/AI", "12z", 77.0, 0.48, "AI weather model placeholder"),
            ("NBM", "13z", 75.5, 0.66, "National Blend of Models"),
        ]
        highs = []
        for model_name, cycle, high, confidence, notes in model_runs:
            highs.append(high)
            cursor = conn.execute(
                """
                INSERT INTO model_runs (
                    run_at, model_name, model_cycle, valid_date, target_date, predicted_high_f,
                    confidence, source_url, provenance, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    base.isoformat(),
                    model_name,
                    cycle,
                    target_date,
                    target_date,
                    high,
                    confidence,
                    "https://example.invalid/demo-model-guidance",
                    "Demo seed data; replace with fetched model source URL when ingestion is added.",
                    notes,
                ),
            )
            model_run_id = cursor.lastrowid
            for bucket, probability in [("<73°F", 0.18), ("73-74°F", 0.24), ("75-76°F", 0.38), ("77°F+", 0.20)]:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO model_probability_buckets
                        (model_run_id, temperature_bucket, probability)
                    VALUES (?, ?, ?)
                    """,
                    (model_run_id, bucket, probability),
                )
        conn.execute(
            """
            INSERT INTO model_spread (
                target_date, min_high_f, max_high_f, mean_high_f, spread_f, model_count, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_date,
                min(highs),
                max(highs),
                sum(highs) / len(highs),
                max(highs) - min(highs),
                len(highs),
                "Demo disagreement tracker across HRRR, NAM, GFS, ECMWF, GraphCast/AI, and NBM.",
            ),
        )
        conn.execute(
            """
            INSERT INTO marine_layer_indicators (
                source_id, observed_at, cloud_cover_pct, ceiling_ft, satellite_trend,
                marine_layer_cleared_before_10am, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                forecast_source["id"],
                (base - timedelta(hours=1)).isoformat(),
                35.0,
                2500,
                "Cloud deck thinning east of Puget Sound in demo notes.",
                1,
                "Track morning marine layer/cloud burn-off because it can cap Seattle highs.",
            ),
        )
        for bucket, yes_bid, yes_ask, no_bid, no_ask, implied in [
            ("73-74°F", 42, 48, 52, 58, 0.45),
            ("75-76°F", 31, 36, 64, 69, 0.335),
            ("77°F+", 18, 23, 77, 82, 0.205),
        ]:
            conn.execute(
                """
                INSERT INTO market_snapshots (
                    market_ticker, temperature_bucket, captured_at, yes_bid_cents, yes_ask_cents,
                    no_bid_cents, no_ask_cents, last_price_cents, implied_probability,
                    settlement_source_note, raw_payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "DEMO-KSEA-HIGH",
                    bucket,
                    base.isoformat(),
                    yes_bid,
                    yes_ask,
                    no_bid,
                    no_ask,
                    yes_bid,
                    implied,
                    "Settlement station/source must be verified from market rules; Robinhood/Kalshi indication alone is not authoritative.",
                    '{"demo": true}',
                ),
            )
        conn.execute(
            """
            INSERT INTO app_events (event_type, message, source_name, provenance_url)
            VALUES (?, ?, ?, ?)
            """,
            (
                "demo.seeded",
                "Inserted demo six-layer Seattle temperature fusion evidence.",
                "Demo seed",
                "https://example.invalid/demo-model-guidance",
            ),
        )
