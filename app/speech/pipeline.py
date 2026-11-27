"""Speech pipeline: convert audio, pick the session's engine, transcribe.

First choice is Wispr Flow; after two failures the dialogue engine moves the session
to the backup engine (Sarvam). With no keys there is no server engine and the
simulator uses the browser's own speech recognition instead.
"""

from __future__ import annotations

from app.models import DialogueSession
from app.packs import get_pack
from app.services import Services
from app.speech.audio import AudioError, to_wav16k
from app.speech.stt import SpeechToText, Transcript


def engine_for(services: Services, session: DialogueSession) -> SpeechToText | None:
    if session.engine == "backup" and services.stt_backup is not None:
        return services.stt_backup
    return services.stt_primary or services.stt_backup


def transcribe(services: Services, session: DialogueSession, audio: bytes) -> Transcript:
    """Never raises: a failure comes back as a Transcript with ``error`` set, which the
    dialogue engine counts as one failed attempt."""
    engine = engine_for(services, session)
    if engine is None:
        return Transcript(text="", engine="none", error="no server speech-to-text configured")
    try:
        wav = to_wav16k(audio)
    except AudioError as exc:
        return Transcript(text="", engine=engine.name, error=str(exc))
    pack = get_pack(session.state_pack)
    key = "sarvam" if engine.name.startswith("sarvam") else "wispr"
    hints = pack.speech_hints(key)
    if key == "sarvam":
        hints = list(dict.fromkeys(hints))
    result = engine.transcribe(wav, hints)
    del wav  # caller audio is dropped right after transcription
    return result
