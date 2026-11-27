from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import queue
from app.dialogue import Dialogue, Event, Reply
from app.models import Card, Complaint, DialogueSession, Outbox, PhoneLink, Shop, Token, Turn

LAKSHMI = "+919000004401"
SALMA = "+919000007702"
FAMILY = "+919000009903"
UNKNOWN = "+919000000000"


class Call:
    def __init__(self, db: Session, phone: str | None, channel: str = "simulator") -> None:
        self.db = db
        self.dialogue = Dialogue(db)
        self.session = self.dialogue.start_session(channel, phone)
        self.first = self.dialogue.handle(self.session, Event("start"))
        self.last = self.first

    def say(self, text: str, engine: str = "text") -> Reply:
        self.last = self.dialogue.handle(self.session, Event("text", text, engine=engine))
        self.db.commit()
        return self.last

    def key(self, digits: str) -> Reply:
        self.last = self.dialogue.handle(self.session, Event("digit", digits))
        return self.last

    def silence(self) -> Reply:
        self.last = self.dialogue.handle(self.session, Event("silence"))
        return self.last


def test_lakshmi_full_telugu_flow(db: Session) -> None:
    call = Call(db, LAKSHMI)
    assert call.first.text == "Namaskaram, Ration Bolo. Card chivari ankelu 0421, sare na?"
    assert "Lakshmi" not in call.first.text
    assert call.first.expect == "yes_no"
    assert call.say("Avunu").text == "Meeku ela sahayam cheyali?"
    r = call.say("Maa shop ki biyyam vachaya?")
    assert r.text.startswith("Avunu, biyyam vachindi. Mee kutumbaniki 24 kilolu.")
    r = call.say("Ippudu entha mandi unnaru?")
    assert r.text.startswith("18 mandi mundu unnaru, sumaru 36 nimishalu.")
    assert "Repu 10:20 ki rush takkuva" in r.text
    r = call.say("Repu poddhuna book cheyyandi.")
    assert r.text == "Repu 10:20 ki, sare na?"
    assert r.gloss == "Tomorrow at 10:20, okay?"
    r = call.say("Avunu")
    assert r.text.startswith("Booking ayindi. Mee token B-036, SMS lo pampamu.")
    assert r.actions[0]["type"] == "booking_created"
    sms = db.scalars(select(Outbox).where(Outbox.channel == "sms")).one()
    assert "B-036" in sms.body and "10:20" in sms.body and sms.to_masked.endswith("4401")
    assert "Lakshmi" not in sms.body


