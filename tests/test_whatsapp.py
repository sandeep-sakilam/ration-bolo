from __future__ import annotations

import io
import subprocess
import wave
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.channels.whatsapp import handle_message
from app.config import Settings
from app.main import create_app
from app.models import Outbox, Shop, Token
from app.services import Services, build_services

SALMA = "whatsapp:+919000007702"
LAKSHMI = "whatsapp:+919000004401"


def notes(mapping: dict[str, str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"OggS....MOCKTEXT:" + mapping[str(request.url)].encode()
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def services() -> Services:
    return build_services(Settings(_env_file=None, speech_mode="mock"))  # type: ignore[call-arg]


def test_booking_by_voice_notes(db: Session, services: Services) -> None:
    urls = {
        f"https://media/{i}": t
        for i, t in enumerate(["Mera ration aaya kya?", "Kal subah book karo", "haan"])
    }
    services.http = notes(urls)
    media = [[(u, "audio/ogg")] for u in urls]
    r = handle_message(db, services, SALMA, "", media[0])
    assert r.text.startswith("Namaste, Ration Bolo. Card ke aakhri ank 0513, theek hai?")
    assert "Haan, chawal aa gaya hai. Aapke parivaar ke liye 18 kilo." in r.text
    assert handle_message(db, services, SALMA, "", media[1]).text == "Kal 10:20 baje, theek hai?"
    r = handle_message(db, services, SALMA, "", media[2])
    assert "Booking ho gayi. Aapka token B-036. WhatsApp par bheja hai." in r.text
    token = db.scalars(
        select(Token).where(Token.channel == "whatsapp", Token.status == "booked")
    ).one()
    assert token.card is not None and token.card.last4 == "0513"
    sent = db.scalars(select(Outbox).where(Outbox.channel == "whatsapp")).all()
    assert any("B-036" in o.body for o in sent)


def test_booking_by_text_messages(db: Session, services: Services) -> None:
    assert "0421, sare na?" in handle_message(db, services, LAKSHMI, "Namaskaram", []).text
    handle_message(db, services, LAKSHMI, "Avunu", [])
    assert (
        handle_message(db, services, LAKSHMI, "Repu poddhuna book cheyyandi", []).text
        == "Repu 10:20 ki, sare na?"
    )
    assert "Booking ayindi" in handle_message(db, services, LAKSHMI, "1", []).text


def test_numbered_menu_fallback(db: Session, services: Services) -> None:
    handle_message(db, services, LAKSHMI, "hi", [])
    handle_message(db, services, LAKSHMI, "Avunu", [])
    for _ in range(2):
        handle_message(db, services, LAKSHMI, "???", [])
    r = handle_message(db, services, LAKSHMI, "???", [])
    assert r.text.startswith("Number pampandi: 1 Stock, 2 Line, 3 Booking, 4 Takkuva ration.")
    assert "18 mandi" in handle_message(db, services, LAKSHMI, "2", []).text


def test_machine_down_refused_on_whatsapp(db: Session, services: Services) -> None:
    shop = db.scalars(select(Shop)).one()
    shop.status_machine = "down"
    db.commit()
    r = handle_message(db, services, SALMA, "Kal subah book karo", [])
    assert "machine band hai" in r.text and "booking ruki hai" in r.text.lower()
    booked = select(Token).where(Token.channel == "whatsapp", Token.status == "booked")
    assert db.scalars(booked).first() is None


def test_new_session_after_30_minutes(db: Session, services: Services) -> None:
    handle_message(db, services, LAKSHMI, "hi", [])
    clock.freeze(clock.now_utc() + timedelta(minutes=31))
    assert "Namaskaram" in handle_message(db, services, LAKSHMI, "hi", []).text


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)
    return buf.getvalue()


class FakeTTS:
    name = "fake"

    def synthesize(self, text: str, language_code: str) -> bytes | None:
        return _wav()


@pytest.fixture
def wa_client(db_url: str, tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        database_url=db_url,
        scheduler_enabled=False,  # type: ignore[call-arg]
        public_base_url="https://rb.example.com",
        audio_cache_dir=str(tmp_path),
    )
    app = create_app(settings)
    app.state.services.tts = FakeTTS()
    with TestClient(app) as client:
        yield client


def test_webhook_replies_with_voice_note_and_text(wa_client: TestClient) -> None:
    xml = wa_client.post(
        "/twilio/whatsapp", data={"From": LAKSHMI, "Body": "biyyam vachaya", "NumMedia": "0"}
    ).text
    assert "<Message><Body>Namaskaram, Ration Bolo." in xml
    assert "<Media>https://rb.example.com/audio/" in xml and ".ogg</Media>" in xml
    media = xml.split("<Media>https://rb.example.com")[1].split("</Media>")[0]
    audio = wa_client.get(media)
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/ogg"
    assert audio.content[:4] == b"OggS"
    assert (
        subprocess.run(["ffprobe", "-v", "error", "-"], input=audio.content, check=False).returncode
        == 0
    )
