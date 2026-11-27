"""Builds the adapters from settings and reports which services are live.

A real adapter turns on only when its keys are present; otherwise a mock stands in
and the status endpoint says "key not set".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy.orm import Session

from app.channels.exotel import ExotelMessenger
from app.channels.messaging import Messenger, MockMessenger, TwilioMessenger
from app.config import Settings

if TYPE_CHECKING:
    from app.dialogue import Dialogue
from app.packs import all_packs
from app.publicpds import MockPublicPds, PublicPdsService
from app.publicpds import current as current_public_pds
from app.publicpds import register as register_public_pds
from app.speech.stt import MockSTT, SarvamSTT, SpeechToText, WisprSTT
from app.speech.tts import MockTTS, ReplyVoice, SarvamTTS, TextToSpeech
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
    http: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=10))

    @property
    def voice(self) -> ReplyVoice:
        return ReplyVoice(self.tts, self.settings.audio_cache_dir)

    @property
    def server_stt(self) -> bool:
        return self.stt_primary is not None or self.stt_backup is not None

    def dialogue(self, db: Session) -> Dialogue:
        from app.dialogue import Dialogue

        return Dialogue(
            db,
            self.sender(db),
            verify_links=self.settings.link_verification != "off",
            demo_mode=self.settings.demo_active,
            reporter_salt=self.settings.reporter_salt,
            settings=self.settings,
        )

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
            svc(
                "missed_call_checkin",
                "Twilio check-in number",
                s.twilio_ready and bool(s.twilio_checkin_number),
                ["TWILIO_CHECKIN_NUMBER"],
                "keypad 9 or 'I am at the shop' on the main number",
            ),
            {
                "service": "indian_telephony",
                "provider": "Exotel (stub)",
                "mode": "real" if s.exotel_ready else "mock",
                "ready": s.exotel_ready,
                "missing_keys": [],
                "note": "active for outbound calls and SMS"
                if s.exotel_ready
                else "not enabled (TELEPHONY_PROVIDER=exotel + EXOTEL_* keys) · using Twilio",
            },
            current_public_pds().status(),
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
    """Mocks everywhere unless keys are present."""
    primary: SpeechToText | None = None
    backup: SpeechToText | None = None
    tts: TextToSpeech = MockTTS()
    messenger: Messenger = MockMessenger()
    words = _vocabulary()
    timeout = settings.speech_timeout_seconds
    if settings.speech_mode == "mock":
        primary, backup = MockSTT("mock"), MockSTT("mock-backup")
    if settings.wispr_ready:
        primary = WisprSTT(settings.wispr_api_key, settings.wispr_base_url, timeout, words)
    if settings.sarvam_ready:
        sarvam = SarvamSTT(
            settings.sarvam_api_key,
            settings.sarvam_base_url,
            settings.sarvam_stt_model,
            timeout,
            words,
        )
        if primary is None:
            primary = sarvam
        else:
            backup = sarvam
        tts = SarvamTTS(
            settings.sarvam_api_key,
            settings.sarvam_base_url,
            settings.sarvam_tts_model,
            settings.sarvam_tts_speaker,
            timeout,
        )
    if settings.twilio_ready:
        voices: dict[str, dict[str, str]] = {}
        for pack in all_packs().values():
            for lang, voice in (pack.raw.get("twilio_voices") or {}).items():
                voices.setdefault(lang, voice)
        messenger = TwilioMessenger(
            settings.twilio_account_sid,
            settings.twilio_auth_token,
            settings.twilio_sms_number,
            settings.twilio_whatsapp_number,
            settings.twilio_voice_number,
            voices,
        )
    if settings.exotel_ready:
        messenger = ExotelMessenger(
            settings.exotel_sid,
            settings.exotel_api_key,
            settings.exotel_api_token,
            settings.exotel_caller_id,
            settings.exotel_subdomain,
            settings.exotel_flow_url,
            settings.exotel_dlt_entity_id,
            settings.exotel_dlt_template_id,
        )
    pds = PublicPdsService(
        mode=settings.public_pds_mode,
        mock=MockPublicPds(settings.public_pds_fixtures, demo=settings.demo_active),
    )
    register_public_pds(pds)
    return Services(settings, primary, backup, tts, messenger, DealerFedStateData())


def _vocabulary() -> list[str]:
    """Pack keywords, given to speech engines as hints (dictionary / key terms)."""
    words: list[str] = []
    for pack in all_packs().values():
        for lists in pack.raw["intents"].values():
            for items in lists.values():
                words.extend(w for w in items if w.isascii())
    return list(dict.fromkeys(words))
