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

from app import (
    crowd,
    demo,
    grievance,
    incentives,
    levels,
    queue,
    reminders,
    shopstate,
    volunteers,
)
from app.clock import fmt_time, ist_today, now_utc, to_ist
from app.db import get_db
from app.models import (
    Card,
    CardHolder,
    Complaint,
    DialogueSession,
    Grievance,
    Outbox,
    PhoneLink,
    Shop,
    Token,
    Volunteer,
    mask_phone,
)
from app.packs import get_pack
from app.ratelimit import RateLimiter
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
    if expected and not secrets.compare_digest(x_dealer_pin.encode(), expected.encode()):
        raise HTTPException(401, "wrong dealer PIN")


VOLUNTEER_FORBIDDEN = ("/reset", "/link-phone", "/complaints/", "/reminders/")


def volunteer_guard(
    request: Request,
    x_volunteer_id: str = Header(default=""),
    x_shop_code: str = Header(default=""),
    db: Session = Depends(get_db),
) -> None:
    """Volunteer mode (F38): the X-Volunteer-Id must name a volunteer of the shop being
    viewed; sales corrections, resets, phone links, complaints and reminders are off."""
    if not x_volunteer_id:
        return
    volunteer = db.get(Volunteer, int(x_volunteer_id)) if x_volunteer_id.isdigit() else None
    if volunteer is None:
        raise HTTPException(404, "no such volunteer")
    shop = db.get_one(Shop, volunteer.shop_id)
    if x_shop_code and x_shop_code != shop.code:
        raise HTTPException(403, "a volunteer can only manage their own shop")
    path = request.url.path.removeprefix("/api/dealer")
    if path.startswith(VOLUNTEER_FORBIDDEN):
        raise HTTPException(403, "not available in volunteer mode")


def acting(db: Session, x_volunteer_id: str) -> tuple[Volunteer | None, str]:
    volunteer = db.get(Volunteer, int(x_volunteer_id)) if x_volunteer_id.isdigit() else None
    return volunteer, volunteers.actor(volunteer)


router = APIRouter(
    prefix="/api/dealer",
    tags=["dealer"],
    dependencies=[Depends(require_pin), Depends(volunteer_guard)],
)


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


def _stage(db: Session, complaint: Complaint) -> str:
    g = db.scalars(select(Grievance).where(Grievance.complaint_id == complaint.id)).first()
    if g is None:
        return ""
    return g.stage.replace("_", " ") + (f" · ref {g.external_ref}" if g.external_ref else "")


def _volunteer_row(db: Session, request: Request, shop: Shop) -> dict[str, Any] | None:
    raw = request.headers.get("X-Volunteer-Id", "")
    v = db.get(Volunteer, int(raw)) if raw.isdigit() else volunteers.active(db, shop)
    if v is None:
        return None
    return {
        "id": v.id,
        "label": v.display_label,
        "on_duty": v.on_duty,
        "mode": bool(raw),
        "shop": db.get_one(Shop, v.shop_id).code,
    }


class DutyIn(BaseModel):
    on_duty: bool


@router.post("/volunteer/duty")
def volunteer_duty(
    body: DutyIn, db: Session = Depends(get_db), x_volunteer_id: str = Header(default="")
) -> dict[str, Any]:
    volunteer, _ = acting(db, x_volunteer_id)
    if volunteer is None:
        raise HTTPException(400, "volunteer mode only")
    volunteers.set_duty(db, volunteer, body.on_duty)
    db.commit()
    return {
        "on_duty": volunteer.on_duty,
        "message": "On duty: bookings are offered"
        if body.on_duty
        else "Off duty: the shop is back to Level 0",
    }


def _report_counts(db: Session, shop: Shop) -> dict[str, int]:
    """Cardholder reports in the last 3 hours, by kind (no identifiers)."""
    counts: dict[str, int] = {}
    for vote in crowd.votes(db, shop):
        counts[vote.kind] = counts.get(vote.kind, 0) + 1
    return counts


def overview_data(db: Session, request: Request) -> dict[str, Any]:
    demo_on = request.app.state.settings.demo_active
    if demo_on and (demo.apply_auto_restore(db) + demo.refresh_demo_reports(db)):
        db.commit()
    code = request.headers.get("X-Shop-Code")
    raw_volunteer = request.headers.get("X-Volunteer-Id", "")
    if not code and raw_volunteer.isdigit():
        v = db.get(Volunteer, int(raw_volunteer))
        code = db.get_one(Shop, v.shop_id).code if v else None
    shop = shop_of(db, code)
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
        "level": levels.effective_level(db, shop),
        "level_label": levels.label(db, shop),
        "volunteer": _volunteer_row(db, request, shop),
        "fair_shop": incentives.fair_shop(db, shop),
        "broadcast_optins": incentives.optin_count(db, shop),
        "disagreements": shopstate.view(db, shop).disagreements,
        "reports_3h": _report_counts(db, shop),
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
                "stage": _stage(db, c),
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
    body: ServeIn,
    db: Session = Depends(get_db),
    x_shop_code: str = Header(default=""),
    x_volunteer_id: str = Header(default=""),
) -> dict[str, Any]:
    shop = shop_of(db, x_shop_code)
    volunteer, actor = acting(db, x_volunteer_id)
    if volunteer is not None and body.kg is not None:
        raise HTTPException(403, "volunteers can't record sale amounts")
    grams = None if body.kg is None else int(round(body.kg * 1000))
    token = queue.serve_next(db, shop, grams, actor=actor, record_sale=volunteer is None)
    db.commit()
    if token is None:
        return {"served": None, "message": "Nobody is waiting."}
    return {"served": _token_row(token), "message": f"Served {token.label}"}


