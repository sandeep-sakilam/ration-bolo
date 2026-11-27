"""The draft Tamil Nadu pack: a new state is a new file, not new code."""

from sqlalchemy.orm import Session

from app.packs import get_pack
from app.understanding import understand
from tests.test_dialogue import Call

MEENA = "+919000006603"


def test_pack_is_draft_and_valid() -> None:
    pack = get_pack("tamil_nadu")
    assert pack.is_draft and pack.default_language == "ta"
    assert pack.entitlement_kg(3) == 15
    assert set(range(101)) <= set(pack.raw["numbers"]["ta"].values())


def test_tamil_understanding() -> None:
    pack = get_pack("tamil_nadu")
    assert understand("Arisi vanthucha?", pack).intent == "stock"
    assert understand("Evvalavu per irukkanga?", pack).intent == "queue"
    assert understand("Naalai kaalai book pannunga", pack).intent == "book"
    r = understand("Enakku pathu kilo thaan kuduthaanga", pack)
    assert r.intent == "complaint" and r.kilos == 10
    assert understand("aamaam", pack).yes and understand("illai", pack).no


def test_meena_tamil_flow(db: Session) -> None:
    call = Call(db, MEENA)
    assert call.first.text == "Vanakkam, Ration Bolo. Card kadaisi engal 0618, sariya?"
    call.say("aamaam")
    assert "15 kilo" in call.say("Arisi vanthucha?").text
    assert call.say("Naalai kaalai book pannunga").text == "Naalai 08:00 manikku, sariya?"
    assert "Pathivu aagivittathu" in call.say("aamaam").text
    r = call.say("Enakku pathu kilo thaan kuduthaanga")
    assert r.text == "10 kilo, sariya?"


def test_simulator_lists_telangana_first(client) -> None:  # type: ignore[no-untyped-def]
    packs = client.get("/api/packs").json()
    assert [p["state"] for p in packs] == ["telangana", "tamil_nadu"]
    assert packs[1]["draft"] is True
