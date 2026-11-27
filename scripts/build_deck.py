"""Print docs/deck.html to docs/Ration-Bolo-Deck.pdf with Playwright's Chromium.

The deck is real text (judges read the text, not images). Numbers such as the test
count are computed here at build time, never typed by hand. The build fails if the PDF
is over 30 pages or 10 MB (Round 2 limits).

Usage: python scripts/build_deck.py [--video URL] [--live URL]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "deck.html"
TARGET = ROOT / "docs" / "Ration-Bolo-Deck.pdf"
FALLBACK_CHROMIUM = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"
MAX_PAGES = 30
MAX_BYTES = 10 * 1024 * 1024
VIDEO_PLACEHOLDER = "[YouTube link — add before submitting]"
LIVE_PLACEHOLDER = "[Railway URL — add before submitting]"


def _collected(path: str) -> int:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", path, "--collect-only", "-q", "-o", "addopts="],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    count = sum(1 for line in out.stdout.splitlines() if "::" in line)
    if count == 0:
        raise SystemExit(
            f"could not count tests in {path}:\n{out.stdout[-500:]}{out.stderr[-500:]}"
        )
    return count


def stats() -> dict[str, str]:
    unit = _collected("tests") - _collected("tests/e2e")
    e2e = _collected("tests/e2e")
    loc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "count_loc.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines = int(loc.strip().splitlines()[-1].split()[-1])
    sys.path.insert(0, str(ROOT))
    from app.packs import load_packs

    packs = load_packs()
    languages = {code for p in packs.values() for code in p.languages}
    sha = (
        subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        or "unknown"
    )
    return {
        "UNIT_TESTS": str(unit),
        "E2E_FLOWS": str(e2e),
        "APP_LINES": f"{lines:,}",
        "PACK_COUNT": str(len(packs)),
        "LANGUAGE_COUNT": str(len(languages)),
        "COMMIT": sha,
    }


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf))


def check_limits(pdf_path: Path) -> tuple[int, int]:
    data = pdf_path.read_bytes()
    pages, size = page_count(data), len(data)
    if pages > MAX_PAGES or size > MAX_BYTES:
        raise SystemExit(
            f"deck too big: {pages} pages, {size / 1e6:.1f} MB "
            f"(limits {MAX_PAGES} pages, {MAX_BYTES // (1024 * 1024)} MB)"
        )
    return pages, size


def render(html: str, values: dict[str, str], video: str | None, live: str | None) -> str:
    for key, value in values.items():
        html = html.replace("{{" + key + "}}", value)
    left = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if left:
        raise SystemExit(f"unfilled deck values: {sorted(set(left))}")
    if video:
        html = html.replace(VIDEO_PLACEHOLDER, video)
    if live:
        html = html.replace(LIVE_PLACEHOLDER, live)
    return html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", help="YouTube link (public or unlisted)")
    parser.add_argument("--live", help="live link (no login wall)")
    args = parser.parse_args()
    if args.video and not re.match(r"^https://(www\.)?(youtube\.com|youtu\.be)/", args.video):
        raise SystemExit("--video must be a YouTube link (Vimeo and Drive are rejected)")
    values = stats()
    html = render(SOURCE.read_text(encoding="utf-8"), values, args.video, args.live)
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
    pages, size = check_limits(TARGET)
    print(
        f"wrote {TARGET.relative_to(ROOT)}: {pages} pages, {size / 1024:.0f} KB "
        f"(limits {MAX_PAGES} pages, 10 MB) · {values}"
    )
    if not args.video or not args.live:
        print(
            "note: video/live placeholders kept; rebuild with --video and --live before submitting"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
