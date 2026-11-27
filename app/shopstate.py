"""What we know about a shop right now, from every source, with source and age (F30).

At Level 1 and 2 the dealer's status is a source (as built). Level 0 shops have no
dealer source; later features add cardholder reports and public PDS data. When no
source has fresh information the caller hears so instead of a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app import levels
from app.clock import now_utc
from app.models import Shop


@dataclass
class Signal:
    kind: str  # stock | machine
    value: str  # in_stock | out | working | down
    source: str  # dealer | reports | public_pds | volunteer
    age_minutes: int | None = None
    count: int = 1
    confirmed: bool = True
    detail: dict[str, object] = field(default_factory=dict)


@dataclass
class ShopView:
    level: int
    stock: Signal | None = None
    machine: Signal | None = None
    queue_ahead: int | None = None
    queue_source: str | None = None
    disagreements: list[str] = field(default_factory=list)

    @property
    def stock_out(self) -> bool:
        return self.stock is not None and self.stock.confirmed and self.stock.value == "out"

    @property
    def machine_down(self) -> bool:
        return self.machine is not None and self.machine.confirmed and self.machine.value == "down"


def view(db: Session, shop: Shop, now: datetime | None = None) -> ShopView:
    now = now or now_utc()
    level = levels.effective_level(db, shop, now)
    result = ShopView(level=level)
    if level >= 1:
        result.stock = Signal("stock", shop.status_stock, "dealer")
        result.machine = Signal("machine", shop.status_machine, "dealer")
    return result
