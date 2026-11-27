"""Deck rules (F27): FAQ headings, no PIN line, numbers filled at build time, limits."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "docs" / "deck.html").read_text(encoding="utf-8")
spec = importlib.util.spec_from_file_location("build_deck", ROOT / "scripts" / "build_deck.py")
assert spec and spec.loader
build_deck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_deck)


@pytest.mark.parametrize(
    "heading",
    [
        "Addressable market",
        "Third-party dependencies: cost and availability risks",
        "Go-to-market plan",
        "Tech stack and why",
    ],
)
def test_faq_headings(heading: str) -> None:
    assert f"<h2>{heading}</h2>" in HTML


def test_no_pin_and_finale_features_present() -> None:
    assert "1234" not in HTML and "PIN (demo)" not in HTML
    for feature in ("Tamil Nadu", "one-time code", "Exotel", "CSV import", "WCAG 2.2 AA"):
        assert feature in HTML


def test_numbers_are_placeholders_filled_at_build() -> None:
    assert "147" not in HTML and "{{UNIT_TESTS}}" in HTML
    values = {
        "UNIT_TESTS": "9",
        "E2E_FLOWS": "8",
        "APP_LINES": "7",
        "PACK_COUNT": "2",
        "LANGUAGE_COUNT": "5",
        "COMMIT": "abc1234",
    }
    out = build_deck.render(HTML, values, "https://youtu.be/x", "https://live.example")
    assert "{{" not in out and "https://youtu.be/x" in out and "https://live.example" in out
    with pytest.raises(SystemExit):
        build_deck.render(HTML, {}, None, None)


def test_pdf_limits(tmp_path: Path) -> None:
    pdf = ROOT / "docs" / "Ration-Bolo-Deck.pdf"
    pages, size = build_deck.check_limits(pdf)
    assert 1 <= pages <= 30 and size <= 10 * 1024 * 1024
    big = tmp_path / "big.pdf"
    big.write_bytes(b"/Type /Page\n" * 31)
    with pytest.raises(SystemExit):
        build_deck.check_limits(big)


def test_v3_risks_present() -> None:
    for risk in (
        "Level 0 is information, not enforcement",
        "can be wrong or gamed",
        "Public PDS data formats differ",
        "Portability",
        "depend on officials",
    ):
        assert risk in HTML, risk
