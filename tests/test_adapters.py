from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.messaging import MockMessenger
from app.config import Settings
from app.models import Outbox
from app.services import build_services
from app.speech.stt import MockSTT
from app.speech.tts import MockTTS


def test_status_without_keys_says_key_not_set(client: TestClient) -> None:
    data = client.get("/api/status").json()
    assert data["demo_data"] is True
    assert data["server_speech_to_text"] is False
    by_name = {s["service"]: s for s in data["services"]}
    assert by_name["speech_to_text"]["mode"] == "mock"
    assert "key not set: WISPR_API_KEY" in by_name["speech_to_text"]["note"]
    assert "key not set: SARVAM_API_KEY" in by_name["reply_voice"]["note"]
    assert data["channels"]["simulator"]["ready"] is True
    assert data["channels"]["phone"]["ready"] is False
    assert "PUBLIC_BASE_URL" in data["channels"]["phone"]["note"]
    assert "WISPR_API_KEY" in data["missing_keys"]


def test_keys_switch_services_to_real() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        wispr_api_key="x", sarvam_api_key="y", twilio_account_sid="AC1",
        twilio_auth_token="t", twilio_voice_number="+1555", public_base_url="https://x",
    )  # fmt: skip
    status = build_services(settings).status()
    by_name = {s["service"]: s for s in status["services"]}
    assert by_name["speech_to_text"]["mode"] == "real"
    assert by_name["voice_calls"]["ready"] is True
    assert status["channels"]["phone"]["ready"] is True
    assert status["channels"]["whatsapp"]["ready"] is False


def test_mock_mode_overrides_keys() -> None:
    settings = Settings(_env_file=None, wispr_api_key="x", speech_mode="mock")  # type: ignore[call-arg]
    assert settings.wispr_ready is False


def test_mock_stt_reads_marker_or_fails() -> None:
    stt = MockSTT()
    assert stt.transcribe(b"RIFF....MOCKTEXT:biyyam vachaya", ["te"]).text == "biyyam vachaya"
    heard = stt.transcribe(b"RIFF....", ["te"])
    assert not heard.ok and heard.error


def test_mock_tts_has_no_voice() -> None:
    assert MockTTS().synthesize("Namaskaram", "te-IN") is None


def test_mock_messenger_writes_masked_outbox(db: Session) -> None:
    m = MockMessenger()
    m.send_sms(db, "+919000004401", "hello")
    m.send_whatsapp(db, "whatsapp:+919000007702", "hi", media_url="https://x/audio/1")
    m.place_call(db, "+919000004401", "Bayaluderandi", "te")
    rows = db.scalars(select(Outbox).order_by(Outbox.id)).all()
    assert [r.channel for r in rows] == ["sms", "whatsapp", "call"]
    assert all(r.status == "mock" for r in rows)
    assert rows[0].to_masked == "+91 •••• ••4401"
    assert rows[1].to_masked == "+91 •••• ••7702"
