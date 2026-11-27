"""Outgoing messages and calls (SMS, WhatsApp, reminder calls).

Every send, mock or real, is written to the outbox shown on the dealer dashboard.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from app.models import Outbox, mask_phone


class Messenger(Protocol):
    name: str

    def send_sms(self, db: Session, to: str, body: str) -> Outbox: ...

    def send_whatsapp(
        self, db: Session, to: str, body: str, media_url: str | None = None
    ) -> Outbox: ...

    def place_call(self, db: Session, to: str, say: str, language: str) -> Outbox: ...


def record(db: Session, channel: str, to: str, body: str, status: str) -> Outbox:
    row = Outbox(channel=channel, to_masked=mask_phone(to), body=body, status=status)
    db.add(row)
    db.flush()
    return row


class MockMessenger:
    """Nothing leaves the server; messages land in the outbox marked "mock"."""

    name = "mock"

    def send_sms(self, db: Session, to: str, body: str) -> Outbox:
        return record(db, "sms", to, body, "mock")

    def send_whatsapp(
        self, db: Session, to: str, body: str, media_url: str | None = None
    ) -> Outbox:
        return record(
            db, "whatsapp", to, body + (f" [voice: {media_url}]" if media_url else ""), "mock"
        )

    def place_call(self, db: Session, to: str, say: str, language: str) -> Outbox:
        return record(db, "call", to, say, "mock")
