from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.ingest import (  # noqa: E402
    collect_forecast_discussion,
    collect_metar_observation,
    load_model_high_records,
    normalize_forecast_discussion,
    normalize_market_snapshot,
    normalize_model_high,
    normalize_observation,
    parse_model_high_records,
    provenance_hash,
    run_forecast_discussion_collector,
    run_metar_collector,
    source_freshness_metadata,
)


def test_normalize_forecast_discussion_stores_core_fields_and_hash() -> None:
    discussion = normalize_forecast_discussion(
        {
            "product_id": "AFDSEW",
            "issued_at": "2026-07-14T10:30:00-07:00",
            "source_url": "https://example.test/afd",
            "text": "AFDSEW\nArea Forecast Discussion\nMarine layer clearing late.",
        }
    )

    assert discussion["product_id"] == "AFDSEW"
    assert discussion["issued_at"] == "2026-07-14T17:30:00+00:00"
    assert discussion["source_url"] == "https://example.test/afd"
    assert discussion["text"].startswith("AFDSEW")
    assert len(discussion["hash"]) == 64
    assert discussion == normalize_forecast_discussion(
        {
            "product_id": "AFDSEW",
            "issued_at": "2026-07-14T10:30:00-07:00",
            "source_url": "https://example.test/afd",
            "text": "AFDSEW\nArea Forecast Discussion\nMarine layer clearing late.",
        }
    )


def test_normalize_forecast_discussion_rejects_missing_product_id() -> None:
    with pytest.raises(ValueError, match="product_id"):
        normalize_forecast_discussion("Area Forecast Discussion text only")


def test_collect_forecast_discussion_uses_injected_fetcher_and_provenance() -> None:
    record = collect_forecast_discussion(
        "https://example.test/afd",
        fetcher=lambda url: "AFDSEW\nTue, 14 Jul 2026 17:30:00 GMT\nMarine layer clearing late.",
        ingest_at="2026-07-14T18:00:00Z",
    )

    assert record["product_id"] == "AFDSEW"
    assert record["issued_at"] == "2026-07-14T17:30:00+00:00"
    assert record["ingest_at"] == "2026-07-14T18:00:00+00:00"
    assert record["parser_status"] == "ok"
    assert len(record["raw_payload_hash"]) == 64
    assert len(record["text_hash"]) == 64


def test_collect_forecast_discussion_surfaces_fetch_failures() -> None:
    def failing_fetcher(url: str) -> str:
        raise RuntimeError("network down")

    with pytest.raises(ValueError, match="network down"):
        collect_forecast_discussion("https://example.test/afd", fetcher=failing_fetcher)


def test_forecast_discussion_collector_result_records_success_and_failure() -> None:
    success = run_forecast_discussion_collector(
        source="Fixture AFD",
        url="https://example.test/afd",
        fetcher=lambda url: "AFDSEW\nTue, 14 Jul 2026 17:30:00 GMT\nMarine layer clearing late.",
        max_attempts=2,
    )

    assert success.succeeded is True
    assert success.records_returned == 1
    assert success.newest_observation_at == "2026-07-14T17:30:00+00:00"
    assert success.poll_record()["collector_name"] == "nws_discussion"

    failure = run_forecast_discussion_collector(
        source="Fixture AFD",
        url="https://example.test/afd",
        fetcher=lambda url: (_ for _ in ()).throw(RuntimeError("network down")),
        max_attempts=2,
    )

    assert failure.succeeded is False
    assert failure.status == "failed"
    assert failure.records_returned == 0
    assert "network down" in (failure.error_message or "")
    assert len(failure.payload_hash or "") == 64


def test_normalize_metar_string_extracts_weather_fields() -> None:
    obs = normalize_observation(
        "KSEA 142253Z 24008KT 10SM FEW015 BKN025 22/13 A2992",
        reference_date="2026-07-14",
    )

    assert obs["station"] == "KSEA"
    assert obs["observed_at"] == "2026-07-14T22:53:00+00:00"
    assert obs["temperature_f"] == 71.6
    assert obs["dew_point_f"] == 55.4
    assert obs["wind_direction_deg"] == 240
    assert obs["wind_speed_mph"] == 9.2
    assert obs["pressure_mb"] == 1013.2
    assert obs["cloud_ceiling_ft"] == 2500
    assert len(obs["hash"]) == 64


