"""Best-time advice (F30 default pattern; F33 adds per-shop hourly profiles).

Deterministic: pick the open hour with the lowest expected wait later today, or
tomorrow if today's hours are over. With too little data the state pack's default
pattern is used and the advice says "usually".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.clock import ist_today, now_utc, to_ist
from app.models import Shop
from app.packs import Pack, get_pack


@dataclass
class Advice:
    day: date
    hour: int
    minutes: int
    known: bool  # True when built from this shop's own data

    @property
    def time(self) -> str:
        return f"{self.hour:02d}:00"


def open_hours(shop: Shop) -> list[int]:
    hours: list[int] = []
    for start, end in shop.sessions:
        h0, h1 = int(start[:2]), int(end[:2])
        hours.extend(range(h0, h1))
    return sorted(set(hours))


def default_wait(pack: Pack, day: date, hour: int) -> int:
    pattern = pack.raw["default_busy_pattern"]
    wait = float(pattern["hours"].get(str(hour), pattern.get("default_wait", 20)))
    if day.day <= 7:
        wait *= float(pattern.get("first_week_factor", 1.0))
    return round(wait)


def expected_waits(db: Session, shop: Shop, day: date) -> tuple[dict[int, int], bool]:
    """Expected wait by open hour for a day, and whether it comes from the shop's own data."""
    pack = get_pack(shop.state_pack)
    return {h: default_wait(pack, day, h) for h in open_hours(shop)}, False


def best_time(db: Session, shop: Shop, now: datetime | None = None) -> Advice | None:
    now = now or now_utc()
    local = to_ist(now)
    today = ist_today(now)
    for day, earliest in ((today, local.hour + 1), (today + timedelta(days=1), 0)):
        waits, known = expected_waits(db, shop, day)
        candidates = {h: w for h, w in waits.items() if h >= earliest}
        if candidates:
            hour = min(candidates, key=lambda h: (candidates[h], h))
            return Advice(day, hour, candidates[hour], known)
    return None
