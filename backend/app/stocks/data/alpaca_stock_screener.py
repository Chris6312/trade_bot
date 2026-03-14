from __future__ import annotations

from typing import Any

import httpx

from backend.app.common.adapters.http import JsonApiClient
from backend.app.core.config import Settings


class AlpacaStockScreenerAdapter:
    def __init__(
        self,
        settings: Settings,
        *,
        market_data_transport: httpx.BaseTransport | None = None,
        trading_transport: httpx.BaseTransport | None = None,
    ) -> None:
        auth_headers: dict[str, str] = {}
        if settings.alpaca_paper_key and settings.alpaca_paper_secret:
            auth_headers = {
                "APCA-API-KEY-ID": settings.alpaca_paper_key,
                "APCA-API-SECRET-KEY": settings.alpaca_paper_secret,
            }

        self._market_data = JsonApiClient(
            base_url=settings.alpaca_market_data_base_url,
            label="alpaca_stock_screener",
            default_headers=auth_headers,
            timeout_seconds=settings.broker_request_timeout_seconds,
            transport=market_data_transport,
        )
        self._trading = JsonApiClient(
            base_url=settings.alpaca_trading_api_base_url,
            label="alpaca_assets",
            default_headers=auth_headers,
            timeout_seconds=settings.broker_request_timeout_seconds,
            transport=trading_transport,
        )

    def close(self) -> None:
        self._market_data.close()
        self._trading.close()

    def fetch_most_active(self, *, top: int = 50, by: str = "volume") -> list[dict[str, Any]]:
        payload = self._market_data.request_json(
            "GET",
            "/v1beta1/screener/stocks/most-actives",
            params={"top": top, "by": by},
        )
        rows = self._extract_rows(payload)
        return [row for row in rows if isinstance(row, dict)]

    def fetch_asset(self, *, symbol: str) -> dict[str, Any]:
        payload = self._trading.request_json("GET", f"/v2/assets/{symbol}")
        if isinstance(payload, dict):
            return payload
        raise ValueError(f"Unexpected asset payload type for {symbol}: {type(payload).__name__}")

    @staticmethod
    def _extract_rows(payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []

        for key in ("most_actives", "mostActives", "data", "symbols", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows

        return []
