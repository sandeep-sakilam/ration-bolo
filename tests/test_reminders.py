from datetime import time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, queue, reminders
from app.clock import ist_to_utc, ist_today
from app.config import Settings
from app.models import Outbox, Reminder, Shop, Token
from app.services import build_services

PIN = {"X-Dealer-Pin": "1234"}
SERVICES = build_services(Settings(_env_file=None))  # type: ignore[call-arg]


def _book_lakshmi(client: TestClient) -> int:
    sid = client.post("/api/sim/start", json={"caller": "lakshmi"}).json()["session_id"]
    client.post(f"/api/sim/{sid}/text", json={"text": "Avunu"})
    client.post(f"/api/sim/{sid}/text", json={"text": "Repu poddhuna book cheyyandi"})
    client.post(f"/api/sim/{sid}/text", json={"text": "Avunu"})
    return sid


def test_booking_schedules_reminder_20_minutes_before(client: TestClient, db: Session) -> None:
    _book_lakshmi(client)
    reminder = db.scalars(select(Reminder)).one()
    tomorrow = ist_today() + timedelta(days=1)
    assert reminder.due_at == ist_to_utc(tomorrow, time(10, 0))
    assert reminder.status == "pending"


def test_due_reminder_calls_with_live_count(client: TestClient, db: Session) -> None:
    _book_lakshmi(client)
    tomorrow = ist_today() + timedelta(days=1)
    assert reminders.run_due(db, SERVICES) == 0  # not due yet
    clock.freeze(ist_to_utc(tomorrow, time(10, 0)))
    assert reminders.run_due(db, SERVICES) == 1
    call = db.scalars(select(Outbox).where(Outbox.channel == "call")).one()
    assert call.body == "Ration Bolo: bayaluderandi, mee slot 10:20 ki. Mundu 5 mandi unnaru."
    assert call.to_masked.endswith("4401")
    assert db.scalars(select(Reminder)).one().status == "sent"


def test_reminder_mentions_status_when_paused(client: TestClient, db: Session) -> None:
    _book_lakshmi(client)
    shop = db.scalars(select(Shop).where(Shop.code == "108")).one()
    queue.set_status(db, shop, stock="out")
    db.commit()
    reminders.send_now(db, SERVICES)
    call = db.scalars(select(Outbox).where(Outbox.channel == "call")).one()
    assert "biyyam aipoyindi" in call.body


def test_cancelled_booking_reminder_not_sent(client: TestClient, db: Session) -> None:
    _book_lakshmi(client)
    token = db.scalars(select(Token).where(Token.channel == "simulator")).one()
    token.status = "cancelled"
    db.commit()
    assert reminders.send_now(db, SERVICES) is None
    assert db.scalars(select(Reminder)).one().status == "cancelled"


def test_reminder_survives_restart(client: TestClient, settings: Settings) -> None:
    _book_lakshmi(client)
    from app.main import create_app

    with TestClient(create_app(settings)) as again:
        d = again.get("/api/dealer/overview", headers=PIN).json()
        assert d["reminders"][0]["status"] == "pending"
        r = again.post("/api/dealer/reminders/send-now", json={}, headers=PIN).json()
        assert "Reminder sent (call, mock)" in r["message"]
        r = again.post("/api/dealer/reminders/send-now", json={}, headers=PIN).json()
        assert r["message"] == "No pending reminder to send."


def test_whatsapp_booking_reminded_on_whatsapp(client: TestClient, db: Session) -> None:
    sid = client.post("/api/sim/start", json={"caller": "salma", "mode": "whatsapp"}).json()
    s = sid["session_id"]
    client.post(f"/api/sim/{s}/text", json={"text": "haan"})
    client.post(f"/api/sim/{s}/text", json={"text": "kal subah book karo"})
    client.post(f"/api/sim/{s}/text", json={"text": "haan"})
    reminders.send_now(db, SERVICES)
    rows = db.scalars(select(Outbox).where(Outbox.channel == "whatsapp")).all()
    assert any("nikal padiye" in r.body for r in rows)


def test_scheduler_starts_and_stops(settings: Settings) -> None:
    from app.db import make_engine, make_sessionmaker

    engine = make_engine(settings.database_url)
    sched = reminders.start_scheduler(make_sessionmaker(engine), SERVICES, interval_seconds=3600)
    assert sched.get_job("reminders") is not None
    sched.shutdown(wait=False)
