"""Demo data for the Hyderabad pilot (Shop 108, Malakpet). Everything here is fictional."""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.clock import ist_to_utc, ist_today, now_utc
from app.models import (
    Card,
    CardHolder,
    Complaint,
    DialogueSession,
    Distribution,
    Event,
    Outbox,
    PhoneLink,
    Reminder,
    Shop,
    Token,
    Turn,
    Window,
)
from app.slots import build_windows

SHOP_CODE = "108"
PILOT_SESSIONS = [["08:00", "12:00"], ["16:00", "20:00"]]
KG_PER_PERSON_RICE = 6

DEMO_CALLERS = {
    "lakshmi": {"phone": "+919000004401", "label": "Lakshmi (Telugu, card 0421)"},
    "salma": {"phone": "+919000007702", "label": "Salma (Hindi, card 0513)"},
    "family": {"phone": "+919000009903", "label": "Family phone (2 cards)"},
    "unknown": {"phone": "+919000000000", "label": "Unknown number"},
}

# Delete order respects foreign keys.
_ALL_TABLES = [
    Turn,
    DialogueSession,
    Reminder,
    Distribution,
    Complaint,
    Token,
    Window,
    PhoneLink,
    CardHolder,
    Outbox,
    Event,
    Card,
    Shop,
]


def is_empty(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(Shop)) or 0) == 0


def ensure_windows(db: Session, shop: Shop, day: date) -> list[Window]:
    """Windows are generated per day, on first use."""
    existing = list(
        db.scalars(
            select(Window)
            .where(Window.shop_id == shop.id, Window.date == day)
            .order_by(Window.start_time)
        )
    )
    if existing:
        return existing
    for spec in build_windows(shop.sessions, shop.families_per_hour, shop.booked_share):
        db.add(
            Window(
                shop_id=shop.id,
                date=day,
                start_time=spec.start,
                booked_capacity=spec.booked_capacity,
                walkin_capacity=spec.walkin_capacity,
            )
        )
    db.flush()
    return ensure_windows(db, shop, day)


def seed_demo(db: Session, now: datetime | None = None) -> None:
    now = now or now_utc()
    today = ist_today(now)
    tomorrow = today + timedelta(days=1)
    rng = random.Random(108)

    shop = Shop(
        code=SHOP_CODE,
        name="Fair Price Shop 108",
        area="Malakpet, Hyderabad",
        state_pack="telangana",
        sessions=PILOT_SESSIONS,
        families_per_hour=30,
        booked_share=0.5,
        status_stock="in_stock",
        status_machine="working",
    )
    db.add(shop)
    db.flush()

    def card(no: str, members: int, lang: str, name: str) -> Card:
        c = Card(
            card_no=no, shop_id=shop.id, members=members, language=lang, state_pack="telangana"
        )
        db.add(c)
        db.flush()
        db.add(CardHolder(card_id=c.id, display_name=name))
        return c

    lakshmi = card("TS-108-0421", 4, "te", "Lakshmi (demo)")
    salma = card("TS-108-0513", 3, "hi", "Salma (demo)")
    fam_a = card("TS-108-0610", 5, "te", "Family card A (demo)")
    fam_b = card("TS-108-0733", 2, "te", "Family card B (demo)")
    for c, phone in [
        (lakshmi, DEMO_CALLERS["lakshmi"]["phone"]),
        (salma, DEMO_CALLERS["salma"]["phone"]),
        (fam_a, DEMO_CALLERS["family"]["phone"]),
        (fam_b, DEMO_CALLERS["family"]["phone"]),
    ]:
        db.add(PhoneLink(phone_e164=phone, card_id=c.id, source="seed"))

    others = [
        card(
            f"TS-108-{1000 + i}",
            rng.randint(1, 6),
            rng.choice(["te", "te", "hi"]),
            f"Demo family {i}",
        )
        for i in range(1, 71)
    ]

    # Today: 18 walk-ins waiting.
    for n, c in enumerate(others[:18], start=1):
        issued = ist_to_utc(today, time(8, 0)) + timedelta(minutes=4 * n)
        db.add(
            Token(
                shop_id=shop.id,
                date=today,
                token_no=n,
                kind="walkin",
                card_id=c.id,
                status="waiting",
                issued_at=min(issued, now),
                channel="dealer",
            )
        )

    # Tomorrow: morning windows 08:00 to 10:00 fully booked → first free is 10:20.
    windows = ensure_windows(db, shop, tomorrow)
    booked_cards = iter(others[18:])
    token_no = 0
    for w in windows:
        if w.start_time > time(10, 0):
            break
        for _ in range(w.booked_capacity):
            token_no += 1
            db.add(
                Token(
                    shop_id=shop.id,
                    date=tomorrow,
                    token_no=token_no,
                    kind="booked",
                    card_id=next(booked_cards).id,
                    window_id=w.id,
                    status="booked",
                    issued_at=now - timedelta(hours=rng.randint(1, 30)),
                    channel="call",
                )
            )

    _seed_history(db, shop, others, today, rng)
    db.add(Event(at=now, actor="system", action="demo_seeded", object=f"shop:{shop.code}"))
    db.commit()


