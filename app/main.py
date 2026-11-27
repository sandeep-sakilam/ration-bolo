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
from app.packs import all_packs
from app.seed import seed_if_empty
from app.services import build_services

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    packs = all_packs()  # a broken pack stops startup with a clear error
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
    app.state.packs = packs
    app.state.services = build_services(settings)
    app.state.engine = engine
    app.state.sessionmaker = factory

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/status")
    def status() -> dict[str, object]:
        result: dict[str, object] = app.state.services.status()
        return result

    @app.get("/api/packs")
    def packs_list() -> list[dict[str, object]]:
        return [
            {
                "state": p.state,
                "name": p.name,
                "draft": p.is_draft,
                "languages": [
                    {"code": c, "name": lang["name"], "browser": lang["browser"]}
                    for c, lang in p.languages.items()
                ],
            }
            for p in packs.values()
        ]

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/simulator")

    @app.get("/simulator", include_in_schema=False)
    def simulator() -> FileResponse:
        return FileResponse(STATIC_DIR / "simulator.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
