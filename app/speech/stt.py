"""Speech-to-text adapters. Speech engines only hear; they never decide anything."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Transcript:
    text: str
    engine: str
    language: str | None = None
    confidence: float | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


class SpeechToText(Protocol):
    name: str

    def transcribe(self, wav: bytes, language_hints: list[str]) -> Transcript: ...


MOCK_PREFIX = b"MOCKTEXT:"


class MockSTT:
    """Keyless stand-in. Tests send 'audio' that is just ``MOCKTEXT:<words>``;
    anything else is heard as silence, so the fallback chain is exercised."""

    def __init__(self, name: str = "mock") -> None:
        self.name = name

    def transcribe(self, wav: bytes, language_hints: list[str]) -> Transcript:
        marker = wav.find(MOCK_PREFIX)
        if marker >= 0:
            text = wav[marker + len(MOCK_PREFIX) :].decode("utf-8", "ignore").strip("\x00 \n")
            return Transcript(text=text, engine=self.name, confidence=1.0)
        return Transcript(text="", engine=self.name, error="mock engine heard no text")