def test_collect_metar_observation_uses_injected_fetcher_and_provenance() -> None:
    obs = collect_metar_observation(
        "KSEA",
        url="https://example.test/metar",
        fetcher=lambda url: "\nKSEA 142253Z 24008KT 10SM FEW015 BKN025 22/13 A2992\n",
        ingest_at="2026-07-14T23:00:00Z",
    )

    assert obs["station"] == "KSEA"
    assert obs["observed_at"] == "2026-07-14T22:53:00+00:00"
    assert obs["source_url"] == "https://example.test/metar"
    assert obs["parser_status"] == "ok"
    assert len(obs["raw_payload_hash"]) == 64


def test_metar_collector_result_records_success_and_failure() -> None:
    success = run_metar_collector(
        source="Fixture METAR",
        station="KSEA",
        url="https://example.test/metar",
        fetcher=lambda url: "KSEA 142253Z 24008KT 10SM FEW015 BKN025 22/13 A2992",
        ingest_at="2026-07-14T23:00:00Z",
    )

    assert success.succeeded is True
    assert success.records_returned == 1
    assert success.newest_observation_at == "2026-07-14T22:53:00+00:00"
    assert success.poll_record()["collector_name"] == "metar"

    failure = run_metar_collector(
        source="Fixture METAR",
        station="KSEA",
        url="https://example.test/metar",
        fetcher=lambda url: "",
    )

    assert failure.succeeded is False
    assert failure.status == "failed"
    assert "did not contain" in (failure.error_message or "")


def test_normalize_observation_mapping_accepts_aliases() -> None:
    obs = normalize_observation(
        {
            "station": "sea",
            "observed_at": datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc),
            "temp_f": "74",
            "dew_f": 52,
            "wind_dir_deg": 270,
            "wind_mph": 10.5,
            "ceiling_ft": 3000,
        }
    )

    assert obs["station"] == "SEA"
    assert obs["temperature_f"] == 74
    assert obs["dew_point_f"] == 52
    assert obs["cloud_ceiling_ft"] == 3000


def test_normalize_observation_rejects_malformed_metar() -> None:
    with pytest.raises(ValueError, match="reference_date"):
        normalize_observation("KSEA 142253Z 24008KT 22/13 A2992")

    with pytest.raises(ValueError, match="temperature"):
        normalize_observation("KSEA 142253Z 24008KT A2992", reference_date="2026-07-14")


def test_normalize_model_high_outputs_run_and_provenance() -> None:
    model = normalize_model_high(
        {
            "model_name": "HRRR",
            "model_cycle": "18z",
            "run_at": "2026-07-14T18:00:00Z",
            "valid_date": "2026-07-15",
            "high_f": 78.4,
            "source_url": "https://example.test/hrrr",
        }
    )

    assert model["model_name"] == "HRRR"
    assert model["run_at"] == "2026-07-14T18:00:00+00:00"
    assert model["target_date"] == "2026-07-15"
    assert model["predicted_high_f"] == 78.4
    assert model["provenance"] == model["provenance_hash"]


def test_parse_model_high_records_accepts_json_csv_and_probability_buckets() -> None:
    records = parse_model_high_records(
        {
            "records": [
                {
                    "model_name": "NBM",
                    "run_at": "2026-07-14T18:00:00Z",
                    "target_date": "2026-07-15",
                    "predicted_high_f": "76.5",
                    "probabilities": {"75-76°F": 62, "77°F+": 0.38},
                }
            ]
        }
    )

    assert records[0]["model_name"] == "NBM"
    assert records[0]["probability_buckets"] == [
        {"temperature_bucket": "75-76°F", "probability": 0.62},
        {"temperature_bucket": "77°F+", "probability": 0.38},
    ]

    csv_records = parse_model_high_records(
        "model_name,run_at,target_date,high_f\n"
        "GFS,2026-07-14T18:00:00Z,2026-07-15,74.2\n"
    )
    assert csv_records[0]["predicted_high_f"] == 74.2


