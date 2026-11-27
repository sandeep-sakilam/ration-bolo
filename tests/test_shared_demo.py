"""F23: shared live demo safety (acceptance checks 11 and 12)."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, demo, queue
from app.config import Settings
from app.dialogue import Dialogue, Event
from app.models import Card, Reminder, Shop, Token
from app.reminders import start_scheduler
from app.services import build_services

PIN = {"X-Dealer-Pin": "1234"}


def _say(client: TestClient, sid: int, text: str) -> str:
    return str(client.post(f"/api/sim/{sid}/text", json={"text": text}).json()["text"])


def _start(client: TestClient, caller: str = "lakshmi") -> tuple[int, str]:
    r = client.post("/api/sim/start", json={"caller": caller}).json()
    return int(r["session_id"]), str(r["text"])


def test_check11_second_lakshmi_call_starts_fresh(client: TestClient, db: Session) -> None:
    sid, _ = _start(client)
    _say(client, sid, "Avunu")
    assert _say(client, sid, "Repu poddhuna book cheyyandi") == "Repu 10:20 ki, sare na?"
    assert "Booking ayindi" in _say(client, sid, "Avunu")
    assert _say(client, sid, "Hindi lo cheppandi").startswith("Theek hai")
    # Within the same session the rules still hold.
    assert "pehle se hai" in _say(client, sid, "kal shaam book karo")
    client.post(f"/api/sim/{sid}/end")

    sid2, greeting = _start(client)
    assert greeting == "Namaskaram, Ration Bolo. Card chivari ankelu 0421, sare na?"
    _say(client, sid2, "Avunu")
    assert _say(client, sid2, "Repu poddhuna book cheyyandi") == "Repu 10:20 ki, sare na?"
    lakshmi = db.scalars(select(Card).where(Card.card_no == "TS-108-0421")).one()
    db.expire_all()
    old = db.scalars(select(Token).where(Token.card_id == lakshmi.id)).all()
    assert [t.status for t in old] == ["cancelled"]
    assert db.scalars(select(Reminder)).one().status == "cancelled"


def test_check12_machine_down_restores_after_10_minutes(client: TestClient) -> None:
    client.post("/api/dealer/status", json={"machine": "down"}, headers=PIN)
    d = client.get("/api/dealer/overview", headers=PIN).json()
    assert d["shop"]["machine"] == "down" and d["restore_in_minutes"] == {"machine": 10}
    clock.freeze(clock.now_utc() + timedelta(minutes=9))
    d = client.get("/api/dealer/overview", headers=PIN).json()
    assert d["shop"]["machine"] == "down" and d["restore_in_minutes"] == {"machine": 1}
    clock.freeze(clock.now_utc() + timedelta(minutes=1))
    d = client.get("/api/dealer/overview", headers=PIN).json()
    assert d["shop"]["machine"] == "working" and d["restore_in_minutes"] == {}
    _, greeting = _start(client, "salma")
    assert "machine band" not in greeting


def test_restore_also_happens_on_a_call(client: TestClient) -> None:
    client.post("/api/dealer/status", json={"stock": "out"}, headers=PIN)
    assert "biyyam aipoyindi" in _start(client)[1]
    clock.freeze(clock.now_utc() + timedelta(minutes=10))
    assert "biyyam aipoyindi" not in _start(client)[1]


def test_manual_restore_clears_the_timer(db: Session) -> None:
    shop = db.scalars(select(Shop).where(Shop.code == "108")).one()
    queue.set_status(db, shop, machine="down")
    queue.set_status(db, shop, machine="working")
    db.flush()
    assert demo.restore_countdown(db, shop) == {}


def test_non_demo_cards_and_demo_off_are_never_reset(db: Session) -> None:
    lakshmi = db.scalars(select(Card).where(Card.card_no == "TS-108-0421")).one()
    lakshmi.language = "hi"
    db.commit()
    # Demo mode off: nothing is reset.
    off = Dialogue(db, demo_mode=False)
    s = off.start_session("simulator", "+919000004401")
    assert off.handle(s, Event("start")).language == "hi"
    # A card without demo marking (e.g. imported) is not touched even in demo mode.
    real = Card(
        card_no="TS-108-9999",
        shop_id=lakshmi.shop_id,
        members=2,
        language="hi",
        state_pack="telangana",
    )
    db.add(real)
    db.flush()
    assert demo.refresh_card(db, real) is False and real.language == "hi"


def test_status_untouched_when_demo_off(db: Session) -> None:
    shop = db.scalars(select(Shop).where(Shop.code == "108")).one()
    queue.set_status(db, shop, machine="down")
    db.commit()
    clock.freeze(clock.now_utc() + timedelta(minutes=30))
    Dialogue(db, demo_mode=False).handle(
        Dialogue(db).start_session("simulator", "+919000007702"), Event("start")
    )
    assert shop.status_machine == "down"


def test_demo_mode_setting() -> None:
    assert Settings(_env_file=None).demo_active is True  # type: ignore[call-arg]
    assert Settings(_env_file=None, seed_demo=False).demo_active is False  # type: ignore[call-arg]
    assert Settings(_env_file=None, demo_mode="off").demo_active is False  # type: ignore[call-arg]


def test_nightly_reset_job_scheduled(settings: Settings) -> None:
    from app.db import make_engine, make_sessionmaker

    factory = make_sessionmaker(make_engine(settings.database_url))
    sched = start_scheduler(factory, build_services(settings), interval_seconds=3600)
    job = sched.get_job("nightly_demo_reset")
    assert job is not None
    assert "hour='21'" in str(job.trigger) and "minute='30'" in str(job.trigger)
    sched.shutdown(wait=False)
    off = Settings(_env_file=None, database_url=settings.database_url, demo_mode="off")  # type: ignore[call-arg]
    sched = start_scheduler(factory, build_services(off), interval_seconds=3600)
    assert sched.get_job("nightly_demo_reset") is None
    sched.shutdown(wait=False)
