"""Call simulator API: a judge or tester plays any demo caller, with no keys needed.

The browser sends text (from its own speech recognition or the text box), recorded
audio (when a server speech engine is configured), keypad digits or silence.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.channels.twilio_common import IP_LIMIT
from app.db import get_db
from app.dialogue import Event, Reply
from app.models import DialogueSession
from app.packs import get_pack
from app.seed import DEMO_CALLERS
from app.services import Services
from app.speech import pipeline

router = APIRouter(prefix="/api/sim", tags=["simulator"])


class StartIn(BaseModel):
    caller: str = "lakshmi"
    state: str = "telangana"
    mode: str = "call"  # call | whatsapp


class TextIn(BaseModel):
    text: str
    language: str | None = None
    engine: str = "text"  # browser | text
    confidence: float | None = None


class DigitIn(BaseModel):
    key: str


def services_of(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def reply_payload(
    services: Services, session: DialogueSession, reply: Reply, heard: dict[str, Any] | None = None
) -> dict[str, Any]:
    pack = get_pack(session.state_pack)
    audio_id = services.voice.get(reply.text, pack.speech_code(reply.language, "sarvam"))
    return {
        "session_id": session.id,
        "text": reply.text,
        "gloss": reply.gloss,
        "language": reply.language,
        "browser_lang": pack.speech_code(reply.language, "browser"),
        "state": reply.state,
        "ended": reply.ended,
        "expect": reply.expect,
        "menu": reply.menu,
        "actions": reply.actions,
        "engine": reply.engine,
        "audio_url": f"/audio/{audio_id}" if audio_id else None,
        "channel": session.channel,
        "heard": heard,
    }


def _session(db: Session, session_id: int) -> DialogueSession:
    session = db.get(DialogueSession, session_id)
    if session is None or session.channel not in ("simulator", "whatsapp"):
        raise HTTPException(404, "no such simulator session")
    return session


@router.get("/callers")
def callers() -> list[dict[str, str]]:
    return [{"id": k, "label": v["label"], "phone": v["phone"]} for k, v in DEMO_CALLERS.items()]


@router.post("/start")
def start(body: StartIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    IP_LIMIT.check(f"sim:{request.client.host if request.client else ''}")
    if body.caller not in DEMO_CALLERS:
        raise HTTPException(400, "unknown caller")
    if body.state not in request.app.state.packs:
        raise HTTPException(400, "unknown state pack")
    services = services_of(request)
    channel = "whatsapp" if body.mode == "whatsapp" else "simulator"
    dialogue = services.dialogue(db)
    session = dialogue.start_session(channel, DEMO_CALLERS[body.caller]["phone"], body.state)
    reply = dialogue.handle(session, Event("start"))
    db.commit()
    return reply_payload(services, session, reply)


@router.post("/{session_id}/text")
def text(
    session_id: int, body: TextIn, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    services = services_of(request)
    session = _session(db, session_id)
    engine = body.engine if body.engine in ("browser", "text") else "text"
    dialogue = services.dialogue(db)
    reply = dialogue.handle(
        session, Event("text", body.text[:500], body.language, engine, body.confidence)
    )
    db.commit()
    return reply_payload(services, session, reply, {"text": body.text, "engine": engine})


@router.post("/{session_id}/audio")
def audio(
    session_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    services = services_of(request)
    session = _session(db, session_id)
    heard = pipeline.transcribe(services, session, file.file.read())
    dialogue = services.dialogue(db)
    reply = dialogue.handle(
        session, Event("text", heard.text, heard.language, heard.engine, heard.confidence)
    )
    db.commit()
    info = {"text": heard.text, "engine": heard.engine, "error": heard.error}
    return reply_payload(services, session, reply, info)


@router.post("/{session_id}/digit")
def digit(
    session_id: int, body: DigitIn, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    services = services_of(request)
    session = _session(db, session_id)
    key = "".join(c for c in body.key if c.isdigit() or c in "*#")[:20]
    reply = services.dialogue(db).handle(session, Event("digit", key, engine="keypad"))
    db.commit()
    return reply_payload(services, session, reply)


@router.post("/{session_id}/silence")
def silence(session_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    services = services_of(request)
    session = _session(db, session_id)
    reply = services.dialogue(db).handle(session, Event("silence"))
    db.commit()
    return reply_payload(services, session, reply)


@router.post("/{session_id}/end")
def end(session_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    services = services_of(request)
    session = _session(db, session_id)
    reply = services.dialogue(db).handle(session, Event("end"))
    db.commit()
    return reply_payload(services, session, reply)
