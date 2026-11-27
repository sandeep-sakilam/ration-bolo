"""F44: after accepting a nearby shop, today's wait (acceptance check 29)."""

from __future__ import annotations

from datetime import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, queue
from app.clock import ist_to_utc, ist_today
from app.dialogue import Reply
from app.models import Shop
from tests.test_dialogue import LAKSHMI, SALMA, Call


def _shop(db: Session, code: str) -> Shop:
    return db.scalars(select(Shop).where(Shop.code == code)).one()


def _accept_112(db: Session, phone: str = LAKSHMI) -> tuple[Reply, Reply]:
    queue.set_status(db, _shop(db, "108"), machine="down")
    db.commit()
    call = Call(db, phone)
    call.say("Avunu" if phone == LAKSHMI else "haan")
    offer = call.say("Maa shop ki biyyam vachaya?" if phone == LAKSHMI else "Mera ration aaya kya?")
    return offer, call.say("Avunu" if phone == LAKSHMI else "haan")


def test_check29_go_now_with_the_quoted_wait(db: Session) -> None:
    offer, r = _accept_112(db)
    quoted = next(a["wait"] for a in offer.actions if a["type"] == "nearby_offer")
    assert f"sumaru {quoted} nimishala wait" in offer.text
    assert r.text == (
        f"Sare, Shop 112. Ippude vellochu, akkada sumaru {quoted} nimishala wait. "
        "Inka emaina kavala?"
    )
    assert "Repu" not in r.text
    assert {"type": "nearby_go_now", "shop": "112", "wait": quoted} in r.actions


def test_go_now_in_hindi(db: Session) -> None:
    _offer, r = _accept_112(db, SALMA)
    assert "Abhi ja sakte hain, wahan lagbhag 10 minute ka intezaar." in r.text


def _accept_at(db: Session, hh: int) -> Reply:
    clock.freeze(ist_to_utc(ist_today(), time(hh, 0)))
    offer, r = _accept_112(db)
    assert offer.state == "nearby_offer"
    return r


@pytest.mark.parametrize("hh", [13, 21])
def test_closed_shop_reply_repeats_the_offer(db: Session, hh: int) -> None:
    # F46: a closed shop is offered with when it opens; "yes" repeats that time and wait.
    clock.freeze(ist_to_utc(ist_today(), time(hh, 0)))
    offer, r = _accept_112(db)
    assert offer.state == "nearby_offer" and "Ippude" not in r.text
    opens = next(a for a in r.actions if a["type"] == "nearby_opens")
    assert f"appudu sadharananga {opens['wait']} nimishala wait" in offer.text
    assert f"appudu sadharananga {opens['wait']} nimishala wait." in r.text
    when = "Repu poddhuna 8 gantalaku" if hh == 21 else "Saayantram 4 gantalaku"
    assert when in r.text and when.lower() in offer.text.lower()
