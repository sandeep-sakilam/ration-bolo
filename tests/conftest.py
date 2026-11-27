"""Shared fixtures. Tests use SQLite by default; set TEST_DATABASE_URL to run on PostgreSQL."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import clock
from app.config import Settings
from app.db import Base, init_db, make_engine, make_sessionmaker
from app.main import create_app

# 27 Nov 2026, 11:00 IST: a weekday morning inside the first session.
FIXED_NOW = datetime(2026, 11, 27, 5, 30)


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[datetime]:
    clock.freeze(FIXED_NOW)
    yield FIXED_NOW
    clock.freeze(None)


@pytest.fixture
def db_url(tmp_path: Path) -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        engine = make_engine(url)
        Base.metadata.drop_all(engine)
        engine.dispose()
        yield url
    else:
        yield f"sqlite:///{tmp_path}/test.db"


@pytest.fixture
def settings(db_url: str) -> Settings:
    return Settings(database_url=db_url, scheduler_enabled=False, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    """A session on the same (seeded) database the client uses."""
    factory = client.app.state.sessionmaker  # type: ignore[attr-defined]
    with factory() as session:
        yield session


@pytest.fixture
def empty_db(db_url: str) -> Iterator[Session]:
    engine = make_engine(db_url)
    init_db(engine)
    with make_sessionmaker(engine)() as session:
        yield session
    engine.dispose()
