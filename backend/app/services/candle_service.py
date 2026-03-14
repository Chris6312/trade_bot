from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from backend.app.common.adapters.models import OhlcvBar
from backend.app.models.core import Candle, CandleFreshness, CandleSyncState

SINGLE_CANDLE_WRITER = "candle_worker"


@dataclass(slots=True, frozen=True)
class CandleSyncSummary:
    asset_class: str
    timeframe: str
    requested_symbols: tuple[str, ...]
    upserted_bars: int
    skipped_reason: str | None = None


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    mapping = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
        "1w": timedelta(weeks=1),
        "15d": timedelta(days=15),
    }
    try:
        return mapping[timeframe]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe: {timeframe}") from exc


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def ensure_single_candle_writer(writer_name: str) -> None:
    if writer_name != SINGLE_CANDLE_WRITER:
        raise PermissionError(
            f"{writer_name!r} is not allowed to write candles. "
            f"Only {SINGLE_CANDLE_WRITER!r} may write OHLCV data.",
        )


def get_sync_state(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
) -> CandleSyncState | None:
    return (
        db.query(CandleSyncState)
        .filter(
            CandleSyncState.asset_class == asset_class,
            CandleSyncState.symbol == symbol,
            CandleSyncState.timeframe == timeframe,
        )
        .one_or_none()
    )


def get_latest_candle_timestamp(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
) -> datetime | None:
    row = (
        db.query(Candle)
        .filter(
            Candle.asset_class == asset_class,
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
        )
        .order_by(Candle.timestamp.desc())
        .first()
    )
    if row is None:
        return None
    return ensure_utc(row.timestamp)


def list_candles(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
) -> list[Candle]:
    return (
        db.query(Candle)
        .filter(
            Candle.asset_class == asset_class,
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
        )
        .order_by(Candle.timestamp.asc())
        .all()
    )


def persist_ohlcv_batch(
    db: Session,
    *,
    writer_name: str,
    asset_class: str,
    venue: str,
    source: str,
    bars: Iterable[OhlcvBar],
    synced_at: datetime | None = None,
) -> int:
    ensure_single_candle_writer(writer_name)
    sync_time = ensure_utc(synced_at) or datetime.now(UTC)

    deduped: dict[tuple[str, str, datetime], OhlcvBar] = {}
    for bar in bars:
        bar_timestamp = ensure_utc(bar.timestamp)
        if bar_timestamp is None:
            continue
        deduped[(bar.symbol, bar.timeframe, bar_timestamp)] = OhlcvBar(
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            timestamp=bar_timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            vwap=bar.vwap,
            trade_count=bar.trade_count,
        )

    upserted = 0
    grouped: dict[tuple[str, str], list[OhlcvBar]] = {}
    for bar in deduped.values():
        grouped.setdefault((bar.symbol, bar.timeframe), []).append(bar)
        existing = (
            db.query(Candle)
            .filter(
                Candle.asset_class == asset_class,
                Candle.symbol == bar.symbol,
                Candle.timeframe == bar.timeframe,
                Candle.timestamp == bar.timestamp,
            )
            .one_or_none()
        )
        if existing is None:
            existing = Candle(
                asset_class=asset_class,
                venue=venue,
                source=source,
                symbol=bar.symbol,
                timeframe=bar.timeframe,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                vwap=bar.vwap,
                trade_count=bar.trade_count,
            )
            db.add(existing)
        else:
            existing.venue = venue
            existing.source = source
            existing.open = bar.open
            existing.high = bar.high
            existing.low = bar.low
            existing.close = bar.close
            existing.volume = bar.volume
            existing.vwap = bar.vwap
            existing.trade_count = bar.trade_count
        upserted += 1

    for (symbol, timeframe), symbol_bars in grouped.items():
        newest_bar_at = max(bar.timestamp for bar in symbol_bars)
        _upsert_sync_state(
            db,
            asset_class=asset_class,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
            last_synced_at=sync_time,
            last_candle_at=newest_bar_at,
            last_status="synced",
            last_error=None,
        )
        _upsert_freshness(
            db,
            asset_class=asset_class,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
            last_synced_at=sync_time,
            last_candle_at=newest_bar_at,
        )

    db.commit()
    return upserted


def mark_symbol_sync_result(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    symbol: str,
    timeframe: str,
    synced_at: datetime,
    last_status: str,
    last_error: str | None = None,
) -> None:
    sync_time = ensure_utc(synced_at) or datetime.now(UTC)
    newest_bar_at = get_latest_candle_timestamp(
        db,
        asset_class=asset_class,
        symbol=symbol,
        timeframe=timeframe,
    )
    _upsert_sync_state(
        db,
        asset_class=asset_class,
        venue=venue,
        symbol=symbol,
        timeframe=timeframe,
        last_synced_at=sync_time,
        last_candle_at=newest_bar_at,
        last_status=last_status,
        last_error=last_error,
    )
    if newest_bar_at is not None:
        _upsert_freshness(
            db,
            asset_class=asset_class,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
            last_synced_at=sync_time,
            last_candle_at=newest_bar_at,
        )
    db.commit()


def _upsert_sync_state(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    symbol: str,
    timeframe: str,
    last_synced_at: datetime,
    last_candle_at: datetime | None,
    last_status: str,
    last_error: str | None,
) -> CandleSyncState:
    record = get_sync_state(
        db,
        asset_class=asset_class,
        symbol=symbol,
        timeframe=timeframe,
    )
    if record is None:
        record = CandleSyncState(
            asset_class=asset_class,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
        )
        db.add(record)

    record.venue = venue
    record.last_synced_at = ensure_utc(last_synced_at)
    record.last_candle_at = ensure_utc(last_candle_at)
    record.last_status = last_status
    record.last_error = last_error
    return record


def _upsert_freshness(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    symbol: str,
    timeframe: str,
    last_synced_at: datetime,
    last_candle_at: datetime,
) -> CandleFreshness:
    record = (
        db.query(CandleFreshness)
        .filter(
            CandleFreshness.asset_class == asset_class,
            CandleFreshness.symbol == symbol,
            CandleFreshness.timeframe == timeframe,
        )
        .one_or_none()
    )
    if record is None:
        record = CandleFreshness(
            asset_class=asset_class,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
        )
        db.add(record)

    normalized_synced_at = ensure_utc(last_synced_at)
    normalized_last_candle_at = ensure_utc(last_candle_at)
    assert normalized_synced_at is not None
    assert normalized_last_candle_at is not None

    record.venue = venue
    record.last_synced_at = normalized_synced_at
    record.last_candle_at = normalized_last_candle_at
    record.fresh_through = normalized_last_candle_at + timeframe_to_timedelta(timeframe)
    return record
