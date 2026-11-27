"""State packs: one JSON file per state in packs/, validated at startup.

Adding a state means adding a file, not changing code.
"""

from __future__ import annotations

import copy
import json
import string
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

PACKS_DIR = Path(__file__).resolve().parent.parent / "packs"

# Every reply language must have every one of these phrases.
REQUIRED_PHRASES = [
    "greeting",
    "status_stock_out",
    "status_machine_down",
    "confirm_card",
    "which_card",
    "how_help",
    "anything_else",
    "ask_card_digits",
    "read_back_digits",
    "card_not_found",
    "card_linked",
    "stock_yes",
    "stock_no",
    "queue",
    "queue_empty",
    "quietest",
    "ask_book_when",
    "book_offer",
    "booked",
    "booking_refused_month",
    "booking_paused",
    "no_slots",
    "ask_other",
    "ask_kg",
    "complaint_readback",
    "complaint_filed",
    "complaint_none",
    "sorry",
    "menu",
    "menu_text",
    "silence",
    "goodbye",
    "language_switched",
    "reminder",
    "sms_booking",
    "summary",
    "dealer_updated",
    "code_sent",
    "code_ok",
    "code_wrong",
    "sms_code",
]
REQUIRED_DISPLAY = ["today", "tomorrow", "morning", "evening"]

