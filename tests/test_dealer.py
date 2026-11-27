from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PhoneLink

PIN = {"X-Dealer-Pin": "1234"}


def test_check13_no_pin_by_default(client: TestClient) -> None:
    assert client.get("/api/dealer/overview").status_code == 200
    assert client.post("/api/dealer/serve", json={}).status_code == 200


def test_pin_required_when_set(db_url: str) -> None:
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        database_url=db_url,
        scheduler_enabled=False,  # type: ignore[call-arg]
        dealer_pin="2468",
        admin_pin="1357",
    )
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/dealer/overview").status_code == 401
        assert c.get("/api/dealer/overview", headers={"X-Dealer-Pin": "0000"}).status_code == 401
        assert c.get("/api/dealer/overview", headers={"X-Dealer-Pin": "2468"}).status_code == 200
        assert c.get("/api/admin/shops", headers={"X-Admin-Pin": "2468"}).status_code == 401
        assert c.get("/api/admin/shops", headers={"X-Admin-Pin": "1357"}).status_code == 200


def test_reset_is_rate_limited(client: TestClient) -> None:
    from app.channels.dealer import RESET_LIMIT

    RESET_LIMIT.reset()
    codes = [client.post("/api/dealer/reset").status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429
    RESET_LIMIT.reset()


def test_overview_masks_cards_and_phones(client: TestClient) -> None:
    d = client.get("/api/dealer/overview", headers=PIN).json()
    assert d["demo_data"] is True and d["waiting"] == 18 and d["wait_minutes"] == 36
    assert len(d["queue"]) == 18 and all(len(t["last4"]) == 4 for t in d["queue"])
    assert d["shop"]["stock"] == "in_stock"
    assert "TS-108" not in str(d["queue"])


def test_serve_next_and_short_amount(client: TestClient) -> None:
    r = client.post("/api/dealer/serve", json={}, headers=PIN).json()
    assert r["served"]["kind"] == "walkin"
    r = client.post("/api/dealer/serve", json={"kg": 3}, headers=PIN).json()
    assert r["served"] is not None
    assert client.get("/api/dealer/overview", headers=PIN).json()["waiting"] == 16


def test_status_buttons_and_voice(client: TestClient) -> None:
    r = client.post("/api/dealer/status", json={"machine": "down"}, headers=PIN).json()
    assert r["paused"] is True
    assert (
        client.post("/api/dealer/status", json={"machine": "broken"}, headers=PIN).status_code
        == 400
    )
    r = client.post("/api/dealer/voice", json={"text": "Machine working"}, headers=PIN).json()
    assert r["understood"] and r["machine"] == "working" and r["paused"] is False
    r = client.post("/api/dealer/voice", json={"text": "Chawal khatam"}, headers=PIN).json()
    assert r["stock"] == "out" and r["paused"] is True
    sim = client.post("/api/sim/start", json={"caller": "lakshmi"}).json()
    assert "biyyam aipoyindi" in sim["text"]
    r = client.post("/api/dealer/voice", json={"text": "Biyyam vachindi"}, headers=PIN).json()
    assert r["stock"] == "in_stock"
    assert not client.post("/api/dealer/voice", json={"text": "hello"}, headers=PIN).json()[
        "understood"
    ]


def test_walkin_and_arrival_late(client: TestClient) -> None:
    r = client.post("/api/dealer/walkin", json={}, headers=PIN).json()
    assert r["token"]["kind"] == "walkin"
    sid = client.post("/api/sim/start", json={"caller": "salma"}).json()["session_id"]
    client.post(f"/api/sim/{sid}/text", json={"text": "haan"})
    offer = client.post(f"/api/sim/{sid}/text", json={"text": "aaj shaam book karo"}).json()
    assert offer["text"].startswith("Aaj 16:00 baje")
    client.post(f"/api/sim/{sid}/text", json={"text": "haan"})
    d = client.get("/api/dealer/overview", headers=PIN).json()
    booking = next(b for b in d["bookings"] if b["date"] == d["today"])
    r = client.post(
        "/api/dealer/arrive",
        json={"token_id": booking["id"], "minutes_after_start": 11},
        headers=PIN,
    ).json()
    assert r["late"] is True and r["token"]["kind"] == "walkin"


def test_complaint_resolve(client: TestClient) -> None:
    d = client.get("/api/dealer/overview", headers=PIN).json()
    open_c = next(c for c in d["complaints"] if c["status"] == "open")
    r = client.post(
        f"/api/dealer/complaints/{open_c['id']}/resolve", json={"outcome": "Gave 3 kg"}, headers=PIN
    ).json()
    assert r["status"] == "resolved"


def test_link_phone(client: TestClient, db: Session) -> None:
    d = client.get("/api/dealer/overview", headers=PIN).json()
    card = d["demo_cards"][0]
    r = client.post(
        "/api/dealer/link-phone", json={"phone": "98765 43210", "card_id": card["id"]}, headers=PIN
    ).json()
    assert r["message"].startswith("+91 •••• ••3210")
    assert db.scalars(select(PhoneLink).where(PhoneLink.phone_e164 == "+919876543210")).one()
    bad = client.post("/api/dealer/link-phone", json={"phone": "12", "card_id": 1}, headers=PIN)
    assert bad.status_code == 400


def test_reset_demo(client: TestClient) -> None:
    client.post("/api/dealer/status", json={"stock": "out"}, headers=PIN)
    client.post("/api/dealer/reset", headers=PIN)
    d = client.get("/api/dealer/overview", headers=PIN).json()
    assert d["shop"]["stock"] == "in_stock" and d["waiting"] == 18


def test_dealer_page(client: TestClient) -> None:
    assert "Dealer login" in client.get("/dealer").text
