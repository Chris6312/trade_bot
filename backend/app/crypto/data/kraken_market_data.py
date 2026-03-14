from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from backend.app.common.adapters.errors import AdapterParseError
from backend.app.common.adapters.http import JsonApiClient
from backend.app.common.adapters.models import OhlcvBar
from backend.app.common.adapters.utils import kraken_interval_value, parse_decimal
from backend.app.core.config import Settings

logger = logging.getLogger(__name__)


class KrakenMarketDataAdapter:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._client = JsonApiClient(
            base_url=settings.kraken_api_base_url,
            label="kraken_market_data",
            timeout_seconds=settings.broker_request_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_ohlcv(self, *, symbol: str, timeframe: str, since: int | None = None) -> list[OhlcvBar]:
        params = {"pair": symbol, "interval": kraken_interval_value(timeframe)}
        if since is not None:
            params["since"] = since

        payload = self._client.request_json("GET", "/public/OHLC", params=params)
        errors = payload.get("error")
        if isinstance(errors, list) and errors:
            raise AdapterParseError(f"Kraken OHLC returned errors: {', '.join(str(item) for item in errors)}")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise AdapterParseError("Kraken OHLC payload missing result object")

        series = result.get(symbol)
        if not isinstance(series, list):
            alt_keys = [key for key in result.keys() if key != "last"]
            if len(alt_keys) != 1:
                raise AdapterParseError(f"Kraken OHLC payload missing series for {symbol}")
            series = result[alt_keys[0]]

        bars: list[OhlcvBar] = []
        for row in series:
            if not isinstance(row, list) or len(row) < 7:
                raise AdapterParseError("Kraken OHLC row malformed")
            timestamp = datetime.fromtimestamp(int(row[0]), tz=UTC)
            bars.append(
                OhlcvBar(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=timestamp,
                    open=parse_decimal(row[1], field_name="open"),
                    high=parse_decimal(row[2], field_name="high"),
                    low=parse_decimal(row[3], field_name="low"),
                    close=parse_decimal(row[4], field_name="close"),
                    vwap=parse_decimal(row[5], field_name="vwap"),
                    volume=parse_decimal(row[6], field_name="volume"),
                    trade_count=int(row[7]) if len(row) > 7 else None,
                    raw={"row": row},
                )
            )

        return bars
