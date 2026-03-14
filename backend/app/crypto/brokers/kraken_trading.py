from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.app.common.adapters.errors import AdapterAuthenticationError, AdapterParseError
from backend.app.common.adapters.http import JsonApiClient
from backend.app.common.adapters.models import AccountPosition, AccountState, OrderRequest, OrderResult
from backend.app.common.adapters.utils import parse_decimal, parse_optional_decimal
from backend.app.core.config import Settings

logger = logging.getLogger(__name__)


class KrakenTradingAdapter:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        if not settings.kraken_api_key or not settings.kraken_api_secret:
            raise AdapterAuthenticationError("Kraken credentials are not configured")

        self._settings = settings
        self._api_key = settings.kraken_api_key
        self._api_secret = settings.kraken_api_secret
        self._quote_currency = settings.kraken_quote_currency
        self._trade_balance_asset = settings.kraken_trade_balance_asset
        self._client = JsonApiClient(
            base_url=settings.kraken_api_base_url,
            label="kraken_trading",
            timeout_seconds=settings.broker_request_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def get_account_state(self) -> AccountState:
        balance_payload = self._private_post("/private/Balance")
        trade_balance_payload = self._private_post(
            "/private/TradeBalance",
            payload={"asset": self._trade_balance_asset},
        )

        balances = self._extract_result(balance_payload)
        trade_balance = self._extract_result(trade_balance_payload)

        positions: list[AccountPosition] = []
        cash = parse_optional_decimal(balances.get(self._quote_currency)) or parse_optional_decimal(
            balances.get(self._trade_balance_asset)
        ) or parse_optional_decimal(trade_balance.get("tb")) or parse_decimal("0", field_name="cash")

        for symbol, raw_balance in balances.items():
            if symbol in {self._quote_currency, self._trade_balance_asset}:
                continue
            quantity = parse_optional_decimal(raw_balance)
            if quantity is None or quantity <= 0:
                continue
            positions.append(
                AccountPosition(
                    symbol=symbol,
                    quantity=quantity,
                    asset_class="crypto",
                    raw={"balance": raw_balance},
                )
            )

        equity = parse_optional_decimal(trade_balance.get("eb")) or cash
        buying_power = parse_optional_decimal(trade_balance.get("mf")) or parse_optional_decimal(
            trade_balance.get("tb")
        )

        return AccountState(
            venue="kraken",
            asset_class="crypto",
            mode="live",
            account_id=self._api_key[-8:] if len(self._api_key) >= 8 else "kraken-live",
            currency=self._trade_balance_asset,
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            positions=tuple(positions),
            raw={"balances": balances, "trade_balance": trade_balance},
        )

    def place_order(self, request: OrderRequest) -> OrderResult:
        payload: dict[str, Any] = {
            "pair": request.symbol,
            "type": request.side.lower(),
            "ordertype": request.order_type.lower(),
        }
        if request.quantity is not None:
            payload["volume"] = str(request.quantity)
        if request.limit_price is not None:
            payload["price"] = str(request.limit_price)
        if request.stop_price is not None:
            payload["price2"] = str(request.stop_price)
        if request.client_order_id:
            payload["userref"] = request.client_order_id

        response = self._private_post("/private/AddOrder", payload=payload)
        result = self._extract_result(response)
        txids = result.get("txid") or []
        order_id = txids[0] if txids else str(result.get("descr", {}).get("order", "submitted"))

        return OrderResult(
            venue="kraken",
            asset_class="crypto",
            order_id=order_id,
            status="submitted",
            client_order_id=request.client_order_id,
            raw=result,
        )

    def _private_post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload.copy() if payload else {}
        nonce = str(int(time.time() * 1000))
        body["nonce"] = nonce
        encoded_body = urlencode(body)
        headers = {
            "API-Key": self._api_key,
            "API-Sign": self._build_signature(path, nonce, encoded_body),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        return self._client.request_json("POST", path, headers=headers, data=encoded_body)

    def _build_signature(self, path: str, nonce: str, encoded_body: str) -> str:
        secret = base64.b64decode(self._api_secret)
        sha256_hash = hashlib.sha256(f"{nonce}{encoded_body}".encode("utf-8")).digest()
        message = path.encode("utf-8") + sha256_hash
        signature = hmac.new(secret, message, hashlib.sha512).digest()
        return base64.b64encode(signature).decode("utf-8")

    @staticmethod
    def _extract_result(payload: dict[str, Any]) -> dict[str, Any]:
        errors = payload.get("error")
        if isinstance(errors, list) and errors:
            raise AdapterParseError(f"Kraken returned errors: {', '.join(str(item) for item in errors)}")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise AdapterParseError("Kraken payload missing result object")

        return result
