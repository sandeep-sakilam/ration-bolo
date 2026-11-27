import pytest
from fastapi.testclient import TestClient

from app import buildinfo


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    buildinfo.commit_sha.cache_clear()


def test_railway_sha_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "ABCDEF1234567890abcdef1234567890abcdef12")
    monkeypatch.setenv("GIT_SHA", "1111111")
    info = buildinfo.build_info("https://github.com/x/y/")
    assert info == {
        "commit": "abcdef1234567890abcdef1234567890abcdef12",
        "short": "abcdef1",
        "url": "https://github.com/x/y/commit/abcdef1234567890abcdef1234567890abcdef12",
    }


def test_build_arg_then_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("GIT_SHA", "1234567abc")
    assert buildinfo.commit_sha() == "1234567abc"
    buildinfo.commit_sha.cache_clear()
    monkeypatch.setenv("GIT_SHA", "not-a-sha")
    sha = buildinfo.commit_sha()
    assert sha == "unknown" or len(sha) == 40  # from `git rev-parse` in a checkout


def test_unknown_without_any_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.setattr(buildinfo, "ROOT", buildinfo.Path("/"))
    assert buildinfo.build_info("https://x") == {
        "commit": "unknown",
        "short": "unknown",
        "url": None,
    }


def test_check14_health_and_status_show_build(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    health = client.get("/health").json()
    assert health["build"]["short"] == "0123456"
    assert health["build"]["url"].endswith("/commit/0123456789abcdef0123456789abcdef01234567")
    assert client.get("/api/status").json()["build"]["short"] == "0123456"
