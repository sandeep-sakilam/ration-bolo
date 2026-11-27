"""F46: closed-shop honesty (acceptance checks 30-32), clock-controlled at 01:30, 11:00,
14:00, 17:00 and 21:00 IST in demo mode."""

from __future__ import annotations

import re
from datetime import date, time, timedelta

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.clock import ist_to_utc
from tests.test_reply_budget import budget

DAY = date(2026, 11, 27)
CLOCK24 = re.compile(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b")
CLOSED = {"01:30": "poddhuna 8 gantalaku", "14:00": "saayantram 4 gantalaku"}
CLOSED["21:00"] = "repu poddhuna 8 gantalaku"


def _at(hhmm: str) -> None:
    hh, mm = (int(x) for x in hhmm.split(":"))
    # 01:30 is the next night (after the 11:00 seed), so the reports belong to yesterday.
    day = DAY + timedelta(days=1) if hh < 8 else DAY
    clock.freeze(ist_to_utc(day, time(hh, mm)))


def _call(client: TestClient, caller: str, lines: list[str]) -> list[dict[str, object]]:
    r = client.post("/api/sim/start", json={"caller": caller}).json()
    replies = [r]
    for text in lines:
        r = client.post(f"/api/sim/{r['session_id']}/text", json={"text": text}).json()
        replies.append(r)
    return replies


def _check_budget(replies: list[dict[str, object]]) -> None:
    for r in replies:
        text = str(r["text"])
        sentences, chars = budget(text)
        assert sentences <= 2 and chars <= 220, text
        assert not CLOCK24.search(text), text  # check 32: no HH:MM advice times


def _lakshmi_nearby(client: TestClient) -> tuple[str, str, list[dict[str, object]]]:
    client.post("/api/dealer/status", json={"machine": "down"})
    replies = _call(client, "lakshmi", ["Avunu", "Maa shop ki biyyam vachaya?", "Avunu"])
    return str(replies[2]["text"]), str(replies[3]["text"]), replies


@pytest.mark.parametrize("hhmm", ["01:30", "14:00", "21:00"])
def test_check30_closed_shop_offer_and_reply_agree(client: TestClient, hhmm: str) -> None:
    _at(hhmm)
    offer, reply, replies = _lakshmi_nearby(client)
    assert "Shop 112" in offer and "ippudu moosi undi" in offer
    assert "akkada biyyam undi, sumaru" not in offer and "Ippude" not in reply
    when = CLOSED[hhmm]
    wait = re.search(r"appudu sadharananga (\d+) nimishala wait", offer)
    assert wait is not None and when in offer
    assert reply.startswith(f"Sare, Shop 112. {when[0].upper()}{when[1:]} terustaru, ")
    assert f"appudu sadharananga {wait.group(1)} nimishala wait." in reply
    # Rice is mentioned only when known for today (not at 01:30: those are yesterday's).
    assert ("ivala" in offer and "biyyam undi" in offer) == (hhmm != "01:30")
    _check_budget(replies)


@pytest.mark.parametrize("hhmm", ["11:00", "17:00"])
def test_check30_open_hours_unchanged(client: TestClient, hhmm: str) -> None:
    _at(hhmm)
    offer, reply, replies = _lakshmi_nearby(client)
    assert offer == (
        "Avunu, biyyam vachindi. Mee kutumbaniki 24 kilolu. Shop 112, near Saidabad bus stop, "
        "1.2 km dooram lo undi; akkada biyyam undi, sumaru 10 nimishala wait, mee card "
        "sadharananga akkada kuda panichestundi; akkadiki veltara?"
    )
    assert (
        reply
        == "Sare, Shop 112. Ippude vellochu, akkada sumaru 10 nimishala wait. Inka emaina kavala?"
    )
    _check_budget(replies)


@pytest.mark.parametrize(
    ("hhmm", "spoken", "page"),
    [
        ("01:30", "ninna saayantram 4 mandi", "confirmed yesterday evening by"),
        ("14:00", "ivala poddhuna 4 mandi", "confirmed this morning by"),
        ("21:00", "ivala saayantram 4 mandi", "confirmed this evening by"),
    ],
)
def test_check31_demo_reports_keep_their_age(
    client: TestClient, hhmm: str, spoken: str, page: str
) -> None:
    _at(hhmm)
    replies = _call(client, "ramu", ["Avunu", "Biyyam vachaya?"])
    text = str(replies[2]["text"])
    assert text.startswith(f"Biyyam vachindi, {spoken} nirdharincharu.")
    assert "nimishallo" not in text
    html = client.get("/shop/112").text
    assert page in html and "minutes ago" not in html.split("Right now")[1].split("</ul>")[0]
    _check_budget(replies)


@pytest.mark.parametrize("hhmm", ["11:00", "17:00"])
def test_check31_open_hours_unchanged(client: TestClient, hhmm: str) -> None:
    _at(hhmm)
    replies = _call(client, "ramu", ["Avunu", "Biyyam vachaya?"])
    assert str(replies[2]["text"]) == (
        "Biyyam vachindi, gata 30 nimishallo 4 mandi nirdharincharu. Public ammakala data "
        "prakaram shop poddhuna 9:10 ki ammakalu modalupettindi. Inka emaina kavala?"
    )
    _check_budget(replies)


def test_hindi_closed_offer(client: TestClient) -> None:
    _at("14:00")
    client.post("/api/dealer/status", json={"machine": "down"})
    replies = _call(client, "salma", ["haan", "Mera ration aaya kya?", "haan"])
    offer, reply = str(replies[2]["text"]), str(replies[3]["text"])
    assert "abhi band hai, shaam 4 baje khulegi, tab aam taur par" in offer
    assert reply.startswith("Theek hai, dukaan 112. Shaam 4 baje khulegi, tab aam taur par")
    _check_budget(replies)
