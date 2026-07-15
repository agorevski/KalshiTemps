from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import connection, database_path, initialize_database
from .ops import ops_status
from .repository import WeatherRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(title="Kalshi Temps", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=PROJECT_ROOT / "templates")


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


def health_payload() -> dict[str, str]:
    db_path = database_path()
    return {
        "status": "ok",
        "service": "kalshi-temps",
        "database": "configured" if db_path else "unknown",
        "database_file": db_path.name,
    }


@app.get("/health/json")
def health_json() -> dict[str, str]:
    return health_payload()


@app.get("/health")
def health() -> dict[str, str]:
    return health_payload()


@app.get("/api/ops/status")
def api_ops_status() -> dict[str, object]:
    status = ops_status()
    database = dict(status["database"])
    database.pop("path", None)
    disk = dict(status["disk"])
    disk.pop("path", None)
    return {"status": "ok", "ops": {"database": database, "disk": disk, "access": status["access"]}}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    with connection() as conn:
        repo = WeatherRepository(conn)
        observations = repo.list_observations(limit=12)
        sources = repo.list_sources()
        daily_high = repo.daily_high()
        model_runs = repo.list_model_runs(limit=8)
        model_spread = repo.latest_model_spread()
        model_spreads = repo.list_model_spread(limit=4)
        bucket_deltas = repo.bucket_probability_deltas()
        marine_indicators = repo.list_marine_indicators(limit=4)
        weather_regime_features = repo.list_weather_regime_features(limit=3)
        intraday_features = repo.list_intraday_features(limit=3)
        market_snapshots = repo.list_market_snapshots(limit=6)
        market_verification = repo.market_verification_summary()
        market_rules = repo.list_market_rules(limit=3)
        collector_health = repo.collector_health_summaries()
        outcomes = repo.list_official_outcomes(limit=5)
        prediction_snapshots = repo.list_prediction_snapshots(limit=5)
        bias_summaries = repo.list_bias_summaries(limit=5)
        calibration_metrics = repo.list_calibration_metrics(limit=5)
        events = repo.list_events(limit=6)
        fusion_summary = repo.fusion_summary()
        ops = api_ops_status()["ops"]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "observations": observations,
            "sources": sources,
            "daily_high": daily_high,
            "model_runs": model_runs,
            "model_spread": model_spread,
            "model_spreads": model_spreads,
            "bucket_deltas": bucket_deltas,
            "marine_indicators": marine_indicators,
            "weather_regime_features": weather_regime_features,
            "intraday_features": intraday_features,
            "market_snapshots": market_snapshots,
            "market_verification": market_verification,
            "market_rules": market_rules,
            "collector_health": collector_health,
            "outcomes": outcomes,
            "prediction_snapshots": prediction_snapshots,
            "bias_summaries": bias_summaries,
            "calibration_metrics": calibration_metrics,
            "events": events,
            "fusion_summary": fusion_summary,
            "ops": ops,
        },
    )


@app.get("/api/observations")
def api_observations(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with connection() as conn:
        observations = WeatherRepository(conn).list_observations(limit=limit)
    return {"observations": observations}


@app.get("/api/sources")
def api_sources() -> dict[str, object]:
    with connection() as conn:
        sources = WeatherRepository(conn).list_sources()
    return {"sources": sources}


@app.get("/api/fusion/summary")
def api_fusion_summary() -> dict[str, object]:
    with connection() as conn:
        summary = WeatherRepository(conn).fusion_summary()
    return {"summary": summary}


@app.get("/api/market-snapshots")
def api_market_snapshots(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with connection() as conn:
        snapshots = WeatherRepository(conn).list_market_snapshots(limit=limit)
    return {"market_snapshots": snapshots}


@app.get("/api/model-runs")
def api_model_runs(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with connection() as conn:
        model_runs = WeatherRepository(conn).list_model_runs(limit=limit)
    return {"model_runs": model_runs}


@app.get("/api/model-spread")
def api_model_spread(limit: int = Query(default=10, ge=1, le=100), target_date: str | None = None) -> dict[str, object]:
    with connection() as conn:
        repo = WeatherRepository(conn)
        spreads = repo.list_model_spread(limit=limit, target_date=target_date)
        latest = repo.latest_model_spread(target_date=target_date)
        bucket_deltas = repo.bucket_probability_deltas()
    return {"model_spreads": spreads, "latest_model_spread": latest, "bucket_deltas": bucket_deltas}


@app.get("/api/market/verification")
def api_market_verification(ticker: str | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with connection() as conn:
        repo = WeatherRepository(conn)
        verification = repo.market_verification_summary(ticker=ticker)
        rules = repo.list_market_rules(limit=limit)
    return {"market_verification": verification, "market_rules": rules}


@app.get("/api/collector/health")
def api_collector_health(
    limit: int = Query(default=20, ge=1, le=200),
    max_age_minutes: float = Query(default=180, ge=1),
) -> dict[str, object]:
    with connection() as conn:
        repo = WeatherRepository(conn)
        health = repo.collector_health_summaries(max_age_minutes=max_age_minutes)
        runs = repo.list_collector_runs(limit=limit)
    return {"collector_health": health, "collector_runs": runs}


@app.get("/api/weather/features")
def api_weather_features(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    with connection() as conn:
        repo = WeatherRepository(conn)
        regimes = repo.list_weather_regime_features(limit=limit)
        intraday = repo.list_intraday_features(limit=limit)
    return {
        "weather_regime_features": regimes,
        "intraday_features": intraday,
        "latest_weather_regime_features": regimes[0] if regimes else None,
        "latest_intraday_features": intraday[0] if intraday else None,
    }


@app.get("/api/calibration/summary")
def api_calibration_summary(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with connection() as conn:
        repo = WeatherRepository(conn)
        outcomes = repo.list_official_outcomes(limit=limit)
        snapshots = repo.list_prediction_snapshots(limit=limit)
        bias = repo.list_bias_summaries(limit=limit)
        calibration = repo.list_calibration_metrics(limit=limit)
    return {
        "official_outcomes": outcomes,
        "prediction_snapshots": snapshots,
        "bias_summaries": bias,
        "calibration_metrics": calibration,
    }
