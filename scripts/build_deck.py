"""Print docs/deck.html to docs/Ration-Bolo-Deck.pdf with Playwright's Chromium.

The deck is real text (judges read the text, not images).
Usage: python scripts/build_deck.py [--video URL] [--live URL]
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "deck.html"
TARGET = ROOT / "docs" / "Ration-Bolo-Deck.pdf"
FALLBACK_CHROMIUM = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", help="YouTube link for slide 11")
    parser.add_argument("--live", help="live link for slide 11")
    args = parser.parse_args()
    html = SOURCE.read_text(encoding="utf-8")
    if args.video:
        html = html.replace("[YouTube link — add before submitting]", args.video)
    if args.live:
        html = html.replace("[Railway URL — add before submitting]", args.live)
    with tempfile.TemporaryDirectory() as tmp:
        page_file = Path(tmp) / "deck.html"
        page_file.write_text(html, encoding="utf-8")
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(executable_path=FALLBACK_CHROMIUM)
            page = browser.new_page()
            page.goto(page_file.as_uri())
            page.pdf(
                path=str(TARGET),
                width="13.333in",
                height="7.5in",
                print_background=True,
                prefer_css_page_size=True,
            )
            browser.close()
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
