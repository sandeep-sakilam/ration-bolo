"""F41: natural spoken times in advice (acceptance check 26)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import queue, spoken
from app.packs import get_pack, load_packs
from tests.test_dialogue import LAKSHMI, SALMA, Call

TS = get_pack("telangana")
# 24-hour clock text: "09:10", "16:00", "19:30" (12-hour "9:10" after a part of day is fine).
CLOCK = re.compile(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b")


@pytest.mark.parametrize(
    ("lang", "kind", "hour", "text"),
    [
        ("te", "before", 9, "poddhuna 9 gantala lopu"),
        ("te", "after", 14, "madhyahnam 2 gantala taruvata"),
        ("te", "after", 19, "saayantram 7 gantala taruvata"),
        ("hi", "before", 9, "subah 9 baje se pehle"),
        ("hi", "after", 14, "dopahar 2 baje ke baad"),
        ("hi", "after", 19, "shaam 7 baje ke baad"),
        ("en", "before", 9, "before 9 in the morning"),
        ("en", "after", 19, "after 7 in the evening"),
        ("en", "at_hour", 8, "at 8 in the morning"),
        ("en", "between", 16, "between 4 and 4 in the evening"),
    ],
)
def test_part_of_day_phrases(lang: str, kind: str, hour: int, text: str) -> None:
    assert spoken.say(TS, lang, kind, hour) == text


def test_parts_of_day_ranges() -> None:
    assert [spoken.part_of_day(h) for h in (5, 11, 12, 15, 16, 19, 20, 2)] == [
        "morning",
        "morning",
        "afternoon",
        "afternoon",
        "evening",
        "evening",
        "night",
        "night",
    ]
    assert spoken.say(TS, "te", "at", 9, 10) == "poddhuna 9:10 ki"


def test_advice_first_hour_of_session_is_before_next_hour() -> None:
    assert spoken.advice_when(TS, "en", 16, [8, 16]) == "before 5 in the evening"
    assert spoken.advice_when(TS, "en", 19, [8, 16]) == "after 7 in the evening"


def test_older_pack_falls_back_and_is_listed(client: TestClient) -> None:
    tn = load_packs()["tamil_nadu"]
    assert spoken.say(tn, "ta", "after", 19) == "after 7 pm"
    status = client.get("/api/status").json()
    assert (
        "time_phrases"
        in next(p for p in status["packs"] if p["state"] == "tamil_nadu")["missing_v3"]
    )


# Sentences that carry exact slot/token times (kept as "10:20" by design).
SLOT_SENTENCES = [
    r"[^.?]*\b(ki|baje|at)\b[^.?]*(sare na|theek hai|okay)\?",  # booking offers
    r"Repu \d{1,2}:\d{2} ki rush takkuva\.",
    r"Kal \d{1,2}:\d{2} baje bheed kam hai\.",
    r"Tomorrow \d{1,2}:\d{2} is the quietest\.",
    r"[^.]*(booking already undi|booking pehle se hai|already has a booking)[^.]*\.",
]


def _advice_text(text: str) -> str:
    for pattern in SLOT_SENTENCES:
        text = re.sub(pattern, "", text)
    return text


def test_check26_no_clock_times_in_advice(db: Session) -> None:
    replies: list[str] = []
    call = Call(db, LAKSHMI)
    for t in (
        "Avunu",
        "Maa shop ki biyyam vachaya?",
        "Ippudu entha mandi unnaru?",
        "Repu poddhuna book cheyyandi",
        "Avunu",
        "Naaku 15 kilolu ichharu",
        "Avunu",
    ):
        r = call.say(t)
        replies += [r.text, r.gloss]
    call = Call(db, SALMA)
    for t in ("haan", "Kitne log hain?", "Kal subah book karo", "haan"):
        r = call.say(t)
        replies += [r.text, r.gloss]
    call = Call(db, "+919000008804")
    for t in ("Avunu", "Biyyam vachaya?", "Repu book cheyyandi", "entha mandi unnaru"):
        r = call.say(t)
        replies += [r.text, r.gloss]
    queue.set_status(
        db,
        call.session.card.shop if call.session.card else None,  # type: ignore[arg-type]
        stock="in_stock",
    )
    from sqlalchemy import select

    from app.models import Shop

    queue.set_status(db, db.scalars(select(Shop).where(Shop.code == "108")).one(), machine="down")
    db.commit()
    call = Call(db, LAKSHMI)
    for t in ("Avunu", "Maa shop ki biyyam vachaya?", "Avunu"):
        r = call.say(t)
        replies += [r.text, r.gloss]
    leftovers = [
        (r, CLOCK.findall(_advice_text(r))) for r in replies if CLOCK.search(_advice_text(r))
    ]
    assert leftovers == []
    # Exact booking times keep their format.
    assert any(r == "Repu 10:20 ki, sare na?" for r in replies)