def test_no_moves_to_next_window_then_asks_other(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    assert call.say("Repu poddhuna book cheyyandi").text == "Repu 10:20 ki, sare na?"
    assert call.say("Kaadu").text == "Repu 10:40 ki, sare na?"
    assert call.say("Kaadu").text == "Repu 11:00 ki, sare na?"
    r = call.say("Kaadu")
    assert r.state == "book_when" and "Vere roju" in r.text
    assert call.say("saayantram").text == "Repu 16:00 ki, sare na?"


def test_booking_refused_twice_in_month(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    call.say("Repu poddhuna book cheyyandi")
    call.say("Avunu")
    r = call.say("Repu saayantram book cheyyandi")
    assert "Ee nela mee card ki booking already undi" in r.text and "10:20" in r.text
    assert any(a["type"] == "booking_refused" and a["reason"] == "month" for a in r.actions)


def test_machine_down_status_first_and_booking_refused(db: Session) -> None:
    shop = db.scalars(select(Shop).where(Shop.code == "108")).one()
    queue.set_status(db, shop, machine="down")
    db.commit()
    call = Call(db, SALMA)
    assert call.first.text.startswith("Namaste, Ration Bolo. Dhyan dijiye: dukaan ki machine band")
    call.say("haan")
    r = call.say("Kal subah book karo")
    assert "booking ruki hai" in r.text.lower()
    assert db.scalars(select(Token).where(Token.card_id == call.session.card_id)).first() is None


def test_hindi_flow(db: Session) -> None:
    call = Call(db, SALMA)
    assert call.first.text == "Namaste, Ration Bolo. Card ke aakhri ank 0513, theek hai?"
    call.say("haan")
    assert "18 kilo" in call.say("Mera ration aaya kya?").text
    assert call.say("Kitne log hain?").text.startswith("18 log aage hain, lagbhag 36 minute.")
    assert call.say("Kal subah book karo").text == "Kal 10:20 baje, theek hai?"
    assert "Booking ho gayi" in call.say("haan").text
    r = call.say("Mujhe kam mila")
    assert r.text == "Aapko kitne kilo mile?"
    assert call.say("das kilo").text == "10 kilo, theek hai?"
    assert "Shikayat darj" in call.say("haan").text


def test_complaint_filed_with_id_and_none_when_full(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    r = call.say("Naaku 15 kilolu ichharu")
    assert r.text == "15 kilolu, sare na?"
    r = call.say("Avunu")
    assert "C-108-0003" in r.text
    assert r.actions[0] == {"type": "complaint_filed", "complaint_no": "C-108-0003",
                            "kg_received": 15, "kg_due": 24}  # fmt: skip
    r = call.say("24 kilolu")
    assert "Meeku 24 kilolu raavali, 24 kilolu vachayi" in r.text
    assert db.query(Complaint).filter(Complaint.complaint_no.like("C-108-%")).count() == 3


def test_complaint_wrong_amount_asks_again(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    call.say("Naaku 15 kilolu ichharu")
    assert call.say("Kaadu").text == "Meeku entha kilolu ichharu?"
    assert call.say("padihaaru kilolu").text.startswith("16 kilolu")


def test_unknown_number_registers_and_is_recognised(db: Session) -> None:
    call = Call(db, UNKNOWN)
    assert call.first.text == "Namaskaram, Ration Bolo. Mee ration card number okko anke cheppandi."
    assert call.first.expect == "digits"
    r = call.say("1 0 8 0 4 2 1")
    assert r.text == "Card number 1 0 8 0 4 2 1, sare na?"
    r = call.say("Avunu")
    assert r.text.startswith("Sare, card 0421 ee phone ki link chesamu.")
    db.commit()
    link = db.scalars(select(PhoneLink).where(PhoneLink.phone_e164 == UNKNOWN)).one()
    assert link.source == "self_registered"
    again = Call(db, UNKNOWN)
    assert "0421, sare na?" in again.first.text


def test_unknown_card_digits_not_found(db: Session) -> None:
    call = Call(db, UNKNOWN)
    call.say("9 9 9 9 9")
    assert "dorakaledu" in call.say("avunu").text


def test_no_to_card_check_asks_for_digits(db: Session) -> None:
    call = Call(db, LAKSHMI)
    assert call.say("Kaadu").text == "Mee ration card number okko anke cheppandi."


def test_several_cards_asks_which(db: Session) -> None:
    call = Call(db, FAMILY)
    assert "rendu" not in call.first.text  # count is a number
    assert "2 cardlu unnayi: 0610, 0733" in call.first.text
    r = call.say("sunna edu moodu moodu")
    assert r.text == "Meeku ela sahayam cheyali?"
    card = db.get_one(Card, call.session.card_id)
    assert card.last4 == "0733"


def test_several_cards_by_keypad(db: Session) -> None:
    call = Call(db, FAMILY)
    call.key("1")
    assert db.get_one(Card, call.session.card_id).last4 == "0610"


def test_failures_switch_engine_then_menu(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    r1 = call.say("hmm hmm", engine="wispr")
    assert r1.text.startswith("Kshaminchandi") and r1.engine == "primary"
    r2 = call.say("", engine="wispr")
    assert r2.engine == "backup" and {"type": "engine_switched", "engine": "backup"} in r2.actions
    r3 = call.say("blah", engine="sarvam")
    assert r3.state == "menu" and r3.expect == "menu" and r3.menu
    assert "1 nokkandi" not in r3.text and "Stock kosam 1" in r3.text
    r4 = call.key("2")
    assert r4.text.startswith("18 mandi mundu unnaru")
    assert db.get_one(DialogueSession, call.session.id).used_menu


def test_whatsapp_menu_is_numbered_text(db: Session) -> None:
    call = Call(db, LAKSHMI, channel="whatsapp")
    call.say("Avunu")
    for _ in range(3):
        r = call.say("???")
    assert r.text.startswith("Number pampandi: 1 Stock")


def test_silence_twice_ends_with_summary(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    call.say("Repu poddhuna book cheyyandi")
    call.say("Avunu")
    assert call.silence().text == "Meeru vintunnara? Dayachesi cheppandi."
    r = call.silence()
    assert r.ended and r.text.startswith("Dhanyavaadalu")
    bodies = [o.body for o in db.scalars(select(Outbox))]
    assert any(b.startswith("Ration Bolo saaramsham: Token B-036") for b in bodies)


def test_language_switch_is_remembered(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    r = call.say("Hindi lo cheppandi")
    assert r.language == "hi" and r.text.startswith("Theek hai, ab main Hindi mein")
    assert "18 log aage hain" in call.say("entha mandi unnaru").text
    db.commit()
    assert db.scalars(select(Card).where(Card.card_no == "TS-108-0421")).one().language == "hi"
    again = Call(db, LAKSHMI)
    assert again.first.text.startswith("Namaste")


def test_intent_during_card_check_counts_as_yes(db: Session) -> None:
    call = Call(db, LAKSHMI)
    assert call.say("biyyam vachaya").text.startswith("Avunu, biyyam vachindi")


def test_goodbye_and_turns_logged_without_audio(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    r = call.say("chalu, dhanyavaadalu")
    assert r.ended
    turns = db.scalars(select(Turn).where(Turn.session_id == call.session.id)).all()
    assert [t.role for t in turns][:2] == ["app", "caller"]
    assert any(t.engine == "text" for t in turns if t.role == "caller")


def test_keypad_book_offers_tomorrow(db: Session) -> None:
    call = Call(db, LAKSHMI)
    call.say("Avunu")
    for _ in range(3):
        call.say("???")
    assert call.key("3").text == "Repu 10:20 ki, sare na?"
    assert call.key("1").text.startswith("Booking ayindi")
