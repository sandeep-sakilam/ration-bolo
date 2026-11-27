"""FastAPI application: routes, pages and startup."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import Settings, get_settings
from app.db import init_db, make_engine, make_sessionmaker
from app.seed import seed_if_empty

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    init_db(engine)
    factory = make_sessionmaker(engine)
    if settings.seed_demo:
        with factory() as db:
            seed_if_empty(db)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="Ration Bolo", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = factory

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/simulator")

    @app.get("/simulator", include_in_schema=False)
    def simulator() -> FileResponse:
        return FileResponse(STATIC_DIR / "simulator.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
