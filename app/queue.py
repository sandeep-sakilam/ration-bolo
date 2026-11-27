"""Queue service: bookings, arrivals, serving, walk-ins, status and complaints.

Database work lives here; every rule it applies comes from ``app.slots``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import slots
from app.clock import ist_to_utc, ist_today, now_utc, to_ist
from app.models import Card, Complaint, Distribution, Event, Shop, Token, Window
from app.packs import get_pack
from app.seed import ensure_windows

ACTIVE_STATUSES = ("arrived", "waiting")


class BookingRefused(Exception):
    def __init__(self, reason: str, existing: Token | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.existing = existing


@dataclass
class QueueInfo:
    ahead: int
    minutes: int


def log_event(db: Session, actor: str, action: str, obj: str = "", **detail: object) -> None:
    db.add(Event(at=now_utc(), actor=actor, action=action, object=obj, detail=dict(detail)))


def paused(shop: Shop) -> bool:
    return shop.status_stock != "in_stock" or shop.status_machine != "working"


def window_start_utc(window: Window) -> datetime:
    return ist_to_utc(window.date, window.start_time)


def window_end_utc(window: Window) -> datetime:
    return window_start_utc(window) + timedelta(minutes=slots.WINDOW_MINUTES)


def entitlement_grams(card: Card) -> int:
    pack = get_pack(card.state_pack)
    return int(round(card.members * pack.kg_per_person("rice") * 1000))


# --- Queue ---------------------------------------------------------------


def people_ahead_now(db: Session, shop: Shop, day: date | None = None) -> QueueInfo:
    """Every waiting token today: booked families who have arrived, plus walk-ins."""
    day = day or ist_today()
    ahead = (
        db.scalar(
            select(func.count())
            .select_from(Token)
            .where(Token.shop_id == shop.id, Token.date == day, Token.status.in_(ACTIVE_STATUSES))
        )
        or 0
    )
    return QueueInfo(ahead, slots.wait_minutes(ahead, shop.families_per_hour))


def window_loads(db: Session, shop: Shop, day: date) -> list[slots.WindowLoad]:
    windows = ensure_windows(db, shop, day)
    counts = dict(
        db.execute(
            select(Token.window_id, func.count())
            .where(
                Token.shop_id == shop.id,
                Token.date == day,
                Token.kind == "booked",
                Token.status != "cancelled",
            )
            .group_by(Token.window_id)
        ).all()
    )
    return [
        slots.WindowLoad(w.id, w.start_time, counts.get(w.id, 0), w.booked_capacity)
        for w in windows
    ]


def quietest_tomorrow(db: Session, shop: Shop, now: datetime | None = None) -> time | None:
    tomorrow = ist_today(now) + timedelta(days=1)
    best = slots.quietest_window(window_loads(db, shop, tomorrow))
    return best.start if best else None


def offers(
    db: Session,
    shop: Shop,
    day: date,
    session: str | None,
    now: datetime | None = None,
    exclude: set[int] | None = None,
) -> list[Window]:
    """Windows with a free booking place, earliest first, skipping ones already started."""
    now = now or now_utc()
    not_before = to_ist(now).time() if day == ist_today(now) else None
    if day < ist_today(now):
        return []
    free = slots.free_windows(window_loads(db, shop, day), session, not_before, exclude or set())
    return [db.get_one(Window, w.id) for w in free]


def booking_this_month(db: Session, card: Card, day: date) -> Token | None:
    month_start = day.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return db.scalars(
        select(Token).where(
            Token.card_id == card.id,
            Token.kind == "booked",
            Token.status.not_in(("cancelled",)),
            Token.date >= month_start,
            Token.date < next_month,
        )
    ).first()


def check_can_book(db: Session, card: Card, day: date) -> None:
    existing = booking_this_month(db, card, day)
    reason = slots.booking_block_reason(paused(card.shop), existing is not None)
    if reason:
        raise BookingRefused(reason, existing)


def _next_token_no(db: Session, shop: Shop, day: date) -> int:
    current = db.scalar(
        select(func.max(Token.token_no)).where(Token.shop_id == shop.id, Token.date == day)
    )
    return (current or 0) + 1


def book(db: Session, card: Card, window: Window, channel: str) -> Token:
    """Create a booking. Refuses when paused, already booked this month, or window full."""
    check_can_book(db, card, window.date)
    taken = (
        db.scalar(
            select(func.count())
            .select_from(Token)
            .where(
                Token.window_id == window.id, Token.kind == "booked", Token.status != "cancelled"
            )
        )
        or 0
    )
    if taken >= window.booked_capacity:
        raise BookingRefused("full")
    token = Token(
        shop_id=card.shop_id,
        date=window.date,
        token_no=_next_token_no(db, card.shop, window.date),
        kind="booked",
        card_id=card.id,
        window_id=window.id,
        status="booked",
        issued_at=now_utc(),
        channel=channel,
    )
    db.add(token)
    db.flush()
    log_event(db, channel, "booked", f"token:{token.id}", window=str(window.start_time))
    return token


def add_walkin(db: Session, shop: Shop, card: Card | None = None, channel: str = "dealer") -> Token:
    today = ist_today()
    token = Token(
        shop_id=shop.id,
        date=today,
        token_no=_next_token_no(db, shop, today),
        kind="walkin",
        card_id=card.id if card else None,
        status="waiting",
        issued_at=now_utc(),
        channel=channel,
    )
    db.add(token)
    db.flush()
    log_event(db, "dealer", "walkin_added", f"token:{token.id}")
    return token


def mark_arrived(db: Session, token: Token, at: datetime | None = None) -> Token:
    """Mark a booked family arrived. More than 10 minutes late → joins the walk-in line."""
    at = at or now_utc()
    if token.kind != "booked" or token.status != "booked" or token.window is None:
        raise ValueError("only an open booking can be marked arrived")
    if slots.is_late(at, window_start_utc(token.window)):
        token.status = "late"
        log_event(db, "dealer", "late", f"token:{token.id}")
        walkin = add_walkin(db, db.get_one(Shop, token.shop_id), token.card)
        walkin.arrived_at = at
        return walkin
    token.status = "arrived"
    token.arrived_at = at
    log_event(db, "dealer", "arrived", f"token:{token.id}")
    return token


def sweep_no_shows(db: Session, shop: Shop, now: datetime | None = None) -> int:
    now = now or now_utc()
    count = 0
    for token in db.scalars(
        select(Token).where(
            Token.shop_id == shop.id, Token.status == "booked", Token.date <= ist_today(now)
        )
    ):
        if token.window and slots.is_no_show(token.status, window_end_utc(token.window), now):
            token.status = "no_show"
            log_event(db, "system", "no_show", f"token:{token.id}")
            count += 1
    return count


def _lines(db: Session, shop: Shop, now: datetime) -> tuple[list[Token], list[Token]]:
    today = ist_today(now)
    booked = [
        t
        for t in db.scalars(
            select(Token).where(
                Token.shop_id == shop.id,
                Token.date == today,
                Token.kind == "booked",
                Token.status == "arrived",
            )
        )
        if t.window is not None and window_start_utc(t.window) <= now
    ]
    booked.sort(key=lambda t: (t.window.start_time if t.window else time(), t.arrived_at or now))
    walkins = list(
        db.scalars(
            select(Token)
            .where(
                Token.shop_id == shop.id,
                Token.date == today,
                Token.kind == "walkin",
                Token.status == "waiting",
            )
            .order_by(Token.issued_at, Token.id)
        )
    )
    return booked, walkins


def last_served_kind(db: Session, shop: Shop, day: date) -> str | None:
    last = db.scalars(
        select(Token)
        .where(Token.shop_id == shop.id, Token.date == day, Token.status == "served")
        .order_by(Token.served_at.desc(), Token.id.desc())
    ).first()
    return last.kind if last else None


def serving_order(db: Session, shop: Shop, now: datetime | None = None) -> list[Token]:
    now = now or now_utc()
    booked, walkins = _lines(db, shop, now)
    by_id = {t.id: t for t in booked + walkins}
    last = last_served_kind(db, shop, ist_today(now))
    return [
        by_id[i] for i in slots.interleave([t.id for t in booked], [t.id for t in walkins], last)
    ]


def serve_next(
    db: Session, shop: Shop, grams: int | None = None, now: datetime | None = None
) -> Token | None:
    """Serve the next family and record a simulated ePoS sale (full entitlement by default)."""
    now = now or now_utc()
    order = serving_order(db, shop, now)
    if not order:
        return None
    token = order[0]
    token.status = "served"
    token.served_at = now
    due = entitlement_grams(token.card) if token.card else 0
    given = due if grams is None else grams
    db.add(
        Distribution(
            card_id=token.card_id,
            shop_id=shop.id,
            grams_given=given,
            served_at=now,
            token_id=token.id,
        )
    )
    start = token.window and window_start_utc(token.window)
    waited = (
        now - (start if start and token.kind == "booked" else token.issued_at)
    ).total_seconds()
    log_event(
        db,
        "dealer",
        "served",
        f"token:{token.id}",
        kind=token.kind,
        grams_given=given,
        grams_due=due,
        wait_minutes=max(0, round(waited / 60)),
    )
    return token


def ahead_of_booking(db: Session, token: Token, now: datetime | None = None) -> int:
    """People ahead of a booked family, computed live (used in reminders)."""
    now = now or now_utc()
    if token.window is None:
        return 0
    start = token.window.start_time
    booked_ahead = 0
    for other in db.scalars(
        select(Token).where(
            Token.shop_id == token.shop_id,
            Token.date == token.date,
            Token.kind == "booked",
            Token.status.in_(("booked", "arrived")),
            Token.id != token.id,
        )
    ):
        if other.window is None:
            continue
        same_window_before = other.window_id == token.window_id and other.token_no < token.token_no
        if other.window.start_time < start or same_window_before:
            booked_ahead += 1
    walkins = (
        db.scalar(
            select(func.count())
            .select_from(Token)
            .where(
                Token.shop_id == token.shop_id,
                Token.date == token.date,
                Token.kind == "walkin",
                Token.status == "waiting",
            )
        )
        or 0
    )
    return slots.ahead_for_booking(booked_ahead, walkins)


# --- Shop status ---------------------------------------------------------


def set_status(
    db: Session,
    shop: Shop,
    stock: str | None = None,
    machine: str | None = None,
    actor: str = "dealer",
) -> None:
    if stock is not None:
        if stock not in ("in_stock", "out"):
            raise ValueError(stock)
        shop.status_stock = stock
    if machine is not None:
        if machine not in ("working", "down"):
            raise ValueError(machine)
        shop.status_machine = machine
    log_event(
        db,
        actor,
        "status",
        f"shop:{shop.code}",
        stock=shop.status_stock,
        machine=shop.status_machine,
    )


# --- Complaints ----------------------------------------------------------


def file_complaint(db: Session, card: Card, grams_received: int, channel: str) -> Complaint:
    count = (
        db.scalar(
            select(func.count()).select_from(Complaint).where(Complaint.shop_id == card.shop_id)
        )
        or 0
    )
    complaint = Complaint(
        complaint_no=f"C-{card.shop.code}-{count + 1:04d}",
        card_id=card.id,
        shop_id=card.shop_id,
        grams_due=entitlement_grams(card),
        grams_received=grams_received,
        status="open",
        created_at=now_utc(),
    )
    db.add(complaint)
    db.flush()
    log_event(
        db,
        channel,
        "complaint_filed",
        f"complaint:{complaint.id}",
        grams_due=complaint.grams_due,
        grams_received=grams_received,
    )
    return complaint


def resolve_complaint(db: Session, complaint: Complaint, outcome: str) -> None:
    complaint.status = "resolved"
    complaint.outcome = outcome
    complaint.resolved_at = now_utc()
    log_event(db, "dealer", "complaint_resolved", f"complaint:{complaint.id}")
