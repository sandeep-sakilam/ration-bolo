"""Speech understanding: deterministic keyword and fuzzy matching. No AI makes decisions.

Takes the text a speech engine heard and returns intents and entities using only
the state pack's word lists, matched across all of the pack's languages, so mixed
speech ("Kal ka slot book cheyyandi") works.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from rapidfuzz import fuzz

from app.packs import Pack

CUSTOMER_INTENTS = ("stock", "queue", "book", "complaint", "end")
DEALER_INTENTS = ("dealer_stock_out", "dealer_stock_in", "dealer_machine_down", "dealer_machine_up")
EXACT_MAX_LEN = 4  # words this short must match exactly ("kal" is not "kam")


@dataclass
class Understanding:
    text: str
    tokens: list[str]
    intent: str | None = None
    scores: dict[str, int] = field(default_factory=dict)
    yes: bool = False
    no: bool = False
    numbers: list[int] = field(default_factory=list)
    digits: str = ""
    kilos: int | None = None
    day: str | None = None
    session: str | None = None
    switch_to: str | None = None
    language: str | None = None

    @property
    def empty(self) -> bool:
        return not self.tokens

    @property
    def understood(self) -> bool:
        return bool(
            self.intent or self.yes or self.no or self.numbers or self.day or self.session
            or self.switch_to
        )  # fmt: skip


def normalise(text: str) -> list[str]:
    """Lowercase; keep letters, combining marks and digits; split digits from letters."""
    out: list[str] = []
    prev = ""
    for ch in text.lower():
        cat = unicodedata.category(ch)
        if cat[0] in "LM" or ch.isdigit():
            kind = "d" if ch.isdigit() else "a"
            if prev and kind != prev:
                out.append(" ")
            out.append(ch)
            prev = kind
        else:
            out.append(" ")
            prev = ""
    return "".join(out).split()


def script_language(text: str) -> str | None:
    """Telugu or Devanagari script gives the language away."""
    for ch in text:
        if "ఀ" <= ch <= "౿":
            return "te"
        if "ऀ" <= ch <= "ॿ":
            return "hi"
    return None


@lru_cache(maxsize=4096)
def _similar(a: str, b: str, threshold: float) -> bool:
    if a == b:
        return True
    if len(a) <= EXACT_MAX_LEN or len(b) <= EXACT_MAX_LEN:
        return False
    return fuzz.ratio(a, b) >= threshold


def find_phrase(tokens: list[str], phrase: str, threshold: float) -> int:
    """Index where ``phrase`` (one or more words) starts in ``tokens``, or -1."""
    words = normalise(phrase)
    n = len(words)
    if n == 0 or n > len(tokens):
        return -1
    for i in range(len(tokens) - n + 1):
        window = tokens[i : i + n]
        if all(_similar(t, w, threshold) for t, w in zip(window, words, strict=True)):
            return i
        if n > 1 and _similar(" ".join(window), " ".join(words), threshold):
            return i
    return -1


def _match_lists(
    tokens: list[str], lists: dict[str, list[str]], threshold: float, langs: Counter[str]
) -> int:
    """Number of distinct words from per-language lists found in ``tokens``."""
    hits: set[str] = set()
    for lang, words in lists.items():
        for word in words:
            if word not in hits and find_phrase(tokens, word, threshold) >= 0:
                hits.add(word)
                langs[lang] += 1
    return len(hits)


def _number_table(pack: Pack) -> dict[tuple[str, ...], int]:
    table: dict[tuple[str, ...], int] = {}
    for words in pack.raw["numbers"].values():
        for word, value in words.items():
            table[tuple(normalise(word))] = int(value)
    return table


_TABLES: dict[int, dict[tuple[str, ...], int]] = {}


def parse_numbers(tokens: list[str], pack: Pack) -> list[tuple[int, int, int, str]]:
    """(start, end, value, digit-string) for each number, longest match first."""
    table = _TABLES.setdefault(id(pack), _number_table(pack))
    found: list[tuple[int, int, int, str]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.isdigit():
            found.append((i, i + 1, int(tok), tok))
            i += 1
            continue
        for size in (3, 2, 1):
            key = tuple(tokens[i : i + size])
            if len(key) == size and key in table:
                value = table[key]
                found.append((i, i + size, value, str(value)))
                i += size
                break
        else:
            i += 1
    return found


def understand(text: str, pack: Pack) -> Understanding:
    tokens = normalise(text)
    result = Understanding(text=text, tokens=tokens)
    if not tokens:
        return result
    t = pack.fuzzy_threshold
    langs: Counter[str] = Counter()

    numbers = parse_numbers(tokens, pack)
    result.numbers = [n[2] for n in numbers]
    result.digits = "".join(n[3] for n in numbers)
    units = pack.raw["units"]["kg"]
    unit_at = {i for i, tok in enumerate(tokens) if any(_similar(tok, u, t) for u in units)}
    for start, end, value, _ in numbers:
        if end in unit_at or (start - 1) in unit_at:
            result.kilos = value
            break

    for intent in CUSTOMER_INTENTS:
        score = _match_lists(tokens, pack.raw["intents"][intent], t, langs)
        if intent == "complaint" and result.kilos is not None:
            score += 2  # "any number of kilos" means a complaint
        if score:
            result.scores[intent] = score
    if result.scores:
        priority = pack.raw["intent_priority"]
        result.intent = max(
            result.scores,
            key=lambda k: (result.scores[k], -priority.index(k) if k in priority else -99),
        )

    result.yes = _match_lists(tokens, pack.raw["yes"], t, langs) > 0
    result.no = _match_lists(tokens, pack.raw["no"], t, langs) > 0
    for day, lists in pack.raw["day_words"].items():
        if _match_lists(tokens, lists, t, langs):
            result.day = day
    for session, lists in pack.raw["session_words"].items():
        if _match_lists(tokens, lists, t, langs):
            result.session = session
    for target, phrases in pack.raw["switch_phrases"].items():
        if any(find_phrase(tokens, p, t) >= 0 for p in phrases):
            result.switch_to = target
            break
    result.language = script_language(text) or (langs.most_common(1)[0][0] if langs else None)
    return result


def dealer_intent(text: str, pack: Pack) -> str | None:
    """Dealer status updates by voice ("Biyyam aipoyindi", "Machine down")."""
    tokens = normalise(text)
    best: tuple[int, str] | None = None
    for intent in DEALER_INTENTS:
        lists = pack.raw["intents"].get(intent, {})
        longest = 0
        for words in lists.values():
            for phrase in words:
                if find_phrase(tokens, phrase, pack.fuzzy_threshold) >= 0:
                    longest = max(longest, len(normalise(phrase)))
        if longest and (best is None or longest > best[0]):
            best = (longest, intent)
    return best[1] if best else None
