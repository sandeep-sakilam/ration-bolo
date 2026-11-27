from fastapi.testclient import TestClient

ADMIN = {"X-Admin-Pin": "1234"}
DEALER = {"X-Dealer-Pin": "1234"}

SHOPS = (
    "code,name,area,state_pack,sessions,families_per_hour,booked_share\n"
    '130,Fair Price Shop 130,"Saidabad, Hyderabad",telangana,09:00-13:00;15:00-19:00,24,0.5\n'
)
CARDS = (
    "card_no,shop_code,members,language,phone\n"
    "TS-130-0007,130,2,hi,+919000001234\n"
    "TS-108-0421,108,5,te,\n"
)


def _post(client: TestClient, kind: str, text: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/admin/import/{kind}",
        headers=ADMIN,
        files={"file": (f"{kind}.csv", text.encode(), "text/csv")},
    )


def test_admin_open_without_pin(client: TestClient) -> None:
    assert client.get("/api/admin/shops").status_code == 200
    shops = client.get("/api/admin/shops", headers=ADMIN).json()
    assert [s["code"] for s in shops] == ["108", "109", "112", "115", "201"]
    assert shops[0]["waiting"] == 18 and shops[0]["cards"] >= 74
    assert client.get("/admin").status_code == 200


def test_import_shops_and_cards_then_call(client: TestClient) -> None:
    r = _post(client, "shops", SHOPS)
    assert r.status_code == 200 and r.json()["created"] == 1
    r = _post(client, "cards", CARDS)
    assert r.json() == {"created": 1, "updated": 1, "message": "Imported: 1 new, 1 updated"}
    shops = {s["code"]: s for s in client.get("/api/admin/shops", headers=ADMIN).json()}
    assert shops["130"]["sessions"] == "09:00-13:00;15:00-19:00" and shops["130"]["cards"] == 1
    # The imported phone is recognised; the new shop's own hours are used for bookings.
    from app.seed import DEMO_CALLERS

    DEMO_CALLERS["imported"] = {"phone": "+919000001234", "label": "test"}
    try:
        sid = client.post("/api/sim/start", json={"caller": "imported"}).json()["session_id"]
        client.post(f"/api/sim/{sid}/text", json={"text": "haan"})
        r = client.post(f"/api/sim/{sid}/text", json={"text": "kal subah book karo"}).json()
        assert r["text"] == "Kal 09:00 baje, theek hai?"
    finally:
        del DEMO_CALLERS["imported"]
    # Updated members change the entitlement.
    sid = client.post("/api/sim/start", json={"caller": "lakshmi"}).json()["session_id"]
    client.post(f"/api/sim/{sid}/text", json={"text": "Avunu"})
    r = client.post(f"/api/sim/{sid}/text", json={"text": "biyyam vachaya"}).json()
    assert "30 kilolu" in r["text"]
    # The dealer dashboard can switch to the new shop.
    d = client.get("/api/dealer/overview", headers={**DEALER, "X-Shop-Code": "130"}).json()
    assert d["shop"]["code"] == "130" and len(d["shops"]) == 6


def test_bad_rows_import_nothing(client: TestClient) -> None:
    bad = (
        "code,name,area,state_pack,sessions,families_per_hour,booked_share\n"
        "110,Shop 110,X,telangana,08:00-12:00,30,0.5\n"
        "111,Shop 111,Y,kerala,08:00-12:00,30,0.5\n"
        "112,Shop 112,Z,telangana,12:00-08:00,30,0.5\n"
    )
    r = _post(client, "shops", bad)
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert errors[0].startswith("row 3: unknown state_pack") and errors[1].startswith("row 4:")
    codes = [s["code"] for s in client.get("/api/admin/shops", headers=ADMIN).json()]
    assert "110" not in codes
    r = _post(client, "cards", "card_no,shop_code,members,language,phone\nX1,999,2,te,123\n")
    assert r.status_code == 422
    r = _post(client, "cards", "card_no,members\nTS-1,2\n")
    assert r.status_code == 400 and "missing columns" in r.json()["detail"]


def test_templates_are_valid_imports(client: TestClient) -> None:
    shops = client.get("/api/admin/templates/shops.csv", headers=ADMIN).text
    cards = client.get("/api/admin/templates/cards.csv", headers=ADMIN).text
    assert _post(client, "shops", shops).status_code == 200
    assert _post(client, "cards", cards).status_code == 200


def test_dealer_shop_switch_changes_status_only_there(client: TestClient) -> None:
    client.post(
        "/api/dealer/status", json={"machine": "down"}, headers={**DEALER, "X-Shop-Code": "201"}
    )
    shops = {s["code"]: s for s in client.get("/api/admin/shops", headers=ADMIN).json()}
    assert shops["201"]["machine"] == "down" and shops["108"]["machine"] == "working"
