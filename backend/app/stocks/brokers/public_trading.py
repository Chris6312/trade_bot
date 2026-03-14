from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from backend.app.common.adapters.errors import AdapterAuthenticationError, AdapterParseError
from backend.app.common.adapters.http import JsonApiClient
from backend.app.common.adapters.models import AccountPosition, AccountState, OpenOrder, OrderRequest, OrderResult
from backend.app.common.adapters.utils import parse_datetime, parse_decimal, parse_optional_decimal
from backend.app.core.config import Settings

logger = logging.getLogger(__name__)


def _parse_optional_datetime(value: Any) -> Any:
    if value in (None, ""):
        return None
    try:
        return parse_datetime(value, field_name="submitted_at")
    except AdapterParseError:
        return None


class PublicTradingAdapter:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        if not settings.public_api_secret:
            raise AdapterAuthenticationError("Public API secret is not configured")

        self._base_url = settings.public_api_base_url
        self._secret = settings.public_api_secret
        self._account_id = self._normalize_account_id(settings.public_account_id)
        self._token_validity_minutes = settings.public_access_token_validity_minutes
        self._timeout_seconds = settings.broker_request_timeout_seconds
        self._transport = transport
        self._client = JsonApiClient(
            base_url=self._base_url,
            label="public_trading",
            timeout_seconds=self._timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def get_account_state(self) -> AccountState:
        account_id = self._resolve_account_id()
        portfolio = self._authenticated_client().request_json(
            "GET",
            f"/userapigateway/trading/{account_id}/portfolio/v2",
        )
        positions_payload = portfolio.get("positions")
        if not isinstance(positions_payload, list):
            raise AdapterParseError("Public portfolio positions must be a list")

        buying_power = self._extract_money_value(portfolio.get("buyingPower"))
        equity = self._extract_equity_value(portfolio.get("equity"))
        cash = self._extract_cash_value(portfolio.get("buyingPower"), portfolio.get("equity"))

        positions = tuple(self._parse_position(item) for item in positions_payload)
        return AccountState(
            venue="public",
            asset_class="stock",
            mode="live",
            account_id=account_id,
            currency="USD",
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            positions=positions,
            raw=portfolio,
        )


    def list_open_orders(self) -> tuple[OpenOrder, ...]:
        account_id = self._resolve_account_id()
        portfolio = self._authenticated_client().request_json(
            "GET",
            f"/userapigateway/trading/{account_id}/portfolio/v2",
        )
        orders_payload = (
            portfolio.get("openOrders")
            or portfolio.get("open_orders")
            or portfolio.get("orders")
            or []
        )
        if not isinstance(orders_payload, list):
            raise AdapterParseError("Public portfolio open orders must be a list")
        return tuple(self._parse_open_order(item) for item in orders_payload)

    def place_order(self, request: OrderRequest) -> OrderResult:
        account_id = self._resolve_account_id()
        order_id = request.client_order_id or str(uuid.uuid4())
        payload: dict[str, Any] = {
            "orderId": order_id,
            "instrument": {
                "symbol": request.symbol,
                "type": "EQUITY",
            },
            "orderType": request.order_type.upper(),
            "side": request.side.upper(),
            "expiration": {"timeInForce": request.time_in_force.upper()},
        }
        if request.quantity is not None:
            payload["quantity"] = str(request.quantity)
        if request.notional is not None:
            payload["notionalAmount"] = str(request.notional)
        if request.limit_price is not None:
            payload["limitPrice"] = str(request.limit_price)
        if request.stop_price is not None:
            payload["stopPrice"] = str(request.stop_price)

        response = self._authenticated_client().request_json(
            "POST",
            f"/userapigateway/trading/{account_id}/order",
            json=payload,
        )
        resolved_order_id = str(response.get("orderId") or order_id)
        status = str(response.get("status") or "submitted")
        return OrderResult(
            venue="public",
            asset_class="stock",
            order_id=resolved_order_id,
            status=status,
            client_order_id=order_id,
            raw=response,
        )

    def _resolve_account_id(self) -> str:
        if self._account_id:
            return self._account_id

        accounts_payload = self._authenticated_client().request_json("GET", "/userapigateway/trading/account")
        accounts = accounts_payload.get("accounts")
        if not isinstance(accounts, list) or not accounts:
            raise AdapterParseError("Public accounts payload missing accounts list")

        for row in accounts:
            if not isinstance(row, dict):
                continue
            account_id = self._normalize_account_id(row.get("accountId"))
            if account_id:
                self._account_id = account_id
                return account_id

        raise AdapterParseError("Public accounts payload missing accountId")

    @staticmethod
    def _normalize_account_id(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        cleaned = value.strip().strip("/")
        return cleaned or None

    def _authenticated_client(self) -> JsonApiClient:
        token_payload = self._client.request_json(
            "POST",
            "/userapiauthservice/personal/access-tokens",
            json={
                "validityInMinutes": self._token_validity_minutes,
                "secret": self._secret,
            },
        )
        access_token = token_payload.get("accessToken")
        if not isinstance(access_token, str) or not access_token:
            raise AdapterParseError("Public access token response missing accessToken")

        return JsonApiClient(
            base_url=self._base_url,
            label="public_trading",
            default_headers={"Authorization": f"Bearer {access_token}"},
            timeout_seconds=self._timeout_seconds,
            transport=self._transport,
        )


    def _parse_open_order(self, payload: dict[str, Any]) -> OpenOrder:
        if not isinstance(payload, dict):
            raise AdapterParseError("Public open order row must be an object")

        instrument = payload.get("instrument") if isinstance(payload.get("instrument"), dict) else {}
        order_id = str(payload.get("orderId") or payload.get("id") or payload.get("clientOrderId") or "unknown")
        quantity = parse_optional_decimal(
            payload.get("quantity")
            or payload.get("qty")
            or payload.get("shares")
            or payload.get("units")
        )
        notional = parse_optional_decimal(
            payload.get("amount")
            or payload.get("notionalAmount")
            or payload.get("notional")
        )
        return OpenOrder(
            symbol=str(payload.get("symbol") or instrument.get("symbol") or "unknown"),
            order_id=order_id,
            client_order_id=str(payload.get("clientOrderId")) if payload.get("clientOrderId") else None,
            status=str(payload.get("status") or "open"),
            side=str(payload.get("side") or payload.get("orderSide") or "buy").lower(),
            order_type=str(payload.get("orderType") or payload.get("type") or "market").lower(),
            quantity=quantity,
            notional=notional,
            limit_price=self._extract_money_value(payload.get("limitPrice") or payload.get("limit_price")),
            stop_price=self._extract_money_value(payload.get("stopPrice") or payload.get("stop_price")),
            submitted_at=_parse_optional_datetime(payload.get("submittedAt") or payload.get("createdAt") or payload.get("updatedAt")),
            asset_class="stock",
            raw=payload,
        )

    def _parse_position(self, payload: dict[str, Any]) -> AccountPosition:
        if not isinstance(payload, dict):
            raise AdapterParseError("Public position row must be an object")

        instrument = payload.get("instrument") if isinstance(payload.get("instrument"), dict) else {}
        symbol = str(payload.get("symbol") or instrument.get("symbol") or "unknown")
        quantity_value = (
            payload.get("quantity")
            or payload.get("qty")
            or payload.get("shares")
            or payload.get("units")
        )
        return AccountPosition(
            symbol=symbol,
            quantity=parse_decimal(quantity_value, field_name="quantity"),
            market_value=self._extract_money_value(payload.get("marketValue")),
            cost_basis=self._extract_money_value(payload.get("costBasis")),
            average_entry_price=self._extract_money_value(payload.get("averagePrice")),
            side="long",
            asset_class="stock",
            raw=payload,
        )

    @staticmethod
    def _extract_money_value(value: Any) -> Any:
        if isinstance(value, dict):
            for key in ("amount", "value", "usd", "marketValue"):
                parsed = parse_optional_decimal(value.get(key))
                if parsed is not None:
                    return parsed
            return None
        return parse_optional_decimal(value)

    def _extract_equity_value(self, value: Any) -> Any:
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("type") or "").lower()
                if label in {"total", "total_equity", "net_liquidation", "equity"}:
                    parsed = self._extract_money_value(item)
                    if parsed is not None:
                        return parsed
            if value and isinstance(value[0], dict):
                parsed = self._extract_money_value(value[0])
                if parsed is not None:
                    return parsed
        parsed = self._extract_money_value(value)
        if parsed is not None:
            return parsed
        raise AdapterParseError("Public portfolio missing equity value")

    def _extract_cash_value(self, buying_power: Any, equity: Any) -> Any:
        if isinstance(buying_power, dict):
            for key in ("availableToTrade", "cashAvailable", "cash", "amount"):
                parsed = parse_optional_decimal(buying_power.get(key))
                if parsed is not None:
                    return parsed
        if isinstance(equity, list):
            for item in equity:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("type") or "").lower()
                if label in {"cash", "cash_balance", "settled_cash"}:
                    parsed = self._extract_money_value(item)
                    if parsed is not None:
                        return parsed
        resolved_buying_power = self._extract_money_value(buying_power)
        if resolved_buying_power is not None:
            return resolved_buying_power
        raise AdapterParseError("Public portfolio missing cash value")