@router.post("/arrive")
def arrive(
    body: ArriveIn, db: Session = Depends(get_db), x_volunteer_id: str = Header(default="")
) -> dict[str, Any]:
    _, actor = acting(db, x_volunteer_id)
    token = db.get(Token, body.token_id)
    if token is None or token.window is None:
        raise HTTPException(404, "no such booking")
    at: datetime | None = None
    if body.minutes_after_start is not None:
        at = queue.window_start_utc(token.window) + timedelta(minutes=body.minutes_after_start)
    try:
        result = queue.mark_arrived(db, token, at, actor=actor)
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
    body: WalkinIn,
    db: Session = Depends(get_db),
    x_shop_code: str = Header(default=""),
    x_volunteer_id: str = Header(default=""),
) -> dict[str, Any]:
    shop = shop_of(db, x_shop_code)
    _, actor = acting(db, x_volunteer_id)
    card = None
    if body.last4:
        matches = [
            c
            for c in db.scalars(select(Card).where(Card.shop_id == shop.id))
            if c.last4 == body.last4
        ]
        card = matches[0] if len(matches) == 1 else None
    token = queue.add_walkin(db, shop, card, actor=actor)
    db.commit()
    return {"token": _token_row(token), "message": f"Walk-in token {token.label}"}


def _apply_status(
    db: Session,
    shop: Shop,
    stock: str | None = None,
    machine: str | None = None,
    actor: str = "dealer",
    sender: Any = None,
) -> dict[str, Any]:
    was_out = shop.status_stock != "in_stock"
    try:
        queue.set_status(db, shop, stock=stock, machine=machine, actor=actor)
    except ValueError as exc:
        raise HTTPException(400, f"bad status {exc}") from exc
    if was_out and shop.status_stock == "in_stock" and sender is not None:
        incentives.stock_arrived(db, shop, sender, "dealer")
    db.commit()
    return {
        "stock": shop.status_stock,
        "machine": shop.status_machine,
        "paused": queue.paused(shop),
    }


@router.post("/status")
def status(
    body: StatusIn,
    request: Request,
    db: Session = Depends(get_db),
    x_shop_code: str = Header(default=""),
) -> dict[str, Any]:
    sender = request.app.state.services.sender(db)
    _, actor = acting(db, request.headers.get("X-Volunteer-Id", ""))
    return _apply_status(db, shop_of(db, x_shop_code), body.stock, body.machine, actor, sender)


def _voice_update(
    db: Session,
    text: str,
    code: str | None = None,
    sender: Any = None,
    actor: str = "dealer_voice",
) -> dict[str, Any]:
    shop = shop_of(db, code)
    pack = get_pack(shop.state_pack)
    intent = dealer_intent(text, pack)
    if intent is None:
        return {
            "understood": False,
            "heard": text,
            "message": "Not understood. Say e.g. 'Biyyam aipoyindi', 'Machine down'.",
        }
    result = _apply_status(db, shop, actor=actor, sender=sender, **STATUS_CHANGES[intent])
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
    body: VoiceIn,
    request: Request,
    db: Session = Depends(get_db),
    x_shop_code: str = Header(default=""),
) -> dict[str, Any]:
    sender = request.app.state.services.sender(db)
    _, actor = acting(db, request.headers.get("X-Volunteer-Id", ""))
    return _voice_update(
        db, body.text[:200], x_shop_code, sender, "dealer_voice" if actor == "dealer" else actor
    )


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
    return _voice_update(db, heard.text, request.headers.get("X-Shop-Code"), services.sender(db))


@router.post("/complaints/{complaint_id}/resolve")
def resolve(complaint_id: int, body: ResolveIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(404)
    queue.resolve_complaint(db, complaint, body.outcome[:300] or "Resolved")
    grievance.mark_resolved(db, complaint)
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


RESET_LIMIT = RateLimiter(limit=6, window_seconds=60)
LOOPBACK = {"127.0.0.1", "::1"}


@router.post("/reset")
def reset(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    host = request.client.host if request.client else ""
    if host not in LOOPBACK:  # local test runs on the same machine are not limited
        RESET_LIMIT.check(f"reset:{host}")
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
