"""F33: best-time advice (acceptance check 18 and the Level 0 half of check 15)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import besttime, clock
from app.besttime import Sample
from app.models import HourlyProfile, Shop
from tests.test_dialogue import Call

TODAY = date(2026, 11, 27)  # a Friday, not in the first week


def _shop(db: Session, code: str) -> Shop:
    return db.scalars(select(Shop).where(Shop.code == code)).one()


def test_build_weights_recent_weeks_and_first_week() -> None:
    samples = [
        Sample(TODAY - timedelta(days=7), 9, 40.0),  # last Friday, weight 1/2
        Sample(TODAY - timedelta(days=14), 9, 10.0),  # 2 weeks ago, weight 1/3
        Sample(date(2026, 11, 6), 9, 70.0),  # first-week Friday: 70 / 1.4 = 50
        Sample(TODAY - timedelta(days=40), 9, 99.0),  # older than 4 weeks: ignored
    ]
    profile = besttime.build(samples, TODAY, 1.4)
    wait, count = profile[(4, 9)]
    assert count == 3
    expected = (40 * 0.5 + 10 / 3 + 50 * 0.25) / (0.5 + 1 / 3 + 0.25)  # Nov 6: 3 weeks, 1/4
    assert round(wait, 2) == round(expected, 2)


def test_spoken_minutes_round_up_to_5() -> None:
    assert [besttime.spoken_minutes(w) for w in (0, 3, 11, 15, 15.2)] == [5, 5, 15, 15, 20]


def test_check18_few_data_points_use_default_and_say_usually(
    client: TestClient, db: Session
) -> None:
    shop = _shop(db, "201")  # no history at all
    waits, known = besttime.expected_waits(db, shop, TODAY)
    assert not known and waits[17] == 25  # Tamil Nadu draft: default pattern
    advice = besttime.best_time(db, shop)
    assert advice is not None and not advice.known
    db.commit()
    # Spoken with "usually" and no number (Telangana default for a new Level 0 shop).
    csv = (
        "code,name,area,state_pack,sessions,families_per_hour,booked_share,level\n"
        "150,Shop 150,X,telangana,08:00-12:00;16:00-20:00,30,0.5,0\n"
        "card_no,shop_code,members,language,phone\n"
    )
    client.post(
        "/api/admin/import/shops",
        files={"file": ("s.csv", csv.split("card_no")[0].encode(), "text/csv")},
    )
    cards = "card_no,shop_code,members,language,phone\nTS-150-0001,150,3,te,+919000001501\n"
    client.post("/api/admin/import/cards", files={"file": ("c.csv", cards.encode(), "text/csv")})
    db.expire_all()
    call = Call(db, "+919000001501")
    call.say("Avunu")
    r = call.say("repu book cheyyandi")
    # v3.1 (F41): advice times are spoken as part-of-day phrases, not "16:00".
    assert "Sadharananga Ivala saayantram 5 gantala lopu rush takkuva." in r.text
    assert "nimishala lopu" not in r.text


def test_shop_history_gives_numbers(db: Session) -> None:
    shop = _shop(db, "112")
    waits, known = besttime.expected_waits(db, shop, TODAY)
    assert known and waits[17] < waits[9]
    advice = besttime.best_time(db, shop)  # 11:00 IST now → best later today is 17:00
    assert advice is not None and advice.known and advice.hour == 19 and advice.minutes <= 15
    assert db.scalars(select(HourlyProfile).where(HourlyProfile.shop_id == shop.id)).first()


def test_tomorrow_when_today_is_over(db: Session) -> None:
    clock.freeze(clock.now_utc() + timedelta(hours=9))  # 20:00 IST
    advice = besttime.best_time(db, _shop(db, "112"))
    assert advice is not None and advice.day == TODAY + timedelta(days=1)


def test_queue_answer_adds_best_time_at_every_level(db: Session) -> None:
    call = Call(db, "+919000004401")
    call.say("Avunu")
    r = call.say("Ippudu entha mandi unnaru?")
    assert r.text.startswith("18 mandi mundu unnaru, sumaru 36 nimishalu.")
    assert "Repu 10:20 ki rush takkuva." in r.text
    assert any(a["type"] == "best_time_advice" for a in r.actions)