# Version 3 fields: optional, so older packs (e.g. the Tamil Nadu draft) keep loading.
# Missing ones fall back to these safe defaults and are listed on the status page.
V3_DEFAULTS: dict[str, Any] = {
    "default_busy_pattern": {
        "hours": {"8": 45, "9": 50, "10": 40, "11": 30, "16": 20, "17": 25, "18": 30, "19": 20},
        "first_week_factor": 1.4,
        "default_wait": 30,
    },
    "portability": True,
    "public_pds": {"enabled": False, "url_template": "", "format": "csv"},
    "grievance": {
        "helpline_number": "",
        "district_officer": "",
        "state_portal": "",
        "national_portal": "https://pgportal.gov.in",
    },
}
# Version 3 phrases: English fallback when a pack has no text for them yet.
V3_PHRASES: dict[str, str] = {
    "no_booking_level0": "This shop doesn't take bookings yet.",
    "best_time_usual": "{day} {when} is usually quietest.",
    "best_time_known": "{day} {when} is usually under {minutes} minutes.",
    "no_recent_reports": "No recent reports for your shop.",
    "level_dropped_booking": (
        "The shop no longer confirms bookings; your {time} time is still a quiet time to go."
    ),
    "ask_at_shop": "Are you at the shop?",
    "report_only_at_shop": "Please report only when you are at the shop. Thank you.",
    "report_readback": "You are reporting: {items}. Right?",
    "report_saved": "Thank you, your report is saved.",
    "report_part_stock_in": "rice has arrived",
    "report_part_stock_out": "no rice",
    "report_part_machine_down": "the machine is down",
    "report_part_machine_ok": "the machine is working",
    "report_part_queue": "{count} people are there",
    "status_from_reports": "{what}, confirmed by {count} people in the last {minutes} minutes.",
    "status_one_report": "{what}: one person reported it {minutes} minutes ago.",
    "queue_reported": (
        "By cardholders' reports about {ahead} people are there, about {minutes} minutes."
    ),
    "public_started": "Public sales data shows the shop started selling {when}.",
    "public_stopped": (
        "Public sales data shows no sales for {minutes} minutes; the shop may have stopped."
    ),
    "nearby_offer": (
        "Shop {code}, {landmark}, {km} km away, has rice and about {minutes} minutes' wait, "
        "and your card usually works there too; want to go there?"
    ),
    "nearby_offer_plain": (
        "Shop {code}, {landmark}, {km} km away, about {minutes} minutes' wait, "
        "and your card usually works there too; want to go there?"
    ),
    "status_from_reports_earlier": ("{what}, confirmed by {count} people {when}."),
    "status_one_report_earlier": ("{what}: one person reported it {when}."),
    "nearby_offer_closed": (
        "Shop {code}, {landmark}, {km} km; closed now, opens {opens},"
        " usually about {minutes} minutes' wait then; want to go there?"
    ),
    "nearby_offer_closed_stock": (
        "Shop {code}, {landmark}, {km} km; it had rice {when}, closed now,"
        " opens {opens}, usually about {minutes} minutes' wait then; want to go there?"
    ),
    "nearby_closed_when": ("It opens {opens}, usually about {minutes} minutes' wait then."),
    "nearby_go_now": "You can go now; about {minutes} minutes' wait there.",
    "nearby_accepted": "Okay, Shop {code}.",
    "grievance_sent": ("We sent the complaint text by {via} to file with the officials."),
    "helpline_offer": ("Shall I connect you to the state food helpline now?"),
    "helpline_connecting": (
        "Connecting you to the helpline. Your complaint number is {complaint_no}."
    ),
    "ask_reference": ("Please say the reference number you were given."),
    "reference_readback": ("Reference number {ref}, right?"),
    "reference_saved": ("Saved the reference number with complaint {complaint_no}."),
    "no_open_complaint": ("Your card has no open complaint."),
    "grievance_formal": (
        "Complaint {complaint_no}: at Fair Price Shop {shop} ({area}) on {date}, card ending "
        "{last4} received {kg} kg against {due} kg due. Under the National Food Security Act, "
        "2013 (Sections 14 and 15: grievance redressal), please inquire and ensure the full "
        "entitlement."
    ),
    "grievance_steps": (
        "To file it: {state_portal} or {national_portal}. Quote complaint {complaint_no}."
    ),
    "escalate_district": (
        "Ration Bolo: complaint {complaint_no} is not resolved after 7 days. Escalate it to the "
        "District Grievance Redressal Officer: {district}. Call us and say the reference number "
        "they give you."
    ),
    "escalate_national": (
        "Ration Bolo: complaint {complaint_no} is still open after 21 days. File it on the "
        "national public grievance portal {national_portal} with the text below."
    ),
    "district_unknown": ("your District Supply Officer's office"),
    "dealer_menu": (
        "Dealer menu: press 1 or say 'stock arrived', 2 'stock finished', "
        "3 'machine down', 4 'machine working'."
    ),
    "dealer_again": ("Say or press another update, or hang up."),
    "optin_saved": ("Okay, we will tell you when rice arrives at your shop."),
    "optout_saved": ("Okay, we will stop rice arrival messages."),
    "broadcast_rice_arrived": ("Ration Bolo: rice has arrived at your shop {shop}."),
    "fair_shop_note": ("It has the 'Fair shop' badge."),
    "public_not_started": ("Public sales data shows no sales yet today."),
    "public_closed": ("{total} sales today; the shop is closed now and opens {opens}."),
    "best_time_part_busy": ("{day} {part} is busy; {when} is usually under {minutes} minutes."),
    "best_time_part_busy_usual": ("{day} {part} is usually busy; {when} is usually quieter."),
    "booking_paused_machine": (
        "The machine is down, so booking is paused. You can still come and join the line."
    ),
    "booking_paused_stock": (
        "Rice has run out, so booking is paused. You can still come and join the line."
    ),
    "checkin_saved": "Noted that you are at the shop. {count} people checked in in the last hour.",
}
V3_INTENTS = [
    "grievance_ref",
    "report_stock_in",
    "report_stock_out",
    "report_machine_down",
    "report_queue",
    "checkin",
    "broadcast_optin",
    "broadcast_optout",
    "nearby_yes",
]


class PackError(RuntimeError):
    """A state pack is missing, malformed or incomplete. Stops startup."""


