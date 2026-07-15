from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys
import uuid

from fastapi.testclient import TestClient
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps import cli  # noqa: E402
from kalshi_temps.app import app  # noqa: E402
from kalshi_temps.cli import (  # noqa: E402
    collect_and_save_forecast_discussion,
    collect_and_save_metar,
    extract_and_save_weather_features,
)
from kalshi_temps.db import connection, initialize_database  # noqa: E402
from kalshi_temps.ingest import normalize_market_snapshot, normalize_model_high  # noqa: E402
from kalshi_temps.repository import WeatherRepository  # noqa: E402
from kalshi_temps.seed import seed_demo_data  # noqa: E402


def _project_temp_db(monkeypatch) -> Path:
    db_path = Path("data") / f"test-app-integration-{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("KALSHI_TEMPS_DB", str(db_path))
    return db_path


def _project_temp_db_path(prefix: str) -> Path:
    return Path("data") / f"{prefix}-{uuid.uuid4().hex}.sqlite3"


def test_db_init_and_seed_populates_fusion_examples(monkeypatch) -> None:
    db_path = _project_temp_db(monkeypatch)
    try:
        initialize_database(str(db_path))
        seed_demo_data(str(db_path))

        with TestClient(app) as client:
            summary = client.get("/api/fusion/summary").json()["summary"]
            market = client.get("/api/market-snapshots").json()["market_snapshots"]
            model_runs = client.get("/api/model-runs").json()["model_runs"]

        assert summary["daily_high"]["high_temperature_f"] > 0
        assert summary["model_spread"]["model_count"] >= 3
        assert summary["source_freshness"]
        assert summary["risk_guards"]
        assert summary["bucket_deltas"]
        assert summary["product_status"]["status"] in {"needs-review", "research-populated"}
        assert market
        assert model_runs
    finally:
        db_path.unlink(missing_ok=True)


