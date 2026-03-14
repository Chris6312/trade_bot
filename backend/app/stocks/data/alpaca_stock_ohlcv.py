from __future__ import annotations

from datetime import UTC

import httpx

from backend.app.common.adapters.errors import AdapterParseError
from backend.app.common.adapters.http import JsonApiClient
from backend.app.common.adapters.models import OhlcvBar
from backend.app.common.adapters.utils import alpaca_timeframe_value, parse_datetime, parse_decimal, parse_optional_decimal
from backend.app.core.config import Settings


class AlpacaStockOhlcvAdapter:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        headers = {}
        if settings.alpaca_paper_key and settings.alpaca_paper_secret:
            headers = {
                "APCA-API-KEY-ID": settings.alpaca_paper_key,
                "APCA-API-SECRET-KEY": settings.alpaca_paper_secret,
            }
        self._client = JsonApiClient(
            base_url=settings.alpaca_market_data_base_url,
            label="alpaca_stock_ohlcv",
            default_headers=headers,
            timeout_seconds=settings.broker_request_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_ohlcv(
        self,
        *,
        symbols: list[str],
        timeframe: str,
        start: str,
        end: str | None = None,
        limit: int | None = None,
        adjustment: str = "raw",
        feed: str | None = None,
    ) -> dict[str, list[OhlcvBar]]:
        params: dict[str, object] = {
            "symbols": ",".join(symbols),
            "timeframe": alpaca_timeframe_value(timeframe),
            "start": start,
            "adjustment": adjustment,
        }
        if end is not None:
            params["end"] = end
        if limit is not None:
            params["limit"] = limit
        if feed is not None:
            params["feed"] = feed

        payload = self._client.request_json("GET", "/v2/stocks/bars", params=params)
        bars_payload = payload.get("bars")
        if not isinstance(bars_payload, dict):
            raise AdapterParseError("Alpaca bars payload missing bars object")

        parsed: dict[str, list[OhlcvBar]] = {}
        for symbol, rows in bars_payload.items():
            if not isinstance(rows, list):
                raise AdapterParseError(f"Alpaca bars for {symbol} must be a list")
            parsed[symbol] = [self._parse_bar(symbol, timeframe, row) for row in rows]

        return parsed

    @staticmethod
    def _parse_bar(symbol: str, timeframe: str, row: dict[str, object]) -> OhlcvBar:
        if not isinstance(row, dict):
            raise AdapterParseError("Alpaca bar row must be an object")

        timestamp = parse_datetime(row.get("t"), field_name="t").astimezone(UTC)
        return OhlcvBar(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            open=parse_decimal(row.get("o"), field_name="o"),
            high=parse_decimal(row.get("h"), field_name="h"),
            low=parse_decimal(row.get("l"), field_name="l"),
            close=parse_decimal(row.get("c"), field_name="c"),
            volume=parse_decimal(row.get("v"), field_name="v"),
            vwap=parse_optional_decimal(row.get("vw")),
            trade_count=int(row["n"]) if row.get("n") is not None else None,
            raw=row,
        )
