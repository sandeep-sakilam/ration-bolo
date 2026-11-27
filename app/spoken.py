"""Natural spoken times for advice (version 3.1, F41).

Advice times (best time, quiet hours, "opens at", "started selling at") are spoken as
part-of-day phrases from the state pack's ``time_phrases``, never as 24-hour clock text:
"saayantram 7 gantala taruvata", "shaam 7 baje ke baad", "after 7 in the evening".
Exact slot and token times ("Repu 10:20 ki, sare na?") are appointments and keep their
format; they never go through this module. Packs without ``time_phrases`` fall back to
English-style 12-hour text ("after 7 pm").
"""

from __future__ import annotations

from typing import Any

from app.packs import Pack

PARTS = (("morning", 5, 12), ("afternoon", 12, 16), ("evening", 16, 20), ("night", 20, 29))

# English-style 12-hour fallback for packs without time_phrases.
FALLBACK = {
    "before": "before {h} {ampm}",
    "after": "after {h} {ampm}",
    "between": "between {h1} {ampm1} and {h2} {ampm2}",
    "at": "at {h}:{mm} {ampm}",
    "at_hour": "at {h} {ampm}",
}


def part_of_day(hour: int) -> str:
    h = hour if hour >= 5 else hour + 24
    for name, start, end in PARTS:
        if start <= h < end:
            return name
    return "night"


def twelve(hour: int) -> int:
    return hour % 12 or 12


def _ampm(hour: int) -> str:
    return "am" if hour % 24 < 12 else "pm"


def _templates(pack: Pack, language: str) -> dict[str, Any] | None:
    phrases = pack.raw.get("time_phrases") or {}
    lang = pack.reply_language(language)
    found = phrases.get(lang) or phrases.get(pack.default_language)
    return dict(found) if found else None


def say(
    pack: Pack, language: str, kind: str, hour: int, minute: int = 0, hour2: int | None = None
) -> str:
    """kind: before | after | between | at | at_hour."""
    t = _templates(pack, language)
    if t is None:
        return FALLBACK[kind].format(
            h=twelve(hour),
            mm=f"{minute:02d}",
            ampm=_ampm(hour),
            h1=twelve(hour),
            ampm1=_ampm(hour),
            h2=twelve(hour2 or hour),
            ampm2=_ampm(hour2 or hour),
        )
    part = t["parts"][part_of_day(hour)]
    words = t.get("hours", {})

    def word(h: int) -> str:
        return str(words.get(str(twelve(h)), twelve(h)))

    return str(t[kind]).format(
        part=part,
        h=word(hour),
        mm=f"{minute:02d}",
        h1=word(hour),
        h2=word(hour2 if hour2 is not None else hour),
    )


def advice_when(pack: Pack, language: str, hour: int, session_starts: list[int]) -> str:
    """An advice hour as speech: "before 9 in the morning" when it is a session's first
    hour (go early), otherwise "after 7 in the evening"."""
    if hour in session_starts:
        return say(pack, language, "before", hour + 1)
    return say(pack, language, "after", hour)
