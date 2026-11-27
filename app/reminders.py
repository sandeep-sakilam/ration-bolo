"""Reminders: 20 minutes before a booked slot the app calls back ("Leave now, three
are ahead"), with the number ahead computed live. Reminders live in the database,
so they survive restarts; an in-process APScheduler job sends the due ones."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import besttime, demo, grievance, incentives, levels, queue
from app.clock import fmt_time, now_utc, to_ist
from app.models import Outbox, PhoneLink, Reminder, Shop, Token
from app.packs import get_pack
from app.publicpds import current as current_public_pds
from app.seed import reset_demo
from app.services import Services

log = logging.getLogger("ration_bolo.reminders")
REMINDER_MINUTES = 20


def schedule(db: Session, token: Token, now: datetime | None = None) -> Reminder | None:
    """Create the reminder for a new booking (sent at once if the slot is under 20 min away)."""
    if token.window is None:
        return None
    now = now or now_utc()
    start = queue.window_start_utc(token.window)
    if start <= now:
        return None
    due = max(now, start - timedelta(minutes=REMINDER_MINUTES))
    reminder = Reminder(token_id=token.id, due_at=due, status="pending")
    db.add(reminder)
    db.flush()
    return reminder


def phone_for(db: Session, token: Token) -> str | None:
    if token.card_id is None:
        return None
    link = db.scalars(
        select(PhoneLink).where(PhoneLink.card_id == token.card_id).order_by(PhoneLink.id)
    ).first()
    return link.phone_e164 if link else None


def reminder_text(db: Session, token: Token) -> tuple[str, str]:
    """(text, language). Existing bookings hear the shop status in their reminder."""
    card = token.card
    if card is None or token.window is None:
        raise ValueError("reminder needs a booked card")
    pack = get_pack(card.state_pack)
    lang = pack.reply_language(card.language)
    parts = []
    if card.shop.status_stock != "in_stock":
        parts.append(pack.phrase("status_stock_out", lang))
    if card.shop.status_machine != "working":
        parts.append(pack.phrase("status_machine_down", lang))
    if not levels.takes_bookings(db, card.shop):
        # The shop dropped to Level 0: the booking is honoured as advice.
        time_s = fmt_time(token.window.start_time)
        return pack.phrase("level_dropped_booking", lang, time=time_s), lang
    ahead = queue.ahead_of_booking(db, token)
    parts.insert(
        0, pack.phrase("reminder", lang, time=fmt_time(token.window.start_time), ahead=ahead)
    )
    return " ".join(parts), lang


def send(db: Session, services: Services, reminder: Reminder) -> Outbox | None:
    token = reminder.token
    if token.status != "booked":
        reminder.status = "cancelled"
        return None
    phone = phone_for(db, token)
    if phone is None:
        reminder.status = "failed"
        return None
    text, lang = reminder_text(db, token)
    if token.channel == "whatsapp":
        row = services.messenger.send_whatsapp(db, phone, text)
    else:
        row = services.messenger.place_call(db, phone, text, lang)
    reminder.status = "sent" if row.status in ("mock", "sent") else "failed"
    reminder.sent_at = now_utc()
    queue.log_event(db, "system", "reminder_sent", f"token:{token.id}", status=reminder.status)
    return row


def run_due(db: Session, services: Services, now: datetime | None = None) -> int:
    now = now or now_utc()
    due = db.scalars(
        select(Reminder)
        .where(Reminder.status == "pending", Reminder.due_at <= now)
        .order_by(Reminder.due_at)
    ).all()
    for reminder in due:
        send(db, services, reminder)
    db.commit()
    return len(due)


def send_now(db: Session, services: Services, reminder_id: int | None = None) -> Outbox | None:
    """Dealer dashboard "Send reminder now" (for demos)."""
    if reminder_id is not None:
        reminder = db.get(Reminder, reminder_id)
    else:
        reminder = db.scalars(
            select(Reminder).where(Reminder.status == "pending").order_by(Reminder.due_at)
        ).first()
    if reminder is None or reminder.status != "pending":
        return None
    row = send(db, services, reminder)
    db.commit()
    return row


def dashboard_rows(db: Session) -> dict[str, Any]:
    rows = db.scalars(select(Reminder).order_by(Reminder.due_at.desc()).limit(15)).all()
    return {
        "reminders": [
            {
                "id": r.id,
                "token": r.token.label,
                "status": r.status,
                "due": to_ist(r.due_at).strftime("%d %b %H:%M"),
            }
            for r in rows
        ]
    }


def start_scheduler(
    factory: sessionmaker[Session], services: Services, interval_seconds: int = 30
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(daemon=True)
    demo_on = services.settings.demo_active

    def tick() -> None:
        try:
            with factory() as db:
                if demo_on and (demo.apply_auto_restore(db) + demo.refresh_demo_reports(db)):
                    db.commit()
                sent = run_due(db, services)
                if sent:
                    log.info("sent %d reminders", sent)
        except Exception:  # keep the scheduler alive whatever happens
            log.exception("reminder run failed")

    scheduler.add_job(
        tick,
        "interval",
        seconds=interval_seconds,
        id="reminders",
        next_run_time=now_utc() + timedelta(seconds=5),
        max_instances=1,
        coalesce=True,
    )

    def poll_public_pds() -> None:
        try:
            with factory() as db:
                pds = current_public_pds()
                added = 0
                for shop in db.scalars(select(Shop)):
                    new = pds.store(db, shop)
                    added += new
                    if new:
                        incentives.stock_arrived(db, shop, services.sender(db), "public_pds")
                db.commit()
                if added:
                    log.info("stored %d public PDS sale snapshots", added)
        except Exception:
            log.exception("public PDS poll failed")

    scheduler.add_job(
        poll_public_pds, "interval", minutes=10, id="public_pds", coalesce=True, max_instances=1
    )

    def escalate() -> None:
        try:
            with factory() as db:
                if grievance.run_due(db, services.sender(db), services.settings):
                    db.commit()
        except Exception:
            log.exception("grievance escalation failed")

    scheduler.add_job(
        escalate, "interval", hours=1, id="grievances", coalesce=True, max_instances=1
    )

    def nightly_profiles() -> None:
        try:
            with factory() as db:
                besttime.rebuild_all(db)
                db.commit()
        except Exception:
            log.exception("hourly profile rebuild failed")

    # 02:30 IST = 21:00 UTC: rebuild every shop's hourly profile from the last 4 weeks.
    scheduler.add_job(
        nightly_profiles,
        "cron",
        hour=21,
        minute=0,
        timezone="UTC",
        id="hourly_profiles",
        coalesce=True,
        max_instances=1,
    )
    if demo_on:

        def nightly_reset() -> None:
            try:
                with factory() as db:
                    reset_demo(db)
                log.info("nightly demo reset done")
            except Exception:
                log.exception("nightly demo reset failed")

        # 03:00 IST = 21:30 UTC the evening before.
        scheduler.add_job(
            nightly_reset,
            "cron",
            hour=21,
            minute=30,
            timezone="UTC",
            id="nightly_demo_reset",
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()
    return scheduler
