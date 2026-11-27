"""End-to-end fixtures: a real server process on a free port and a headless Chromium."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FALLBACK_CHROMIUM = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    port = _free_port()
    data = tmp_path_factory.mktemp("e2e")
    env = {
        **os.environ,
        "DATABASE_URL": os.environ.get("E2E_DATABASE_URL", f"sqlite:///{data}/e2e.db"),
        "AUDIO_CACHE_DIR": str(data / "audio"),
        "SPEECH_MODE": "auto",
        "MESSAGING_MODE": "mock",
        # Freeze the server clock at 11:00 IST today so time-of-day never changes the flows.
        "RATION_BOLO_NOW": datetime.now(UTC)
        .replace(hour=5, minute=30, second=0, microsecond=0)
        .isoformat(),
    }
    for key in ("WISPR_API_KEY", "SARVAM_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"):
        env.pop(key, None)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "app.main:create_app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=env,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/health", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("server did not start")
    yield base
    proc.terminate()
    proc.wait(10)


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            b = p.chromium.launch(executable_path=FALLBACK_CHROMIUM)
        yield b
        b.close()


@pytest.fixture
def page(browser: Browser, server: str) -> Iterator[Page]:
    context = browser.new_context(base_url=server)
    pg = context.new_page()
    yield pg
    context.close()


@pytest.fixture
def reset(server: str) -> None:
    """Restore the demo data before a test."""
    req = urllib.request.Request(
        server + "/api/dealer/reset", method="POST", headers={"X-Dealer-Pin": "1234"}
    )
    urllib.request.urlopen(req, timeout=10)
