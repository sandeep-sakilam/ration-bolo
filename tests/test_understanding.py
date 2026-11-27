import pytest

from app.packs import get_pack
from app.understanding import dealer_intent, normalise, understand

PACK = get_pack("telangana")


def u(text: str):  # type: ignore[no-untyped-def]
    return understand(text, PACK)


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Maa shop ki biyyam vachaya?", "stock"),
        ("Mera ration aaya kya?", "stock"),
        ("Ippudu entha mandi unnaru?", "queue"),
        ("Kitne log hain?", "queue"),
        ("Repu poddhuna book cheyyandi.", "book"),
        ("Kal subah book karo", "book"),
        ("Kal ka slot book cheyyandi", "book"),
        ("Naaku 15 kilolu ichharu", "complaint"),
        ("Mujhe kam mila", "complaint"),
        ("Mera ration kam mila", "complaint"),
        ("biyam vachaya", "stock"),  # fuzzy
        ("బియ్యం వచ్చాయా", "stock"),  # Telugu script
        ("चावल आया क्या", "stock"),  # Devanagari
        ("Has rice come?", "stock"),
        ("Book a slot for tomorrow morning", "book"),
        ("bas, dhanyavaad", "end"),
    ],
)
def test_intents(text: str, intent: str) -> None:
    assert u(text).intent == intent


def test_short_words_need_exact_match() -> None:
    assert u("kam").intent == "complaint"
    assert u("kal").intent == "book"
    assert u("kaam").intent is None


def test_unknown_text() -> None:
    result = u("the weather is nice")
    assert result.intent is None and not result.understood
    assert u("").empty


def test_kilos() -> None:
    assert u("Naaku 15 kilolu ichharu").kilos == 15
    assert u("padihenu kilolu").kilos == 15
    assert u("iravai naalugu kilolu").kilos == 24
    assert u("mujhe pandrah kilo mila").kilos == 15
    assert u("15kg").kilos == 15
    assert u("24 kilolu").kilos == 24
    assert u("Repu book").kilos is None


def test_card_digits() -> None:
    assert u("sunna naalugu rendu okati").digits == "0421"
    assert u("1 0 8 0 4 2 1").digits == "1080421"
    assert u("one zero eight zero four two one").digits == "1080421"
    assert u("TS 108 0421").digits == "1080421"
    assert u("ek shunya aath shunya chaar do ek").digits == "1080421"


def test_yes_no() -> None:
    assert u("Avunu").yes and not u("Avunu").no
    assert u("haan ji").yes
    assert u("hau").yes
    assert u("Kaadu").no and u("nahi").no and u("No").no
    assert not u("biyyam").yes


def test_day_and_session() -> None:
    r = u("Repu poddhuna book cheyyandi")
    assert (r.day, r.session) == ("tomorrow", "morning")
    r = u("aaj shaam")
    assert (r.day, r.session) == ("today", "evening")
    assert u("ivala saayantram").session == "evening"


def test_language_switch() -> None:
    assert u("Hindi lo cheppandi").switch_to == "hi"
    assert u("Telugu mein bolo").switch_to == "te"
    assert u("biyyam vachaya").switch_to is None


def test_language_detection() -> None:
    assert u("Kitne log hain").language == "hi"
    assert u("Ippudu entha mandi unnaru").language == "te"
    assert u("బియ్యం").language == "te"


def test_normalise_splits_digits() -> None:
    assert normalise("15kg, ok!") == ["15", "kg", "ok"]
    assert normalise("బియ్యం?") == ["బియ్యం"]


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Biyyam aipoyindi", "dealer_stock_out"),
        ("Chawal khatam", "dealer_stock_out"),
        ("Machine down", "dealer_machine_down"),
        ("Biyyam vachindi", "dealer_stock_in"),
        ("Machine working", "dealer_machine_up"),
        ("hello", None),
    ],
)
def test_dealer_intents(text: str, intent: str | None) -> None:
    assert dealer_intent(text, PACK) == intent
