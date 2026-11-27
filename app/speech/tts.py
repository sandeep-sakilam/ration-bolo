"""Text-to-speech adapters for reply voice."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Protocol

import httpx


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


class SarvamTTS:
    """Sarvam AI Bulbul text-to-speech. Returns WAV bytes."""

    name = "sarvam"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        speaker: str,
        timeout: float = 6.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key, self.base_url = api_key, base_url.rstrip("/")
        self.model, self.speaker, self.timeout = model, speaker, timeout
        self.client = client or httpx.Client()

    def synthesize(self, text: str, language_code: str) -> bytes | None:
        body = {
            "text": text[:2500],
            "language_code": language_code,
            "model": self.model,
            "speaker": self.speaker,
            "speech_sample_rate": 16000,
        }
        try:
            resp = self.client.post(
                f"{self.base_url}/text-to-speech",
                json=body,
                timeout=self.timeout,
                headers={"api-subscription-key": self.api_key},
            )
            resp.raise_for_status()
            audios = resp.json().get("audios") or []
            return base64.b64decode(audios[0]) if audios else None
        except (httpx.HTTPError, ValueError, IndexError):
            return None


class ReplyVoice:
    """Reply audio cached by text and language, so each sentence is synthesised once.

    Fixed prompts (phrases with no placeholders) can be generated ahead of time with
    ``scripts/generate_prompts.py``; they land in the same cache.
    """

    ID_RE = re.compile(r"^[0-9a-f]{40}$")

    def __init__(self, tts: TextToSpeech, cache_dir: str) -> None:
        self.tts = tts
        self.dir = Path(cache_dir)

    @staticmethod
    def audio_id(text: str, language_code: str) -> str:
        return hashlib.sha1(f"{language_code}|{text}".encode()).hexdigest()

    def path(self, audio_id: str) -> Path | None:
        if not self.ID_RE.match(audio_id):
            return None
        return self.dir / f"{audio_id}.wav"

    def get(self, text: str, language_code: str) -> str | None:
        """Audio id for this reply (synthesising it if needed), or None if no voice."""
        if not text:
            return None
        audio_id = self.audio_id(text, language_code)
        path = self.dir / f"{audio_id}.wav"
        if path.exists():
            return audio_id
        audio = self.tts.synthesize(text, language_code)
        if not audio:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return audio_id
