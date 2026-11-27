"""Dealer dashboard API, protected by the dealer PIN.

Card numbers appear only as their last 4 digits and phone numbers are masked.
Demo holder labels are shown only here, never spoken or sent.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import demo, queue, reminders
from app.clock import fmt_time, ist_today, now_utc, to_ist
from app.db import get_db
from app.models import (
    Card,
    CardHolder,
    Complaint,
    DialogueSession,
    Outbox,
    PhoneLink,
    Shop,
    Token,
    mask_phone,
)
from app.packs import get_pack
from app.seed import reset_demo
from app.services import Services
from app.speech import pipeline
from app.understanding import dealer_intent

STATUS_CHANGES = {
    "dealer_stock_out": {"stock": "out"},
    "dealer_stock_in": {"stock": "in_stock"},
    "dealer_machine_down": {"machine": "down"},
    "dealer_machine_up": {"machine": "working"},
}


def require_pin(request: Request, x_dealer_pin: str = Header(default="")) -> None:
    expected: str = request.app.state.settings.dealer_pin
    if not secrets.compare_digest(x_dealer_pin.encode(), expected.encode()):
        raise HTTPException(401, "wrong dealer PIN")


router = APIRouter(prefix="/api/dealer", tags=["dealer"], dependencies=[Depends(require_pin)])


class ServeIn(BaseModel):
    kg: float | None = None


class ArriveIn(BaseModel):
    token_id: int
    minutes_after_start: int | None = None  # demo: arrive N minutes after the window starts


class StatusIn(BaseModel):
    stock: str | None = None
    machine: str | None = None


class VoiceIn(BaseModel):
    text: str


class ResolveIn(BaseModel):
    outcome: str


class LinkIn(BaseModel):
    phone: str
    card_id: int


class WalkinIn(BaseModel):
    last4: str | None = None


def shop_of(db: Session, code: str | None = None) -> Shop:
    """The shop the dashboard is looking at (X-Shop-Code header), else the first one."""
    query = select(Shop).order_by(Shop.id)
    if code:
        query = query.where(Shop.code == code)
    shop = db.scalars(query).first()
    if shop is None:
        raise HTTPException(404, "no shop")
    return shop


def _token_row(t: Token) -> dict[str, Any]:
    return {
        "id": t.id,
        "token": t.label,
        "kind": t.kind,
        "status": t.status,
        "last4": t.card.last4 if t.card else "----",
        "window": fmt_time(t.window.start_time) if t.window else None,
        "issued": fmt_time(to_ist(t.issued_at).time()),
        "channel": t.channel,
    }


def overview_data(db: Session, request: Request) -> dict[str, Any]:
    demo_on = request.app.state.settings.demo_active
    if demo_on and demo.apply_auto_restore(db):
        db.commit()
    shop = shop_of(db, request.headers.get("X-Shop-Code"))
    queue.sweep_no_shows(db, shop)
    db.commit()
    today = ist_today()
    info = queue.people_ahead_now(db, shop)
    order = queue.serving_order(db, shop)
    bookings = db.scalars(
        select(Token)
        .where(
            Token.shop_id == shop.id,
            Token.kind == "booked",
            Token.date >= today,
            Token.date <= today + timedelta(days=1),
        )
        .order_by(Token.date, Token.window_id, Token.token_no)
    ).all()
    complaints = db.scalars(
        select(Complaint)
        .where(Complaint.shop_id == shop.id)
        .order_by(Complaint.id.desc())
        .limit(20)
    ).all()
    outbox = db.scalars(select(Outbox).order_by(Outbox.id.desc()).limit(30)).all()
    cards = db.execute(
        select(Card, CardHolder.display_name)
        .join(CardHolder, CardHolder.card_id == Card.id)
        .where(Card.shop_id == shop.id)
        .order_by(Card.id)
        .limit(10)
    ).all()
    extra = getattr(request.app.state, "dealer_extras", None)
    return {
        "demo_data": True,
        "demo_mode": demo_on,
        "restore_in_minutes": demo.restore_countdown(db, shop) if demo_on else {},
        "shops": [
            {"code": x.code, "name": x.name, "area": x.area}
            for x in db.scalars(select(Shop).order_by(Shop.id))
        ],
        "shop": {
            "code": shop.code,
            "name": shop.name,
            "area": shop.area,
            "stock": shop.status_stock,
            "machine": shop.status_machine,
            "paused": queue.paused(shop),
            "families_per_hour": shop.families_per_hour,
        },
        "today": today.isoformat(),
        "waiting": info.ahead,
        "wait_minutes": info.minutes,
        "queue": [_token_row(t) for t in order],
        "bookings": [{**_token_row(t), "date": t.date.isoformat()} for t in bookings],
        "complaints": [
            {
                "id": c.id,
                "complaint_no": c.complaint_no,
                "last4": c.card.last4,
                "kg_due": c.grams_due / 1000,
                "kg_received": c.grams_received / 1000,
                "status": c.status,
                "outcome": c.outcome,
                "created": to_ist(c.created_at).strftime("%d %b %H:%M"),
            }
            for c in complaints
        ],
        "outbox": [
            {
                "id": o.id,
                "channel": o.channel,
                "to": o.to_masked,
                "body": o.body,
                "status": o.status,
                "at": to_ist(o.created_at).strftime("%d %b %H:%M"),
            }
            for o in outbox
        ],
        "demo_cards": [{"id": c.id, "last4": c.last4, "label": name} for c, name in cards],
        **(extra(db) if extra else {}),
    }


@router.get("/overview")
def overview(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return overview_data(db, request)


@router.post("/serve")
def serve(
    body: ServeIn, db: Session = Depends(get_db), x_shop_code: str = Header(default="")
) -> dict[str, Any]:
    shop = shop_of(db, x_shop_code)
    grams = None if body.kg is None else int(round(body.kg * 1000))
    token = queue.serve_next(db, shop, grams)
    db.commit()
    if token is None:
        return {"served": None, "message": "Nobody is waiting."}
    return {"served": _token_row(token), "message": f"Served {token.label}"}


@router.post("/arrive")
def arrive(body: ArriveIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    token = db.get(Token, body.token_id)
    if token is None or token.window is None:
        raise HTTPException(404, "no such booking")
    at: datetime | None = None
    if body.minutes_after_start is not None:
        at = queue.window_start_utc(token.window) + timedelta(minutes=body.minutes_after_start)
    try:
        result = queue.mark_arrived(db, token, at)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    late = result.id != token.id
    return {
        "token": _token_row(result),
        "late": late,
        "message": f"{token.label} was late: now walk-in {result.label}"
        if late
        else f"{token.label} arrived",
    }


@router.post("/walkin")
def walkin(
    body: WalkinIn, db: Session = Depends(get_db), x_shop_code: str = Header(default="")
) -> dict[str, Any]:
    shop = shop_of(db, x_shop_code)
    card = None
    if body.last4:
        matches = [
            c
            for c in db.scalars(select(Card).where(Card.shop_id == shop.id))
            if c.last4 == body.last4
        ]
        card = matches[0] if len(matches) == 1 else None
    token = queue.add_walkin(db, shop, card)
    db.commit()
    return {"token": _token_row(token), "message": f"Walk-in token {token.label}"}


def _apply_status(
    db: Session,
    shop: Shop,
    stock: str | None = None,
    machine: str | None = None,
    actor: str = "dealer",
) -> dict[str, Any]:
    try:
        queue.set_status(db, shop, stock=stock, machine=machine, actor=actor)
    except ValueError as exc:
        raise HTTPException(400, f"bad status {exc}") from exc
    db.commit()
    return {
        "stock": shop.status_stock,
        "machine": shop.status_machine,
        "paused": queue.paused(shop),
    }


@router.post("/status")
def status(
    body: StatusIn, db: Session = Depends(get_db), x_shop_code: str = Header(default="")
) -> dict[str, Any]:
    return _apply_status(db, shop_of(db, x_shop_code), body.stock, body.machine, "dealer")


def _voice_update(db: Session, text: str, code: str | None = None) -> dict[str, Any]:
    shop = shop_of(db, code)
    pack = get_pack(shop.state_pack)
    intent = dealer_intent(text, pack)
    if intent is None:
        return {
            "understood": False,
            "heard": text,
            "message": "Not understood. Say e.g. 'Biyyam aipoyindi', 'Machine down'.",
        }
    result = _apply_status(db, shop, actor="dealer_voice", **STATUS_CHANGES[intent])
    label = {
        "dealer_stock_out": "rice finished",
        "dealer_stock_in": "rice in stock",
        "dealer_machine_down": "machine down",
        "dealer_machine_up": "machine working",
    }[intent]
    return {
        "understood": True,
        "heard": text,
        "intent": intent,
        **result,
        "message": pack.phrase("dealer_updated", "en", status=label),
    }


@router.post("/voice")
def voice(
    body: VoiceIn, db: Session = Depends(get_db), x_shop_code: str = Header(default="")
) -> dict[str, Any]:
    return _voice_update(db, body.text[:200], x_shop_code)


@router.post("/voice-audio")
def voice_audio(
    request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    services: Services = request.app.state.services
    probe = DialogueSession(
        channel="simulator",
        state_pack=shop_of(db, request.headers.get("X-Shop-Code")).state_pack,
        language="te",
        engine="primary",
        data={},
    )
    heard = pipeline.transcribe(services, probe, file.file.read())
    if not heard.ok:
        return {"understood": False, "heard": "", "message": heard.error or "nothing heard"}
    return _voice_update(db, heard.text, request.headers.get("X-Shop-Code"))


@router.post("/complaints/{complaint_id}/resolve")
def resolve(complaint_id: int, body: ResolveIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(404)
    queue.resolve_complaint(db, complaint, body.outcome[:300] or "Resolved")
    db.commit()
    return {"complaint_no": complaint.complaint_no, "status": complaint.status}


PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")


def normalise_phone(raw: str) -> str:
    digits = re.sub(r"[\s\-()]", "", raw)
    if not PHONE_RE.match(digits):
        raise HTTPException(400, "phone must be 10 to 15 digits, e.g. +91 98xxxxxxxx")
    if not digits.startswith("+"):
        digits = "+91" + digits[-10:] if len(digits) == 10 else "+" + digits
    return digits


@router.post("/link-phone")
def link_phone(body: LinkIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """For testers: link your own phone to a demo card, so a real call recognises it."""
    phone = normalise_phone(body.phone)
    card = db.get(Card, body.card_id)
    if card is None:
        raise HTTPException(404, "no such card")
    exists = db.scalars(
        select(PhoneLink).where(PhoneLink.phone_e164 == phone, PhoneLink.card_id == card.id)
    ).first()
    if not exists:
        db.add(PhoneLink(phone_e164=phone, card_id=card.id, source="self_registered"))
        queue.log_event(db, "dealer", "phone_linked", f"card:{card.id}")
        db.commit()
    return {"message": f"{mask_phone(phone)} linked to card ••{card.last4}"}


@router.post("/reset")
def reset(db: Session = Depends(get_db)) -> dict[str, str]:
    reset_demo(db, now_utc())
    return {"message": "Demo data restored"}


class ReminderIn(BaseModel):
    reminder_id: int | None = None


@router.post("/reminders/send-now")
def reminder_now(
    body: ReminderIn, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    services: Services = request.app.state.services
    row = reminders.send_now(db, services, body.reminder_id)
    if row is None:
        return {"message": "No pending reminder to send."}
    return {"message": f"Reminder sent ({row.channel}, {row.status}): {row.body}"}
