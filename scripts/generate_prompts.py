"""Pre-generate reply audio for every fixed prompt (phrases with no placeholders).

Needs SARVAM_API_KEY. Writes into AUDIO_CACHE_DIR so the phone line can <Play> them
without waiting for text-to-speech. Usage: python scripts/generate_prompts.py
"""

from __future__ import annotations

import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.packs import all_packs  # noqa: E402
from app.services import build_services  # noqa: E402


def main() -> int:
    services = build_services(get_settings())
    if services.tts.name == "mock":
        print("SARVAM_API_KEY not set: nothing to generate (replies use <Say> / browser voice).")
        return 0
    made = 0
    for pack in all_packs().values():
        for key, texts in pack.raw["phrases"].items():
            for lang, text in texts.items():
                if any(name for _, name, _, _ in string.Formatter().parse(text) if name):
                    continue
                code = pack.speech_code(lang, "sarvam")
                if services.voice.get(text, code):
                    made += 1
                    print(f"{pack.state}/{lang}/{key}")
    print(f"{made} prompts ready in {services.settings.audio_cache_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
