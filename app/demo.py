"""Shared live demo safety (F23).

On the live link many judges use the same demo data, minutes apart. In demo mode:
1. a demo card starts fresh on every new call/chat/simulator session (earlier open
   bookings and pending reminders cancelled, seeded language restored);
2. "out of stock" / "machine down" switch back to normal 10 minutes after being set;
3. the scheduler resets the demo every night at 03:00 IST.
Demo cards are never touched outside demo mode; real cards are never reset.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import queue
from app.clock import now_utc
from app.models import Card, DemoCard, Reminder, Shop, StatusTimer, Token

RESTORE_AFTER = timedelta(minutes=10)
NORMAL = {"stock": "in_stock", "machine": "working"}


def refresh_card(db: Session, card: Card) -> bool:
    """Make a demo card fresh for a new session. Returns False for non-demo cards."""
    demo = db.get(DemoCard, card.id)
    if demo is None:
        return False
    tokens = db.scalars(
        select(Token).where(
            Token.card_id == card.id, Token.kind == "booked", Token.status == "booked"
        )
    ).all()
    for token in tokens:
        token.status = "cancelled"
        for reminder in db.scalars(
            select(Reminder).where(Reminder.token_id == token.id, Reminder.status == "pending")
        ):
            reminder.status = "cancelled"
    card.language = demo.language
    if tokens:
        queue.log_event(db, "demo", "demo_card_refreshed", f"card:{card.id}", cancelled=len(tokens))
    return True


def record_status(db: Session, shop: Shop, now: datetime | None = None) -> None:
    """Keep one timer per abnormal status; clear it when the status is normal again."""
    now = now or now_utc()
    for kind, normal in NORMAL.items():
        value = shop.status_stock if kind == "stock" else shop.status_machine
        timer = db.get(StatusTimer, (shop.id, kind))
        if value == normal and timer is not None:
            db.delete(timer)
        elif value != normal and timer is None:
            db.add(StatusTimer(shop_id=shop.id, kind=kind, set_at=now))


def apply_auto_restore(db: Session, now: datetime | None = None) -> int:
    """Switch statuses back to normal 10 minutes after they were set."""
    now = now or now_utc()
    restored = 0
    for timer in db.scalars(select(StatusTimer).where(StatusTimer.set_at <= now - RESTORE_AFTER)):
        shop = db.get(Shop, timer.shop_id)
        if shop is None:
            continue
        queue.set_status(db, shop, **{timer.kind: NORMAL[timer.kind]}, actor="demo_auto_restore")
        restored += 1
    if restored:
        db.flush()
    return restored


def restore_countdown(db: Session, shop: Shop, now: datetime | None = None) -> dict[str, int]:
    """Minutes until each abnormal status switches back (for the dashboard)."""
    now = now or now_utc()
    out: dict[str, int] = {}
    for timer in db.scalars(select(StatusTimer).where(StatusTimer.shop_id == shop.id)):
        left = timer.set_at + RESTORE_AFTER - now
        out[timer.kind] = max(1, int(-(-left.total_seconds() // 60)))
    return out


def clear_timers(db: Session) -> None:
    db.execute(delete(StatusTimer))
