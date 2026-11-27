from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import queue
from app.clock import ist_to_utc, ist_today
from app.models import Card, Distribution, Shop, Token
from app.queue import BookingRefused


def _shop(db: Session) -> Shop:
    return db.scalars(select(Shop)).one()


def _card(db: Session, last: str) -> Card:
    return db.scalars(select(Card).where(Card.card_no.endswith(last))).one()


def test_people_ahead_is_18_and_36_minutes(db: Session) -> None:
    info = queue.people_ahead_now(db, _shop(db))
    assert (info.ahead, info.minutes) == (18, 36)


def test_first_free_tomorrow_morning_is_1020(db: Session) -> None:
    tomorrow = ist_today() + timedelta(days=1)
    windows = queue.offers(db, _shop(db), tomorrow, "morning")
    assert [w.start_time for w in windows[:3]] == [time(10, 20), time(10, 40), time(11, 0)]
    assert queue.quietest_tomorrow(db, _shop(db)) == time(10, 20)


def test_today_skips_started_windows(db: Session) -> None:
    windows = queue.offers(db, _shop(db), ist_today(), None)  # now is 11:00 IST
    assert windows[0].start_time == time(11, 20)


def test_book_once_per_month(db: Session) -> None:
    lakshmi = _card(db, "0421")
    window = queue.offers(db, _shop(db), ist_today() + timedelta(days=1), "morning")[0]
    token = queue.book(db, lakshmi, window, "simulator")
    assert token.status == "booked" and token.window_id == window.id
    with pytest.raises(BookingRefused) as err:
        queue.book(db, lakshmi, queue.offers(db, _shop(db), window.date, "evening")[0], "call")
    assert err.value.reason == "month" and err.value.existing is token


def test_booking_paused_when_machine_down(db: Session) -> None:
    shop = _shop(db)
    queue.set_status(db, shop, machine="down")
    window = queue.offers(db, shop, ist_today() + timedelta(days=1), "morning")[0]
    with pytest.raises(BookingRefused) as err:
        queue.book(db, _card(db, "0513"), window, "call")
    assert err.value.reason == "paused"
    queue.set_status(db, shop, machine="working", stock="out")
    with pytest.raises(BookingRefused):
        queue.book(db, _card(db, "0513"), window, "call")


def test_full_window_refused(db: Session) -> None:
    tomorrow = ist_today() + timedelta(days=1)
    full = db.scalars(select(Token).where(Token.date == tomorrow)).first()
    assert full is not None and full.window is not None
    with pytest.raises(BookingRefused) as err:
        queue.book(db, _card(db, "0421"), full.window, "call")
    assert err.value.reason == "full"


def _today_booking(db: Session, start: time) -> Token:
    shop = _shop(db)
    window = next(
        w
        for w in queue.offers(db, shop, ist_today(), None, now=ist_to_utc(ist_today(), time(7, 0)))
        if w.start_time == start
    )
    return queue.book(db, _card(db, "0421"), window, "call")


def test_arrival_11_minutes_late_joins_walkins(db: Session) -> None:
    token = _today_booking(db, time(11, 20))
    late = queue.mark_arrived(db, token, at=ist_to_utc(ist_today(), time(11, 31)))
    assert token.status == "late"
    assert late.kind == "walkin" and late.status == "waiting" and late.card_id == token.card_id


def test_arrival_on_time(db: Session) -> None:
    token = _today_booking(db, time(11, 20))
    same = queue.mark_arrived(db, token, at=ist_to_utc(ist_today(), time(11, 30)))
    assert same is token and token.status == "arrived"


def test_serve_alternates_and_records_sale(db: Session) -> None:
    shop = _shop(db)
    token = _today_booking(db, time(11, 20))
    queue.mark_arrived(db, token, at=ist_to_utc(ist_today(), time(11, 22)))
    now = ist_to_utc(ist_today(), time(11, 25))
    first = queue.serve_next(db, shop, now=now)
    second = queue.serve_next(db, shop, now=now)
    assert first is token and second is not None and second.kind == "walkin"
    sale = db.scalars(select(Distribution).where(Distribution.token_id == token.id)).one()
    assert sale.grams_given == 24000
    third = queue.serve_next(db, shop, grams=3000, now=now)
    assert third is not None and third.kind == "walkin"
    assert queue.people_ahead_now(db, shop).ahead == 16


def test_no_show_sweep(db: Session) -> None:
    token = _today_booking(db, time(11, 20))
    assert queue.sweep_no_shows(db, _shop(db), now=ist_to_utc(ist_today(), time(11, 39))) == 0
    assert queue.sweep_no_shows(db, _shop(db), now=ist_to_utc(ist_today(), time(11, 40))) == 1
    assert token.status == "no_show"


def test_ahead_of_booking_is_live(db: Session) -> None:
    tomorrow = ist_today() + timedelta(days=1)
    first = db.scalars(select(Token).where(Token.date == tomorrow).order_by(Token.token_no)).first()
    assert first is not None
    assert queue.ahead_of_booking(db, first) == 0  # no walk-ins yet tomorrow
    second = db.scalars(select(Token).where(Token.date == tomorrow, Token.token_no == 2)).one()
    assert queue.ahead_of_booking(db, second) == 1


def test_complaints_numbered_and_resolved(db: Session) -> None:
    c = queue.file_complaint(db, _card(db, "0421"), 15000, "call")
    assert c.complaint_no == "C-108-0003" and c.grams_due == 24000
    queue.resolve_complaint(db, c, "Gave 9 kg")
    assert c.status == "resolved" and c.resolved_at is not None


def test_entitlement(db: Session) -> None:
    assert queue.entitlement_grams(_card(db, "0513")) == 18000
    assert datetime is not None