def _seed_history(
    db: Session, shop: Shop, cards: list[Card], today: date, rng: random.Random
) -> None:
    """A week of past activity so the metrics page looks real."""
    engines = ["wispr"] * 7 + ["sarvam"] * 2 + ["browser"]
    for back in range(7, 0, -1):
        day = today - timedelta(days=back)
        for n in range(1, 13):
            c = rng.choice(cards)
            kind = "booked" if n % 2 else "walkin"
            slot_start = ist_to_utc(day, time(8, 0)) + timedelta(minutes=20 * (n // 2))
            wait = rng.randint(4, 18) if kind == "booked" else rng.randint(25, 95)
            issued = slot_start if kind == "booked" else slot_start - timedelta(minutes=wait - 5)
            served = issued + timedelta(minutes=wait)
            tok = Token(
                shop_id=shop.id,
                date=day,
                token_no=n,
                kind=kind,
                card_id=c.id,
                status="served",
                issued_at=issued,
                arrived_at=issued,
                served_at=served,
                channel=rng.choice(["call", "whatsapp", "dealer"]),
            )
            db.add(tok)
            db.flush()
            grams = c.members * KG_PER_PERSON_RICE * 1000
            db.add(
                Distribution(
                    card_id=c.id,
                    shop_id=shop.id,
                    grams_given=grams,
                    served_at=served,
                    token_id=tok.id,
                )
            )
            db.add(
                Event(
                    at=served,
                    actor="dealer",
                    action="served",
                    object=f"token:{tok.id}",
                    detail={"kind": kind, "wait_minutes": wait},
                )
            )
        for _ in range(rng.randint(5, 9)):
            c = rng.choice(cards)
            started = ist_to_utc(day, time(rng.randint(7, 19), rng.randint(0, 59)))
            menu = rng.random() < 0.12
            heard_by = rng.choice(engines)
            sess = DialogueSession(
                channel=rng.choice(["call", "call", "whatsapp"]),
                phone_masked="+91 •••• ••" + str(rng.randint(1000, 9999)),
                card_id=c.id,
                language=c.language,
                state="ended",
                used_menu=menu,
                engine="backup" if heard_by == "sarvam" else "primary",
                started_at=started,
                last_activity_at=started,
                ended_at=started + timedelta(minutes=2),
            )
            db.add(sess)
            db.flush()
            for t in range(rng.randint(2, 4)):
                db.add(
                    Turn(
                        session_id=sess.id,
                        role="caller",
                        text="(demo transcript)",
                        language=c.language,
                        engine=heard_by,
                        understood=not (menu and t == 0),
                        created_at=started + timedelta(seconds=20 * t),
                    )
                )
            db.add(
                Event(
                    at=started,
                    actor=sess.channel,
                    action="intent",
                    object=f"session:{sess.id}",
                    detail={"intent": rng.choice(["stock", "queue", "book"])},
                )
            )
    c1, c2 = cards[60], cards[61]
    db.add(
        Complaint(
            complaint_no="C-108-0001",
            card_id=c1.id,
            shop_id=shop.id,
            grams_due=c1.members * 6000,
            grams_received=c1.members * 6000 - 4000,
            status="resolved",
            outcome="Dealer gave the missing 4 kg on recheck",
            created_at=ist_to_utc(today - timedelta(days=6), time(10, 0)),
            resolved_at=ist_to_utc(today - timedelta(days=3), time(12, 0)),
        )
    )
    db.add(
        Complaint(
            complaint_no="C-108-0002",
            card_id=c2.id,
            shop_id=shop.id,
            grams_due=c2.members * 6000,
            grams_received=c2.members * 6000 - 3000,
            status="open",
            created_at=ist_to_utc(today - timedelta(days=2), time(17, 0)),
        )
    )


def reset_demo(db: Session, now: datetime | None = None) -> None:
    for model in _ALL_TABLES:
        db.execute(delete(model))
    db.commit()
    seed_demo(db, now)


def seed_if_empty(db: Session) -> bool:
    if is_empty(db):
        seed_demo(db)
        return True
    return False
