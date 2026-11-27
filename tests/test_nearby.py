"""F34: nearby-shop portability (acceptance check 19)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import levels, nearby, queue
from app.models import Shop, Token
from tests.test_dialogue import LAKSHMI, SALMA, Call


def _shop(db: Session, code: str) -> Shop:
    return db.scalars(select(Shop).where(Shop.code == code)).one()


def _machine_down(db: Session) -> None:
    queue.set_status(db, _shop(db, "108"), machine="down")
    db.commit()


def test_haversine_demo_distances() -> None:
    assert round(nearby.haversine_km(17.3752, 78.4983, 17.3644, 78.4983), 1) == 1.2
    assert round(nearby.haversine_km(17.3752, 78.4983, 17.3752, 78.5153), 1) == 1.8


def test_no_suggestion_when_shop_is_fine(db: Session) -> None:
    assert not nearby.needs_alternative(db, _shop(db, "108"))
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    assert call.say("Maa shop ki biyyam vachaya?").text.endswith("Inka emaina kavala?")


def test_ranking_rice_confirmed_then_wait_then_distance(db: Session) -> None:
    found = nearby.candidates(db, _shop(db, "108"))
    assert [c.shop.code for c in found] == ["112", "115"]
    assert found[0].confirmed_ok and found[0].wait == 10 and round(found[0].km, 1) == 1.2
    assert found[1].wait == 24 and found[1].level == 1


def test_check19_machine_down_offers_112_then_best_time(db: Session) -> None:
    _machine_down(db)
    call = Call(db, LAKSHMI)
    assert "machine pani cheyyatledu" in call.first.text
    call.say("Avunu")
    r = call.say("Maa shop ki biyyam vachaya?")
    assert (
        "Shop 112, near Saidabad bus stop, 1.2 km dooram lo undi; akkada biyyam undi, "
        "sumaru 10 nimishala wait, mee card sadharananga akkada kuda panichestundi; "
        "akkadiki veltara?"
    ) in r.text
    assert r.text.endswith("akkadiki veltara?") and r.state == "nearby_offer"
    assert (
        "Shop 112, near Saidabad bus stop, 1.2 km away, has rice and about 10 minutes' wait"
        in r.gloss
    )
    r = call.say("Avunu")
    # F44 (check 29): open, in stock and working now, so "go now" with the quoted wait.
    assert r.text.startswith("Sare, Shop 112. Ippude vellochu, akkada sumaru 10 nimishala wait.")
    assert {"type": "nearby_accepted", "shop": "112"} in r.actions
    shop112 = _shop(db, "112")
    assert db.scalars(select(Token).where(Token.shop_id == shop112.id)).first() is None


def test_no_then_second_shop_and_booking_there(db: Session) -> None:
    _machine_down(db)
    call = Call(db, SALMA)
    call.say("haan")
    r = call.say("Kal subah book karo")
    assert "booking ruki hai" in r.text.lower() and "Dukaan 112" in r.text
    r = call.say("nahi")
    assert "Dukaan 115, near Moosarambagh bridge, 1.8 km door hai" in r.text
    r = call.say("haan")
    assert r.text == (
        "Theek hai, dukaan 115. Abhi ja sakte hain, wahan lagbhag 24 minute ka intezaar. "
        "Kis din, subah ya shaam?"
    )
    r = call.say("kal subah")
    assert r.text == "Kal 08:00 baje, theek hai?"
    r = call.say("haan")
    assert "Booking ho gayi" in r.text
    token = db.scalars(
        select(Token).where(Token.channel == "simulator", Token.status == "booked")
    ).one()
    assert token.shop_id == _shop(db, "115").id  # the month rule still follows the card


def test_long_wait_triggers_and_complaints_count_only_when_upheld(db: Session) -> None:
    shop = _shop(db, "108")
    for _ in range(5):
        queue.add_walkin(db, shop)
    assert nearby.predicted_wait(db, shop) == 46 and nearby.needs_alternative(db, shop)


def test_portability_off_and_far_shops_excluded(db: Session) -> None:
    levels.set_profile(db, _shop(db, "112"), portability=False)
    levels.set_profile(db, _shop(db, "115"), lat=17.50)  # ~14 km away
    assert [c.shop.code for c in nearby.candidates(db, _shop(db, "108"))] == ["109"]
