from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.app.common.adapters.errors import AdapterAuthenticationError, AdapterParseError
from backend.app.common.adapters.http import JsonApiClient
from backend.app.common.adapters.models import AccountPosition, AccountState, OpenOrder, OrderRequest, OrderResult
from backend.app.common.adapters.utils import parse_datetime, parse_decimal, parse_optional_decimal

logger = logging.getLogger(__name__)


def parse_optional_datetime(value: Any):
    if value in (None, ""):
        return None
    try:
        return parse_datetime(value, field_name="submitted_at")
    except AdapterParseError:
        return None


class AlpacaPaperTradingAdapterBase:
    venue = "alpaca"
    mode = "paper"
    asset_class = "unknown"

    def __init__(
        self,
        *,
        api_key: str | None,
        api_secret: str | None,
        base_url: str,
        label: str,
        transport: httpx.BaseTransport | None = None,
        account_currency: str = "USD",
    ) -> None:
        if not api_key or not api_secret:
            raise AdapterAuthenticationError(f"{label} credentials are not configured")

        self._account_currency = account_currency
        self._client = JsonApiClient(
            base_url=base_url,
            label=label,
            default_headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
            },
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def get_account_state(self) -> AccountState:
        account_payload = self._client.request_json("GET", "/v2/account")
        positions_payload = self._client.request_json("GET", "/v2/positions")
        if not isinstance(positions_payload, list):
            raise AdapterParseError("Alpaca positions payload must be a list")

        positions = tuple(self._parse_position(item) for item in positions_payload)
        account_id = str(account_payload.get("id") or "alpaca-paper")
        return AccountState(
            venue=self.venue,
            asset_class=self.asset_class,
            mode=self.mode,
            account_id=account_id,
            currency=self._account_currency,
            equity=parse_decimal(account_payload.get("equity"), field_name="equity"),
            cash=parse_decimal(account_payload.get("cash"), field_name="cash"),
            buying_power=parse_optional_decimal(account_payload.get("buying_power")),
            positions=positions,
            raw={"account": account_payload, "positions": positions_payload},
        )


    def list_open_orders(self) -> tuple[OpenOrder, ...]:
        payload = self._client.request_json(
            "GET",
            "/v2/orders",
            params={"status": "open", "nested": "false"},
        )
        if not isinstance(payload, list):
            raise AdapterParseError("Alpaca open orders payload must be a list")
        return tuple(self._parse_open_order(item) for item in payload)

    def place_order(self, request: OrderRequest) -> OrderResult:
        payload: dict[str, Any] = {
            "symbol": request.symbol,
            "side": request.side.lower(),
            "type": request.order_type.lower(),
            "time_in_force": request.time_in_force.lower(),
        }
        if request.quantity is not None:
            payload["qty"] = str(request.quantity)
        if request.notional is not None:
            payload["notional"] = str(request.notional)
        if request.limit_price is not None:
            payload["limit_price"] = str(request.limit_price)

        # Bracket order: both TP and SL present → use Alpaca bracket class.
        # SL-only → simple stop attached to entry, no bracket needed.
        if request.take_profit_price is not None and request.stop_price is not None:
            payload["order_class"] = "bracket"
            payload["take_profit"] = {"limit_price": str(request.take_profit_price)}
            payload["stop_loss"] = {"stop_price": str(request.stop_price)}
        elif request.take_profit_price is not None:
            # TP without SL: use oco (one-cancels-other) with only the profit leg.
            payload["order_class"] = "oto"
            payload["take_profit"] = {"limit_price": str(request.take_profit_price)}
        elif request.stop_price is not None:
            payload["stop_price"] = str(request.stop_price)

        if request.client_order_id:
            payload["client_order_id"] = request.client_order_id

        response = self._client.request_json("POST", "/v2/orders", json=payload)
        order_id = str(response.get("id") or response.get("client_order_id") or "submitted")
        status = str(response.get("status") or "submitted")
        return OrderResult(
            venue=self.venue,
            asset_class=self.asset_class,
            order_id=order_id,
            status=status,
            client_order_id=str(response.get("client_order_id")) if response.get("client_order_id") else request.client_order_id,
            raw=response,
        )


    def _parse_open_order(self, payload: dict[str, Any]) -> OpenOrder:
        if not isinstance(payload, dict):
            raise AdapterParseError("Alpaca open order row must be an object")

        order_id = str(payload.get("id") or payload.get("client_order_id") or "unknown")
        return OpenOrder(
            symbol=str(payload.get("symbol") or payload.get("asset_id") or "unknown"),
            order_id=order_id,
            client_order_id=str(payload.get("client_order_id")) if payload.get("client_order_id") else None,
            status=str(payload.get("status") or "open"),
            side=str(payload.get("side") or "buy").lower(),
            order_type=str(payload.get("type") or payload.get("order_type") or "market").lower(),
            quantity=parse_optional_decimal(payload.get("qty")),
            notional=parse_optional_decimal(payload.get("notional")),
            limit_price=parse_optional_decimal(payload.get("limit_price")),
            stop_price=parse_optional_decimal(payload.get("stop_price")),
            submitted_at=parse_optional_datetime(payload.get("submitted_at") or payload.get("created_at")),
            asset_class=self.asset_class,
            raw=payload,
        )

    def _parse_position(self, payload: dict[str, Any]) -> AccountPosition:
        if not isinstance(payload, dict):
            raise AdapterParseError("Alpaca position row must be an object")

        return AccountPosition(
            symbol=str(payload.get("symbol") or payload.get("asset_id") or "unknown"),
            quantity=parse_decimal(payload.get("qty"), field_name="qty"),
            market_value=parse_optional_decimal(payload.get("market_value")),
            cost_basis=parse_optional_decimal(payload.get("cost_basis")),
            average_entry_price=parse_optional_decimal(payload.get("avg_entry_price")),
            side="long" if str(payload.get("side", "long")).lower() != "short" else "short",
            asset_class=self.asset_class,
            raw=payload,
        )
