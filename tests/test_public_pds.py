"""F32: public PDS data (acceptance check 17). Never fetches a real portal."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, publicpds, shopstate
from app.clock import to_ist
from app.models import PublicSale, Shop
from app.publicpds import HttpPublicPds, MockPublicPds, PublicPdsService, SaleEvent
from tests.test_dialogue import Call

FIX = Path(__file__).parent / "fixtures" / "public_pds"
DAY = date(2026, 11, 27)
RAMU = "+919000008804"


def _shop(db: Session, code: str) -> Shop:
    return db.scalars(select(Shop).where(Shop.code == code)).one()


@pytest.fixture(autouse=True)
def fresh_service() -> None:
    publicpds.register(PublicPdsService(mode="auto", mock=MockPublicPds(FIX)))


def test_parse_assumed_csv_and_html_formats() -> None:
    csv_events = publicpds.parse_csv((FIX / "sample.csv").read_text(), DAY)
    assert [(to_ist(e.time).strftime("%H:%M"), e.count) for e in csv_events] == [
        ("09:10", 4),
        ("09:20", 4),
        ("09:30", 5),
    ]
    html_events = publicpds.parse_html_table((FIX / "sample.html").read_text(), DAY)
    assert [(to_ist(e.time).strftime("%H:%M"), e.count) for e in html_events] == [
        ("09:10", 4),
        ("09:20", 4),
        ("16:05", 3),
    ]
    with pytest.raises(publicpds.PublicPdsError):
        publicpds.parse_csv("a,b\n1,2\n", DAY)
    assert publicpds.parse_time("12:30 AM") is not None and publicpds.parse_time("25:00") is None


def test_http_adapter_uses_template_and_polite_agent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=(FIX / "sample.csv").read_text())

    client = httpx.Client(
        transport=httpx.MockTransport(handler), headers={"User-Agent": publicpds.USER_AGENT}
    )
    source = HttpPublicPds(
        "https://portal.example/fps?shop={shop_code}&d={date_dmy}", "csv", client=client
    )
    events = source.sales_today("112", DAY)
    assert len(events) == 3
    assert str(seen[0].url) == "https://portal.example/fps?shop=112&d=27/11/2026"
    assert seen[0].headers["user-agent"].startswith("RationBolo/")
    failing = HttpPublicPds(
        "https://x/{shop_code}",
        "csv",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))),
    )
    with pytest.raises(publicpds.PublicPdsError):
        failing.sales_today("112", DAY)


def test_signals() -> None:
    now = datetime(2026, 11, 27, 5, 30)  # 11:00 IST
    events = [SaleEvent(now - timedelta(minutes=m), 4) for m in (110, 50, 40, 20, 10)]
    s = publicpds.signals(events, now, open_now=True)
    assert s.first_sale == now - timedelta(minutes=110) and s.sales_last_hour == 16
    assert s.minutes_per_family == 60 / 16 and not s.possibly_stopped
    s = publicpds.signals(events[:1], now, open_now=True)
    assert s.possibly_stopped and s.stopped_minutes == 110 and s.minutes_per_family is None
    assert not publicpds.signals(events[:1], now, open_now=False).possibly_stopped


def test_check17_level0_status_from_public_data(db: Session) -> None:
    call = Call(db, RAMU)
    call.say("Avunu")
    text = call.say("biyyam vachaya").text
    assert "Public ammakala data prakaram shop 09:10 ki ammakalu modalupettindi." in text
    view = shopstate.view(db, _shop(db, "112"))
    assert view.public is not None and view.public.sales_last_hour >= 20
    assert view.minutes_per_family is not None and view.minutes_per_family < 3


def test_public_alone_says_stock_arrived(db: Session) -> None:
    from app.models import Report

    for row in db.scalars(select(Report)):
        db.delete(row)
    db.commit()
    text = Call(db, RAMU).say("biyyam vachaya").text  # question during the card check
    assert text.startswith("Public ammakala data prakaram shop 09:10 ki ammakalu")


def test_check17_failing_source_never_breaks_a_call(client: TestClient, db: Session) -> None:
    publicpds.register(PublicPdsService(mode="auto", mock=MockPublicPds(FIX, fail=True)))
    sid = client.post("/api/sim/start", json={"caller": "ramu"}).json()["session_id"]
    client.post(f"/api/sim/{sid}/text", json={"text": "Avunu"})
    r = client.post(f"/api/sim/{sid}/text", json={"text": "biyyam vachaya"}).json()
    assert r["text"].startswith("Biyyam vachindi, gata 30 nimishallo 4 mandi")
    status = {s["service"]: s for s in client.get("/api/status").json()["services"]}
    assert status["public_pds"]["note"].startswith("unavailable")
    assert status["public_pds"]["ready"] is False


def test_backoff_after_errors(db: Session) -> None:
    service = PublicPdsService(mode="auto", mock=MockPublicPds(FIX, fail=True))
    shop = _shop(db, "112")
    first = service.events(shop)
    assert first is not None and first.failures == 1
    again = service.events(shop)  # still inside the backoff window: no new attempt
    assert again is first
    clock.freeze(clock.now_utc() + timedelta(minutes=11))
    assert service.events(shop).failures == 2  # type: ignore[union-attr]


def test_cached_for_10_minutes_and_polling_stores_snapshots(db: Session) -> None:
    service = PublicPdsService(mode="auto", mock=MockPublicPds(FIX))
    shop = _shop(db, "112")
    entry = service.events(shop)
    assert entry is service.events(shop)
    added = service.store(db, shop)
    db.commit()
    assert added > 0 and service.store(db, shop) == 0
    assert db.scalars(select(PublicSale)).first() is not None


def test_off_mode_and_shops_without_data(db: Session) -> None:
    assert PublicPdsService(mode="off").signals(_shop(db, "112")) is None
    assert PublicPdsService(mode="auto", mock=MockPublicPds(FIX)).signals(_shop(db, "108")) is None


def test_shop_108_flow_unchanged_by_public_data(db: Session) -> None:
    call = Call(db, "+919000004401")
    call.say("Avunu")
    assert call.say("Ippudu entha mandi unnaru?").text.startswith(
        "18 mandi mundu unnaru, sumaru 36 nimishalu."
    )
