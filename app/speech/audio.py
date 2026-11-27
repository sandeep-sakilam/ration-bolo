"""Audio conversion with ffmpeg: browser WebM, WhatsApp OGG/Opus and 8 kHz call
recordings → 16 kHz mono 16-bit WAV. Audio stays in memory and is never stored."""

from __future__ import annotations

import shutil
import subprocess

from app.speech.stt import MOCK_PREFIX

MAX_BYTES = 25 * 1024 * 1024  # Wispr's per-request limit


class AudioError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def to_wav16k(data: bytes, timeout: float = 20.0) -> bytes:
    if not data:
        raise AudioError("empty audio")
    if len(data) > MAX_BYTES:
        raise AudioError("audio larger than 25 MB")
    if MOCK_PREFIX in data:  # test audio for the mock engine passes through untouched
        return data
    if not ffmpeg_available():
        raise AudioError("ffmpeg is not installed")
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-acodec",
                "pcm_s16le",
                "-t",
                "360",
                "-f",
                "wav",
                "pipe:1",
            ],
            input=data,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioError("audio conversion timed out") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise AudioError(f"could not convert audio: {proc.stderr.decode(errors='ignore')[:200]}")
    return proc.stdout
