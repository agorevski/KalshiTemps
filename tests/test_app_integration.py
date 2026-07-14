from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import uuid

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalshi_temps.app import app  # noqa: E402
from kalshi_temps.db import connection, initialize_database  # noqa: E402
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

        seed_demo_data(str(db_path))
        with connection(str(db_path)) as conn:
            repo = WeatherRepository(conn)
            assert len(repo.list_sources()) >= 3
            assert len(repo.list_observations(limit=50)) >= 6
            assert len(repo.list_marine_indicators()) == 1
            assert len(repo.list_market_snapshots()) == 3
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
        assert {"daily_high", "model_spread", "source_freshness", "risk_guards", "bucket_deltas", "product_status"} <= set(fusion)
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
