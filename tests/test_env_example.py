"""Every setting is listed in .env.example (Round 2 rule), and no .env is committed."""

import re
import subprocess
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent


def test_env_example_lists_every_setting() -> None:
    listed = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.M))
    missing = {name.upper() for name in Settings.model_fields} - listed
    assert not missing, f"add to .env.example: {sorted(missing)}"


def test_no_env_file_committed() -> None:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    assert not [f for f in files.splitlines() if f == ".env" or f.endswith("/.env")]
