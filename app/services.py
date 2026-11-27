"""Builds the adapters from settings and reports which services are live.

A real adapter turns on only when its keys are present; otherwise a mock stands in
and the status endpoint says "key not set".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.channels.messaging import Messenger, MockMessenger
from app.config import Settings
from app.speech.stt import MockSTT, SpeechToText
from app.speech.tts import MockTTS, TextToSpeech
from app.statedata import DealerFedStateData, StateData


@dataclass
class Services:
    settings: Settings
    stt_primary: SpeechToText | None
    stt_backup: SpeechToText | None
    tts: TextToSpeech
    messenger: Messenger
    state_data: StateData
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def server_stt(self) -> bool:
        return self.stt_primary is not None or self.stt_backup is not None

    def sender(self, db: Session) -> Callable[[str, str, str], None]:
        """Dialogue sender backed by the messenger."""

        def send(channel: str, phone: str, body: str) -> None:
            if channel == "whatsapp":
                self.messenger.send_whatsapp(db, phone, body)
            elif channel == "call":
                self.messenger.place_call(db, phone, body, "")
            else:
                self.messenger.send_sms(db, phone, body)

        return send

    def status(self) -> dict[str, Any]:
        s = self.settings

        def svc(
            name: str, provider: str, ready: bool, keys: list[str], fallback: str
        ) -> dict[str, Any]:
            missing = [k for k in keys if not getattr(s, k.lower())]
            return {
                "service": name,
                "provider": provider,
                "mode": "real" if ready else "mock",
                "ready": ready,
                "missing_keys": missing,
                "note": "active"
                if ready
                else (f"key not set: {', '.join(missing)}" if missing else "mock mode")
                + ("" if ready else f" · using {fallback}"),
            }

        twilio_keys = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]
        services = [
            svc(
                "speech_to_text",
                "Wispr Flow",
                s.wispr_ready,
                ["WISPR_API_KEY"],
                "Sarvam if set, else browser speech recognition",
            ),
            svc(
                "speech_to_text_backup",
                "Sarvam AI",
                s.sarvam_ready,
                ["SARVAM_API_KEY"],
                "browser speech recognition / text box",
            ),
            svc(
                "reply_voice",
                "Sarvam AI Bulbul",
                s.sarvam_ready,
                ["SARVAM_API_KEY"],
                "browser speech synthesis / Twilio <Say>",
            ),
            svc(
                "sms",
                "Twilio SMS",
                s.twilio_ready and bool(s.twilio_sms_number),
                [*twilio_keys, "TWILIO_SMS_NUMBER"],
                "outbox (mock)",
            ),
            svc(
                "whatsapp",
                "Twilio WhatsApp",
                s.twilio_ready and bool(s.twilio_whatsapp_number),
                [*twilio_keys, "TWILIO_WHATSAPP_NUMBER"],
                "outbox (mock)",
            ),
            svc(
                "voice_calls",
                "Twilio Voice",
                s.twilio_ready and bool(s.twilio_voice_number),
                [*twilio_keys, "TWILIO_VOICE_NUMBER"],
                "outbox (mock)",
            ),
            {
                "service": "state_data",
                "provider": "State Civil Supplies (ePoS)",
                "mode": "mock",
                "ready": False,
                "missing_keys": [],
                "note": "needs a department agreement · using dealer dashboard (demo data)",
            },
        ]
        public = bool(s.public_base_url)
        channels = {
            "simulator": {"ready": True, "note": "works with no keys"},
            "phone": {
                "ready": public and s.twilio_ready and bool(s.twilio_voice_number),
                "note": "not configured: "
                + ", ".join(
                    k
                    for k, v in [
                        ("PUBLIC_BASE_URL", public),
                        ("TWILIO_ACCOUNT_SID", s.twilio_account_sid),
                        ("TWILIO_AUTH_TOKEN", s.twilio_auth_token),
                        ("TWILIO_VOICE_NUMBER", s.twilio_voice_number),
                    ]
                    if not v
                )
                if not (public and s.twilio_ready and s.twilio_voice_number)
                else "active",
            },
            "whatsapp": {
                "ready": public and s.twilio_ready and bool(s.twilio_whatsapp_number),
                "note": "not configured: "
                + ", ".join(
                    k
                    for k, v in [
                        ("PUBLIC_BASE_URL", public),
                        ("TWILIO_ACCOUNT_SID", s.twilio_account_sid),
                        ("TWILIO_AUTH_TOKEN", s.twilio_auth_token),
                        ("TWILIO_WHATSAPP_NUMBER", s.twilio_whatsapp_number),
                    ]
                    if not v
                )
                if not (public and s.twilio_ready and s.twilio_whatsapp_number)
                else "active",
            },
        }
        return {
            "demo_data": True,
            "server_speech_to_text": self.server_stt,
            "server_voice": self.tts.name != "mock",
            "services": services,
            "channels": channels,
            "missing_keys": sorted({k for x in services for k in x["missing_keys"]}),
        }


def build_services(settings: Settings) -> Services:
    """Mocks everywhere unless keys are present. Real adapters are added by later modules."""
    primary: SpeechToText | None = None
    backup: SpeechToText | None = None
    tts: TextToSpeech = MockTTS()
    messenger: Messenger = MockMessenger()
    if settings.speech_mode == "mock":
        primary, backup = MockSTT("mock"), MockSTT("mock-backup")
    return Services(settings, primary, backup, tts, messenger, DealerFedStateData())
