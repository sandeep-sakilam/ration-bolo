from urllib.parse import parse_qs

import httpx
from sqlalchemy.orm import Session

from app.channels.exotel import ExotelMessenger
from app.config import Settings
from app.services import build_services


def _client(seen: list[httpx.Request], status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_exotel_sms_and_call(db: Session) -> None:
    seen: list[httpx.Request] = []
    m = ExotelMessenger(
        "acme",
        "k",
        "t",
        "08012345678",
        flow_url="http://my.exotel.com/acme/exoml/start_voice/1",
        dlt_entity_id="E1",
        dlt_template_id="T1",
        client=_client(seen),
    )
    assert m.send_sms(db, "+919000004401", "token B-036").status == "sent"
    assert m.place_call(db, "+919000004401", "Bayaluderandi", "te").status == "sent"
    sms, call = seen
    assert str(sms.url) == "https://api.in.exotel.com/v1/Accounts/acme/Sms/send.json"
    form = parse_qs(sms.content.decode())
    assert form["To"] == ["+919000004401"] and form["DltTemplateId"] == ["T1"]
    assert sms.headers["authorization"].startswith("Basic ")
    assert str(call.url).endswith("/Calls/connect.json")
    assert parse_qs(call.content.decode())["CallerId"] == ["08012345678"]


def test_exotel_failures_are_recorded(db: Session) -> None:
    seen: list[httpx.Request] = []
    m = ExotelMessenger("acme", "k", "t", "080", client=_client(seen, 401))
    assert m.send_sms(db, "+919000004401", "x").status == "failed"
    assert m.place_call(db, "+919000004401", "x", "te").status == "failed"  # no call flow
    assert len(seen) == 1


def test_exotel_selected_only_when_asked() -> None:
    keys = {"exotel_sid": "a", "exotel_api_key": "k", "exotel_api_token": "t"}
    off = build_services(Settings(_env_file=None, **keys))  # type: ignore[arg-type]
    assert off.messenger.name == "mock"
    on = build_services(Settings(_env_file=None, telephony_provider="exotel", **keys))  # type: ignore[arg-type]
    assert on.messenger.name == "exotel"
    status = {s["service"]: s for s in on.status()["services"]}
    assert status["indian_telephony"]["ready"] is True
