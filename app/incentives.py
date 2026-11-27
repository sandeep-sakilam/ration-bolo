"""Dealer incentives (F37). The "Fair shop" badge is computed here."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Shop


def fair_shop(db: Session, shop: Shop, now: datetime | None = None) -> bool:
    return False
