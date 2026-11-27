"""WhatsApp (Twilio sandbox). Callers send voice notes or text; replies are a voice
note (when a reply voice and PUBLIC_BASE_URL are configured) plus a one-line text.
The fallback menu is a numbered text list: the sandbox can't send tappable buttons
without approved templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from twilio.twiml.messaging_response import MessagingResponse

from app.channels.twilio_common import public_url, verified_form
from app.clock import now_utc
from app.db import get_db
from app.dialogue import Dialogue, Event, Reply
from app.models import DialogueSession
from app.packs import get_pack
from app.services import Services
from app.speech import pipeline
from app.understanding import understand

router = APIRouter(prefix="/twilio/whatsapp", tags=["twilio-whatsapp"])

SESSION_IDLE = timedelta(minutes=30)
KEYPAD_RE = re.compile(r"^[0-9#*\s]+$")


@dataclass
class WhatsAppReply:
    text: str
    audio_id: str | None
    replies: list[Reply] = field(default_factory=list)


def plain_phone(sender: str) -> str:
    return sender.removeprefix("whatsapp:").strip()


def current_session(
    db: Session, dialogue: Dialogue, phone: str, state_pack: str
) -> tuple[DialogueSession, Reply | None]:
    """Reuse the caller's open chat if it was active in the last 30 minutes."""
    session = db.scalars(
        select(DialogueSession)
        .where(
            DialogueSession.channel == "whatsapp",
            DialogueSession.phone_e164 == phone,
            DialogueSession.state != "ended",
        )
        .order_by(DialogueSession.id.desc())
    ).first()
    if session is not None and session.last_activity_at >= now_utc() - SESSION_IDLE:
        return session, None
    if session is not None:
        dialogue.handle(session, Event("end"))
    session = dialogue.start_session("whatsapp", phone, state_pack)
    return session, dialogue.handle(session, Event("start"))


def fetch_media(services: Services, url: str) -> bytes:
    s = services.settings
    auth = (s.twilio_account_sid, s.twilio_auth_token) if s.twilio_account_sid else None
    try:
        resp = services.http.get(
            url, auth=auth, timeout=s.speech_timeout_seconds, follow_redirects=True
        )
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPError:
        return b""


def handle_message(
    db: Session,
    services: Services,
    sender: str,
    body: str,
    media: list[tuple[str, str]],
    state_pack: str = "telangana",
) -> WhatsAppReply:
    """Channel handler, independent of HTTP: one incoming WhatsApp message → reply."""
    phone = plain_phone(sender)
    dialogue = Dialogue(db, services.sender(db))
    session, greeting = current_session(db, dialogue, phone, state_pack)
    replies = [greeting] if greeting else []
    audio = next((url for url, ctype in media if ctype.startswith("audio/")), None)
    event: Event | None = None
    if audio:
        heard = pipeline.transcribe(services, session, fetch_media(services, audio))
        event = Event("text", heard.text, heard.language, heard.engine, heard.confidence)
    elif body.strip() and KEYPAD_RE.match(body):
        event = Event("digit", re.sub(r"\s", "", body), engine="keypad")
    elif body.strip():
        event = Event("text", body[:500], engine="text")
    # A first message like "hi" just gets the greeting; a real question is answered too.
    pack = get_pack(session.state_pack)
    if event is not None and (
        greeting is None or event.kind == "digit" or understand(event.text, pack).understood
    ):
        replies.append(dialogue.handle(session, event))
    elif event is None and greeting is None:
        replies.append(dialogue.handle(session, Event("silence")))
    db.commit()
    text = " ".join(r.text for r in replies)
    last = replies[-1]
    audio_id = services.voice.get(text, pack.speech_code(last.language, "sarvam"))
    return WhatsAppReply(text=text, audio_id=audio_id, replies=replies)


@router.post("")
async def incoming(request: Request, db: Session = Depends(get_db)) -> Response:
    form = await verified_form(request)
    services: Services = request.app.state.services
    count = int(form.get("NumMedia", "0") or 0)
    media = [
        (form.get(f"MediaUrl{i}", ""), form.get(f"MediaContentType{i}", "")) for i in range(count)
    ]
    result = handle_message(
        db,
        services,
        form.get("From", ""),
        form.get("Body", ""),
        media,
        request.app.state.settings.default_state_pack,
    )
    twiml = MessagingResponse()
    message = twiml.message()
    message.body(result.text)
    if result.audio_id and services.settings.public_base_url:
        message.media(public_url(request, f"/audio/{result.audio_id}.ogg"))
    return Response(str(twiml), media_type="application/xml")
