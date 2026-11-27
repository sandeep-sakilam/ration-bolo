"""F43: one status warning per call and the reply length budget (acceptance check 28)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import queue
from app.models import Shop
from tests.test_dialogue import LAKSHMI, SALMA, Call

RAMU = "+919000008804"
CLOSING = {"Inka emaina kavala?", "Aur kuch chahiye?", "Anything else?"}


def budget(text: str) -> tuple[int, int]:
    """(sentences, characters) before the closing question."""
    parts = re.split(r"(?<=[.?!])\s+", text.strip())
    if parts and parts[-1].endswith("?"):
        parts = parts[:-1]
    return len(parts), len(" ".join(parts))


def _flow(db: Session, phone: str, lines: list[str]) -> list[str]:
    call = Call(db, phone)
    return [call.first.text] + [call.say(line).text for line in lines]


def _machine_down(db: Session) -> None:
    shop = db.scalars(select(Shop).where(Shop.code == "108")).one()
    queue.set_status(db, shop, machine="down")
    db.commit()


def _assert_budget(replies: list[str]) -> None:
    for text in replies:
        sentences, chars = budget(text)
        assert sentences <= 2 and chars <= 220, text


def test_budget_shop108_flow(db: Session) -> None:
    lines = ["Avunu", "Maa shop ki biyyam vachaya?", "Ippudu entha mandi unnaru?"]
    lines += ["Repu poddhuna book cheyyandi", "Avunu", "Naaku 15 kilolu ichharu", "Avunu"]
    replies = _flow(db, LAKSHMI, lines)
    assert "Repu 10:20 ki, sare na?" in replies
    _assert_budget(replies)


def test_budget_hindi_flow(db: Session) -> None:
    lines = ["haan", "Mera ration aaya kya?", "Kitne log hain?", "Kal subah book karo", "haan"]
    lines += ["Mujhe kam mila", "das kilo", "haan"]
    _assert_budget(_flow(db, SALMA, lines))


def test_budget_level0_flow(db: Session) -> None:
    lines = ["Avunu", "Biyyam vachaya?", "Repu poddhuna book cheyyandi", "entha mandi unnaru"]
    lines += ["Biyyam vachindi, ikkada 12 mandi unnaru", "Avunu"]
    _assert_budget(_flow(db, RAMU, lines))


def test_budget_nearby_flows(db: Session) -> None:
    _machine_down(db)
    _assert_budget(_flow(db, LAKSHMI, ["Avunu", "Maa shop ki biyyam vachaya?", "Avunu"]))
    _assert_budget(_flow(db, SALMA, ["haan", "Kal subah book karo", "nahi", "haan"]))


def test_check28_machine_warning_once_per_call(db: Session) -> None:
    _machine_down(db)
    call = Call(db, LAKSHMI)
    assert "machine pani cheyyatledu" in call.first.text
    call.say("Avunu")
    r = call.say("Maa shop ki biyyam vachaya?")
    assert "machine" not in r.text.lower()
    assert r.text.startswith("Avunu, biyyam vachindi. Mee kutumbaniki 24 kilolu.")
    # Trying to book while paused: the reason is the answer, said once.
    call.say("Kaadu")
    r = call.say("Repu poddhuna book cheyyandi")
    assert r.text.lower().count("machine") == 1 and "booking aagipoyindi" in r.text


def test_warning_repeated_when_status_changes(db: Session) -> None:
    call = Call(db, LAKSHMI)
    assert "machine" not in call.first.text.lower()
    call.say("Avunu")
    _machine_down(db)
    r = call.say("Maa shop ki biyyam vachaya?")
    assert "machine pani cheyyatledu" in r.text.lower()
    r = call.say("Kaadu")
    r = call.say("Maa shop ki biyyam vachaya?")
    assert "gamaninchandi" not in r.text.lower()
