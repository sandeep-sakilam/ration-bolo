"""F38: volunteer queue coordinators (acceptance check 23)."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import levels, volunteers
from app.clock import ist_today
from app.models import Card, Distribution, Event, PhoneLink, Shop, Token, Volunteer
from tests.test_dialogue import Call


def _shop(db: Session, code: str) -> Shop:
    return db.scalars(select(Shop).where(Shop.code == code)).one()


def _volunteer(db: Session) -> Volunteer:
    return db.scalars(select(Volunteer)).one()


def _caller_at_109(db: Session) -> str:
    card = db.scalars(select(Card).where(Card.card_no == "TS-109-3001")).one()
    db.add(PhoneLink(phone_e164="+919000001091", card_id=card.id, source="seed"))
    db.commit()
    return "+919000001091"


def test_check23_on_duty_offers_bookings_off_duty_is_level0(db: Session) -> None:
    shop = _shop(db, "109")
    assert levels.effective_level(db, shop) == 1
    assert levels.label(db, shop) == "Level 1 · volunteer on duty"
    phone = _caller_at_109(db)
    call = Call(db, phone)
    call.say("Avunu")
    assert call.say("Repu poddhuna book cheyyandi").text == "Repu 08:00 ki, sare na?"
    volunteers.set_duty(db, _volunteer(db), False)
    db.commit()
    assert levels.effective_level(db, shop) == 0
    call = Call(db, phone)
    call.say("Avunu")
    assert call.say("Repu poddhuna book cheyyandi").text.startswith("Ee shop lo inka booking ledu.")


def test_outside_date_range_is_level0(db: Session) -> None:
    v = _volunteer(db)
    v.ends_on = ist_today() - timedelta(days=1)
    db.commit()
    assert levels.effective_level(db, _shop(db, "109")) == 0


def test_volunteer_dashboard_tokens_tagged_no_sales(client: TestClient, db: Session) -> None:
    vid = str(_volunteer(db).id)
    head = {"X-Volunteer-Id": vid}
    d = client.get("/api/dealer/overview", headers=head).json()
    assert d["shop"]["code"] == "109" and d["volunteer"]["mode"] is True and d["waiting"] == 15
    head["X-Shop-Code"] = "109"
    assert client.post("/api/dealer/walkin", json={}, headers=head).status_code == 200
    served = client.post("/api/dealer/serve", json={}, headers=head).json()
    assert served["served"] is not None
    assert client.post("/api/dealer/serve", json={"kg": 3}, headers=head).status_code == 403
    db.expire_all()
    token = db.get(Token, served["served"]["id"])
    assert db.scalars(select(Distribution).where(Distribution.token_id == token.id)).first() is None
    actors = {
        e.actor
        for e in db.scalars(select(Event).where(Event.action.in_(("served", "walkin_added"))))
    }
    assert f"volunteer:{vid}" in actors
    r = client.post("/api/dealer/status", json={"stock": "out"}, headers=head).json()
    assert r["stock"] == "out"
    event = db.scalars(
        select(Event).where(Event.action == "status").order_by(Event.id.desc())
    ).first()
    assert event is not None and event.actor == f"volunteer:{vid}"


def test_volunteer_mode_restrictions(client: TestClient, db: Session) -> None:
    head = {"X-Volunteer-Id": str(_volunteer(db).id)}
    assert client.post("/api/dealer/reset", headers=head).status_code == 403
    assert (
        client.post(
            "/api/dealer/link-phone", json={"phone": "9876543210", "card_id": 1}, headers=head
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/dealer/complaints/1/resolve", json={"outcome": "x"}, headers=head
        ).status_code
        == 403
    )
    other = {**head, "X-Shop-Code": "108"}
    assert client.get("/api/dealer/overview", headers=other).status_code == 403
    assert client.get("/api/dealer/overview", headers={"X-Volunteer-Id": "999"}).status_code == 404


def test_volunteer_goes_off_duty_from_dashboard(client: TestClient, db: Session) -> None:
    head = {"X-Volunteer-Id": str(_volunteer(db).id)}
    r = client.post("/api/dealer/volunteer/duty", json={"on_duty": False}, headers=head).json()
    assert r["on_duty"] is False
    db.expire_all()
    assert levels.effective_level(db, _shop(db, "109")) == 0


def test_admin_registers_volunteer(client: TestClient) -> None:
    today = ist_today()
    r = client.post(
        "/api/admin/shops/112/volunteers",
        json={
            "display_label": "Ward volunteer",
            "starts_on": today.isoformat(),
            "ends_on": (today + timedelta(days=5)).isoformat(),
            "on_duty": True,
        },
    ).json()
    assert r["dashboard"].startswith("/dealer?volunteer=")
    shops = {s["code"]: s for s in client.get("/api/admin/shops").json()}
    assert shops["112"]["level"] == 1 and shops["112"]["base_level"] == 0
    assert shops["112"]["volunteers"][0]["on_duty"] is True
    bad = client.post(
        "/api/admin/shops/112/volunteers",
        json={
            "display_label": "x",
            "starts_on": today.isoformat(),
            "ends_on": (today - timedelta(days=1)).isoformat(),
        },
    )
    assert bad.status_code == 400
