"""SPEC "Done when" checks that run without a browser (the rest are in tests/e2e)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import queue
from app.channels.whatsapp import handle_message
from app.config import Settings
from app.models import Shop, Token
from app.services import build_services

ROOT = Path(__file__).resolve().parent.parent


def test_check3_whatsapp_handler_books_with_mock_adapter(db: Session) -> None:
    services = build_services(Settings(_env_file=None, speech_mode="mock"))  # type: ignore[call-arg]
    sender = "whatsapp:+919000004401"
    handle_message(db, services, sender, "Namaskaram", [])
    handle_message(db, services, sender, "Avunu", [])
    assert (
        handle_message(db, services, sender, "Repu poddhuna book cheyyandi", []).text
        == "Repu 10:20 ki, sare na?"
    )
    assert (
        "Booking ayindi. Mee token B-036. WhatsApp lo pampamu."
        in handle_message(db, services, sender, "Avunu", []).text
    )


def test_check4_paused_on_every_channel(db: Session) -> None:
    services = build_services(Settings(_env_file=None, speech_mode="mock"))  # type: ignore[call-arg]
    queue.set_status(db, db.scalars(select(Shop).where(Shop.code == "108")).one(), machine="down")
    db.commit()
    r = handle_message(db, services, "whatsapp:+919000007702", "Kal subah book karo", [])
    assert r.text.index("machine band hai") < r.text.index("booking ruki hai")
    assert (
        db.scalars(
            select(Token).where(
                Token.status == "booked", Token.card_id.is_not(None), Token.channel == "whatsapp"
            )
        ).first()
        is None
    )


def test_check10_more_than_300_lines_of_application_code() -> None:
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "count_loc.py")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    total = int(out.strip().splitlines()[-1].split()[-1])
    assert total > 300