def test_load_model_high_records_from_project_file() -> None:
    path = Path("data") / "test-model-high-records.json"
    path.parent.mkdir(exist_ok=True)
    try:
        path.write_text(
            '[{"model_name":"HRRR","run_at":"2026-07-14T18:00:00Z",'
            '"target_date":"2026-07-15","high_f":78}]',
            encoding="utf-8",
        )
        assert load_model_high_records(path)[0]["model_name"] == "HRRR"
    finally:
        path.unlink(missing_ok=True)


def test_normalize_model_high_rejects_missing_required_fields() -> None:
    with pytest.raises(ValueError, match="model_name"):
        normalize_model_high({"run_at": "2026-07-14T18:00:00Z", "target_date": "2026-07-15", "high_f": 78})

    with pytest.raises(ValueError, match="target_date|valid_date"):
        normalize_model_high({"model_name": "GFS", "run_at": "2026-07-14T18:00:00Z", "high_f": 78})


def test_normalize_market_snapshot_computes_implied_probability() -> None:
    snapshot = normalize_market_snapshot(
        {
            "market_ticker": "KXHIGHSEA-26JUL14-B75",
            "temperature_bucket": "75-79",
            "yes_bid_cents": 44,
            "yes_ask_cents": 48,
            "no_bid_cents": 52,
            "no_ask_cents": 56,
            "captured_at": "2026-07-14T20:00:00Z",
            "settlement_source_note": "demo fixture",
        }
    )

    assert snapshot["ticker"] == "KXHIGHSEA-26JUL14-B75"
    assert snapshot["bucket"] == "75-79"
    assert snapshot["yes_bid"] == 44
    assert snapshot["implied_probability"] == 0.46
    assert len(snapshot["provenance_hash"]) == 64


def test_normalize_market_snapshot_rejects_bad_prices() -> None:
    with pytest.raises(ValueError, match="captured_at"):
        normalize_market_snapshot({"ticker": "T", "yes_bid": 10})

    with pytest.raises(ValueError, match="yes_bid"):
        normalize_market_snapshot(
            {"ticker": "T", "captured_at": "2026-07-14T20:00:00Z", "yes_bid": 55, "yes_ask": 40}
        )


def test_source_freshness_metadata_and_provenance_hash_are_deterministic() -> None:
    metadata = source_freshness_metadata(
        source_name="NWS AFD",
        observed_at="2026-07-14T19:30:00Z",
        checked_at="2026-07-14T20:00:00Z",
        max_age_minutes=45,
        source_url="https://example.test/afd",
    )

    assert metadata["age_minutes"] == 30
    assert metadata["is_fresh"] is True
    assert metadata["provenance_hash"] == provenance_hash({key: value for key, value in metadata.items() if key != "provenance_hash"})


def test_model_forecast_import_persists_extraction_metadata_and_deltas() -> None:
    from kalshi_temps.db import connection, initialize_database
    from kalshi_temps.repository import WeatherRepository
    import uuid

    db_path = Path("data") / f"test-model-adapter-foundations-{uuid.uuid4().hex}.sqlite3"
    try:
        initialize_database(str(db_path))
        records = parse_model_high_records(
            [
                {
                    "model_name": "NBM",
                    "run_at": "2026-07-14T12:00:00Z",
                    "valid_at": "2026-07-15T00:00:00Z",
                    "station": "KSEA",
                    "high_f": 74,
                },
                {
                    "model_name": "NBM",
                    "run_at": "2026-07-14T18:00:00Z",
                    "valid_at": "2026-07-15T06:00:00Z",
                    "station": "KSEA",
                    "high_f": 77,
                },
            ]
        )
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            repo.import_model_high_records(records)
            repo.import_model_high_records(records)
            assert conn.execute("SELECT COUNT(*) AS c FROM model_runs").fetchone()["c"] == 2
            assert conn.execute("SELECT COUNT(*) AS c FROM model_run_extractions").fetchone()["c"] == 2
            delta = repo.list_model_run_deltas(target_date="2026-07-15")[0]
        assert delta["change_f"] == 3
        assert delta["previous_predicted_high_f"] == 74
    finally:
        db_path.unlink(missing_ok=True)
