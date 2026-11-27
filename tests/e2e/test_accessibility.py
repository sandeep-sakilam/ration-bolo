"""Accessibility (WCAG 2.2 AA, automated part via axe-core) and low-bandwidth checks."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page, expect

TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
AXE = Axe()


def _violations(page: Page) -> list[str]:
    result = AXE.run(page, options={"runOnly": {"type": "tag", "values": TAGS}})
    return [f"{v['id']}: {v['nodes'][0]['target']}" for v in result.response["violations"]]


@pytest.mark.parametrize("path", ["/simulator", "/dealer", "/metrics", "/admin"])
def test_pages_have_no_axe_violations(page: Page, path: str) -> None:
    page.goto(path)
    page.wait_for_load_state("networkidle")
    assert _violations(page) == []


def test_simulator_in_call_and_dashboard_have_no_violations(page: Page, reset: None) -> None:
    page.goto("/simulator")
    page.click("#start")
    expect(page.locator("#log .bubble.app")).to_have_count(1)
    page.click("#toggle-keypad")
    assert _violations(page) == []
    page.goto("/dealer")
    expect(page.locator("#dash")).to_be_visible()
    assert _violations(page) == []


def test_simulator_works_by_keyboard_only(page: Page, reset: None) -> None:
    page.goto("/simulator")
    page.focus("#caller")
    for _ in range(20):
        if page.evaluate("document.activeElement.id") == "start":
            break
        page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    expect(page.locator("#log .bubble.app").first).to_contain_text("0421")
    page.focus("#textbox")
    page.keyboard.type("Avunu")
    page.keyboard.press("Enter")
    expect(page.locator("#log .bubble.app").last).to_contain_text("sahayam")
    assert page.locator("#log .bubble.app").first.get_attribute("lang") == "te-IN"


@pytest.mark.parametrize("path", ["/simulator", "/dealer", "/metrics", "/admin"])
def test_pages_are_light_and_self_contained(page: Page, server: str, path: str) -> None:
    sizes: dict[str, int] = {}

    def on_response(response) -> None:  # type: ignore[no-untyped-def]
        sizes[response.url] = len(response.body()) if response.ok else 0

    page.on("response", on_response)
    page.goto(path)
    page.wait_for_load_state("networkidle")
    host = urlparse(server).netloc
    assert all(urlparse(u).netloc == host for u in sizes), "no third-party requests"
    static = sum(v for u, v in sizes.items() if "/api/" not in u)
    assert static < 80_000, f"{path} loads {static} bytes of HTML/CSS/JS"
