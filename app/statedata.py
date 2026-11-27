"""State government data (ePoS feed, card database).

Production needs an agreement with each state's Civil Supplies Department. Until
then the mock adapter is fed by the dealer dashboard: stock and machine status are
what the dealer sets, and sales are the simulated ePoS sales from "Serve next".
"""

from __future__ import annotations

from typing import Protocol

from app.models import Shop


class StateData(Protocol):
    name: str

    def shop_status(self, shop: Shop) -> tuple[str, str]: ...


class DealerFedStateData:
    name = "mock"

    def shop_status(self, shop: Shop) -> tuple[str, str]:
        return shop.status_stock, shop.status_machine
