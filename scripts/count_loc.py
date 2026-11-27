"""Count non-blank, non-comment lines of application code (outside tests and config).

Acceptance check 10: more than 300 lines must exist. Usage: python scripts/count_loc.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {"app": ("*.py", "*.js", "*.html", "*.css")}


def count(path: Path) -> int:
    lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith(("#", "//")):
            lines += 1
    return lines


def main() -> int:
    total = 0
    for folder, patterns in SOURCES.items():
        for pattern in patterns:
            for path in sorted((ROOT / folder).rglob(pattern)):
                n = count(path)
                total += n
                print(f"{n:6d}  {path.relative_to(ROOT)}")
    print(f"total application lines: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
