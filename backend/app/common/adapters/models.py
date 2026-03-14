from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(slots=True, frozen=True)
class AccountPosition:
    symbol: str
    quantity: Decimal
    market_value: Decimal | None = None
    cost_basis: Decimal | None = None
    average_entry_price: Decimal | None = None
    side: str = "long"
    asset_class: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class AccountState:
    venue: str
    asset_class: str
    mode: str
    account_id: str
    currency: str
    equity: Decimal
    cash: Decimal
    buying_power: Decimal | None
    positions: tuple[AccountPosition, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OhlcvBar:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    vwap: Decimal | None = None
    trade_count: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OrderRequest:
    symbol: str
    side: str
    order_type: str
    quantity: Decimal | None = None
    notional: Decimal | None = None
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: str = "day"
    client_order_id: str | None = None


@dataclass(slots=True, frozen=True)
class OrderResult:
    venue: str
    asset_class: str
    order_id: str
    status: str
    client_order_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
