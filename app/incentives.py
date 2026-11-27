"""Dealer incentives (F37).

- Dealer phone line: a registered dealer phone (stored only as a salted hash on the
  shop profile) calling the main number gets the dealer menu: "Press 1 or say 'stock
  arrived', 2 'stock finished', 3 'machine down', 4 'machine working'." At Level 1/2 one
  call updates the status; at Level 0 it counts as a strong report.
- "Rice arrived" broadcast: cardholders opt in or out by voice; when stock is confirmed
  (dealer, public data or cardholder agreement) opted-in cardholders of that shop get one
  voice call or WhatsApp message, at most once a day, between 8 a.m. and 8 p.m.
- "Fair shop" badge: no upheld short-ration complaints in 90 days, at least 80% of
  cardholder status reports matched by the dealer within 30 minutes, and open on
  scheduled days (activity on at least 6 of the last 7 days). Level 1 and 2 only.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import crowd, levels, queue
from app.clock import ist_to_utc, ist_today, now_utc, to_ist
from app.models import (
    BroadcastOptin,
    Complaint,
    Event,
    PhoneLink,
    PublicSale,
    Report,
    Shop,
    ShopProfile,
    Token,
)
from app.packs import get_pack

Sender = Callable[[str, str, str], None]
BROADCAST_HOURS = (time(8, 0), time(20, 0))
DEALER_KEYS = {
    "1": "dealer_stock_in",
    "2": "dealer_stock_out",
    "3": "dealer_machine_down",
    "4": "dealer_machine_up",
}
CHANGES = {
    "dealer_stock_in": {"stock": "in_stock"},
    "dealer_stock_out": {"stock": "out"},
    "dealer_machine_down": {"machine": "down"},
    "dealer_machine_up": {"machine": "working"},
}
REPORT_KIND = {
    "dealer_stock_in": "stock_in",
    "dealer_stock_out": "stock_out",
    "dealer_machine_down": "machine_down",
    "dealer_machine_up": "machine_ok",
}


# --- dealer phone line ------------------------------------------------------------


def dealer_shop(db: Session, phone: str | None, salt: str) -> Shop | None:
    if not phone:
        return None
    h = crowd.reporter_hash(phone, salt)
    prof = db.scalars(select(ShopProfile).where(ShopProfile.dealer_phone_hash == h)).first()
    return db.get(Shop, prof.shop_id) if prof else None


def register_dealer_phone(db: Session, shop: Shop, phone: str, salt: str) -> None:
    levels.set_profile(db, shop, dealer_phone_hash=crowd.reporter_hash(phone, salt))


def apply_dealer_update(
    db: Session,
    shop: Shop,
    intent: str,
    phone: str,
    salt: str,
    send: Sender | None = None,
    now: datetime | None = None,
) -> str:
    """Level 1/2: change the status. Level 0: a strong (dealer) report. Returns a label."""
    now = now or now_utc()
    was_out = shop.status_stock != "in_stock"
    if levels.takes_bookings(db, shop, now):
        queue.set_status(db, shop, actor="dealer_phone", **CHANGES[intent])
        arrived = intent == "dealer_stock_in" and was_out
    else:
        crowd.save(
            db, shop, REPORT_KIND[intent], crowd.reporter_hash(phone, salt), "dealer", now=now
        )
        arrived = intent == "dealer_stock_in"
    if arrived and send is not None:
        stock_arrived(db, shop, send, "dealer", now)
    return {
        "dealer_stock_in": "rice in stock",
        "dealer_stock_out": "rice finished",
        "dealer_machine_down": "machine down",
        "dealer_machine_up": "machine working",
    }[intent]


# --- "Rice arrived" broadcast --------------------------------------------------------


def opt(db: Session, card_id: int, shop_id: int, channel: str, opt_in: bool) -> None:
    row = db.get(BroadcastOptin, card_id)
    now = now_utc()
    if row is None:
        row = BroadcastOptin(card_id=card_id, shop_id=shop_id, channel=channel, opted_in_at=now)
        db.add(row)
    if opt_in:
        row.shop_id, row.channel, row.opted_in_at, row.opted_out_at = shop_id, channel, now, None
    else:
        row.opted_out_at = now
    queue.log_event(
        db, "caller", "broadcast_optin" if opt_in else "broadcast_optout", f"card:{card_id}"
    )
    db.flush()


def stock_arrived(
    db: Session, shop: Shop, send: Sender, source: str, now: datetime | None = None
) -> int:
    """Tell opted-in cardholders once a day, 8 a.m.–8 p.m. Returns messages sent."""
    now = now or now_utc()
    local = to_ist(now).time()
    if not BROADCAST_HOURS[0] <= local < BROADCAST_HOURS[1]:
        return 0
    day_start = ist_to_utc(ist_today(now), time(0, 0))
    sent_today = {
        e.object
        for e in db.scalars(
            select(Event).where(Event.action == "broadcast_sent", Event.at >= day_start)
        )
    }
    pack = get_pack(shop.state_pack)
    sent = 0
    for row in db.scalars(
        select(BroadcastOptin).where(
            BroadcastOptin.shop_id == shop.id, BroadcastOptin.opted_out_at.is_(None)
        )
    ):
        key = f"card:{row.card_id}"
        if key in sent_today:
            continue
        link = db.scalars(
            select(PhoneLink).where(PhoneLink.card_id == row.card_id).order_by(PhoneLink.id)
        ).first()
        if link is None:
            continue
        card = link.card
        body = pack.phrase(
            "broadcast_rice_arrived", pack.reply_language(card.language), shop=shop.code
        )
        send("whatsapp" if row.channel == "whatsapp" else "call", link.phone_e164, body)
        queue.log_event(db, "system", "broadcast_sent", key, shop=shop.code, source=source)
        sent += 1
    db.flush()
    return sent


def optin_count(db: Session, shop: Shop) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(BroadcastOptin)
            .where(BroadcastOptin.shop_id == shop.id, BroadcastOptin.opted_out_at.is_(None))
        )
        or 0
    )


def crowd_confirmed_today(db: Session, shop: Shop, now: datetime | None = None) -> bool:
    """True when cardholder reports now confirm rice in stock (for the broadcast)."""
    verdict = crowd.verdict(crowd.votes(db, shop, now), "stock")
    return verdict is not None and verdict.confirmed and verdict.value == "in_stock"


# --- "Fair shop" badge ---------------------------------------------------------------


def _upheld_90(db: Session, shop: Shop, now: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Complaint)
            .where(
                Complaint.shop_id == shop.id,
                Complaint.status == "resolved",
                Complaint.created_at >= now - timedelta(days=90),
                ~func.lower(func.coalesce(Complaint.outcome, "")).startswith("not upheld"),
            )
        )
        or 0
    )


def dealer_responsiveness(db: Session, shop: Shop, now: datetime) -> float:
    """Share of cardholder status reports (90 days) matched by a dealer update of the
    same status within 30 minutes. 1.0 when there were no such reports."""
    reports = db.scalars(
        select(Report).where(
            Report.shop_id == shop.id,
            Report.source == "caller",
            Report.kind.in_(("stock_in", "stock_out", "machine_down")),
            Report.created_at >= now - timedelta(days=90),
        )
    ).all()
    if not reports:
        return 1.0
    updates = db.scalars(
        select(Event).where(
            Event.action == "status",
            Event.object == f"shop:{shop.code}",
            Event.actor.in_(("dealer", "dealer_voice", "dealer_phone")),
            Event.at >= now - timedelta(days=90, minutes=30),
        )
    ).all()
    want = {
        "stock_in": ("stock", "in_stock"),
        "stock_out": ("stock", "out"),
        "machine_down": ("machine", "down"),
    }
    matched = 0
    for r in reports:
        key, value = want[r.kind]
        if any(
            abs((u.at - r.created_at).total_seconds()) <= 1800 and u.detail.get(key) == value
            for u in updates
        ):
            matched += 1
    return matched / len(reports)


def open_days(db: Session, shop: Shop, now: datetime) -> int:
    """Days with activity (sales, served tokens, reports) among the last 7."""
    days = set()
    since = now - timedelta(days=7)
    for t in db.scalars(
        select(Token.served_at).where(Token.shop_id == shop.id, Token.served_at >= since)
    ):
        if t is not None:
            days.add(to_ist(t).date())
    for t in db.scalars(
        select(PublicSale.sale_time).where(
            PublicSale.shop_id == shop.id, PublicSale.sale_time >= since
        )
    ):
        days.add(to_ist(t).date())
    for t in db.scalars(
        select(Report.created_at).where(Report.shop_id == shop.id, Report.created_at >= since)
    ):
        days.add(to_ist(t).date())
    return len(days)


def fair_shop(db: Session, shop: Shop, now: datetime | None = None) -> bool:
    now = now or now_utc()
    if levels.effective_level(db, shop, now) < 1:
        return False
    return (
        _upheld_90(db, shop, now) == 0
        and dealer_responsiveness(db, shop, now) >= 0.8
        and open_days(db, shop, now) >= 6
    )
