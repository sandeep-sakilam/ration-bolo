"""Volunteer queue coordinators (F38).

A self-help-group member or ward volunteer can run tokens at a Level 0 shop, turning it
into "Level 1 (volunteer)" while on duty within their date range. In volunteer mode the
dealer dashboard allows tokens, mark arrived, serve next (calling the next token, no
sale recorded) and status updates — no sales or entitlement changes. Every volunteer
action is tagged "volunteer:<id>" in the events log.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import queue
from app.clock import ist_today, now_utc
from app.models import Shop, Volunteer


def active(db: Session, shop: Shop, now: datetime | None = None) -> Volunteer | None:
    today = ist_today(now or now_utc())
    return db.scalars(
        select(Volunteer).where(
            Volunteer.shop_id == shop.id,
            Volunteer.on_duty.is_(True),
            Volunteer.starts_on <= today,
            Volunteer.ends_on >= today,
        )
    ).first()


def register(db: Session, shop: Shop, label: str, starts_on: date, ends_on: date) -> Volunteer:
    if ends_on < starts_on:
        raise ValueError("ends_on must not be before starts_on")
    v = Volunteer(
        shop_id=shop.id,
        display_label=label[:80],
        starts_on=starts_on,
        ends_on=ends_on,
        on_duty=False,
    )
    db.add(v)
    db.flush()
    queue.log_event(db, "admin", "volunteer_registered", f"volunteer:{v.id}", shop=shop.code)
    return v


def set_duty(db: Session, volunteer: Volunteer, on_duty: bool) -> None:
    volunteer.on_duty = on_duty
    queue.log_event(
        db,
        f"volunteer:{volunteer.id}",
        "on_duty" if on_duty else "off_duty",
        f"volunteer:{volunteer.id}",
    )
    db.flush()


def actor(volunteer: Volunteer | None) -> str:
    return f"volunteer:{volunteer.id}" if volunteer else "dealer"
