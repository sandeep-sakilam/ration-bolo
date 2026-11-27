"""Nearby-shop portability (F34, One Nation One Ration Card).

NFSA cardholders can usually collect their entitlement at another ePoS-enabled shop.
When the caller's shop is out of stock, has its machine down, has a predicted wait over
45 minutes, or has 3+ upheld short-ration complaints in 30 days, up to two nearby shops
(within 3 km, accepting portability) are suggested, ranked by: confirmed in stock and
working, then predicted wait, then distance. Suggestions say "usually"; they never
promise the other shop will serve the caller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import besttime, levels, queue, shopstate
from app.clock import ist_today, now_utc, to_ist
from app.models import Complaint, Shop
from app.packs import get_pack

RADIUS_KM = 3.0
WAIT_TRIGGER_MIN = 45
COMPLAINTS_TRIGGER = 3
MAX_SUGGESTIONS = 2


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Candidate:
    shop: Shop
    km: float
    wait: int
    confirmed_ok: bool
    level: int
    landmark: str


def predicted_wait(db: Session, shop: Shop, now: datetime | None = None) -> int:
    """Minutes: tokens at Level 1/2; reports and public sales at Level 0; else the
    shop's usual wait for this hour."""
    now = now or now_utc()
    view = shopstate.view(db, shop, now)
    if view.level >= 1:
        return queue.people_ahead_now(db, shop).minutes
    if view.queue_ahead is not None:
        return view.wait_minutes(shop.families_per_hour)
    waits, _ = besttime.expected_waits(db, shop, ist_today(now), now)
    hour = to_ist(now).hour
    if hour in waits:
        return waits[hour]
    return min(waits.values()) if waits else 0


def status_ok(db: Session, shop: Shop, now: datetime | None = None) -> tuple[bool, bool]:
    """(confirmed in stock and working, known to be out or down)."""
    view = shopstate.view(db, shop, now)
    stock_in = view.stock is not None and view.stock.confirmed and view.stock.value == "in_stock"
    bad = view.stock_out or view.machine_down
    return stock_in and not bad, bad


def upheld_complaints(db: Session, shop: Shop, now: datetime | None = None) -> int:
    """Short-ration complaints in the last 30 days that were resolved in the caller's
    favour (an outcome was recorded). Open ones don't count until upheld."""
    now = now or now_utc()
    return (
        db.scalar(
            select(func.count())
            .select_from(Complaint)
            .where(
                Complaint.shop_id == shop.id,
                Complaint.status == "resolved",
                Complaint.created_at >= now - timedelta(days=30),
                ~func.lower(func.coalesce(Complaint.outcome, "")).startswith("not upheld"),
            )
        )
        or 0
    )


def needs_alternative(db: Session, shop: Shop, now: datetime | None = None) -> bool:
    _, bad = status_ok(db, shop, now)
    if bad:
        return True
    if predicted_wait(db, shop, now) > WAIT_TRIGGER_MIN:
        return True
    return upheld_complaints(db, shop, now) >= COMPLAINTS_TRIGGER


def candidates(db: Session, shop: Shop, now: datetime | None = None) -> list[Candidate]:
    origin = levels.profile(db, shop)
    if origin.lat is None or origin.lon is None:
        return []
    if not get_pack(shop.state_pack).raw.get("portability", True):
        return []
    found: list[Candidate] = []
    for other in db.scalars(select(Shop).where(Shop.id != shop.id)):
        prof = levels.profile(db, other)
        if prof.lat is None or prof.lon is None or not prof.portability:
            continue
        km = haversine_km(origin.lat, origin.lon, prof.lat, prof.lon)
        if km > RADIUS_KM:
            continue
        ok, bad = status_ok(db, other, now)
        if bad:
            continue
        found.append(
            Candidate(
                other,
                km,
                predicted_wait(db, other, now),
                ok,
                levels.effective_level(db, other, now),
                prof.landmark,
            )
        )
    found.sort(key=lambda c: (not c.confirmed_ok, c.wait, c.km))
    return found[:MAX_SUGGESTIONS]
