from fastapi.testclient import TestClient


def test_simulator_conversation(client: TestClient) -> None:
    r = client.post("/api/sim/start", json={"caller": "lakshmi"}).json()
    sid = r["session_id"]
    assert r["text"].endswith("Card chivari ankelu 0421, sare na?")
    assert r["browser_lang"] == "te-IN" and r["audio_url"] is None and r["expect"] == "yes_no"
    r = client.post(f"/api/sim/{sid}/text", json={"text": "Avunu", "engine": "browser"}).json()
    assert r["text"] == "Meeku ela sahayam cheyali?"
    r = client.post(f"/api/sim/{sid}/text", json={"text": "Repu poddhuna book cheyyandi"}).json()
    assert r["text"] == "Repu 10:20 ki, sare na?"
    r = client.post(f"/api/sim/{sid}/digit", json={"key": "1"}).json()
    assert r["actions"][0]["type"] == "booking_created"
    r = client.post(f"/api/sim/{sid}/silence").json()
    r = client.post(f"/api/sim/{sid}/end").json()
    assert r["ended"] is True


def test_simulator_whatsapp_mode(client: TestClient) -> None:
    r = client.post("/api/sim/start", json={"caller": "salma", "mode": "whatsapp"}).json()
    assert r["channel"] == "whatsapp"


def test_simulator_audio_without_keys_fails_softly(client: TestClient) -> None:
    sid = client.post("/api/sim/start", json={"caller": "lakshmi"}).json()["session_id"]
    files = {"file": ("a.webm", b"MOCKTEXT:avunu", "audio/webm")}
    r = client.post(f"/api/sim/{sid}/audio", files=files).json()
    assert r["heard"]["engine"] == "none" and r["text"].startswith("Kshaminchandi")


def test_simulator_rejects_bad_input(client: TestClient) -> None:
    assert client.post("/api/sim/start", json={"caller": "nobody"}).status_code == 400
    assert client.post("/api/sim/start", json={"state": "atlantis"}).status_code == 400
    assert client.post("/api/sim/99999/text", json={"text": "hi"}).status_code == 404
    callers = client.get("/api/sim/callers").json()
    assert {c["id"] for c in callers} == {"lakshmi", "salma", "family", "unknown"}
