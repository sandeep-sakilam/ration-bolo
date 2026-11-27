"""Dialogue engine: one channel-independent state machine. Rules only, no AI.

Input: an event (start, text with language and engine, keypad digit, silence, end).
Output: a Reply with text, language, actions and the next state. The phone line,
WhatsApp and the call simulator are thin wrappers around ``Dialogue.handle``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import queue, reminders
from app.clock import fmt_time, ist_today, now_utc
from app.models import (
    Card,
    DialogueSession,
    Outbox,
    PhoneLink,
    Shop,
    Token,
    Turn,
    Window,
    mask_phone,
)
from app.packs import Pack, get_pack
from app.understanding import Understanding, understand

MAX_OFFERS = 3  # the first offer plus up to two more
MENU = {"1": "stock", "2": "queue", "3": "book", "4": "complaint"}
YES_KEY, NO_KEY = "1", "2"

Sender = Callable[[str, str, str], None]  # (channel, phone_e164, body)


def outbox_sender(db: Session) -> Sender:
    """Default sender: every message goes to the outbox as a mock send."""

    def send(channel: str, phone: str, body: str) -> None:
        db.add(Outbox(channel=channel, to_masked=mask_phone(phone), body=body, status="mock"))

    return send


@dataclass
class Event:
    kind: str  # start | text | digit | silence | end
    text: str = ""
    language: str | None = None
    engine: str = "text"
    confidence: float | None = None


@dataclass
class Reply:
    session_id: int
    text: str
    gloss: str
    language: str
    state: str
    ended: bool = False
    expect: str = "speech"  # speech | yes_no | digits | menu
    actions: list[dict[str, Any]] = field(default_factory=list)
    menu: list[dict[str, str]] | None = None
    engine: str = "primary"
    audio_id: str | None = None


@dataclass(frozen=True)
class Word:
    """A display word (today, tomorrow, morning, evening) rendered in each reply language."""

    key: str


class _Out:
    """Collects reply parts as (phrase key, values) so text and gloss stay in step."""

    def __init__(self, pack: Pack, language: str) -> None:
        self.pack, self.language = pack, language
        self.parts: list[tuple[str, dict[str, object]]] = []
        self.actions: list[dict[str, Any]] = []
        self.expect = "speech"
        self.menu: list[dict[str, str]] | None = None

    def say(self, key: str, **values: object) -> None:
        self.parts.append((key, values))

    def render(self, language: str) -> str:
        def value(v: object) -> object:
            return self.pack.display(v.key, language) if isinstance(v, Word) else v

        return " ".join(
            self.pack.phrase(k, language, **{n: value(v) for n, v in vals.items()})
            for k, vals in self.parts
        )


class Dialogue:
    def __init__(self, db: Session, send: Sender | None = None) -> None:
        self.db = db
        self.send = send or outbox_sender(db)

    # --- sessions ---------------------------------------------------------

    def start_session(
        self,
        channel: str,
        phone: str | None,
        state_pack: str = "telangana",
        external_id: str | None = None,
    ) -> DialogueSession:
        pack = get_pack(state_pack)
        session = DialogueSession(
            channel=channel,
            phone_e164=phone,
            phone_masked=mask_phone(phone),
            state_pack=state_pack,
            language=pack.default_language,
            state="start",
            data={},
            external_id=external_id,
            started_at=now_utc(),
            last_activity_at=now_utc(),
        )
        self.db.add(session)
        self.db.flush()
        return session

    def handle(self, session: DialogueSession, event: Event) -> Reply:
        pack = get_pack(session.state_pack)
        session.last_activity_at = now_utc()
        out = _Out(pack, session.language)
        if session.state == "ended":
            out.say("goodbye")
            return self._finish(session, out, ended=True)
        if event.kind == "start":
            self._start(session, out)
        elif event.kind == "end":
            return self._end(session, out, silent=True)
        elif event.kind == "silence":
            session.silences += 1
            self._log_caller(session, "", event, understood=False)
            if session.silences >= 2:
                out.say("goodbye")
                return self._end(session, out)
            out.say("silence")
        else:
            session.silences = 0
            if event.kind == "digit":
                self._log_caller(session, f"[keypad {event.text}]", event, understood=True)
                self._digit(session, event.text.strip(), out)
            else:
                u = understand(event.text, pack)
                self._log_caller(session, event.text, event, understood=u.understood)
                if u.switch_to:
                    self._switch_language(session, u.switch_to, out)
                    if not u.intent and session.state == "main":
                        out.say("how_help")
                else:
                    self._speech(session, u, out)
        if session.state == "ended":
            return self._end(session, out)
        return self._finish(session, out)

    # --- event handlers ---------------------------------------------------

    def _start(self, session: DialogueSession, out: _Out) -> None:
        out.say("greeting")
        cards = self._linked_cards(session.phone_e164)
        if len(cards) == 1:
            card = cards[0]
            self._set_card(session, card, out)
            self._status_alerts(card.shop, out)
            out.say("confirm_card", last4=card.last4)
            self._goto(session, "confirm_card", out)
        elif len(cards) > 1:
            session.data = {**session.data, "cards": [c.id for c in cards]}
            shops = {c.shop_id for c in cards}
            if len(shops) == 1:
                self._status_alerts(cards[0].shop, out)
            out.say("which_card", count=len(cards), options=", ".join(_card_labels(cards)))
            self._goto(session, "choose_card", out)
        else:
            out.say("ask_card_digits")
            self._goto(session, "ask_digits", out)

    def _digit(self, session: DialogueSession, key: str, out: _Out) -> None:
        state = session.state
        if state in ("main", "menu") and key in MENU:
            session.failures = 0
            self._intent(session, MENU[key], None, out)
        elif state == "choose_card":
            self._choose_card(session, key, out)
        elif state == "ask_digits" and len(key.strip("#*")) >= 4:
            self._read_back_digits(session, key.strip("#*"), out)
        elif state in _YES_NO_STATES and key in (YES_KEY, NO_KEY):
            fake = Understanding(text=key, tokens=[key], yes=key == YES_KEY, no=key == NO_KEY)
            self._speech(session, fake, out)
        else:
            self._failure(session, out)

    def _speech(self, session: DialogueSession, u: Understanding, out: _Out) -> None:
        handler = getattr(self, f"_in_{session.state}", None)
        handled = handler(session, u, out) if handler else False
        if handled:
            session.failures = 0
        else:
            self._failure(session, out)

    # --- per-state speech handlers (return False when not understood) ------

    def _in_confirm_card(self, session: DialogueSession, u: Understanding, out: _Out) -> bool:
        if u.no:
            session.card_id = None
            out.say("ask_card_digits")
            self._goto(session, "ask_digits", out)
            return True
        if u.yes:
            out.say("how_help")
            self._goto(session, "main", out)
            return True
        if u.intent:  # going straight to a question counts as a yes
            self._goto(session, "main", out)
            return self._in_main(session, u, out)
        return False

    def _in_choose_card(self, session: DialogueSession, u: Understanding, out: _Out) -> bool:
        if not u.digits:
            return False
        return self._choose_card(session, u.digits, out)

    def _choose_card(self, session: DialogueSession, digits: str, out: _Out) -> bool:
        cards = [self.db.get_one(Card, i) for i in session.data.get("cards", [])]
        if len(digits) < 4 and digits.isdigit() and 1 <= int(digits) <= len(cards):
            matches = [cards[int(digits) - 1]]
        else:
            matches = [c for c in cards if len(digits) >= 4 and c.digits.endswith(digits)]
        if len(matches) != 1:
            out.say("which_card", count=len(cards), options=", ".join(_card_labels(cards)))
            out.expect = "digits"
            return False
        self._set_card(session, matches[0], out)
        out.say("how_help")
        self._goto(session, "main", out)
        return True

    def _in_ask_digits(self, session: DialogueSession, u: Understanding, out: _Out) -> bool:
        if len(u.digits) < 4:
            return False
        self._read_back_digits(session, u.digits, out)
        return True

    def _read_back_digits(self, session: DialogueSession, digits: str, out: _Out) -> None:
        session.data = {**session.data, "digits": digits}
        out.say("read_back_digits", digits=" ".join(digits))
        self._goto(session, "confirm_digits", out)

    def _in_confirm_digits(self, session: DialogueSession, u: Understanding, out: _Out) -> bool:
        if len(u.digits) >= 4 and not u.yes:
            self._read_back_digits(session, u.digits, out)
            return True
        if u.no:
            out.say("ask_card_digits")
            self._goto(session, "ask_digits", out)
            return True
        if not u.yes:
            return False
        digits = session.data.get("digits", "")
        card = self._card_by_digits(digits)
        if card is None:
            out.say("card_not_found")
            self._goto(session, "ask_digits", out)
            return True
        if session.phone_e164:
            exists = self.db.scalars(
                select(PhoneLink).where(
                    PhoneLink.phone_e164 == session.phone_e164, PhoneLink.card_id == card.id
                )
            ).first()
            if not exists:
                self.db.add(
                    PhoneLink(
                        phone_e164=session.phone_e164, card_id=card.id, source="self_registered"
                    )
                )
                out.actions.append({"type": "phone_linked", "last4": card.last4})
        self._set_card(session, card, out)
        out.say("card_linked", last4=card.last4)
        self._status_alerts(card.shop, out)
        out.say("how_help")
        self._goto(session, "main", out)
        return True

    def _in_main(self, session: DialogueSession, u: Understanding, out: _Out) -> bool:
        if u.intent:
            self._intent(session, u.intent, u, out)
            return True
        if u.no:
            out.say("goodbye")
            self._goto(session, "ended", out)
            return True
        if u.yes:
            out.say("how_help")
            return True
        if u.numbers and session.state == "menu":
            key = str(u.numbers[0])
            if key in MENU:
                self._intent(session, MENU[key], None, out)
                return True
        return False

    _in_menu = _in_main

    def _in_book_when(self, session: DialogueSession, u: Understanding, out: _Out) -> bool:
        if u.day or u.session:
            self._plan_booking(session, u.day, u.session, out)
            return True
        if u.no:
            out.say("anything_else")
            self._goto(session, "main", out)
            return True
        return self._in_main(session, u, out)

    def _in_confirm_booking(self, session: DialogueSession, u: Understanding, out: _Out) -> bool:
        offer = dict(session.data.get("offer", {}))
        if (u.day or u.session) and not u.yes:
            self._plan_booking(session, u.day or offer.get("day"), u.session, out)
            return True
        if u.yes:
            self._confirm_booking(session, offer, out)
            return True
        if u.no:
            tried = list(offer.get("tried", []))
            card = self._card(session)
            day = date.fromisoformat(offer["day"])
            nxt = queue.offers(self.db, card.shop, day, offer.get("session"), exclude=set(tried))
            if len(tried) < MAX_OFFERS and nxt:
                self._offer(session, nxt[0], offer.get("session"), tried, out)
            else:
                out.say("ask_other")
                self._goto(session, "book_when", out)
            return True
        return False

    def _in_ask_kg(self, session: DialogueSession, u: Understanding, out: _Out) -> bool:
        kg = u.kilos if u.kilos is not None else (u.numbers[0] if u.numbers else None)
        if kg is None:
            return False
        self._complaint_amount(session, kg, out)
        return True

    def _in_confirm_kg(self, session: DialogueSession, u: Understanding, out: _Out) -> bool:
        if u.numbers and not u.yes:
            return self._in_ask_kg(session, u, out)
        if u.no:
            out.say("ask_kg")
            self._goto(session, "ask_kg", out)
            return True
        if not u.yes:
            return False
        card = self._card(session)
        kg = int(session.data["complaint_kg"])
        complaint = queue.file_complaint(self.db, card, kg * 1000, session.channel)
        out.say("complaint_filed", complaint_no=complaint.complaint_no)
        out.actions.append(
            {
                "type": "complaint_filed",
                "complaint_no": complaint.complaint_no,
                "kg_received": kg,
                "kg_due": complaint.grams_due // 1000,
            }
        )
        self._summary(session, f"Complaint {complaint.complaint_no}")
        out.say("anything_else")
        self._goto(session, "main", out)
        return True

    # --- intents ------------------------------------------------------------

    def _intent(
        self, session: DialogueSession, intent: str, u: Understanding | None, out: _Out
    ) -> None:
        card = self._card(session)
        shop = card.shop
        kg_due = queue.entitlement_grams(card) // 1000
        if intent == "stock":
            if shop.status_machine != "working":
                out.say("status_machine_down")
            out.say("stock_yes" if shop.status_stock == "in_stock" else "stock_no", kg=kg_due)
            out.say("anything_else")
            self._goto(session, "main", out)
        elif intent == "queue":
            info = queue.people_ahead_now(self.db, shop)
            if info.ahead:
                out.say("queue", ahead=info.ahead, minutes=info.minutes)
            else:
                out.say("queue_empty")
            quiet = queue.quietest_tomorrow(self.db, shop)
            if quiet:
                out.say("quietest", time=fmt_time(quiet))
            out.say("anything_else")
            self._goto(session, "main", out)
        elif intent == "book":
            if u is None:  # keypad: first free window tomorrow, any session
                self._plan_booking(session, "tomorrow", None, out)
            elif u.day or u.session:
                self._plan_booking(session, u.day, u.session, out)
            elif queue.paused(shop):
                self._plan_booking(session, "tomorrow", None, out)
            else:
                out.say("ask_book_when")
                self._goto(session, "book_when", out)
        elif intent == "complaint":
            kg = None
            if u is not None:
                kg = u.kilos if u.kilos is not None else (u.numbers[0] if u.numbers else None)
            if kg is None:
                out.say("ask_kg")
                self._goto(session, "ask_kg", out)
            else:
                self._complaint_amount(session, kg, out)
        elif intent == "end":
            out.say("goodbye")
            self._goto(session, "ended", out)

    def _plan_booking(
        self, session: DialogueSession, day_word: str | None, session_word: str | None, out: _Out
    ) -> None:
        card = self._card(session)
        shop = card.shop
        today = ist_today()
        day = today if day_word == "today" else today + timedelta(days=1)
        if isinstance(day_word, str) and len(day_word) == 10:  # ISO date carried in offer
            day = date.fromisoformat(day_word)
        try:
            queue.check_can_book(self.db, card, day)
        except queue.BookingRefused as refused:
            self._refused(session, refused, out)
            return
        windows = queue.offers(self.db, shop, day, session_word)
        if not windows:
            out.say(
                "no_slots",
                day=self._day_label(day),
                session=Word(session_word) if session_word else "",
            )
            self._goto(session, "book_when", out)
            return
        self._offer(session, windows[0], session_word, [], out)

    def _offer(
        self,
        session: DialogueSession,
        window: Window,
        session_word: str | None,
        tried: list[int],
        out: _Out,
    ) -> None:
        session.data = {
            **session.data,
            "offer": {
                "day": window.date.isoformat(),
                "session": session_word,
                "tried": [*tried, window.id],
                "window_id": window.id,
            },
        }
        out.say("book_offer", day=self._day_label(window.date), time=fmt_time(window.start_time))
        self._goto(session, "confirm_booking", out)

    def _confirm_booking(self, session: DialogueSession, offer: dict[str, Any], out: _Out) -> None:
        card = self._card(session)
        window = self.db.get_one(Window, offer["window_id"])
        try:
            token = queue.book(self.db, card, window, session.channel)
        except queue.BookingRefused as refused:
            if refused.reason == "full":
                self._plan_booking(session, offer["day"], offer.get("session"), out)
            else:
                self._refused(session, refused, out)
            return
        reminders.schedule(self.db, token)
        via = "WhatsApp" if session.channel == "whatsapp" else "SMS"
        out.say("booked", token=token.label, via=via)
        out.actions.append(
            {
                "type": "booking_created",
                "token": token.label,
                "date": window.date.isoformat(),
                "time": fmt_time(window.start_time),
            }
        )
        if session.phone_e164:
            pack = get_pack(session.state_pack)
            body = pack.phrase(
                "sms_booking",
                session.language,
                date=window.date.strftime("%d %b"),
                time=fmt_time(window.start_time),
                token=token.label,
                last4=card.last4,
                shop=card.shop.code,
            )
            self.send("whatsapp" if via == "WhatsApp" else "sms", session.phone_e164, body)
        self._summary(
            session, f"Token {token.label} {window.date:%d %b} {fmt_time(window.start_time)}"
        )
        out.say("anything_else")
        self._goto(session, "main", out)

    def _refused(self, session: DialogueSession, refused: queue.BookingRefused, out: _Out) -> None:
        if refused.reason == "paused":
            shop = self._card(session).shop
            self._status_alerts(shop, out)
            out.say("booking_paused")
        elif refused.reason == "month" and refused.existing is not None:
            existing: Token = refused.existing
            when = existing.window.start_time if existing.window else None
            out.say(
                "booking_refused_month",
                day=self._day_label(existing.date),
                time=fmt_time(when) if when else "",
                token=existing.label,
            )
        out.actions.append({"type": "booking_refused", "reason": refused.reason})
        out.say("anything_else")
        self._goto(session, "main", out)

    def _complaint_amount(self, session: DialogueSession, kg: int, out: _Out) -> None:
        card = self._card(session)
        due = queue.entitlement_grams(card) // 1000
        if kg >= due:
            out.say("complaint_none", due=due, kg=kg)
            out.say("anything_else")
            self._goto(session, "main", out)
            return
        session.data = {**session.data, "complaint_kg": kg}
        out.say("complaint_readback", kg=kg)
        self._goto(session, "confirm_kg", out)

    # --- failures, language, ending -----------------------------------------

    def _failure(self, session: DialogueSession, out: _Out) -> None:
        session.failures += 1
        if session.failures == 2 and session.engine == "primary":
            session.engine = "backup"
            out.actions.append({"type": "engine_switched", "engine": "backup"})
        if session.failures >= 3:
            session.used_menu = True
            out.say("menu_text" if session.channel == "whatsapp" else "menu")
            out.actions.append({"type": "menu_shown"})
            self._goto(session, "menu", out)
            return
        out.say("sorry")
        if session.state == "choose_card":
            out.expect = "digits"

    def _switch_language(self, session: DialogueSession, target: str, out: _Out) -> None:
        pack = get_pack(session.state_pack)
        lang = pack.reply_language(target)
        session.language = lang
        out.language = lang
        if session.card_id:
            self._card(session).language = lang
        out.say("language_switched")
        out.actions.append({"type": "language_switched", "language": lang})

    def _end(self, session: DialogueSession, out: _Out, silent: bool = False) -> Reply:
        session.state = "ended"
        session.ended_at = now_utc()
        items = session.data.get("summary", [])
        if items and session.phone_e164 and not session.data.get("summary_sent"):
            pack = get_pack(session.state_pack)
            body = pack.phrase("summary", session.language, items="; ".join(items))
            self.send(
                "whatsapp" if session.channel == "whatsapp" else "sms", session.phone_e164, body
            )
            session.data = {**session.data, "summary_sent": True}
            out.actions.append({"type": "summary_sent"})
        out.actions.append({"type": "call_ended"})
        if silent and not out.parts:
            return self._finish(session, out, ended=True, log=False)
        return self._finish(session, out, ended=True)

    # --- helpers --------------------------------------------------------------

    def _finish(
        self, session: DialogueSession, out: _Out, ended: bool = False, log: bool = True
    ) -> Reply:
        text = out.render(session.language)
        if out.menu is None and session.state == "menu":
            out.menu = [{"key": k, "intent": v} for k, v in MENU.items()]
        expect = out.expect
        if session.state in _YES_NO_STATES:
            expect = "yes_no"
        elif session.state in ("ask_digits", "choose_card"):
            expect = "digits"
        elif session.state == "menu":
            expect = "menu"
        if log and text:
            self.db.add(
                Turn(
                    session_id=session.id,
                    role="app",
                    text=text,
                    language=session.language,
                    created_at=now_utc(),
                )
            )
        self.db.flush()
        return Reply(
            session_id=session.id,
            text=text,
            gloss=out.render("en"),
            language=session.language,
            state=session.state,
            ended=ended or session.state == "ended",
            expect=expect,
            actions=out.actions,
            menu=out.menu,
            engine=session.engine,
        )

    def _goto(self, session: DialogueSession, state: str, out: _Out) -> None:
        session.state = state

    def _log_caller(
        self, session: DialogueSession, text: str, event: Event, understood: bool
    ) -> None:
        self.db.add(
            Turn(
                session_id=session.id,
                role="caller",
                text=text,
                language=event.language or "",
                engine=event.engine,
                confidence=event.confidence,
                understood=understood,
                created_at=now_utc(),
            )
        )

    def _summary(self, session: DialogueSession, item: str) -> None:
        session.data = {**session.data, "summary": [*session.data.get("summary", []), item]}

    def _linked_cards(self, phone: str | None) -> list[Card]:
        if not phone:
            return []
        links = self.db.scalars(
            select(PhoneLink).where(PhoneLink.phone_e164 == phone).order_by(PhoneLink.id)
        )
        return [link.card for link in links]

    def _card_by_digits(self, digits: str) -> Card | None:
        for card in self.db.scalars(select(Card)):
            if card.digits == digits:
                return card
        return None

    def _set_card(self, session: DialogueSession, card: Card, out: _Out) -> None:
        session.card_id = card.id
        session.state_pack = card.state_pack
        pack = get_pack(card.state_pack)
        session.language = pack.reply_language(card.language)
        out.pack, out.language = pack, session.language

    def _card(self, session: DialogueSession) -> Card:
        if session.card_id is None:
            raise RuntimeError("no card on this session yet")
        return self.db.get_one(Card, session.card_id)

    def _status_alerts(self, shop: Shop, out: _Out) -> None:
        if shop.status_stock != "in_stock":
            out.say("status_stock_out")
        if shop.status_machine != "working":
            out.say("status_machine_down")

    def _day_label(self, day: date) -> Word | str:
        today = ist_today()
        if day == today:
            return Word("today")
        if day == today + timedelta(days=1):
            return Word("tomorrow")
        return day.strftime("%d %b")


_YES_NO_STATES = {"confirm_card", "confirm_digits", "confirm_booking", "confirm_kg"}


def _card_labels(cards: list[Card]) -> list[str]:
    """Last 4 digits, or last 6 when two cards share their last 4."""
    last4 = [c.last4 for c in cards]
    return [c.digits[-6:] if last4.count(c.last4) > 1 else c.last4 for c in cards]
