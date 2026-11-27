"""F36: public transparency page and monthly report (acceptance check 21)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import transparency
from app.models import Card, CardHolder, PhoneLink, Shop

MONTH = "2026-11"


def test_shown_hides_small_counts() -> None:
    assert [transparency.shown(n) for n in (0, 1, 4, 5, 12)] == [
        "0",
        "fewer than 5",
        "fewer than 5",
        "5",
        "12",
    ]


def test_check21_shop_112_page_no_login_no_identifiers(client: TestClient, db: Session) -> None:
    r = client.get("/shop/112")
    assert r.status_code == 200 and "Shop 112" in r.text and "Level 0" in r.text
    assert "confirmed by fewer than 5 cardholders" in r.text  # 4 reports
    assert "Public sales data: selling since 09:10" in r.text
    assert "fewer than 5" in r.text and "Demo data" in r.text
    # No names, phone numbers or card numbers.
    names = [h.display_name.split(" (")[0] for h in db.scalars(select(CardHolder))]
    assert not any(n in r.text for n in ("Ramu", "Lakshmi", "Salma"))
    assert not re.search(r"\+91\d{10}|\b9000\d{6}\b", r.text)
    cards = [c.card_no for c in db.scalars(select(Card))]
    assert not any(c in r.text for c in cards)
    phones = [p.phone_e164 for p in db.scalars(select(PhoneLink))]
    assert not any(p in r.text or p[-10:] in r.text for p in phones)
    assert names  # sanity: the demo does have names, they are just never shown


def test_monthly_csv_downloads(client: TestClient) -> None:
    r = client.get(f"/shop/109/report/{MONTH}.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="shop-109-2026-11.csv"' in r.headers["content-disposition"]
    rows = dict(line.split(",", 3)[2:] for line in r.text.strip().splitlines()[1:])
    assert rows["Short-ration complaints"] == "6"
    assert rows["Resolved within 7 days"] == "fewer than 5"
    assert rows["Share resolved within 7 days"] == "67%"
    small = client.get(f"/shop/112/report/{MONTH}.csv").text
    assert "not shown (fewer than 5 complaints)" in small


def test_printable_report_and_json(client: TestClient) -> None:
    page = client.get(f"/shop/108/report/{MONTH}")
    assert page.status_code == 200 and "vigilance committee" in page.text
    assert "window.print()" in page.text
    data = client.get("/api/shop/108").json()
    assert data["level"].startswith("Level 2") and data["month"] == MONTH
    assert client.get("/shop/999").status_code == 404
    assert client.get("/shop/108/report/2026-13.csv").status_code == 400


def test_best_times_and_status_on_page(db: Session) -> None:
    shop = db.scalars(select(Shop).where(Shop.code == "109")).one()
    data = transparency.page_data(db, shop)
    assert data["status"] == ["No recent reports for this shop."]
    assert len(data["best_times"]) == 3 and "usually under" in data["best_times"][0]
