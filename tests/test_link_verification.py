import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.models import Outbox, PhoneLink
from tests.test_dialogue import UNKNOWN, Call


def _register(db: Session) -> Call:
    call = Call(db, UNKNOWN)
    call.say("1 0 8 0 4 2 1")
    r = call.say("Avunu")
    assert "card 0421 ee phone ki link chesamu" in r.text
    assert "4 ankela code SMS lo pampamu" in r.text and r.state == "verify_code"
    return call


def _code(db: Session) -> str:
    sms = db.scalars(select(Outbox).where(Outbox.body.contains("code"))).all()[-1]
    match = re.search(r"code: (\d{4})", sms.body)
    assert match and sms.channel == "sms" and sms.to_masked.endswith("0000")
    return match.group(1)


def _link(db: Session) -> PhoneLink:
    return db.scalars(select(PhoneLink).where(PhoneLink.phone_e164 == UNKNOWN)).one()


def test_correct_code_verifies_link(db: Session) -> None:
    call = _register(db)
    assert _link(db).source == "self_registered"
    code = _code(db)
    r = call.say(" ".join(code))
    assert r.text.startswith("Dhanyavaadalu, mee phone dhruveekarinchabadindi.")
    assert r.text.endswith("Meeku ela sahayam cheyali?") and r.state == "main"
    assert _link(db).source == "verified"


def test_wrong_code_then_give_up(db: Session) -> None:
    call = _register(db)
    wrong = "0000" if _code(db) != "0000" else "1111"
    assert call.say(wrong).text == "Code sari kaadu. Malli cheppandi."
    call.say(wrong)
    r = call.say(wrong)
    assert r.state == "main" and _link(db).source == "self_registered"


def test_skip_verification(db: Session) -> None:
    call = _register(db)
    r = call.say("Kaadu")
    assert r.state == "main" and _link(db).source == "self_registered"


def test_question_skips_verification(db: Session) -> None:
    call = _register(db)
    assert "24 kilolu" in call.say("biyyam vachaya").text


def test_expired_code(db: Session) -> None:
    call = _register(db)
    code = _code(db)
    clock.freeze(clock.now_utc() + timedelta(minutes=11))
    r = call.say(code)
    assert r.state == "main" and _link(db).source == "self_registered"


def test_code_never_stored_in_plain_text(db: Session) -> None:
    call = _register(db)
    code = _code(db)
    assert code not in str(call.session.data)
