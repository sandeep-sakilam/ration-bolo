"""Speech-to-text adapters. Speech engines only hear; they never decide anything."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Protocol

import httpx


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


def describe_error(exc: Exception) -> str:
    """Error name plus HTTP status and the start of the provider's message (no secrets:
    request headers are never included)."""
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text.strip().replace("\n", " ")[:200]
        return f"HTTP {exc.response.status_code} {body}".strip()
    return type(exc).__name__


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


class WisprSTT:
    """Wispr Flow REST API: base64 16 kHz mono WAV, language hints from the pack."""

    name = "wispr"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float = 6.0,
        dictionary: list[str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key, self.base_url, self.timeout = api_key, base_url.rstrip("/"), timeout
        self.dictionary = dictionary or []
        self.client = client or httpx.Client()

    def transcribe(self, wav: bytes, language_hints: list[str]) -> Transcript:
        body = {
            "audio": base64.b64encode(wav).decode("ascii"),
            "language": language_hints,
            "context": {"app": {"type": "other"}, "dictionary_context": self.dictionary[:100]},
        }
        try:
            resp = self.client.post(
                f"{self.base_url}/api",
                json=body,
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return Transcript(text="", engine=self.name, error=f"wispr: {describe_error(exc)}")
        lang = data.get("detected_language")
        return Transcript(text=str(data.get("text") or ""), engine=self.name, language=lang)


class SarvamSTT:
    """Sarvam AI speech-to-text REST (clips under ~30 s)."""

    name = "sarvam"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 6.0,
        keyterms: list[str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.timeout, self.keyterms = timeout, keyterms or []
        self.client = client or httpx.Client()

    def transcribe(self, wav: bytes, language_hints: list[str]) -> Transcript:
        # One hint pins the language; several mean "detect it".
        language = language_hints[0] if len(language_hints) == 1 else "unknown"
        form = {"model": self.model, "language_code": language}
        if self.keyterms and self.model.startswith("saaras:v4"):
            form["keyterms"] = json.dumps(self.keyterms[:50], ensure_ascii=False)
        try:
            resp = self.client.post(
                f"{self.base_url}/speech-to-text",
                data=form,
                timeout=self.timeout,
                files={"file": ("audio.wav", wav, "audio/wav")},
                headers={"api-subscription-key": self.api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return Transcript(text="", engine=self.name, error=f"sarvam: {describe_error(exc)}")
        code = data.get("language_code") or ""
        return Transcript(
            text=str(data.get("transcript") or ""),
            engine=self.name,
            language=code.split("-")[0] or None,
        )
