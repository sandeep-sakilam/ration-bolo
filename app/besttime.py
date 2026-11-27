"""Best-time advice (F30 default pattern, F33 per-shop hourly profiles).

A deterministic hourly profile per shop and weekday: expected wait for each open hour,
built from served tokens, check-ins, queue reports and public sales over the last 4
weeks (recent weeks weigh more), with a "first week of the month" adjustment. With fewer
than 20 data points the state pack's default pattern is used and advice says "usually"
without a number. Advice = the open hour with the lowest expected wait later today, or
tomorrow when today's hours are over.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clock import ist_today, now_utc, to_ist
from app.models import HourlyProfile, PublicSale, Report, Shop, Token
from app.packs import Pack, get_pack

HISTORY_DAYS = 28
MIN_SAMPLES = 20
REBUILD_AFTER = timedelta(hours=6)


@dataclass
class Advice:
    day: date
    hour: int
    minutes: int
    known: bool  # True when built from this shop's own data

    @property
    def time(self) -> str:
        return f"{self.hour:02d}:00"


@dataclass(frozen=True)
class Sample:
    day: date
    hour: int
    wait: float


def session_starts(shop: Shop) -> tuple[int, ...]:
    return tuple(int(start[:2]) for start, _ in shop.sessions)


def open_hours(shop: Shop) -> list[int]:
    hours: list[int] = []
    for start, end in shop.sessions:
        h0, h1 = int(start[:2]), int(end[:2])
        hours.extend(range(h0, h1))
    return sorted(set(hours))


def first_week_factor(pack: Pack) -> float:
    return float(pack.raw["default_busy_pattern"].get("first_week_factor", 1.0))


def default_wait(pack: Pack, day: date, hour: int) -> int:
    pattern = pack.raw["default_busy_pattern"]
    wait = float(pattern["hours"].get(str(hour), pattern.get("default_wait", 20)))
    if day.day <= 7:
        wait *= first_week_factor(pack)
    return round(wait)


# --- profile building (pure) ----------------------------------------------------------


def build(
    samples: list[Sample], today: date, first_week: float
) -> dict[tuple[int, int], tuple[float, int]]:
    """(weekday, hour) -> (expected wait on an ordinary day, sample count).

    Weight = 1 / (1 + weeks ago); first-week samples are divided by the first-week factor
    so the profile describes an ordinary day (prediction multiplies it back)."""
    acc: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for s in samples:
        age_days = (today - s.day).days
        if age_days < 0 or age_days > HISTORY_DAYS:
            continue
        weight = 1.0 / (1 + age_days // 7)
        wait = s.wait / first_week if s.day.day <= 7 else s.wait
        acc[(s.day.weekday(), s.hour)].append((wait, weight))
    return {
        key: (sum(w * x for x, w in vals) / sum(w for _, w in vals), len(vals))
        for key, vals in acc.items()
    }


# --- samples from the database ------------------------------------------------------------


def collect(db: Session, shop: Shop, now: datetime) -> list[Sample]:
    since = now - timedelta(days=HISTORY_DAYS)
    per_family = 60 / shop.families_per_hour
    out: list[Sample] = []
    for t in db.scalars(
        select(Token).where(
            Token.shop_id == shop.id, Token.status == "served", Token.served_at >= since
        )
    ):
        if t.served_at is None:
            continue
        start = t.arrived_at if t.kind == "booked" and t.arrived_at else t.issued_at
        local = to_ist(t.served_at)
        out.append(
            Sample(local.date(), local.hour, max(0.0, (t.served_at - start).total_seconds() / 60))
        )
    for r in db.scalars(
        select(Report).where(
            Report.shop_id == shop.id, Report.kind == "queue_size", Report.created_at >= since
        )
    ):
        local = to_ist(r.created_at)
        out.append(Sample(local.date(), local.hour, float(r.value or 0) * per_family))
    hourly: dict[tuple[date, int], int] = defaultdict(int)
    for sale in db.scalars(
        select(PublicSale).where(PublicSale.shop_id == shop.id, PublicSale.sale_time >= since)
    ):
        local = to_ist(sale.sale_time)
        hourly[(local.date(), local.hour)] += sale.count
    # A busy public sales hour means people waited: on average half that hour's families
    # were in the line, each taking the shop's service time.
    for (day, hour), count in hourly.items():
        out.append(Sample(day, hour, count / 2 * per_family))
    return out


def rebuild(db: Session, shop: Shop, now: datetime | None = None) -> int:
    now = now or now_utc()
    pack = get_pack(shop.state_pack)
    samples = collect(db, shop, now)
    profile = build(samples, ist_today(now), first_week_factor(pack))
    db.execute(delete(HourlyProfile).where(HourlyProfile.shop_id == shop.id))
    for (weekday, hour), (wait, count) in profile.items():
        db.add(
            HourlyProfile(
                shop_id=shop.id,
                weekday=weekday,
                hour=hour,
                expected_wait_min=round(wait, 1),
                samples=count,
                updated_at=now,
            )
        )
    db.flush()
    return len(samples)


def _profile(db: Session, shop: Shop, now: datetime) -> list[HourlyProfile]:
    rows = list(db.scalars(select(HourlyProfile).where(HourlyProfile.shop_id == shop.id)))
    if not rows or now - min(r.updated_at for r in rows) > REBUILD_AFTER:
        rebuild(db, shop, now)
        rows = list(db.scalars(select(HourlyProfile).where(HourlyProfile.shop_id == shop.id)))
    return rows


def expected_waits(
    db: Session, shop: Shop, day: date, now: datetime | None = None
) -> tuple[dict[int, int], bool]:
    """Expected wait by open hour for a day, and whether it comes from the shop's own data."""
    now = now or now_utc()
    pack = get_pack(shop.state_pack)
    rows = _profile(db, shop, now)
    if sum(r.samples for r in rows) < MIN_SAMPLES:
        return {h: default_wait(pack, day, h) for h in open_hours(shop)}, False
    by_key = {(r.weekday, r.hour): r.expected_wait_min for r in rows}
    factor = first_week_factor(pack) if day.day <= 7 else 1.0
    waits = {}
    for h in open_hours(shop):
        value = by_key.get((day.weekday(), h))
        waits[h] = round(value * factor) if value is not None else default_wait(pack, day, h)
    return waits, True


def best_time(db: Session, shop: Shop, now: datetime | None = None) -> Advice | None:
    now = now or now_utc()
    local = to_ist(now)
    today = ist_today(now)
    for day, earliest in ((today, local.hour + 1), (today + timedelta(days=1), 0)):
        waits, known = expected_waits(db, shop, day, now)
        candidates = {h: w for h, w in waits.items() if h >= earliest}
        if candidates:
            hour = min(candidates, key=lambda h: (candidates[h], h))
            return Advice(day, hour, spoken_minutes(candidates[hour]), known)
    return None


def spoken_minutes(wait: float) -> int:
    """ "Under N minutes": rounded up to the next 5."""
    return max(5, int(math.ceil(max(wait, 1) / 5.0) * 5))


def rebuild_all(db: Session, now: datetime | None = None) -> None:
    for shop in db.scalars(select(Shop)):
        rebuild(db, shop, now)
