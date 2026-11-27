"""The real-adapter smoke script is never run here (it would call paid APIs); only its
committed test clip and its syntax are checked."""

import py_compile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_clip_is_16k_mono_wav() -> None:
    with wave.open(str(ROOT / "tests" / "fixtures" / "biyyam_vachaya_te.wav")) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert 1.0 < w.getnframes() / w.getframerate() < 6.0


def test_smoke_script_compiles() -> None:
    py_compile.compile(str(ROOT / "scripts" / "smoke_real.py"), doraise=True)
