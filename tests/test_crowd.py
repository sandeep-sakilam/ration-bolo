"""F31: cardholder reports and check-ins (acceptance check 16)."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, crowd, shopstate
from app.crowd import Vote
from app.models import Card, PhoneLink, Report, ReporterScore, Shop
from tests.test_dialogue import Call

RAMU = "+919000008804"
SALT = "ration-bolo-reporter-salt"


def _shop(db: Session, code: str) -> Shop:
    return db.scalars(select(Shop).where(Shop.code == code)).one()


def _phone_at(db: Session, shop_code: str, phone: str, n: int = 1) -> str:
    card = db.scalars(select(Card).where(Card.card_no == f"TS-{shop_code}-{3000 + n}")).one()
    db.add(PhoneLink(phone_e164=phone, card_id=card.id, source="seed"))
    db.commit()
    return phone


# --- pure rules -------------------------------------------------------------


def test_decay_halves_every_30_minutes_and_stops_after_3_hours() -> None:
    assert crowd.decayed(1.0, 0) == 1.0
    assert crowd.decayed(1.0, 30) == 0.5 and crowd.decayed(2.0, 60) == 0.5
    assert crowd.decayed(1.0, 181) == 0.0


def test_two_phones_within_45_minutes_confirm() -> None:
    one = [Vote("stock_in", "a", "caller", 1.0, 10)]
    v = crowd.verdict(one, "stock")
    assert v is not None and not v.confirmed and v.count == 1
    two = [*one, Vote("stock_in", "b", "caller", 1.0, 40)]
    assert crowd.verdict(two, "stock").confirmed  # type: ignore[union-attr]
    far = [*one, Vote("stock_in", "b", "caller", 1.0, 50)]
    assert not crowd.verdict(far, "stock").confirmed  # type: ignore[union-attr]
    dealer = [Vote("stock_out", "d", "dealer", 2.0, 5)]
    assert crowd.verdict(dealer, "stock").confirmed  # type: ignore[union-attr]


def test_reports_older_than_3_hours_are_ignored() -> None:
    old = [Vote("stock_in", "a", "caller", 1.0, 200), Vote("stock_in", "b", "caller", 1.0, 190)]
    assert crowd.verdict(old, "stock") is None


def test_newer_and_heavier_evidence_wins() -> None:
    votes = [Vote("stock_in", "a", "caller", 1.0, 120), Vote("stock_out", "b", "caller", 1.0, 5)]
    assert crowd.verdict(votes, "stock").value == "out"  # type: ignore[union-attr]


def test_queue_outlier_dropped_and_checkins_count() -> None:
    votes = [
        Vote("queue_size", p, "caller", 1.0, 5, v)
        for p, v in (("a", 10), ("b", 12), ("c", 11), ("d", 40))
    ]
    assert crowd.queue_estimate(votes) == 11  # 40 > 3 × 11.5 is dropped
    assert crowd.queue_estimate([Vote("checkin", x, "caller", 1.0, 3) for x in "abc"]) == 3
    assert crowd.queue_estimate([]) is None


def test_reliability_bounds() -> None:
    w = 1.0
    for _ in range(20):
        w = crowd.adjust(w, True)
    assert w == 2.0
    for _ in range(20):
        w = crowd.adjust(w, False)
    assert w == 0.2


# --- in the dialogue ------------------------------------------------------------


def test_check16_two_reports_confirm_one_is_one_person(db: Session, shop109_level0: None) -> None:
    shop = _shop(db, "109")
    a, b = _phone_at(db, "109", "+919000001091", 1), _phone_at(db, "109", "+919000001092", 2)
    call = Call(db, a)
    call.say("Avunu")
    r = call.say("biyyam vachindi")
    assert r.text == "Meeru shop daggara unnara?"
    assert call.say("Avunu").text == "Biyyam vachindi ani cheptunnaru, sare na?"
    r = call.say("Avunu")
    assert r.text.startswith("Dhanyavaadalu, mee report namodu chesamu.")
    assert {"type": "report_saved", "kinds": ["stock_in"]} in r.actions
    # One report: spoken as one person.
    view = shopstate.view(db, shop)
    assert view.stock is not None and not view.stock.confirmed and view.stock.count == 1
    asked = Call(db, b)
    asked.say("Avunu")
    text = asked.say("biyyam vachaya").text
    assert text.startswith("Biyyam vachindi: 5 nimishala kritam okka vyakti cheppaaru.")
    # A second phone within 45 minutes: confirmed, with source and age.
    clock.freeze(clock.now_utc() + timedelta(minutes=12))
    crowd.save(db, shop, "stock_in", crowd.reporter_hash(b, SALT))
    db.commit()
    asked = Call(db, b)
    asked.say("Avunu")
    text = asked.say("biyyam vachaya").text
    assert text.startswith("Biyyam vachindi, gata 15 nimishallo 2 mandi nirdharincharu.")
    # After 3 hours the reports are ignored.
    clock.freeze(clock.now_utc() + timedelta(hours=3, minutes=1))
    assert shopstate.view(db, shop).stock is None


def test_report_needs_caller_at_shop(db: Session) -> None:
    call = Call(db, RAMU)
    call.say("Avunu")
    call.say("biyyam ledu")
    assert call.say("Kaadu").text.startswith("Shop daggara unnappude report cheyyandi.")
    assert db.scalars(select(Report).where(Report.kind == "stock_out")).first() is None


def test_ramu_scripted_report_with_queue(db: Session) -> None:
    call = Call(db, RAMU)
    call.say("Avunu")
    call.say("biyyam vachindi, ikkada 12 mandi unnaru")
    r = call.say("Avunu")
    assert r.text == "Biyyam vachindi, 12 mandi unnaru ani cheptunnaru, sare na?"
    assert r.gloss == "You are reporting: rice has arrived, 12 people are there. Right?"
    r = call.say("Avunu")
    assert {"type": "report_saved", "kinds": ["stock_in", "queue_size"]} in r.actions
    rows = db.scalars(
        select(Report).where(
            Report.reporter_hash.not_like("demo-%"), Report.reporter_hash.not_like("hist-%")
        )
    ).all()
    assert {(x.kind, x.value) for x in rows} == {("stock_in", None), ("queue_size", 12)}
    assert all(RAMU not in x.reporter_hash and len(x.reporter_hash) == 64 for x in rows)


def test_one_vote_per_phone_per_signal_per_hour(db: Session) -> None:
    shop = _shop(db, "109")
    who = crowd.reporter_hash("+919000001099", SALT)
    crowd.save(db, shop, "stock_in", who)
    crowd.save(db, shop, "stock_out", who)
    rows = db.scalars(select(Report).where(Report.reporter_hash == who)).all()
    assert [r.kind for r in rows] == ["stock_out"]


def test_level0_stock_from_reports_and_queue(db: Session) -> None:
    call = Call(db, RAMU)
    call.say("Avunu")
    text = call.say("biyyam vachaya").text
    assert text.startswith("Biyyam vachindi, gata 30 nimishallo 4 mandi nirdharincharu.")
    text = call.say("entha mandi unnaru").text
    assert text.startswith("Cardholders cheppina prakaram sumaru 4 mandi unnaru, sumaru 10")


def test_checkin_by_keypad_9_and_phrase(db: Session) -> None:
    call = Call(db, RAMU)
    call.say("Avunu")
    r = call.key("9")
    assert r.text.startswith("Meeru shop daggara unnaru ani namodu chesamu. Gata gantalo 1")
    call.say("biyyam ledu")  # already at the shop: straight to the read-back
    assert call.last.text == "Biyyam ledu ani cheptunnaru, sare na?"
    assert call.say("Kaadu").text == "Meeku ela sahayam cheyali?"


def test_reliability_moves_with_evidence(db: Session) -> None:
    shop = _shop(db, "109")
    good, bad = crowd.reporter_hash("+911", SALT), crowd.reporter_hash("+912", SALT)
    crowd.save(db, shop, "stock_out", bad)
    crowd.save(db, shop, "stock_in", good)
    crowd.save(db, shop, "stock_in", crowd.reporter_hash("+913", SALT))
    db.commit()
    assert db.get(ReporterScore, good).weight == 1.1  # type: ignore[union-attr]
    assert db.get(ReporterScore, bad).weight == 0.8  # type: ignore[union-attr]


def test_disagreement_shown_on_dashboard(client: TestClient, db: Session) -> None:
    shop = _shop(db, "108")
    for n in range(3):
        crowd.save(db, shop, "stock_in", crowd.reporter_hash(f"+9190{n}", SALT))
    shop.status_stock = "out"
    db.commit()
    d = client.get("/api/dealer/overview").json()
    assert d["disagreements"] == [
        "Dealer says stock is out of stock; 3 cardholders report in stock in the last 5 minutes"
    ]
    assert d["reports_3h"]["stock_in"] == 3


def test_missed_call_checkin_is_rejected_and_counted(client: TestClient, db: Session) -> None:
    r = client.post("/twilio/voice/checkin", data={"From": RAMU, "CallSid": "CAx"})
    assert "<Reject />" in r.text
    shop = _shop(db, "112")
    assert crowd.checkins_recent(db, shop) == 1
    assert client.post("/twilio/voice/checkin", data={"From": "+15550000000"}).status_code == 200


def test_demo_reports_stay_fresh(client: TestClient, db: Session) -> None:
    clock.freeze(clock.now_utc() + timedelta(hours=5))
    sid = client.post("/api/sim/start", json={"caller": "ramu"}).json()["session_id"]
    client.post(f"/api/sim/{sid}/text", json={"text": "Avunu"})
    text = client.post(f"/api/sim/{sid}/text", json={"text": "biyyam vachaya"}).json()["text"]
    assert text.startswith("Biyyam vachindi, gata 30 nimishallo 4 mandi nirdharincharu.")
