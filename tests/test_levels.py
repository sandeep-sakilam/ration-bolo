"""F30: shop levels 0/1/2 (acceptance check 15, Level 0 half)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import levels
from app.models import Shop, Token
from app.packs import get_pack, load_packs
from tests.test_dialogue import Call

RAMU = "+919000008804"


def _shop(db: Session, code: str) -> Shop:
    return db.scalars(select(Shop).where(Shop.code == code)).one()


def test_demo_levels(db: Session) -> None:
    assert levels.effective_level(db, _shop(db, "108")) == 2
    assert levels.effective_level(db, _shop(db, "112")) == 0
    assert levels.effective_level(db, _shop(db, "115")) == 1
    assert levels.effective_level(db, _shop(db, "201")) == 1  # no profile → as built


def test_check15_level0_book_gives_best_time_and_no_booking(db: Session) -> None:
    call = Call(db, RAMU)
    assert call.first.text == "Namaskaram, Ration Bolo. Card chivari ankelu 0207, sare na?"
    call.say("Avunu")
    r = call.say("Repu poddhuna book cheyyandi")
    assert r.text.startswith("Ee shop lo inka booking ledu.")
    assert "rush takkuva" in r.text and "Sadharananga" in r.text
    assert {"type": "booking_refused", "reason": "level0"} in r.actions
    assert any(a["type"] == "best_time_advice" for a in r.actions)
    assert r.gloss.startswith("This shop doesn't take bookings yet.")
    shop = _shop(db, "112")
    assert db.scalars(select(Token).where(Token.shop_id == shop.id)).first() is None
    # Keypad 3 also gives advice, never a booking.
    for _ in range(3):
        call.say("???")
    assert call.key("3").text.startswith("Ee shop lo inka booking ledu.")


def test_level0_stock_and_queue_say_no_recent_reports(db: Session) -> None:
    call = Call(db, RAMU)
    call.say("Avunu")
    assert call.say("biyyam vachaya").text.startswith(
        "Mee shop gurinchi ippudu kotta samacharam ledu."
    )
    assert call.say("entha mandi unnaru").text.startswith(
        "Mee shop gurinchi ippudu kotta samacharam ledu."
    )


def test_level1_and_2_book_as_before(db: Session) -> None:
    call = Call(db, "+919000004401")
    call.say("Avunu")
    assert call.say("Repu poddhuna book cheyyandi").text == "Repu 10:20 ki, sare na?"
    shop = _shop(db, "108")
    levels.set_profile(db, shop, level=1)
    db.commit()
    call2 = Call(db, "+919000007702")
    call2.say("haan")
    assert call2.say("Kal subah book karo").text == "Kal 10:20 baje, theek hai?"


def test_level_change_honours_booking_as_advice(client: TestClient, db: Session) -> None:
    from app import reminders
    from app.config import Settings
    from app.models import Outbox
    from app.services import build_services

    sid = client.post("/api/sim/start", json={"caller": "lakshmi"}).json()["session_id"]
    for text in ("Avunu", "Repu poddhuna book cheyyandi", "Avunu"):
        client.post(f"/api/sim/{sid}/text", json={"text": text})
    r = client.post("/api/admin/shops/108/profile", json={"level": 0}).json()
    assert r["level"] == 0
    reminders.send_now(db, build_services(Settings(_env_file=None)))  # type: ignore[call-arg]
    call = db.scalars(select(Outbox).where(Outbox.channel == "call")).one()
    assert "bookings nirdharinchadam ledu" in call.body and "10:20" in call.body
    assert client.post("/api/admin/shops/108/profile", json={"level": 7}).status_code == 400


def test_dashboard_admin_and_status_show_levels(client: TestClient) -> None:
    d = client.get("/api/dealer/overview").json()
    assert d["level"] == 2 and d["level_label"].startswith("Level 2")
    d = client.get("/api/dealer/overview", headers={"X-Shop-Code": "112"}).json()
    assert d["level"] == 0
    shops = {s["code"]: s for s in client.get("/api/admin/shops").json()}
    assert shops["112"]["level"] == 0 and shops["112"]["landmark"] == "near Saidabad bus stop"
    status = client.get("/api/status").json()
    tn = next(p for p in status["packs"] if p["state"] == "tamil_nadu")
    assert "default_busy_pattern" in tn["missing_v3"]


def test_csv_import_sets_level_and_location(client: TestClient) -> None:
    csv = (
        "code,name,area,state_pack,sessions,families_per_hour,booked_share,level,lat,lon,"
        "ward,landmark,portability\n"
        "140,Shop 140,X,telangana,08:00-12:00,30,0.5,0,17.36,78.49,Saidabad,near a temple,no\n"
    )
    r = client.post("/api/admin/import/shops", files={"file": ("s.csv", csv.encode(), "text/csv")})
    assert r.status_code == 200
    shops = {s["code"]: s for s in client.get("/api/admin/shops").json()}
    assert shops["140"]["level"] == 0 and shops["140"]["portability"] is False
    bad = csv.replace(",0,17.36", ",5,17.36")
    r = client.post("/api/admin/import/shops", files={"file": ("s.csv", bad.encode(), "text/csv")})
    assert r.status_code == 422


def test_older_pack_still_loads_with_defaults() -> None:
    tn = load_packs()["tamil_nadu"]
    assert tn.raw["portability"] is True and "phrases.no_booking_level0" in tn.missing_v3
    assert tn.phrase("no_booking_level0", "ta") == "This shop doesn't take bookings yet."
    assert get_pack("telangana").phrase("no_booking_level0", "hi").startswith("Is dukaan")
