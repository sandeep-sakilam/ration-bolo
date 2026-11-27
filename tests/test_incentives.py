"""F37: dealer phone line, "Rice arrived" broadcast, "Fair shop" badge (check 22)."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, crowd, incentives, queue
from app.models import BroadcastOptin, Card, Outbox, Shop
from tests.test_dialogue import LAKSHMI, Call

DEALER = "+919000001080"
SALT = "ration-bolo-reporter-salt"


def _shop(db: Session, code: str) -> Shop:
    return db.scalars(select(Shop).where(Shop.code == code)).one()


def _broadcasts(db: Session) -> list[Outbox]:
    return [
        o
        for o in db.scalars(select(Outbox))
        if "biyyam vachindi" in o.body or "chawal aa gaya" in o.body or "rice has arrived" in o.body
    ]


def test_check22_dealer_presses_1_and_optins_get_one_message(db: Session) -> None:
    shop = _shop(db, "108")
    queue.set_status(db, shop, stock="out")
    db.commit()
    call = Call(db, DEALER)
    assert call.first.text.startswith("Namaskaram, Ration Bolo. Dealer menu:")
    assert call.first.expect == "menu"
    r = call.key("1")
    assert r.text.startswith("Status maarchamu: rice in stock.")
    assert shop.status_stock == "in_stock"
    sent = _broadcasts(db)
    assert len(sent) == 2 and {o.channel for o in sent} == {"call", "whatsapp"}
    assert all("108" in o.body for o in sent)
    # Again the same day: nobody gets a second message.
    call.key("2")
    call.key("1")
    assert len(_broadcasts(db)) == 2


def test_dealer_line_by_voice_and_level0_counts_as_strong_report(
    db: Session, shop109_level0: None
) -> None:
    shop = _shop(db, "109")
    incentives.register_dealer_phone(db, shop, "+919000001090", SALT)
    db.commit()
    call = Call(db, "+919000001090")
    r = call.say("machine down")
    assert r.text.startswith("Status maarchamu: machine down.")
    assert shop.status_machine == "working"  # Level 0: no dealer status, a strong report
    verdict = crowd.verdict(crowd.votes(db, shop), "machine")
    assert verdict is not None and verdict.confirmed and "dealer" in verdict.sources


def test_optin_and_optout_by_voice(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    r = call.say("biyyam vachinappudu cheppandi")
    assert r.text.startswith("Sare, shop lo biyyam vachinappudu meeku cheptamu.")
    card = db.scalars(select(Card).where(Card.card_no == "TS-108-0421")).one()
    row = db.get(BroadcastOptin, card.id)
    assert row is not None and row.opted_out_at is None and row.channel == "call"
    assert call.say("cheppakandi").text.startswith("Sare, ika biyyam samacharam pampamu.")
    assert row.opted_out_at is not None


def test_broadcast_only_between_8_and_8(db: Session) -> None:
    shop = _shop(db, "108")
    sent: list[str] = []
    clock.freeze(clock.now_utc() + timedelta(hours=10))  # 21:00 IST
    assert incentives.stock_arrived(db, shop, lambda c, p, b: sent.append(b), "dealer") == 0
    assert sent == []


def test_crowd_confirmation_triggers_broadcast(db: Session) -> None:
    shop = _shop(db, "112")
    card = db.scalars(select(Card).where(Card.card_no == "TS-112-0207")).one()
    incentives.opt(db, card.id, shop.id, "whatsapp", True)
    db.commit()
    call = Call(db, "+919000008804")
    call.say("Avunu")
    call.key("9")
    call.say("biyyam vachindi")
    call.say("Avunu")
    assert any("112" in o.body for o in _broadcasts(db))


def test_fair_shop_badge(client: TestClient, db: Session) -> None:
    assert incentives.fair_shop(db, _shop(db, "115"))  # Level 1, no complaints, open daily
    assert not incentives.fair_shop(db, _shop(db, "108"))  # an upheld complaint 6 days ago
    assert not incentives.fair_shop(db, _shop(db, "112"))  # Level 0: no dealer to reward
    assert "Fair shop" in client.get("/shop/115").text
    d = client.get("/api/dealer/overview", headers={"X-Shop-Code": "115"}).json()
    assert d["fair_shop"] is True
    assert client.get("/api/dealer/overview").json()["broadcast_optins"] == 2


def test_dealer_responsiveness(db: Session) -> None:
    shop = _shop(db, "115")
    for n in range(2):
        crowd.save(db, shop, "stock_out", crowd.reporter_hash(f"+91x{n}", SALT))
    assert incentives.dealer_responsiveness(db, shop, clock.now_utc()) == 0.0
    queue.set_status(db, shop, stock="out")
    db.flush()
    assert incentives.dealer_responsiveness(db, shop, clock.now_utc()) == 1.0


def test_admin_registers_dealer_phone_as_hash(client: TestClient, db: Session) -> None:
    r = client.post("/api/admin/shops/115/dealer-phone", json={"phone": "+91 90000 01150"})
    assert r.status_code == 200
    from app import levels

    prof = levels.profile(db, _shop(db, "115"))
    assert prof.dealer_phone_hash and "9000001150" not in prof.dealer_phone_hash
    assert client.post("/api/admin/shops/115/dealer-phone", json={"phone": "12"}).status_code == 400


def test_dashboard_back_in_stock_broadcasts(client: TestClient, db: Session) -> None:
    client.post("/api/dealer/status", json={"stock": "out"})
    client.post("/api/dealer/status", json={"stock": "in_stock"})
    db.expire_all()
    assert len(_broadcasts(db)) == 2


def test_nearby_offer_mentions_fair_shop(db: Session) -> None:
    queue.set_status(db, _shop(db, "108"), machine="down")
    db.commit()
    call = Call(db, "+919000007702")
    call.say("haan")
    call.say("Kal subah book karo")
    r = call.say("nahi")
    assert "Yeh 'Fair shop' wali dukaan hai." in r.text
