"""F40: demo public sales stay fresh all day (acceptance check 25)."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, publicpds
from app.clock import ist_to_utc, ist_today, to_ist
from app.models import Shop
from app.publicpds import MockPublicPds, PublicPdsService
from tests.test_dialogue import Call

FIX = Path(__file__).parent / "fixtures" / "public_pds"
RAMU = "+919000008804"
SESSIONS = [["08:00", "12:00"], ["16:00", "20:00"]]


def _at(hh: int, mm: int) -> datetime:
    return ist_to_utc(ist_today(), time(hh, mm))


def _service(stopped: bool = False) -> PublicPdsService:
    service = PublicPdsService(mode="auto", mock=MockPublicPds(FIX, demo=True, stopped=stopped))
    publicpds.register(service)
    return service


def _shop(db: Session) -> Shop:
    return db.scalars(select(Shop).where(Shop.code == "112")).one()


def test_generated_sales_follow_open_hours() -> None:
    day = date(2026, 11, 27)
    now = ist_to_utc(day, time(19, 30))
    events = publicpds.generate_demo_sales(day, SESSIONS, now)
    times = [to_ist(e.time).strftime("%H:%M") for e in events]
    assert times[0] == "09:10" and "11:50" in times and "12:00" not in times
    assert "16:00" in times and times[-1] == "19:30"
    per_hour = sum(e.count for e in events if to_ist(e.time).hour == 17)
    assert 23 <= per_hour <= 27


@pytest.mark.parametrize(("hh", "mm"), [(9, 30), (19, 30)])
def test_check25_open_hours_show_about_25_an_hour(db: Session, hh: int, mm: int) -> None:
    _service()
    clock.freeze(_at(hh, mm))
    s = _service().signals(_shop(db))
    assert s is not None and s.open_now and not s.possibly_stopped
    elapsed = min(60, (hh * 60 + mm) - (9 * 60 + 10))
    expected = 25 * elapsed / 60
    assert abs(s.sales_last_hour - expected) <= 6
    call = Call(db, RAMU)
    call.say("Avunu")
    text = call.say("biyyam vachaya").text
    assert "Public ammakala data prakaram shop poddhuna 9:10 ki ammakalu modalupettindi." in text
    assert "aagi undavachu" not in text


def test_check25_between_sessions_and_after_closing(db: Session) -> None:
    for hh, opens in ((14, "16:00"), (21, "08:00")):
        clock.freeze(_at(hh, 0))
        s = _service().signals(_shop(db))
        assert s is not None and s.closed_now and not s.possibly_stopped
        assert s.total_today > 0 and to_ist(s.opens_at).strftime("%H:%M") == opens  # type: ignore[arg-type]
    call = Call(db, RAMU)
    call.say("Avunu")
    text = call.say("biyyam vachaya").text
    assert "shop ippudu moosi undi, poddhuna 8 gantalaku terustaru." in text


def test_check25_before_opening_not_started(db: Session) -> None:
    clock.freeze(_at(8, 30))
    s = _service().signals(_shop(db))
    assert s is not None and s.first_sale is None and s.not_started and s.open_now
    from app.models import Report

    for row in db.scalars(select(Report)):
        db.delete(row)
    db.commit()
    call = Call(db, RAMU)
    call.say("Avunu")
    assert "ivala inka ammakalu modalukaledu" in call.say("biyyam vachaya").text


def test_stopped_switch_still_detects_stoppage(db: Session) -> None:
    clock.freeze(_at(11, 0))
    s = _service(stopped=True).signals(_shop(db))
    assert s is not None and s.possibly_stopped and s.stopped_minutes >= 60


def test_non_demo_mode_uses_fixed_fixture(db: Session) -> None:
    clock.freeze(_at(19, 30))
    service = PublicPdsService(mode="auto", mock=MockPublicPds(FIX, demo=False))
    s = service.signals(_shop(db))
    assert s is not None and s.last_sale is not None
    assert to_ist(s.last_sale).strftime("%H:%M") == "19:30"  # the fixed v3 fixture times


def test_check25_transparency_page_fresh(client: TestClient) -> None:
    clock.freeze(_at(19, 30))
    _service()
    text = client.get("/shop/112").text
    assert (
        "Public sales data: selling since 09:10" in text and " 0 sales in the last hour" not in text
    )
    clock.freeze(_at(21, 0))
    _service()
    assert "closed now, opens 08:00" in client.get("/shop/112").text
