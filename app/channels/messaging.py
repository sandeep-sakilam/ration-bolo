"""Outgoing messages and calls (SMS, WhatsApp, reminder calls).

Every send, mock or real, is written to the outbox shown on the dealer dashboard.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from sqlalchemy.orm import Session
from twilio.twiml.voice_response import VoiceResponse

from app.models import Outbox, mask_phone

log = logging.getLogger("ration_bolo.messaging")


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


class TwilioMessenger:
    """Real sends through Twilio. Used only when Twilio keys are set; failures are
    recorded in the outbox as "failed" and never raise into the caller's flow."""

    name = "twilio"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        sms_from: str,
        whatsapp_from: str,
        voice_from: str,
        voices: dict[str, dict[str, str]],
        client: Any | None = None,
    ) -> None:
        self.sms_from, self.whatsapp_from, self.voice_from = sms_from, whatsapp_from, voice_from
        self.voices = voices
        if client is None:
            from twilio.rest import Client

            client = Client(account_sid, auth_token)
        self.client = client

    def _send(self, db: Session, channel: str, to: str, body: str, **kwargs: Any) -> Outbox:
        try:
            if channel == "call":
                self.client.calls.create(to=to, from_=self.voice_from, **kwargs)
            else:
                self.client.messages.create(to=to, body=body, **kwargs)
            status = "sent"
        except Exception as exc:  # network, auth, unverified number on trial accounts...
            log.warning("twilio %s send failed: %s", channel, type(exc).__name__)
            status = "failed"
        return record(db, channel, to, body, status)

    def send_sms(self, db: Session, to: str, body: str) -> Outbox:
        if not self.sms_from:
            return record(db, "sms", to, body, "mock")
        return self._send(db, "sms", to, body, from_=self.sms_from)

    def send_whatsapp(
        self, db: Session, to: str, body: str, media_url: str | None = None
    ) -> Outbox:
        if not self.whatsapp_from:
            return record(db, "whatsapp", to, body, "mock")
        to_wa = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
        extra: dict[str, Any] = {"media_url": [media_url]} if media_url else {}
        return self._send(db, "whatsapp", to_wa, body, from_=self.whatsapp_from, **extra)

    def place_call(self, db: Session, to: str, say: str, language: str) -> Outbox:
        if not self.voice_from:
            return record(db, "call", to, say, "mock")
        voice = self.voices.get(language) or {}
        twiml = VoiceResponse()
        twiml.say(say, voice=voice.get("voice"), language=voice.get("language"))
        return self._send(db, "call", to, say, twiml=str(twiml))
