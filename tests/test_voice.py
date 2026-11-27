from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from twilio.request_validator import RequestValidator

from app.channels.messaging import TwilioMessenger
from app.config import Settings
from app.main import create_app
from app.models import Outbox
from app.ratelimit import RateLimiter

LAKSHMI = "+919000004401"


class Recordings:
    """Fake Twilio media host: each recording URL 'contains' some speech."""

    def __init__(self) -> None:
        self.speech: dict[str, str] = {}
        self.deleted: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "DELETE":
            self.deleted.append(url)
            return httpx.Response(204)
        key = url.removesuffix(".wav")
        return httpx.Response(200, content=b"RIFF....MOCKTEXT:" + self.speech[key].encode())


@pytest.fixture
def call(db_url: str) -> Iterator[tuple[TestClient, Recordings]]:
    settings = Settings(
        _env_file=None,
        database_url=db_url,
        scheduler_enabled=False,  # type: ignore[call-arg]
        speech_mode="mock",
    )
    app = create_app(settings)
    recs = Recordings()
    app.state.services.http = httpx.Client(transport=httpx.MockTransport(recs.handler))
    with TestClient(app) as client:
        yield client, recs


def answer(client: TestClient, recs: Recordings, n: int, text: str, sid: str = "CA1") -> str:
    url = f"https://api.twilio.com/2010-04-01/Accounts/AC1/Recordings/RE{n}"
    recs.speech[url] = text
    form = {"CallSid": sid, "From": LAKSHMI, "RecordingUrl": url, "RecordingDuration": "3"}
    return client.post("/twilio/voice/recording", data=form).text


def test_call_flow_book_by_voice(call: tuple[TestClient, Recordings]) -> None:
    client, recs = call
    xml = client.post("/twilio/voice", data={"CallSid": "CA1", "From": LAKSHMI}).text
    assert "Card chivari ankelu 0421, sare na?" in xml
    assert 'voice="Google.te-IN-Standard-A"' in xml and 'language="te-IN"' in xml
    assert '<Record action="http://testserver/twilio/voice/recording"' in xml
    assert 'timeout="8"' in xml and 'maxLength="15"' in xml
    assert "Meeku ela sahayam cheyali?" in answer(client, recs, 1, "Avunu")
    assert "Repu 10:20 ki, sare na?" in answer(client, recs, 2, "Repu poddhuna book cheyyandi")
    xml = answer(client, recs, 3, "Avunu")
    assert "Booking ayindi. Mee token B-036" in xml
    assert len(recs.deleted) == 0  # no Twilio keys → nothing to delete remotely
    xml = answer(client, recs, 4, "chalu")
    assert "<Hangup />" in xml


def test_silence_and_menu_by_keypad(call: tuple[TestClient, Recordings]) -> None:
    client, recs = call
    client.post("/twilio/voice", data={"CallSid": "CA2", "From": LAKSHMI})
    answer(client, recs, 1, "Avunu", "CA2")
    answer(client, recs, 2, "blah", "CA2")
    answer(client, recs, 3, "blah", "CA2")
    xml = answer(client, recs, 4, "blah", "CA2")
    assert '<Gather action="http://testserver/twilio/voice/digits"' in xml
    assert 'input="dtmf"' in xml and "Stock kosam 1" in xml
    xml = client.post(
        "/twilio/voice/digits", data={"CallSid": "CA2", "From": LAKSHMI, "Digits": "2"}
    ).text
    assert "18 mandi mundu unnaru" in xml
    xml = client.post("/twilio/voice/silence", data={"CallSid": "CA2", "From": LAKSHMI}).text
    assert "Meeru vintunnara?" in xml
    xml = client.post("/twilio/voice/silence", data={"CallSid": "CA2", "From": LAKSHMI}).text
    assert "<Hangup />" in xml


def test_hangup_status_ends_session(call: tuple[TestClient, Recordings]) -> None:
    client, recs = call
    client.post("/twilio/voice", data={"CallSid": "CA3", "From": LAKSHMI})
    answer(client, recs, 1, "Avunu", "CA3")
    answer(client, recs, 2, "Repu poddhuna book cheyyandi", "CA3")
    answer(client, recs, 3, "Avunu", "CA3")
    r = client.post("/twilio/voice/status", data={"CallSid": "CA3", "CallStatus": "completed"})
    assert r.status_code == 204


def test_unknown_caller_gets_digit_prompt(call: tuple[TestClient, Recordings]) -> None:
    client, _ = call
    xml = client.post("/twilio/voice", data={"CallSid": "CA4", "From": "+15550001111"}).text
    assert "okko anke cheppandi" in xml


def test_signature_required_when_keys_set(db_url: str) -> None:
    settings = Settings(
        _env_file=None,
        database_url=db_url,
        scheduler_enabled=False,  # type: ignore[call-arg]
        twilio_auth_token="secret",
        twilio_account_sid="AC1",
        public_base_url="https://rb.example.com",
        messaging_mode="mock",
    )
    with TestClient(create_app(settings)) as client:
        form = {"CallSid": "CA9", "From": LAKSHMI}
        assert client.post("/twilio/voice", data=form).status_code == 403
        sig = RequestValidator("secret").compute_signature(
            "https://rb.example.com/twilio/voice", form
        )
        ok = client.post("/twilio/voice", data=form, headers={"X-Twilio-Signature": sig})
        assert ok.status_code == 200
        assert "https://rb.example.com/twilio/voice/recording" in ok.text
        bad = client.post("/twilio/voice", data=form, headers={"X-Twilio-Signature": "x"})
        assert bad.status_code == 403


class FakeTwilio:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail
        self.messages = self
        self.calls = self

    def create(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.sent.append(kwargs)


def test_twilio_messenger_sends_and_records(db: Session) -> None:
    fake = FakeTwilio()
    voices = {"te": {"voice": "Google.te-IN-Standard-A", "language": "te-IN"}}
    m = TwilioMessenger(
        "AC", "t", "+15550001", "whatsapp:+14155238886", "+15550002", voices, client=fake
    )
    assert m.send_sms(db, LAKSHMI, "token B-036").status == "sent"
    m.send_whatsapp(db, LAKSHMI, "hi", media_url="https://x/audio/1.wav")
    m.place_call(db, LAKSHMI, "Bayaluderandi", "te")
    assert fake.sent[0] == {"to": LAKSHMI, "body": "token B-036", "from_": "+15550001"}
    assert fake.sent[1]["to"] == "whatsapp:" + LAKSHMI and fake.sent[1]["media_url"]
    assert "Google.te-IN-Standard-A" in fake.sent[2]["twiml"]
    failing = TwilioMessenger("AC", "t", "+1", "", "", {}, client=FakeTwilio(fail=True))
    assert failing.send_sms(db, LAKSHMI, "x").status == "failed"
    assert failing.send_whatsapp(db, LAKSHMI, "x").status == "mock"  # no WhatsApp sender
    rows = db.scalars(select(Outbox)).all()
    assert all("4401" in r.to_masked for r in rows)


def test_rate_limiter() -> None:
    rl = RateLimiter(limit=2, window_seconds=60)
    assert rl.allow("a", 0) and rl.allow("a", 1) and not rl.allow("a", 2)
    assert rl.allow("a", 61)
    assert rl.allow("b", 2)
