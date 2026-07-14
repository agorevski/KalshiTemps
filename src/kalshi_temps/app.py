from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import connection, database_path, initialize_database
from .repository import WeatherRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(title="Kalshi Temps", version="0.1.0")
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=PROJECT_ROOT / "templates")


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


def health_payload() -> dict[str, str]:
    return {"status": "ok", "service": "kalshi-temps", "database": str(database_path())}


@app.get("/health/json")
def health_json() -> dict[str, str]:
    return health_payload()


@app.get("/health")
def health() -> dict[str, str]:
    return health_payload()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    with connection() as conn:
        repo = WeatherRepository(conn)
        observations = repo.list_observations(limit=12)
        sources = repo.list_sources()
        daily_high = repo.daily_high()
        model_runs = repo.list_model_runs(limit=8)
        model_spread = repo.latest_model_spread()
        marine_indicators = repo.list_marine_indicators(limit=4)
        market_snapshots = repo.list_market_snapshots(limit=6)
        events = repo.list_events(limit=6)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "observations": observations,
            "sources": sources,
            "daily_high": daily_high,
            "model_runs": model_runs,
            "model_spread": model_spread,
            "marine_indicators": marine_indicators,
            "market_snapshots": market_snapshots,
            "events": events,
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
