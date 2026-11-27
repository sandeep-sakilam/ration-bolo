import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.packs import PACKS_DIR, PackError, get_pack, load_pack_file, load_packs, validate_pack

SCHEMA = json.loads((PACKS_DIR / "schema.json").read_text())
RAW = json.loads((PACKS_DIR / "telangana.json").read_text())


def test_telangana_loads() -> None:
    pack = get_pack("telangana")
    assert pack.default_language == "te"
    assert pack.entitlement_kg(4) == 24 and pack.entitlement_kg(3) == 18
    assert pack.phrase("confirm_card", "te", last4="0421") == "Card chivari ankelu 0421, sare na?"
    assert pack.phrase("queue", "te", ahead=18, minutes=36).startswith("18 mandi mundu unnaru")


def test_urdu_gets_hindi_replies() -> None:
    pack = get_pack("telangana")
    assert pack.reply_language("ur") == "hi"
    assert pack.reply_language("xx") == "te"
    assert pack.speech_code("ur", "sarvam") == "hi-IN"
    assert "te" in pack.speech_hints("wispr")


def test_numbers_cover_zero_to_hundred() -> None:
    for lang in ("te", "hi", "en"):
        values = set(RAW["numbers"][lang].values())
        assert set(range(101)) <= values, lang


def test_missing_phrase_is_rejected() -> None:
    raw = copy.deepcopy(RAW)
    del raw["phrases"]["queue"]["hi"]
    with pytest.raises(PackError, match="queue"):
        validate_pack(raw, SCHEMA)


def test_schema_violation_is_rejected() -> None:
    raw = copy.deepcopy(RAW)
    raw["fuzzy_threshold"] = "high"
    with pytest.raises(PackError, match="fuzzy_threshold"):
        validate_pack(raw, SCHEMA)


def test_placeholder_mismatch_is_rejected() -> None:
    raw = copy.deepcopy(RAW)
    raw["phrases"]["queue"]["hi"] = "{ahead} log aage hain."
    with pytest.raises(PackError, match="placeholders"):
        validate_pack(raw, SCHEMA)


def test_broken_pack_stops_loading(tmp_path: Path) -> None:
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA))
    (tmp_path / "broken.json").write_text("{not json")
    with pytest.raises(PackError, match="not valid JSON"):
        load_packs(tmp_path)


def test_state_must_match_file_name(tmp_path: Path) -> None:
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA))
    path = tmp_path / "andhra.json"
    path.write_text(json.dumps(RAW))
    with pytest.raises(PackError, match="file name"):
        load_pack_file(path)


def test_packs_endpoint(client: TestClient) -> None:
    data = client.get("/api/packs").json()
    assert data[0]["state"] == "telangana"
    assert {"te", "hi"} <= {lang["code"] for lang in data[0]["languages"]}
