from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import uuid

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps import cli  # noqa: E402
from kalshi_temps.app import app  # noqa: E402
from kalshi_temps.cli import collect_and_save_forecast_discussion, collect_and_save_metar  # noqa: E402
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


def test_new_app_endpoints_return_expected_shapes(monkeypatch) -> None:
    db_path = _project_temp_db(monkeypatch)
    try:
        seed_demo_data(str(db_path))

        with TestClient(app) as client:
            root_response = client.get("/", follow_redirects=False)
            health_response = client.get("/health")
            health_json_response = client.get("/health/json")
            observations_response = client.get("/api/observations?limit=3")
            sources_response = client.get("/api/sources")
            fusion_response = client.get("/api/fusion/summary")
            snapshots_response = client.get("/api/market-snapshots?limit=2")
            model_runs_response = client.get("/api/model-runs?limit=2")
            dashboard_response = client.get("/dashboard")

        assert root_response.status_code in {307, 308}
        assert root_response.headers["location"] == "/dashboard"
        assert health_response.status_code == 200
        assert health_response.json()["status"] == "ok"
        assert health_json_response.json()["service"] == "kalshi-temps"
        assert observations_response.status_code == 200
        assert len(observations_response.json()["observations"]) == 3
        assert sources_response.status_code == 200
        assert sources_response.json()["sources"]
        assert fusion_response.status_code == 200
        assert snapshots_response.status_code == 200
        assert model_runs_response.status_code == 200
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
        assert "Research view" in dashboard_response.text
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
