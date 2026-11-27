"""Settings and service status. Every value is optional so the app always starts without keys."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/ration_bolo.db"
    dealer_pin: str = "1234"
    public_base_url: str = ""
    seed_demo: bool = True
    default_state_pack: str = "telangana"

    # Adapter selection: "auto" uses a real adapter when its keys are set, "mock" forces mocks.
    speech_mode: str = "auto"
    messaging_mode: str = "auto"
    speech_timeout_seconds: float = 6.0

    # Wispr Flow (primary speech-to-text).
    wispr_api_key: str = ""
    wispr_base_url: str = "https://platform-api.wisprflow.ai/api/v1/dash"

    # Sarvam AI (backup speech-to-text and reply voice).
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_stt_model: str = "saaras:v4"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_speaker: str = "kavya"

    # Twilio (voice, WhatsApp sandbox, SMS).
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_voice_number: str = ""
    twilio_whatsapp_number: str = ""
    twilio_sms_number: str = ""

    audio_cache_dir: str = "./data/audio_cache"
    scheduler_enabled: bool = True
    # After a caller registers a card by digits, send a one-time code by SMS to verify the
    # phone ("optional": caller may skip; "off": never ask).
    link_verification: str = "optional"

    @property
    def wispr_ready(self) -> bool:
        return self.speech_mode != "mock" and bool(self.wispr_api_key)

    @property
    def sarvam_ready(self) -> bool:
        return self.speech_mode != "mock" and bool(self.sarvam_api_key)

    @property
    def twilio_ready(self) -> bool:
        return (
            self.messaging_mode != "mock"
            and bool(self.twilio_account_sid)
            and bool(self.twilio_auth_token)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
