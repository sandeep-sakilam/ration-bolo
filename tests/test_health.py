from fastapi.testclient import TestClient

from app.main import create_app


def test_health() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_redirects_to_simulator() -> None:
    client = TestClient(create_app())
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/simulator"
    page = client.get("/simulator")
    assert page.status_code == 200
    assert "call simulator" in page.text.lower()
