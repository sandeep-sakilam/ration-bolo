"""Phone line (Twilio Voice). The caller speaks; we record each answer (8 s of
silence ends it, 15 s max), transcribe it, run the dialogue engine and play the
reply. A keypad menu (<Gather input="dtmf">) is the fallback."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from twilio.twiml.voice_response import VoiceResponse

from app.channels.twilio_common import public_url, verified_form
from app.db import get_db
from app.dialogue import Dialogue, Event, Reply
from app.models import DialogueSession
from app.packs import get_pack
from app.services import Services
from app.speech import pipeline

log = logging.getLogger("ration_bolo.voice")
router = APIRouter(prefix="/twilio/voice", tags=["twilio-voice"])

RECORD_TIMEOUT = 8
RECORD_MAX = 15


def twiml(xml: VoiceResponse) -> Response:
    return Response(str(xml), media_type="application/xml")


def speak(
    request: Request, services: Services, session: DialogueSession, reply: Reply, xml: VoiceResponse
) -> None:
    """<Play> Sarvam audio when we have it and a public URL; otherwise <Say>."""
    pack = get_pack(session.state_pack)
    settings = services.settings
    audio_id = None
    if settings.public_base_url:
        audio_id = services.voice.get(reply.text, pack.speech_code(reply.language, "sarvam"))
    if audio_id:
        xml.play(public_url(request, f"/audio/{audio_id}.wav"))
    else:
        voice = pack.twilio_voice(reply.language) or {}
        xml.say(reply.text, voice=voice.get("voice"), language=voice.get("language"))


def respond(
    request: Request, services: Services, session: DialogueSession, reply: Reply
) -> Response:
    xml = VoiceResponse()
    if reply.expect == "menu":
        gather = xml.gather(
            input="dtmf",
            num_digits=1,
            timeout=RECORD_TIMEOUT,
            action=public_url(request, "/twilio/voice/digits"),
            method="POST",
        )
        speak(request, services, session, reply, gather)
        xml.redirect(public_url(request, "/twilio/voice/silence"), method="POST")
        return twiml(xml)
    speak(request, services, session, reply, xml)
    if reply.ended:
        xml.hangup()
        return twiml(xml)
    xml.record(
        action=public_url(request, "/twilio/voice/recording"),
        method="POST",
        timeout=RECORD_TIMEOUT,
        max_length=RECORD_MAX,
        play_beep=False,
        trim="trim-silence",
    )
    # <Record> falls through to the next verb when nothing was said.
    xml.redirect(public_url(request, "/twilio/voice/silence"), method="POST")
    return twiml(xml)


def _services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def session_for(
    db: Session, dialogue: Dialogue, form: dict[str, str], request: Request
) -> tuple[DialogueSession, Reply | None]:
    """The call's session; a new one (with its greeting) if this is the first webhook."""
    sid = form.get("CallSid", "")
    session = (
        db.scalars(
            select(DialogueSession).where(
                DialogueSession.external_id == sid, DialogueSession.channel == "call"
            )
        ).first()
        if sid
        else None
    )
    if session is not None:
        return session, None
    state = request.app.state.settings.default_state_pack
    session = dialogue.start_session("call", form.get("From") or None, state, sid or None)
    return session, dialogue.handle(session, Event("start"))


@router.post("")
async def incoming(request: Request, db: Session = Depends(get_db)) -> Response:
    form = await verified_form(request)
    services = _services(request)
    dialogue = Dialogue(db, services.sender(db))
    session, greeting = session_for(db, dialogue, form, request)
    reply = greeting or dialogue.handle(session, Event("start"))
    db.commit()
    return respond(request, services, session, reply)


def download_recording(services: Services, url: str) -> bytes:
    s = services.settings
    auth = (s.twilio_account_sid, s.twilio_auth_token) if s.twilio_account_sid else None
    resp = services.http.get(
        url + ".wav", auth=auth, timeout=s.speech_timeout_seconds, follow_redirects=True
    )
    resp.raise_for_status()
    return resp.content


def delete_recording(services: Services, url: str) -> None:
    """Caller audio is deleted from Twilio right after transcription."""
    s = services.settings
    if not s.twilio_account_sid:
        return
    try:
        services.http.delete(
            url + ".json", auth=(s.twilio_account_sid, s.twilio_auth_token), timeout=5
        )
    except httpx.HTTPError:
        log.warning("could not delete a call recording")


@router.post("/recording")
async def recording(request: Request, db: Session = Depends(get_db)) -> Response:
    form = await verified_form(request)
    services = _services(request)
    dialogue = Dialogue(db, services.sender(db))
    session, _ = session_for(db, dialogue, form, request)
    url = form.get("RecordingUrl", "")
    if not url or form.get("RecordingDuration") == "0":
        reply = dialogue.handle(session, Event("silence"))
    else:
        try:
            audio = download_recording(services, url)
        except httpx.HTTPError:
            audio = b""
        delete_recording(services, url)
        heard = pipeline.transcribe(services, session, audio)
        reply = dialogue.handle(
            session, Event("text", heard.text, heard.language, heard.engine, heard.confidence)
        )
    db.commit()
    return respond(request, services, session, reply)


@router.post("/digits")
async def digits(request: Request, db: Session = Depends(get_db)) -> Response:
    form = await verified_form(request)
    services = _services(request)
    dialogue = Dialogue(db, services.sender(db))
    session, _ = session_for(db, dialogue, form, request)
    key = "".join(c for c in form.get("Digits", "") if c.isdigit() or c in "*#")
    event = Event("digit", key, engine="keypad") if key else Event("silence")
    reply = dialogue.handle(session, event)
    db.commit()
    return respond(request, services, session, reply)


@router.post("/silence")
async def silence(request: Request, db: Session = Depends(get_db)) -> Response:
    form = await verified_form(request)
    services = _services(request)
    dialogue = Dialogue(db, services.sender(db))
    session, _ = session_for(db, dialogue, form, request)
    reply = dialogue.handle(session, Event("silence"))
    db.commit()
    return respond(request, services, session, reply)


@router.post("/status")
async def status(request: Request, db: Session = Depends(get_db)) -> Response:
    """Call status callback: when the caller hangs up, close the session (and send the
    summary if something happened)."""
    form = await verified_form(request)
    if form.get("CallStatus") in ("completed", "busy", "failed", "no-answer", "canceled"):
        services = _services(request)
        session = db.scalars(
            select(DialogueSession).where(DialogueSession.external_id == form.get("CallSid", ""))
        ).first()
        if session is not None and session.state != "ended":
            Dialogue(db, services.sender(db)).handle(session, Event("end"))
            db.commit()
    return Response(status_code=204)
