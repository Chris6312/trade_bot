from __future__ import annotations

from datetime import UTC, datetime

import httpx

from backend.app.common.adapters.errors import AdapterParseError
from backend.app.common.adapters.http import JsonApiClient
from backend.app.common.adapters.models import OrderBookLevel, OrderBookSnapshot
from backend.app.common.adapters.utils import parse_decimal
from backend.app.core.config import Settings


class KrakenOrderBookAdapter:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._client = JsonApiClient(
            base_url=settings.kraken_api_base_url,
            label="kraken_orderbook",
            timeout_seconds=settings.broker_request_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_snapshot(self, *, symbol: str, depth: int = 25) -> OrderBookSnapshot:
        if depth <= 0:
            raise AdapterParseError("Kraken order book depth must be positive")

        payload = self._client.request_json("GET", "/public/Depth", params={"pair": symbol, "count": depth})
        errors = payload.get("error")
        if isinstance(errors, list) and errors:
            raise AdapterParseError(f"Kraken order book returned errors: {', '.join(str(item) for item in errors)}")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise AdapterParseError("Kraken order book payload missing result object")

        book = result.get(symbol)
        if not isinstance(book, dict):
            alt_keys = [key for key in result.keys() if isinstance(result.get(key), dict)]
            if len(alt_keys) != 1:
                raise AdapterParseError(f"Kraken order book payload missing book for {symbol}")
            book = result[alt_keys[0]]

        bids = self._parse_levels(book.get("bids"), side="bids")
        asks = self._parse_levels(book.get("asks"), side="asks")
        if not bids or not asks:
            raise AdapterParseError("Kraken order book payload missing bids or asks")

        timestamps = [level.timestamp for level in [*bids, *asks] if level.timestamp is not None]
        as_of = max(timestamps) if timestamps else datetime.now(UTC)
        return OrderBookSnapshot(
            symbol=symbol,
            as_of=as_of,
            bids=tuple(bids),
            asks=tuple(asks),
            raw={"book": book, "requested_depth": depth},
        )

    @staticmethod
    def _parse_levels(levels: object, *, side: str) -> list[OrderBookLevel]:
        if not isinstance(levels, list):
            raise AdapterParseError(f"Kraken order book missing {side} array")

        parsed: list[OrderBookLevel] = []
        for row in levels:
            if not isinstance(row, list) or len(row) < 2:
                raise AdapterParseError(f"Kraken order book {side} row malformed")
            timestamp = None
            if len(row) > 2 and row[2] not in (None, ""):
                try:
                    timestamp = datetime.fromtimestamp(float(row[2]), tz=UTC)
                except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
                    raise AdapterParseError(f"Kraken order book {side} timestamp malformed: {row[2]!r}") from exc
            parsed.append(
                OrderBookLevel(
                    price=parse_decimal(row[0], field_name=f"{side}.price"),
                    volume=parse_decimal(row[1], field_name=f"{side}.volume"),
                    timestamp=timestamp,
                )
            )
        return parsed
