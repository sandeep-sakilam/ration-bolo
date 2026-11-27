"""F35: official complaint routing and escalation (acceptance check 20).

The helpline handoff is only ever rendered as TwiML here, with a fictional number from
the demo range; nothing is dialled and no real helpline number is used."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, grievance
from app.config import Settings
from app.dialogue import Dialogue
from app.main import create_app
from app.models import Complaint, Grievance, Outbox
from tests.test_dialogue import LAKSHMI, Call

FAKE_HELPLINE = "+919000000001"  # fictional demo-range number, never dialled


def _file(db: Session, call: Call) -> Complaint:
    call.say("Avunu")
    call.say("Naaku 15 kilolu ichharu")
    call.say("Avunu")
    return db.scalars(select(Complaint).order_by(Complaint.id.desc())).first()  # type: ignore[return-value]


def test_complaint_is_routed_with_prepared_text(db: Session) -> None:
    call = Call(db, LAKSHMI)
    complaint = _file(db, call)
    r = call.last
    assert "C-108-0003" in r.text and "complaint text SMS lo pampamu" in r.text
    assert {"type": "grievance_routed", "channel": "prepared"} in r.actions
    g = db.scalars(select(Grievance).where(Grievance.complaint_id == complaint.id)).one()
    assert g.stage == "filed" and g.next_action_at == clock.now_utc() + timedelta(days=7)
    sms = db.scalars(select(Outbox).where(Outbox.channel == "sms")).all()[-1]
    assert "C-108-0003" in sms.body and "24 kilolu raavalsindi, 15 kilolu" in sms.body
    assert "National Food Security Act, 2013 (Sections 14 and 15" in sms.body
    assert "https://pgportal.gov.in" in sms.body and "Lakshmi" not in sms.body


def test_check20_escalation_ladder(db: Session) -> None:
    call = Call(db, LAKSHMI)
    complaint = _file(db, call)
    db.commit()
    sent: list[tuple[str, str, str]] = []

    def send(channel: str, phone: str, body: str) -> None:
        sent.append((channel, phone, body))

    assert grievance.run_due(db, send) == 0  # not due yet
    clock.freeze(clock.now_utc() + timedelta(days=7, minutes=1))
    assert grievance.run_due(db, send) == 1
    assert "C-108-0003 7 rojulaina parishkarinchaledu" in sent[0][2]
    assert "mee District Supply Officer office" in sent[0][2]
    g = db.scalars(select(Grievance).where(Grievance.complaint_id == complaint.id)).one()
    assert g.stage == "escalated_district"
    clock.freeze(clock.now_utc() + timedelta(days=14))
    assert grievance.run_due(db, send) == 1
    assert "21 rojulaina" in sent[1][2] and "pgportal.gov.in" in sent[1][2]
    assert g.stage == "escalated_national" and g.next_action_at is None
    assert grievance.run_due(db, send) == 0


def test_resolved_complaints_are_not_escalated(client: TestClient, db: Session) -> None:
    call = Call(db, LAKSHMI)
    complaint = _file(db, call)
    db.commit()
    client.post(f"/api/dealer/complaints/{complaint.id}/resolve", json={"outcome": "Gave 9 kg"})
    db.expire_all()
    clock.freeze(clock.now_utc() + timedelta(days=8))
    assert grievance.run_due(db, lambda *a: None) == 0
    d = client.get("/api/dealer/overview").json()
    assert d["complaints"][0]["stage"] == "resolved"


def test_reference_number_read_back_and_stored(db: Session) -> None:
    call = Call(db, LAKSHMI)
    complaint = _file(db, call)
    r = call.say("reference number 4 5 6 7 8")
    assert r.text == "Reference number 4 5 6 7 8, sare na?"
    r = call.say("Avunu")
    assert r.text.startswith("Reference number ni complaint C-108-0003 tho namodu chesamu.")
    g = db.scalars(select(Grievance).where(Grievance.complaint_id == complaint.id)).one()
    assert g.external_ref == "45678"


def test_reference_without_open_complaint(db: Session) -> None:
    call = Call(db, "+919000007702")
    call.say("haan")
    assert call.say("reference number 1 2 3 4").text.startswith(
        "Aapke card par koi khuli shikayat nahi hai."
    )


def test_mock_mode_records_only(db: Session) -> None:
    dialogue = Dialogue(db, settings=Settings(_env_file=None, grievance_channel="mock"))  # type: ignore[call-arg]
    session = dialogue.start_session("simulator", LAKSHMI)
    from app.dialogue import Event

    dialogue.handle(session, Event("start"))
    for text in ("Avunu", "Naaku 15 kilolu ichharu", "Avunu"):
        r = dialogue.handle(session, Event("text", text))
    assert {"type": "grievance_routed", "channel": "mock"} in r.actions
    assert "pampamu" not in r.text
    assert not [o for o in db.scalars(select(Outbox)) if "C-108-0003" in o.body]


def test_no_helpline_offer_in_simulator_or_without_number(db: Session) -> None:
    call = Call(db, LAKSHMI)
    _file(db, call)
    assert call.last.state == "main"


@pytest.fixture
def voice_client(db_url: str) -> Iterator[tuple[TestClient, dict[str, str]]]:
    settings = Settings(
        _env_file=None,
        database_url=db_url,
        scheduler_enabled=False,  # type: ignore[call-arg]
        speech_mode="mock",
        grievance_helpline_number=FAKE_HELPLINE,
    )
    app = create_app(settings)
    speech: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, content=b"MOCKTEXT:" + speech[str(request.url)].encode())

    app.state.services.http = httpx.Client(transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        yield client, speech


def test_helpline_handoff_only_after_yes_as_twiml(
    voice_client: tuple[TestClient, dict[str, str]],
) -> None:
    client, speech = voice_client
    form = {"CallSid": "CAg", "From": LAKSHMI}
    client.post("/twilio/voice", data=form)
    xml = ""
    for n, text in enumerate(("Avunu", "Naaku 15 kilolu ichharu", "Avunu"), start=1):
        url = f"https://api.twilio.com/rec/RE{n}"
        speech[url + ".wav"] = text
        xml = client.post(
            "/twilio/voice/recording", data={**form, "RecordingUrl": url, "RecordingDuration": "2"}
        ).text
    assert "Ippude state food helpline ki connect cheyyamantara?" in xml and "<Dial" not in xml
    speech["https://api.twilio.com/rec/RE4.wav"] = "Avunu"
    xml = client.post(
        "/twilio/voice/recording",
        data={**form, "RecordingUrl": "https://api.twilio.com/rec/RE4", "RecordingDuration": "2"},
    ).text
    assert f"<Dial>{FAKE_HELPLINE}</Dial>" in xml
    assert "Helpline ki connect chestunnamu" in xml
