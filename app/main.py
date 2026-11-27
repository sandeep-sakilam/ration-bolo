"""FastAPI application: routes, pages and startup."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app import admin as admin_module
from app.channels import dealer as dealer_channel
from app.channels import simulator as simulator_channel
from app.channels import voice as voice_channel
from app.channels import whatsapp as whatsapp_channel
from app.config import Settings, get_settings
from app.db import init_db, make_engine, make_sessionmaker
from app.metrics import compute as compute_metrics
from app.packs import all_packs
from app.reminders import dashboard_rows, start_scheduler
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

    services = build_services(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        scheduler = start_scheduler(factory, services) if settings.scheduler_enabled else None
        yield
        if scheduler:
            scheduler.shutdown(wait=False)
        engine.dispose()

    app = FastAPI(title="Ration Bolo", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(GZipMiddleware, minimum_size=500)

    @app.middleware("http")
    async def cache_static(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith(("/static/", "/audio/")):
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        return response

    app.state.packs = packs
    app.state.services = services
    app.state.dealer_extras = dashboard_rows
    app.state.engine = engine
    app.state.sessionmaker = factory

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/status")
    def status() -> dict[str, object]:
        result: dict[str, object] = app.state.services.status()
        return result

    @app.get("/audio/{audio_id}", include_in_schema=False)
    def audio(audio_id: str) -> FileResponse:
        """Reply audio (never caller audio) for <Play>, WhatsApp and the simulator."""
        stem, _, ext = audio_id.partition(".")
        fmt = ext or "wav"
        path = app.state.services.voice.path(stem, fmt)
        if path is None or not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="audio/ogg" if fmt == "ogg" else "audio/wav")

    @app.get("/api/metrics")
    def metrics(days: int = 7) -> dict[str, object]:
        with factory() as db:
            return compute_metrics(db, max(1, min(days, 90)))

    @app.get("/metrics", include_in_schema=False)
    def metrics_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "metrics.html")

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
            for p in sorted(packs.values(), key=lambda p: (p.is_draft, p.name))
        ]

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/simulator")

    @app.get("/simulator", include_in_schema=False)
    def simulator() -> FileResponse:
        return FileResponse(STATIC_DIR / "simulator.html")

    app.include_router(simulator_channel.router)
    app.include_router(dealer_channel.router)
    app.include_router(admin_module.router)

    @app.get("/admin", include_in_schema=False)
    def admin_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "admin.html")

    app.include_router(voice_channel.router)
    app.include_router(whatsapp_channel.router)

    @app.get("/dealer", include_in_schema=False)
    def dealer_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "dealer.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
