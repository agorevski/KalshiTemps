from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.ingest import (  # noqa: E402
    collect_forecast_discussion,
    collect_metar_observation,
    normalize_forecast_discussion,
    normalize_market_snapshot,
    normalize_model_high,
    normalize_observation,
    provenance_hash,
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
