from datetime import time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import ist_today
from app.models import Card, PhoneLink, Shop, Token, Window
from app.seed import ensure_windows, reset_demo, seed_demo, seed_if_empty


def test_seed_matches_pilot(empty_db: Session) -> None:
    db = empty_db
    seed_demo(db)
    shop = db.scalars(select(Shop).where(Shop.code == "108")).one()
    assert shop.code == "108" and shop.families_per_hour == 30
    lakshmi = db.scalars(select(Card).where(Card.card_no == "TS-108-0421")).one()
    assert lakshmi.members == 4 and lakshmi.language == "te" and lakshmi.last4 == "0421"
    salma = db.scalars(select(Card).where(Card.card_no == "TS-108-0513")).one()
    assert salma.members == 3 and salma.language == "hi"
    assert (db.scalar(select(func.count()).select_from(Card)) or 0) >= 44
    today = ist_today()
    waiting = db.scalars(select(Token).where(Token.date == today, Token.status == "waiting")).all()
    assert len(waiting) == 18 and all(t.kind == "walkin" for t in waiting)
    links = db.scalars(select(PhoneLink).where(PhoneLink.phone_e164 == "+919000009903")).all()
    assert len(links) == 2


def test_tomorrow_booked_until_ten(empty_db: Session) -> None:
    db = empty_db
    seed_demo(db)
    tomorrow = ist_today() + timedelta(days=1)
    windows = db.scalars(select(Window).where(Window.date == tomorrow)).all()
    assert len(windows) == 24  # 12 per session
    for w in windows:
        booked = db.scalar(select(func.count()).select_from(Token).where(Token.window_id == w.id))
        expected = 5 if w.start_time <= time(10, 0) else 0
        assert booked == expected, w.start_time


def test_seed_only_when_empty_and_reset(empty_db: Session) -> None:
    db = empty_db
    assert seed_if_empty(db) is True
    assert seed_if_empty(db) is False
    shop = db.scalars(select(Shop).where(Shop.code == "108")).one()
    shop.status_machine = "down"
    db.commit()
    reset_demo(db)
    assert db.scalars(select(Shop).where(Shop.code == "108")).one().status_machine == "working"
    assert db.scalar(select(func.count()).select_from(Shop)) == 2


def test_ensure_windows_idempotent(empty_db: Session) -> None:
    db = empty_db
    seed_demo(db)
    shop = db.scalars(select(Shop).where(Shop.code == "108")).one()
    day = ist_today() + timedelta(days=5)
    assert len(ensure_windows(db, shop, day)) == 24
    assert len(ensure_windows(db, shop, day)) == 24
