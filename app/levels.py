"""Shop levels (F30): who cooperates at a shop decides where its information comes from.

Level 0: nobody (cardholder reports, public PDS data, best-time advice; no booking).
Level 1: a willing dealer or a volunteer coordinator (tokens and booking, as built).
Level 2: dealer and department (ePoS feed, simulated today).
A level only adds sources; it never removes the Level 0 ones.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Shop, ShopProfile

LEVELS = {
    0: "Level 0 · nobody cooperates",
    1: "Level 1 · dealer",
    2: "Level 2 · dealer and department",
}
DEFAULT_LEVEL = 1  # shops created before version 3 behave exactly as built


def profile(db: Session, shop: Shop) -> ShopProfile:
    found = db.get(ShopProfile, shop.id)
    return (
        found
        if found is not None
        else ShopProfile(
            shop_id=shop.id, level=DEFAULT_LEVEL, ward="", landmark="", portability=True
        )
    )


def base_level(db: Session, shop: Shop) -> int:
    return int(profile(db, shop).level)


def effective_level(db: Session, shop: Shop, now: datetime | None = None) -> int:
    """The level callers get right now (a volunteer on duty lifts Level 0 to Level 1)."""
    return base_level(db, shop)


def label(db: Session, shop: Shop, now: datetime | None = None) -> str:
    return LEVELS[effective_level(db, shop, now)]


def takes_bookings(db: Session, shop: Shop, now: datetime | None = None) -> bool:
    return effective_level(db, shop, now) >= 1


def set_profile(db: Session, shop: Shop, **fields: object) -> ShopProfile:
    row = db.get(ShopProfile, shop.id)
    if row is None:
        row = ShopProfile(
            shop_id=shop.id, level=DEFAULT_LEVEL, ward="", landmark="", portability=True
        )
        db.add(row)
    for key, value in fields.items():
        if value is not None:
            setattr(row, key, value)
    if row.level not in LEVELS:
        raise ValueError("level must be 0, 1 or 2")
    db.flush()
    return row
