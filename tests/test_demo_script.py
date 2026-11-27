"""Demo script v2 (F28) covers the FAQ video rules and the live voice interaction."""

from pathlib import Path

TEXT = (Path(__file__).resolve().parent.parent / "docs" / "DEMO_SCRIPT.md").read_text()


def test_demo_script_rules() -> None:
    for must in (
        "YouTube only",
        "3:00",
        "live voice interaction",
        "Unlisted",
        "Reset demo",
        "microphone",
        "system audio",
        "Primary path",
        "Fallback path",
        "Keyless mode",
        "Wispr Flow",
        "build_deck.py --video",
    ):
        assert must in TEXT, must


def test_shot_list_ends_by_three_minutes() -> None:
    ends = [
        line.split("|")[1].strip().split("–")[1]
        for line in TEXT.splitlines()
        if line.startswith("| ") and "–" in line.split("|")[1]
    ]
    minutes = [int(t.split(":")[0]) * 60 + int(t.split(":")[1]) for t in ends]
    assert minutes and max(minutes) <= 180
