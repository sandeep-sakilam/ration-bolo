"""Official complaint routing and escalation (F35).

Complaints must reach someone who can act, even without a department partnership. Our
own complaint ID stays the single reference across all channels. Automatic filing into
government portals is not attempted (no public API): the app prepares and guides.

``GrievanceChannel`` adapters:
- ``mock``: records only;
- ``prepared``: writes a formal complaint (caller's language and English: shop, date,
  kg due and received, the NFSA grievance basis) and sends it by SMS or WhatsApp with
  steps to file it on the state portal or the national public grievance portal;
- ``helpline``: on phone calls, offers to connect the caller to the state's food
  grievance helpline with Twilio <Dial> — number from the state pack (or
  ``GRIEVANCE_HELPLINE_NUMBER``), only after the caller says yes. Never dialled in tests.

Escalation ladder: not resolved in 7 days → the caller is reminded and offered the
district grievance officer; 14 more days → the national public grievance portal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import queue
from app.clock import now_utc, to_ist
from app.config import Settings
from app.models import Complaint, Grievance, PhoneLink
from app.packs import Pack, get_pack

FIRST_ESCALATION = timedelta(days=7)
SECOND_ESCALATION = timedelta(days=14)
Sender = Callable[[str, str, str], None]


@dataclass(frozen=True)
class Contacts:
    helpline: str
    district: str
    state_portal: str
    national_portal: str


def contacts(pack: Pack, settings: Settings | None = None) -> Contacts:
    g = pack.raw["grievance"]
    s = settings
    return Contacts(
        helpline=(
            s.grievance_helpline_number
            if s and s.grievance_helpline_number
            else g.get("helpline_number", "")
        ),
        district=(
            s.district_grievance_contact
            if s and s.district_grievance_contact
            else g.get("district_officer", "")
        ),
        state_portal=g.get("state_portal", ""),
        national_portal=g.get("national_portal", "") or "https://pgportal.gov.in",
    )


def channel_mode(settings: Settings | None) -> str:
    return settings.grievance_channel if settings else "auto"


def helpline_available(pack: Pack, settings: Settings | None, session_channel: str) -> bool:
    mode = channel_mode(settings)
    return (
        mode in ("auto", "helpline")
        and session_channel == "call"
        and bool(contacts(pack, settings).helpline)
    )


def formal_text(complaint: Complaint, language: str, settings: Settings | None = None) -> str:
    """The prepared complaint in the caller's language and English."""
    card = complaint.card
    pack = get_pack(card.state_pack)
    c = contacts(pack, settings)
    values = {
        "complaint_no": complaint.complaint_no,
        "shop": card.shop.code,
        "area": card.shop.area,
        "date": to_ist(complaint.created_at).strftime("%d %b %Y"),
        "last4": card.last4,
        "kg": complaint.grams_received // 1000,
        "due": complaint.grams_due // 1000,
        "state_portal": c.state_portal or c.national_portal,
        "national_portal": c.national_portal,
    }
    local = (
        pack.phrase("grievance_formal", language, **values)
        + " "
        + pack.phrase("grievance_steps", language, **values)
    )
    english = (
        pack.phrase("grievance_formal", "en", **values)
        + " "
        + pack.phrase("grievance_steps", "en", **values)
    )
    return local if local == english else f"{local}\n\n{english}"


def file(
    db: Session,
    complaint: Complaint,
    language: str,
    phone: str | None,
    session_channel: str,
    send: Sender,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> Grievance:
    """Route a new complaint: record it, and (prepared/auto) send the formal text."""
    now = now or now_utc()
    mode = channel_mode(settings)
    kind = "mock" if mode == "mock" else ("helpline" if mode == "helpline" else "prepared")
    grievance = Grievance(
        complaint_id=complaint.id,
        channel=kind,
        stage="filed",
        next_action_at=now + FIRST_ESCALATION,
        created_at=now,
        updated_at=now,
    )
    db.add(grievance)
    db.flush()
    if kind != "mock" and phone:
        send(
            "whatsapp" if session_channel == "whatsapp" else "sms",
            phone,
            formal_text(complaint, language, settings),
        )
    queue.log_event(db, "system", "grievance_filed", f"complaint:{complaint.id}", channel=kind)
    return grievance


def record_reference(db: Session, complaint: Complaint, ref: str) -> Grievance:
    grievance = db.scalars(select(Grievance).where(Grievance.complaint_id == complaint.id)).first()
    if grievance is None:
        grievance = Grievance(
            complaint_id=complaint.id,
            channel="mock",
            stage="filed",
            next_action_at=now_utc() + FIRST_ESCALATION,
        )
        db.add(grievance)
    grievance.external_ref = ref[:64]
    grievance.updated_at = now_utc()
    queue.log_event(db, "caller", "grievance_reference", f"complaint:{complaint.id}")
    db.flush()
    return grievance


def _phone_for(db: Session, complaint: Complaint) -> str | None:
    link = db.scalars(
        select(PhoneLink).where(PhoneLink.card_id == complaint.card_id).order_by(PhoneLink.id)
    ).first()
    return link.phone_e164 if link else None


def run_due(
    db: Session, send: Sender, settings: Settings | None = None, now: datetime | None = None
) -> int:
    """Advance the escalation ladder for every due grievance. Returns steps taken."""
    now = now or now_utc()
    steps = 0
    due = db.scalars(
        select(Grievance).where(
            Grievance.stage.in_(("filed", "escalated_district")), Grievance.next_action_at <= now
        )
    ).all()
    for g in due:
        complaint = g.complaint
        if complaint.status == "resolved":
            g.stage, g.next_action_at, g.updated_at = "resolved", None, now
            continue
        card = complaint.card
        pack = get_pack(card.state_pack)
        lang = pack.reply_language(card.language)
        c = contacts(pack, settings)
        phone = _phone_for(db, complaint)
        if g.stage == "filed":
            body = pack.phrase(
                "escalate_district",
                lang,
                complaint_no=complaint.complaint_no,
                district=c.district or pack.phrase("district_unknown", lang),
            )
            g.stage, g.next_action_at = "escalated_district", now + SECOND_ESCALATION
        else:
            body = pack.phrase(
                "escalate_national",
                lang,
                complaint_no=complaint.complaint_no,
                national_portal=c.national_portal,
            )
            body += "\n\n" + formal_text(complaint, lang, settings)
            g.stage, g.next_action_at = "escalated_national", None
        g.updated_at = now
        if phone:
            send("sms", phone, body)
        queue.log_event(db, "system", f"grievance_{g.stage}", f"complaint:{complaint.id}")
        steps += 1
    db.flush()
    return steps


def mark_resolved(db: Session, complaint: Complaint) -> None:
    g = db.scalars(select(Grievance).where(Grievance.complaint_id == complaint.id)).first()
    if g is not None:
        g.stage, g.next_action_at, g.updated_at = "resolved", None, now_utc()
