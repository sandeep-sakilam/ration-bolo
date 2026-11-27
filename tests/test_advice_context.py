"""F42: advice honours the day and part of day asked for (acceptance check 27)."""

from __future__ import annotations

from datetime import time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import besttime, clock
from app.clock import ist_to_utc, ist_today
from app.models import Shop
from tests.test_dialogue import Call

RAMU = "+919000008804"


def _shop(db: Session, code: str = "112") -> Shop:
    return db.scalars(select(Shop).where(Shop.code == code)).one()


def test_check27_ramu_tomorrow_morning_gets_morning_advice(db: Session) -> None:
    call = Call(db, RAMU)
    call.say("Avunu")
    r = call.say("Repu poddhuna book cheyyandi")
    assert r.text.startswith("Ee shop lo inka booking ledu. Repu poddhuna 11 gantala taruvata")
    assert "saayantram" not in r.text
    assert r.gloss.startswith(
        "This shop doesn't take bookings yet. Tomorrow after 11 in the morning"
    )


def test_busy_part_says_so_and_offers_best_other_part(db: Session) -> None:
    shop = _shop(db, "109")  # mornings 30–55 minutes in its history
    advice = besttime.best_time(db, shop, day_word="tomorrow", part="morning")
    assert advice is not None and advice.busy_part == "morning" and advice.hour >= 16
    from app.models import Card, PhoneLink, Volunteer

    for v in db.scalars(select(Volunteer)):
        v.on_duty = False
    card = db.scalars(select(Card).where(Card.card_no == "TS-109-3001")).one()
    db.add(PhoneLink(phone_e164="+919000001091", card_id=card.id, source="seed"))
    db.commit()
    call = Call(db, "+919000001091")
    call.say("Avunu")
    r = call.say("Repu poddhuna book cheyyandi")
    assert "Repu poddhuna rush ekkuva; saayantram" in r.text
    assert "Tomorrow morning is busy; after" in r.gloss


def test_this_evening_and_no_day(db: Session) -> None:
    shop = _shop(db)
    evening = besttime.best_time(db, shop, day_word="today", part="evening")
    assert evening is not None and evening.day == ist_today() and evening.hour >= 16
    plain = besttime.best_time(db, shop)  # 11:00 IST: today still has hours
    assert plain is not None and plain.day == ist_today()


def test_no_day_after_closing_is_tomorrow(db: Session) -> None:
    clock.freeze(ist_to_utc(ist_today(), time(20, 30)))
    advice = besttime.best_time(db, _shop(db))
    assert advice is not None and advice.day == ist_today() + timedelta(days=1)


def test_morning_over_today_moves_to_tomorrow_morning(db: Session) -> None:
    clock.freeze(ist_to_utc(ist_today(), time(13, 0)))
    advice = besttime.best_time(db, _shop(db), part="morning")
    assert advice is not None and advice.day == ist_today() + timedelta(days=1)
    assert advice.hour < 12 and advice.busy_part is None
