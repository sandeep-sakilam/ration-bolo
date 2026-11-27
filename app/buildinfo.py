"""Build identity (F25): which commit is this app built from?

Order: RAILWAY_GIT_COMMIT_SHA (Railway), GIT_SHA (Docker build argument), `git rev-parse`
when a checkout is present, else "unknown". Shown on /health, /api/status and every page
footer, so the live link can be matched to the repo's `main`.
"""

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


@lru_cache
def commit_sha() -> str:
    for var in ("RAILWAY_GIT_COMMIT_SHA", "GIT_SHA"):
        value = os.environ.get(var, "").strip().lower()
        if SHA_RE.match(value):
            return value
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        value = out.stdout.strip().lower()
        if out.returncode == 0 and SHA_RE.match(value):
            return value
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def build_info(repo_url: str) -> dict[str, str | None]:
    sha = commit_sha()
    known = sha != "unknown"
    return {
        "commit": sha,
        "short": sha[:7] if known else "unknown",
        "url": f"{repo_url.rstrip('/')}/commit/{sha}" if known else None,
    }
