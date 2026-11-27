from fastapi.testclient import TestClient


def test_metrics_from_seeded_history(client: TestClient) -> None:
    m = client.get("/api/metrics").json()
    assert m["demo_data"] is True
    assert m["wait"]["served"] > 0
    assert m["wait"]["booked_avg_minutes"] < m["wait"]["walkin_avg_minutes"]
    assert 0 < m["bookings"]["adoption"] <= 1
    assert 0 < m["voice"]["voice_success"] <= 1
    assert "wispr" in m["voice"]["engines"]
    assert m["complaints"]["filed"] >= 2
    assert len(m["daily"]) == 7


def test_metrics_follow_new_activity(client: TestClient) -> None:
    before = client.get("/api/metrics").json()
    sid = client.post("/api/sim/start", json={"caller": "lakshmi"}).json()["session_id"]
    for text in [
        "Avunu",
        "biyyam vachaya",
        "Repu poddhuna book cheyyandi",
        "Avunu",
        "Naaku 15 kilolu ichharu",
        "Avunu",
    ]:
        client.post(f"/api/sim/{sid}/text", json={"text": text, "engine": "browser"})
    after = client.get("/api/metrics").json()
    assert after["bookings"]["made"] == before["bookings"]["made"] + 1
    assert (
        after["bookings"]["status_checks_by_phone"]
        == before["bookings"]["status_checks_by_phone"] + 1
    )
    assert after["voice"]["engines"]["browser"] == before["voice"]["engines"].get("browser", 0) + 6
    assert after["complaints"]["open"] == before["complaints"]["open"] + 1
    assert client.get("/metrics").status_code == 200
