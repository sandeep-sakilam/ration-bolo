"""What we know about a shop right now, from every source, with source and age (F30).

At Level 1 and 2 the dealer's status is a source (as built). Level 0 shops have no
dealer source; later features add cardholder reports and public PDS data. When no
source has fresh information the caller hears so instead of a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app import crowd, levels
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
    detail: dict[str, float] = field(default_factory=dict)


@dataclass
class ShopView:
    level: int
    stock: Signal | None = None
    machine: Signal | None = None
    queue_ahead: int | None = None
    queue_source: str | None = None
    minutes_per_family: float | None = None
    disagreements: list[str] = field(default_factory=list)

    def wait_minutes(self, families_per_hour: int) -> int:
        ahead = self.queue_ahead or 0
        per_family = self.minutes_per_family or 60 / families_per_hour
        return round(ahead * per_family)

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
    current = crowd.votes(db, shop, now)
    reported = {sig: crowd.verdict(current, sig) for sig in ("stock", "machine")}
    if level >= 1:
        result.stock = Signal("stock", shop.status_stock, "dealer")
        result.machine = Signal("machine", shop.status_machine, "dealer")
        for sig, dealer_value in (("stock", shop.status_stock), ("machine", shop.status_machine)):
            v = reported[sig]
            if v is not None and v.confirmed and v.value != dealer_value:
                result.disagreements.append(
                    f"Dealer says {sig} is {_WORDS[dealer_value]}; {v.count} cardholder"
                    f"{'s' if v.count != 1 else ''} report {_WORDS[v.value]} in the last "
                    f"{crowd.rounded_minutes(v.oldest_age_min)} minutes"
                )
    else:
        for sig, v in reported.items():
            if v is None:
                continue
            signal = Signal(
                sig,
                v.value,
                "reports",
                round(v.newest_age_min),
                v.count,
                v.confirmed,
                {"oldest": v.oldest_age_min},
            )
            setattr(result, sig, signal)
    ahead = crowd.queue_estimate(current)
    if ahead is not None and level == 0:
        result.queue_ahead, result.queue_source = ahead, "reports"
    return result


_WORDS = {"in_stock": "in stock", "out": "out of stock", "working": "working", "down": "down"}
