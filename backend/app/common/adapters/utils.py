from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.common.adapters.errors import AdapterParseError


def parse_decimal(value: Any, *, field_name: str) -> Decimal:
    if value in (None, ""):
        raise AdapterParseError(f"Missing decimal field: {field_name}")

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise AdapterParseError(f"Invalid decimal for {field_name}: {value!r}") from exc


def parse_optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_datetime(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)

    if not isinstance(value, str) or not value.strip():
        raise AdapterParseError(f"Missing datetime field: {field_name}")

    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AdapterParseError(f"Invalid datetime for {field_name}: {value!r}") from exc

    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def kraken_interval_value(timeframe: str) -> int:
    mapping = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
        "1w": 10080,
        "15d": 21600,
    }
    try:
        return mapping[timeframe]
    except KeyError as exc:
        raise AdapterParseError(f"Unsupported Kraken timeframe: {timeframe}") from exc


def alpaca_timeframe_value(timeframe: str) -> str:
    mapping = {
        "1m": "1Min",
        "5m": "5Min",
        "15m": "15Min",
        "30m": "30Min",
        "1h": "1Hour",
        "1d": "1Day",
        "1w": "1Week",
    }
    try:
        return mapping[timeframe]
    except KeyError as exc:
        raise AdapterParseError(f"Unsupported Alpaca timeframe: {timeframe}") from exc