@dataclass
class Pack:
    raw: dict[str, Any]
    languages: dict[str, dict[str, str]] = field(init=False)

    missing_v3: list[str] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.languages = {lang["code"]: lang for lang in self.raw["languages"]}
        for key, default in V3_DEFAULTS.items():
            if key not in self.raw:
                self.raw[key] = copy.deepcopy(default)
                self.missing_v3.append(key)
        for key in V3_PHRASES:
            if key not in self.raw["phrases"]:
                self.missing_v3.append(f"phrases.{key}")
        if "time_phrases" not in self.raw:
            self.missing_v3.append("time_phrases")
        for intent in V3_INTENTS:
            if intent not in self.raw["intents"]:
                self.raw["intents"][intent] = {}
                self.missing_v3.append(f"intents.{intent}")

    @property
    def state(self) -> str:
        return str(self.raw["state"])

    @property
    def name(self) -> str:
        return str(self.raw["name"])

    @property
    def is_draft(self) -> bool:
        return self.raw["status"] == "draft"

    @property
    def default_language(self) -> str:
        return str(self.raw["default_language"])

    @property
    def fuzzy_threshold(self) -> float:
        return float(self.raw["fuzzy_threshold"])

    def kg_per_person(self, commodity: str = "rice") -> float:
        return float(self.raw["kg_per_person"][commodity])

    def entitlement_kg(self, members: int, commodity: str = "rice") -> int:
        return round(members * self.kg_per_person(commodity))

    def reply_language(self, language: str) -> str:
        """Language replies are spoken in (Urdu speakers get Hindi replies)."""
        if language in self.raw["reply_languages"]:
            return language
        lang = self.languages.get(language)
        if lang and lang["reply_language"] in self.raw["reply_languages"]:
            return lang["reply_language"]
        return self.default_language

    def speech_code(self, language: str, engine: str) -> str:
        lang = self.languages.get(language) or self.languages[self.default_language]
        return lang[engine]

    def speech_hints(self, engine: str) -> list[str]:
        return [lang[engine] for lang in self.raw["languages"]]

    def phrase(self, key: str, language: str, **values: object) -> str:
        texts = self.raw["phrases"].get(key) or {self.default_language: V3_PHRASES[key]}
        lang = self.reply_language(language)
        template = texts.get(lang) or texts[self.default_language]
        return template.format(**values)

    def display(self, key: str, language: str) -> str:
        texts = self.raw["display"][key]
        return str(texts.get(self.reply_language(language)) or texts[self.default_language])

    def twilio_voice(self, language: str) -> dict[str, str] | None:
        voices = self.raw.get("twilio_voices") or {}
        voice = voices.get(self.reply_language(language))
        return dict(voice) if voice else None


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def validate_pack(raw: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        jsonschema.validate(raw, schema)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        raise PackError(
            f"pack '{raw.get('state', '?')}' is invalid at {where}: {exc.message}"
        ) from exc
    codes = {lang["code"] for lang in raw["languages"]}
    name = raw["state"]
    if raw["default_language"] not in raw["reply_languages"]:
        raise PackError(f"pack '{name}': default_language must be a reply language")
    for lang in raw["reply_languages"]:
        if lang not in codes:
            raise PackError(f"pack '{name}': reply language '{lang}' is not in languages")
    for key in REQUIRED_PHRASES:
        texts = raw["phrases"].get(key)
        if texts is None:
            raise PackError(f"pack '{name}': phrase '{key}' is missing")
        missing = [lang for lang in raw["reply_languages"] if lang not in texts]
        if missing:
            raise PackError(f"pack '{name}': phrase '{key}' has no text for {missing}")
        names = {lang: _placeholders(text) for lang, text in texts.items()}
        if len({frozenset(v) for v in names.values()}) > 1:
            raise PackError(f"pack '{name}': phrase '{key}' placeholders differ: {names}")
    for key in REQUIRED_DISPLAY:
        if key not in raw["display"]:
            raise PackError(f"pack '{name}': display word '{key}' is missing")


def load_pack_file(path: Path, schema: dict[str, Any] | None = None) -> Pack:
    schema = schema or load_schema(path.parent)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackError(f"{path.name} is not valid JSON: {exc}") from exc
    validate_pack(raw, schema)
    if raw["state"] != path.stem:
        raise PackError(f"{path.name}: 'state' must match the file name ('{path.stem}')")
    return Pack(raw)


def load_schema(directory: Path = PACKS_DIR) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((directory / "schema.json").read_text(encoding="utf-8"))
    return data


def load_packs(directory: Path = PACKS_DIR) -> dict[str, Pack]:
    schema = load_schema(directory)
    packs = {
        p.stem: load_pack_file(p, schema)
        for p in sorted(directory.glob("*.json"))
        if p.name != "schema.json"
    }
    if not packs:
        raise PackError(f"no state packs found in {directory}")
    return packs


@lru_cache
def all_packs() -> dict[str, Pack]:
    return load_packs()


def get_pack(state: str) -> Pack:
    packs = all_packs()
    if state not in packs:
        raise PackError(f"unknown state pack '{state}'")
    return packs[state]