def test_repository_methods_cover_empty_and_seeded_sqlite_flows(monkeypatch) -> None:
    db_path = _project_temp_db(monkeypatch)
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            empty_repo = WeatherRepository(conn)
            assert empty_repo.list_sources() == []
            assert empty_repo.list_observations() == []
            assert empty_repo.daily_high() is None
            assert empty_repo.latest_model_spread() is None
            assert empty_repo.list_market_snapshots() == []
            assert empty_repo.list_model_runs() == []
            assert empty_repo.fusion_summary()["product_status"]["source_count"] == 0

            source = empty_repo.upsert_source(
                "Repository Test Source",
                url="https://example.invalid/source",
                last_seen_at="2026-07-14T18:00:00+00:00",
            )
            observation = empty_repo.add_observation(
                "Repository Test Source",
                "KSEA",
                "2026-07-14T19:00:00+00:00",
                72.5,
                raw_payload={"fixture": True},
            )

        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            assert repo.get_source_by_name("Repository Test Source")["id"] == source["id"]
            assert repo.list_sources()[0]["observation_count"] == 1
            assert repo.list_observations(limit=1)[0]["raw_payload"] == '{"fixture": true}'
            assert observation["source_name"] == "Repository Test Source"
            assert repo.daily_high()["high_temperature_f"] == 72.5

            discussion = repo.save_forecast_discussion(
                "NWS Seattle Forecast Discussion",
                {
                    "product_id": "AFDSEW",
                    "issued_at": "2026-07-14T17:30:00+00:00",
                    "ingest_at": "2026-07-14T18:00:00+00:00",
                    "source_url": "https://example.test/afd",
                    "text": "AFDSEW\nMarine layer clearing late.",
                    "text_hash": "text-hash",
                    "raw_payload_hash": "raw-hash",
                    "parser_status": "ok",
                    "parser_notes": "fixture",
                },
            )
            model = repo.save_model_high_record(
                normalize_model_high(
                    {
                        "model_name": "Placeholder Blend",
                        "run_at": "2026-07-14T18:00:00Z",
                        "target_date": "2026-07-01",
                        "predicted_high_f": 78,
                    }
                )
            )
            market = repo.save_market_snapshot_record(
                normalize_market_snapshot(
                    {
                        "ticker": "KXHIGHSEA-26JUL14-B75",
                        "captured_at": "2026-07-14T20:00:00Z",
                        "yes_bid": 44,
                        "yes_ask": 48,
                    }
                )
            )
            assert discussion["source_name"] == "NWS Seattle Forecast Discussion"
            assert repo.list_forecast_discussions()[0]["product_id"] == "AFDSEW"
            assert model["model_name"] == "Placeholder Blend"
            assert market["implied_probability"] == 0.46

        seed_demo_data(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            assert len(repo.list_sources()) >= 3
            assert len(repo.list_observations(limit=50)) >= 6
            assert len(repo.list_marine_indicators()) == 1
            assert len(repo.list_market_snapshots()) >= 3
            assert len(repo.list_model_runs()) >= 6
            assert repo.latest_model_bucket_probabilities()
            assert repo.latest_market_bucket_probabilities()
            assert repo.latest_model_spread()["model_count"] == 6
            assert repo.bucket_probability_deltas()
            assert len(repo.risk_guard_status()) == 4
            assert repo.product_status()["source_count"] >= 3
            assert repo.list_events()
    finally:
        db_path.unlink(missing_ok=True)


def test_seed_demo_is_idempotent_for_market_and_model_fixtures() -> None:
    db_path = _project_temp_db_path("test-seed-idempotent")
    try:
        seed_demo_data(str(db_path))
        seed_demo_data(str(db_path))

        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            assert len(repo.list_market_snapshots(limit=20)) == 3
            assert len(repo.list_model_runs(limit=20)) == 6
            assert repo.latest_model_spread()["model_count"] == 6
            assert len(repo.list_marine_indicators(limit=20)) == 1
    finally:
        db_path.unlink(missing_ok=True)


def test_manual_model_high_import_is_idempotent_and_persists_spread_and_deltas() -> None:
    db_path = _project_temp_db_path("test-model-ingestion")
    try:
        initialize_database(str(db_path))
        records = [
            normalize_model_high(
                {
                    "model_name": "HRRR",
                    "run_at": "2020-07-14T12:00:00Z",
                    "target_date": "2020-07-15",
                    "high_f": 75,
                    "probabilities": {"75-76°F": 60},
                }
            ),
            normalize_model_high(
                {"model_name": "GFS", "run_at": "2020-07-14T12:00:00Z", "target_date": "2020-07-15", "high_f": 74}
            ),
            normalize_model_high(
                {
                    "model_name": "HRRR",
                    "run_at": "2020-07-14T18:00:00Z",
                    "target_date": "2020-07-15",
                    "high_f": 77,
                    "probabilities": {"75-76°F": 25, "77°F+": 75},
                }
            ),
        ]

        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            first = repo.import_model_high_records(records)
            second = repo.import_model_high_records(records)
            spread = repo.latest_model_spread("2020-07-15")
            run_count = conn.execute("SELECT COUNT(*) AS count FROM model_runs").fetchone()["count"]
            spread_count = conn.execute("SELECT COUNT(*) AS count FROM model_spread").fetchone()["count"]

        assert first["imported_count"] == 3
        assert second["imported_count"] == 3
        assert run_count == 3
        assert spread_count == 1
        assert spread["model_count"] == 2
        assert spread["spread_f"] == 3
        assert spread["run_change_count"] == 1
        assert spread["mean_run_change_f"] == 2
    finally:
        db_path.unlink(missing_ok=True)


def test_manual_model_high_import_rejects_invalid_records() -> None:
    db_path = _project_temp_db_path("test-model-invalid")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            with pytest.raises(ValueError, match="validation"):
                repo.save_model_high_record(
                    normalize_model_high(
                        {"model_name": "NAM", "run_at": "2020-07-14T12:00:00Z", "target_date": "2020-07-15", "high_f": 200}
                    )
                )
    finally:
        db_path.unlink(missing_ok=True)


def test_cli_import_model_highs_and_list_spread(capsys) -> None:
    db_path = _project_temp_db_path("test-cli-model-import")
    file_path = Path("data") / f"test-model-import-{uuid.uuid4().hex}.json"
    file_path.parent.mkdir(exist_ok=True)
    try:
        file_path.write_text(
            json.dumps(
                [
                    {"model_name": "NBM", "run_at": "2020-07-14T12:00:00Z", "target_date": "2020-07-15", "high_f": 76},
                    {"model_name": "GFS", "run_at": "2020-07-14T12:00:00Z", "target_date": "2020-07-15", "high_f": 74},
                ]
            ),
            encoding="utf-8",
        )
        assert cli.main(["--db", str(db_path), "import-model-highs", str(file_path)]) == 0
        assert cli.main(["--db", str(db_path), "list-model-spread", "--target-date", "2020-07-15"]) == 0
        output = capsys.readouterr().out
        assert "Imported 2 model-high records" in output
        assert '"spread_f": 2.0' in output
    finally:
        db_path.unlink(missing_ok=True)
        file_path.unlink(missing_ok=True)


def test_collect_cli_helpers_persist_with_injected_fetchers() -> None:
    db_path = _project_temp_db_path("test-cli-collect")
    try:
        discussion = collect_and_save_forecast_discussion(
            str(db_path),
            url="https://example.test/afd",
            fetcher=lambda url: "AFDSEW\nTue, 14 Jul 2026 17:30:00 GMT\nMarine layer clearing late.",
        )
        observation = collect_and_save_metar(
            str(db_path),
            station="KSEA",
            url="https://example.test/metar",
            fetcher=lambda url: "KSEA 142253Z 24008KT 10SM FEW015 BKN025 22/13 A2992",
        )

        assert discussion["product_id"] == "AFDSEW"
        assert observation["station"] == "KSEA"
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            assert repo.list_forecast_discussions()
            assert repo.list_observations(limit=1)[0]["source_url"] == "https://example.test/metar"
            runs = repo.list_collector_runs(limit=5)
            assert [run["status"] for run in runs] == ["success", "success"]
            health = repo.collector_health_summaries(max_age_minutes=10_000_000)
            assert {item["collector_name"] for item in health} == {"nws_discussion", "metar"}
            assert all(item["is_fresh"] for item in health)
    finally:
        db_path.unlink(missing_ok=True)


def test_collect_cli_helpers_persist_failed_poll_records() -> None:
    db_path = _project_temp_db_path("test-cli-collect-failure")
    try:
        try:
            collect_and_save_forecast_discussion(
                str(db_path),
                url="https://example.test/afd",
                fetcher=lambda url: (_ for _ in ()).throw(RuntimeError("network down")),
            )
        except RuntimeError as exc:
            assert "network down" in str(exc)
        else:
            raise AssertionError("collector failure should be surfaced")

        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            runs = repo.list_collector_runs(limit=1)
            assert runs[0]["status"] == "failed"
            assert runs[0]["records_returned"] == 0
            assert "network down" in runs[0]["error_message"]
            health = repo.collector_health_summaries()
            assert health[0]["collector_name"] == "nws_discussion"
            assert health[0]["is_stale"] is True
    finally:
        db_path.unlink(missing_ok=True)


def test_extract_weather_features_cli_helper_uses_latest_discussion() -> None:
    db_path = _project_temp_db_path("test-cli-features")
    try:
        collect_and_save_forecast_discussion(
            str(db_path),
            url="https://example.test/afd",
            fetcher=lambda url: "AFDSEW\nTue, 14 Jul 2026 17:30:00 GMT\nMarine layer and stratus burn off before 10 AM.",
        )
        saved = extract_and_save_weather_features(str(db_path))

        assert "marine_layer" in saved["regime_tags"]
        assert "burn_off_timing" in saved["regime_tags"]
        with connection(str(db_path)) as conn:
            assert WeatherRepository(conn).latest_weather_regime_features()["id"] == saved["id"]
    finally:
        db_path.unlink(missing_ok=True)


def test_cli_collection_commands_dispatch_without_live_network(monkeypatch, capsys) -> None:
    calls = []

    def fake_discussion(db_path, *, url, source_name, fetcher=None):
        calls.append(("discussion", db_path, url, source_name, fetcher))
        return {"product_id": "AFDSEW", "ingest_at": "2026-07-14T18:00:00+00:00"}

    def fake_metar(db_path, *, station, url, source_name, fetcher=None):
        calls.append(("metar", db_path, station, url, source_name, fetcher))
        return {"station": "KSEA", "observed_at": "2026-07-14T22:53:00+00:00"}

    monkeypatch.setattr(cli, "collect_and_save_forecast_discussion", fake_discussion)
    monkeypatch.setattr(cli, "collect_and_save_metar", fake_metar)

    assert cli.main(
        [
            "--db",
            "data/test-cli-dispatch.sqlite3",
            "collect-nws-discussion",
            "--url",
            "https://example.test/afd",
            "--source-name",
            "Fixture AFD",
        ]
    ) == 0
    assert cli.main(
        [
            "--db",
            "data/test-cli-dispatch.sqlite3",
            "collect-metar",
            "--station",
            "KSEA",
            "--url",
            "https://example.test/metar",
            "--source-name",
            "Fixture METAR",
        ]
    ) == 0

    assert calls == [
        ("discussion", "data/test-cli-dispatch.sqlite3", "https://example.test/afd", "Fixture AFD", None),
        ("metar", "data/test-cli-dispatch.sqlite3", "KSEA", "https://example.test/metar", "Fixture METAR", None),
    ]
    output = capsys.readouterr().out
    assert "Collected forecast discussion AFDSEW" in output
    assert "Collected METAR KSEA" in output


def test_cli_collector_health_and_runs_smoke(capsys) -> None:
    db_path = _project_temp_db_path("test-cli-collector-health")
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            WeatherRepository(conn).record_collector_run(
                {
                    "source": "Fixture METAR",
                    "collector_name": "metar",
                    "started_at": "2026-07-14T23:00:00+00:00",
                    "finished_at": "2026-07-14T23:00:01+00:00",
                    "status": "success",
                    "records_returned": 1,
                    "newest_observation_at": "2026-07-14T22:53:00+00:00",
                    "latency_seconds": 1.0,
                    "source_url": "https://example.test/metar",
                    "payload_hash": "hash",
                }
            )

        assert cli.main(["--db", str(db_path), "collector-runs", "--limit", "1"]) == 0
        assert cli.main(["--db", str(db_path), "collector-health", "--max-age-minutes", "10000000"]) == 0
        output = capsys.readouterr().out
        assert "Fixture METAR" in output
        assert "collector_name" in output
    finally:
        db_path.unlink(missing_ok=True)


def test_new_app_endpoints_return_expected_shapes(monkeypatch) -> None:
    db_path = _project_temp_db(monkeypatch)
    try:
        seed_demo_data(str(db_path))

        with TestClient(app) as client:
            root_response = client.get("/", follow_redirects=False)
            health_response = client.get("/health")
            health_json_response = client.get("/health/json")
            ops_response = client.get("/api/ops/status")
            observations_response = client.get("/api/observations?limit=3")
            sources_response = client.get("/api/sources")
            fusion_response = client.get("/api/fusion/summary")
            snapshots_response = client.get("/api/market-snapshots?limit=2")
            model_runs_response = client.get("/api/model-runs?limit=2")
            model_spread_response = client.get("/api/model-spread?limit=2")
            market_verification_response = client.get("/api/market/verification")
            collector_health_response = client.get("/api/collector/health?limit=2")
            weather_features_response = client.get("/api/weather/features?limit=2")
            calibration_response = client.get("/api/calibration/summary?limit=2")
            dashboard_response = client.get("/dashboard")

        assert root_response.status_code in {307, 308}
        assert root_response.headers["location"] == "/dashboard"
        assert health_response.status_code == 200
        assert health_response.json()["status"] == "ok"
        assert health_json_response.json()["service"] == "kalshi-temps"
        assert ops_response.status_code == 200
        assert {"database", "disk", "access"} <= set(ops_response.json()["ops"])
        assert "path" not in ops_response.json()["ops"]["database"]
        assert "path" not in ops_response.json()["ops"]["disk"]
        assert observations_response.status_code == 200
        assert len(observations_response.json()["observations"]) == 3
        assert sources_response.status_code == 200
        assert sources_response.json()["sources"]
        assert fusion_response.status_code == 200
        assert snapshots_response.status_code == 200
        assert model_runs_response.status_code == 200
        assert model_spread_response.status_code == 200
        assert market_verification_response.status_code == 200
        assert collector_health_response.status_code == 200
        assert weather_features_response.status_code == 200
        assert calibration_response.status_code == 200
        assert dashboard_response.status_code == 200

        fusion = fusion_response.json()["summary"]
        assert {
            "daily_high",
            "model_spread",
            "source_freshness",
            "risk_guards",
            "bucket_deltas",
            "observation_quality",
            "forecast_quality",
            "product_status",
        } <= set(fusion)
        assert fusion["observation_quality"]
        assert fusion["forecast_quality"]
        assert len(snapshots_response.json()["market_snapshots"]) == 2
        assert len(model_runs_response.json()["model_runs"]) == 2
        assert {"model_spreads", "latest_model_spread", "bucket_deltas"} <= set(model_spread_response.json())
        assert {"market_verification", "market_rules"} <= set(market_verification_response.json())
        assert {"collector_health", "collector_runs"} <= set(collector_health_response.json())
        assert {"weather_regime_features", "intraday_features"} <= set(weather_features_response.json())
        assert {"official_outcomes", "prediction_snapshots", "bias_summaries", "calibration_metrics"} <= set(calibration_response.json())
        assert "Research workflow" in dashboard_response.text
        assert "No financial advice" in dashboard_response.text
    finally:
        db_path.unlink(missing_ok=True)



def test_research_foundations_endpoints_and_dashboard_render(monkeypatch) -> None:
    db_path = _project_temp_db(monkeypatch)
    try:
        initialize_database(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            repo.record_collector_run(
                {
                    "source": "Fixture METAR",
                    "collector_name": "metar",
                    "started_at": "2026-07-14T18:00:00+00:00",
                    "finished_at": "2026-07-14T18:00:02+00:00",
                    "status": "success",
                    "records_returned": 1,
                    "newest_observation_at": "2026-07-14T18:00:00+00:00",
                }
            )
            repo.upsert_market_rule(
                {
                    "ticker": "DEMO-KSEA-HIGH",
                    "title": "Demo KSEA high",
                    "settlement_rule_text": "Settles to the official KSEA daily high temperature.",
                    "official_source_name": "NOAA ASOS",
                    "official_station_id": "KSEA",
                    "product": "daily high temperature",
                    "timezone": "America/Los_Angeles",
                    "daily_cutoff": "23:59",
                    "units": "fahrenheit",
                    "rounding": "nearest tenth",
                    "fallback_policy": "Manual review if official source unavailable.",
                    "correction_policy": "Manual review for corrections.",
                    "verification_status": "verified",
                    "verified_by": "test",
                    "verified_at": "2026-07-14T18:00:00+00:00",
                    "source_url": "https://example.test/rules",
                }
            )
            discussion = repo.save_forecast_discussion(
                "Fixture Discussion",
                {
                    "product_id": "AFDSEW",
                    "issued_at": "2026-07-14T17:30:00+00:00",
                    "ingest_at": "2026-07-14T18:00:00+00:00",
                    "text": "Marine layer burns off before 10 AM.",
                    "text_hash": "foundation-text",
                    "raw_payload_hash": "foundation-raw",
                    "parser_status": "ok",
                },
            )
            repo.save_weather_regime_features(
                {
                    "forecast_discussion_id": discussion["id"],
                    "source_id": discussion["source_id"],
                    "product_id": "AFDSEW",
                    "issued_at": "2026-07-14T17:30:00+00:00",
                    "extracted_at": "2026-07-14T18:01:00+00:00",
                    "regime_tags": ["marine_layer", "burn_off_timing"],
                    "evidence": {"phrase": "burns off"},
                    "confidence_label": "medium",
                }
            )
            repo.save_intraday_features(
                {
                    "station": "KSEA",
                    "snapshot_at": "2026-07-14T18:05:00+00:00",
                    "local_snapshot_time": "2026-07-14 11:05 PDT",
                    "day_of_year": 195,
                    "current_temp_f": 72.0,
                    "intraday_max_f": 75.5,
                    "warming_rate_f_per_hour": 1.2,
                    "cloud_trend": "clearing",
                    "marine_layer_cleared_before_10am": True,
                }
            )
            repo.save_official_outcome(
                station="KSEA",
                target_date="2026-07-14",
                high_temperature_f=75.5,
                source_name="NOAA ASOS",
            )
            repo.save_prediction_snapshot(
                {
                    "snapshot_at": "2026-07-14T12:00:00+00:00",
                    "model_name": "FixtureModel",
                    "station": "KSEA",
                    "target_date": "2026-07-14",
                    "predicted_high_f": 76.5,
                    "regime": "marine_layer",
                }
            )
            repo.save_prediction_snapshot(
                {
                    "snapshot_at": "2026-07-14T12:00:00+00:00",
                    "model_name": "FixtureModel",
                    "station": "KSEA",
                    "target_date": "2026-07-14",
                    "temperature_bucket": "75-76°F",
                    "probability": 0.7,
                }
            )
            repo.compute_bias_summaries()
            repo.compute_calibration_metrics()

        with TestClient(app) as client:
            market = client.get("/api/market/verification?ticker=DEMO-KSEA-HIGH").json()
            collector = client.get("/api/collector/health?max_age_minutes=10000000").json()
            features = client.get("/api/weather/features").json()
            calibration = client.get("/api/calibration/summary").json()
            dashboard = client.get("/dashboard")

        assert market["market_verification"]["is_actionable"] is True
        assert collector["collector_health"][0]["collector_name"] == "metar"
        assert features["latest_weather_regime_features"]["regime_tags"] == ["marine_layer", "burn_off_timing"]
        assert features["latest_intraday_features"]["marine_layer_cleared_before_10am"] is True
        assert calibration["bias_summaries"][0]["sample_count"] == 1
        assert calibration["calibration_metrics"][0]["sample_count"] == 1
        assert dashboard.status_code == 200
        assert "Market verification/actionability" in dashboard.text
        assert "Collector health/staleness" in dashboard.text
        assert "Regimes and intraday signals" in dashboard.text
        assert "Historical bias, calibration, outcomes" in dashboard.text
    finally:
        db_path.unlink(missing_ok=True)

def test_dashboard_renders_without_data(monkeypatch) -> None:
    db_path = _project_temp_db(monkeypatch)
    try:
        initialize_database(str(db_path))

        with TestClient(app) as client:
            dashboard_response = client.get("/dashboard")
            fusion_response = client.get("/api/fusion/summary")

        assert dashboard_response.status_code == 200
        assert "No data yet" in dashboard_response.text
        assert "No forecast model runs yet." in dashboard_response.text
        assert "No market snapshots yet." in dashboard_response.text
        assert "No sources configured" in dashboard_response.text
        summary = fusion_response.json()["summary"]
        assert summary["daily_high"] is None
        assert summary["model_spread"] is None
        assert summary["source_freshness"] == []
        assert summary["bucket_deltas"] == []
        assert summary["product_status"]["source_count"] == 0
    finally:
        db_path.unlink(missing_ok=True)


def test_script_syntax_validation() -> None:
    for script in (
        "scripts/run_local.sh",
        "scripts/seed_demo_data.sh",
        "scripts/check_tailscale_access.sh",
        "scripts/backup_sqlite.sh",
        "scripts/restore_sqlite.sh",
    ):
        result = subprocess.run(["bash", "-n", script], check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_cli_smoke_init_db_and_seed_demo_against_project_temp_db() -> None:
    db_path = _project_temp_db_path("test-cli-smoke")
    env = os.environ.copy()
    env["PYTHONPATH"] = "src" + (f":{env['PYTHONPATH']}" if env.get("PYTHONPATH") else "")
    env["KALSHI_TEMPS_DB"] = str(db_path)
    try:
        init_result = subprocess.run(
            [sys.executable, "-m", "kalshi_temps", "init-db"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert init_result.returncode == 0, init_result.stderr
        assert "Initialized database" in init_result.stdout
        assert db_path.exists()

        seed_result = subprocess.run(
            [sys.executable, "-m", "kalshi_temps", "seed-demo"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert seed_result.returncode == 0, seed_result.stderr
        assert "Seeded demo observations" in seed_result.stdout

        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            assert repo.list_observations()
            assert repo.fusion_summary()["bucket_deltas"]
    finally:
        db_path.unlink(missing_ok=True)
