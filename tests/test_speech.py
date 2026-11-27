from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.models import DialogueSession
from app.services import build_services
from app.speech import pipeline
from app.speech.audio import AudioError, to_wav16k
from app.speech.stt import MockSTT, SarvamSTT, WisprSTT
from app.speech.tts import ReplyVoice, SarvamTTS


def _make_audio(fmt: str, rate: int = 48000) -> bytes:
    args = ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=f=440:d=0.5:r={rate}"]
    codec = {"ogg": ["-c:a", "libopus"], "webm": ["-c:a", "libopus"], "wav": []}[fmt]
    out = subprocess.run([*args, *codec, "-f", fmt, "pipe:1"], capture_output=True, check=True)
    return out.stdout


@pytest.mark.parametrize(("fmt", "rate"), [("ogg", 48000), ("webm", 48000), ("wav", 8000)])
def test_converts_to_16k_mono_wav(fmt: str, rate: int) -> None:
    wav = to_wav16k(_make_audio(fmt, rate))
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    channels = int.from_bytes(wav[22:24], "little")
    sample_rate = int.from_bytes(wav[24:28], "little")
    assert (channels, sample_rate) == (1, 16000)


def test_bad_audio_raises() -> None:
    with pytest.raises(AudioError):
        to_wav16k(b"not audio at all")
    with pytest.raises(AudioError):
        to_wav16k(b"")


def test_wispr_request_and_response() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"text": "Biyyam vachaya", "detected_language": "te"})

    stt = WisprSTT(
        "k1",
        "https://wispr.test/api/v1/dash",
        6,
        ["biyyam"],
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    out = stt.transcribe(b"RIFFdata", ["te", "hi", "ur"])
    assert out.ok and out.text == "Biyyam vachaya" and out.language == "te"
    assert seen["url"] == "https://wispr.test/api/v1/dash/api"
    assert seen["auth"] == "Bearer k1"
    body = seen["body"]
    assert isinstance(body, dict)
    assert base64.b64decode(body["audio"]) == b"RIFFdata"
    assert body["language"] == ["te", "hi", "ur"]
    assert body["context"]["dictionary_context"] == ["biyyam"]


def test_wispr_timeout_is_a_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    stt = WisprSTT("k", "https://w", client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = stt.transcribe(b"x", ["te"])
    assert not out.ok and out.error == "wispr: ReadTimeout"


def test_sarvam_stt_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["api-subscription-key"]
        seen["body"] = request.content
        return httpx.Response(200, json={"transcript": "कितने लोग हैं", "language_code": "hi-IN"})

    stt = SarvamSTT(
        "s1",
        "https://sarvam.test",
        "saaras:v4",
        keyterms=["chawal"],
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    out = stt.transcribe(b"RIFF", ["te-IN", "hi-IN"])
    assert out.text == "कितने लोग हैं" and out.language == "hi"
    assert seen["key"] == "s1"
    body = seen["body"]
    assert isinstance(body, bytes)
    assert b'name="language_code"\r\n\r\nunknown' in body and b"saaras:v4" in body


def test_sarvam_error_is_a_failure() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert not SarvamSTT("s", "https://s", "m", client=client).transcribe(b"x", ["te-IN"]).ok


def test_sarvam_tts_and_cache(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"audios": [base64.b64encode(b"RIFFvoice").decode()]})

    tts = SarvamTTS(
        "s",
        "https://s",
        "bulbul:v3",
        "kavya",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    voice = ReplyVoice(tts, str(tmp_path))
    first = voice.get("Namaskaram", "te-IN")
    again = voice.get("Namaskaram", "te-IN")
    assert first and first == again and len(calls) == 1
    assert calls[0]["language_code"] == "te-IN" and calls[0]["speaker"] == "kavya"
    path = voice.path(first)
    assert path is not None and path.read_bytes() == b"RIFFvoice"
    assert voice.path("../../etc/passwd") is None


def test_no_voice_without_key(tmp_path: Path) -> None:
    services = build_services(Settings(_env_file=None, audio_cache_dir=str(tmp_path)))  # type: ignore[call-arg]
    assert services.voice.get("Namaskaram", "te-IN") is None


def _session(engine: str = "primary") -> DialogueSession:
    return DialogueSession(
        channel="simulator", state_pack="telangana", language="te", engine=engine, data={}
    )


def test_pipeline_uses_primary_then_backup() -> None:
    services = build_services(Settings(_env_file=None, speech_mode="mock"))  # type: ignore[call-arg]
    audio = b"MOCKTEXT:biyyam vachaya"
    assert pipeline.transcribe(services, _session(), audio).engine == "mock"
    backup = pipeline.transcribe(services, _session("backup"), audio)
    assert backup.engine == "mock-backup" and backup.text == "biyyam vachaya"


def test_pipeline_without_engines_fails_softly() -> None:
    services = build_services(Settings(_env_file=None))  # type: ignore[call-arg]
    out = pipeline.transcribe(services, _session(), b"MOCKTEXT:x")
    assert not out.ok and "no server speech-to-text" in (out.error or "")


def test_pipeline_bad_audio_is_a_failure() -> None:
    services = build_services(Settings(_env_file=None, speech_mode="mock"))  # type: ignore[call-arg]
    services.stt_primary = MockSTT()
    out = pipeline.transcribe(services, _session(), b"garbage")
    assert not out.ok


def test_keys_build_real_engines() -> None:
    services = build_services(
        Settings(_env_file=None, wispr_api_key="w", sarvam_api_key="s")  # type: ignore[call-arg]
    )
    assert services.stt_primary is not None and services.stt_primary.name == "wispr"
    assert services.stt_backup is not None and services.stt_backup.name == "sarvam"
    assert services.tts.name == "sarvam"


def test_audio_route(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/audio/" + "0" * 40).status_code == 404
    assert client.get("/audio/nope").status_code == 404
