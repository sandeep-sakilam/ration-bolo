"""Text-to-speech adapters for reply voice."""

from __future__ import annotations

from typing import Protocol


class TextToSpeech(Protocol):
    name: str

    def synthesize(self, text: str, language_code: str) -> bytes | None:
        """WAV bytes, or None when this engine can't speak (callers then fall back)."""
        ...


class MockTTS:
    """No server voice: the simulator uses the browser's speech synthesis and the
    phone line uses Twilio <Say>."""

    name = "mock"

    def synthesize(self, text: str, language_code: str) -> bytes | None:
        return None
