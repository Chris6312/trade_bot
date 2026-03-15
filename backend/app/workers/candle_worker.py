from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.adapter_registry import AdapterRegistry
from backend.app.services.candle_service import SINGLE_CANDLE_WRITER, CandleSyncSummary, ensure_utc, get_sync_state, mark_symbol_sync_result, persist_ohlcv_batch, timeframe_to_timedelta

logger = logging.getLogger(__name__)
INCREMENTAL_RELEASE_DELAY = timedelta(seconds=20)


@dataclass(slots=True, frozen=True)
class SyncWindow:
    start: datetime
    end: datetime


class SingleCandleWorker:
    def __init__(self, db: Session, *, registry: AdapterRegistry | None = None, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.registry = registry or AdapterRegistry(self.settings)
        self._nyse_tz = ZoneInfo("America/New_York")

    def sync_stock_backfill(self, *, symbols: list[str], timeframe: str, start: datetime | None = None, end: datetime | None = None, limit: int | None = None, adjustment: str = "raw", feed: str | None = None, now: datetime | None = None) -> CandleSyncSummary:
        if not symbols:
            return CandleSyncSummary(asset_class="stock", timeframe=timeframe, requested_symbols=(), upserted_bars=0)
        sync_time = self._coerce_datetime(now)
        window = self._resolve_backfill_window(timeframe=timeframe, default_bars=self.settings.stock_default_backfill_bars, now=sync_time, start=start, end=end)
        adapter = self.registry.alpaca_stock_ohlcv()
        bars_by_symbol = adapter.fetch_ohlcv(symbols=symbols, timeframe=timeframe, start=window.start.isoformat().replace("+00:00", "Z"), end=window.end.isoformat().replace("+00:00", "Z"), limit=limit, adjustment=adjustment, feed=feed)
        total = 0
        for symbol in symbols:
            symbol_bars = bars_by_symbol.get(symbol, [])
            if symbol_bars:
                total += persist_ohlcv_batch(self.db, writer_name=SINGLE_CANDLE_WRITER, asset_class="stock", venue="alpaca", source="alpaca_stock_ohlcv", bars=symbol_bars, synced_at=sync_time)
            else:
                mark_symbol_sync_result(self.db, asset_class="stock", venue="alpaca", symbol=symbol, timeframe=timeframe, synced_at=sync_time, last_status="no_data")
        logger.info("stock_backfill_completed", extra={"symbols": symbols, "timeframe": timeframe, "upserted_bars": total, "start": window.start.isoformat(), "end": window.end.isoformat()})
        return CandleSyncSummary(asset_class="stock", timeframe=timeframe, requested_symbols=tuple(symbols), upserted_bars=total)

    def sync_stock_incremental(self, *, symbols: list[str], timeframe: str, now: datetime | None = None, adjustment: str = "raw", feed: str | None = None) -> CandleSyncSummary:
        if not symbols:
            return CandleSyncSummary(asset_class="stock", timeframe=timeframe, requested_symbols=(), upserted_bars=0)
        sync_time = self._coerce_datetime(now)
        if not self._is_stock_incremental_window_open(timeframe=timeframe, at=sync_time):
            logger.info("stock_incremental_skipped_outside_nyse_hours", extra={"symbols": symbols, "timeframe": timeframe, "at": sync_time.isoformat()})
            return CandleSyncSummary(asset_class="stock", timeframe=timeframe, requested_symbols=tuple(symbols), upserted_bars=0, skipped_reason="outside_nyse_hours")
        end_at = self._latest_released_close(asset_class="stock", timeframe=timeframe, at=sync_time)
        if end_at is None or self._is_before_first_stock_close(timeframe=timeframe, close_at=end_at):
            logger.info("stock_incremental_skipped_awaiting_candle_close", extra={"symbols": symbols, "timeframe": timeframe, "at": sync_time.isoformat()})
            return CandleSyncSummary(asset_class="stock", timeframe=timeframe, requested_symbols=tuple(symbols), upserted_bars=0, skipped_reason="awaiting_candle_close")
        if not self._has_incremental_gap(asset_class="stock", symbols=symbols, timeframe=timeframe, close_at=end_at):
            logger.info("stock_incremental_skipped_no_new_closed_candle", extra={"symbols": symbols, "timeframe": timeframe, "at": sync_time.isoformat(), "close_at": end_at.isoformat()})
            return CandleSyncSummary(asset_class="stock", timeframe=timeframe, requested_symbols=tuple(symbols), upserted_bars=0, skipped_reason="awaiting_next_close")
        start = min(self._stock_incremental_start(symbol=symbol, timeframe=timeframe, now=sync_time) for symbol in symbols)
        return self.sync_stock_backfill(symbols=symbols, timeframe=timeframe, start=start, end=end_at, adjustment=adjustment, feed=feed, now=sync_time)

    def sync_crypto_backfill(self, *, symbols: list[str], timeframe: str, since: datetime | None = None, now: datetime | None = None) -> CandleSyncSummary:
        if not symbols:
            return CandleSyncSummary(asset_class="crypto", timeframe=timeframe, requested_symbols=(), upserted_bars=0)
        sync_time = self._coerce_datetime(now)
        start = self._coerce_datetime(since) if since is not None else sync_time - (timeframe_to_timedelta(timeframe) * self.settings.crypto_default_backfill_bars)
        adapter = self.registry.kraken_market_data()
        total = 0
        for symbol in symbols:
            symbol_bars = adapter.fetch_ohlcv(symbol=symbol, timeframe=timeframe, since=int(start.timestamp()))
            if symbol_bars:
                total += persist_ohlcv_batch(self.db, writer_name=SINGLE_CANDLE_WRITER, asset_class="crypto", venue="kraken", source="kraken_market_data", bars=symbol_bars, synced_at=sync_time)
            else:
                mark_symbol_sync_result(self.db, asset_class="crypto", venue="kraken", symbol=symbol, timeframe=timeframe, synced_at=sync_time, last_status="no_data")
        logger.info("crypto_backfill_completed", extra={"symbols": symbols, "timeframe": timeframe, "upserted_bars": total, "since": start.isoformat()})
        return CandleSyncSummary(asset_class="crypto", timeframe=timeframe, requested_symbols=tuple(symbols), upserted_bars=total)

    def sync_crypto_incremental(self, *, symbols: list[str], timeframe: str, now: datetime | None = None) -> CandleSyncSummary:
        if not symbols:
            return CandleSyncSummary(asset_class="crypto", timeframe=timeframe, requested_symbols=(), upserted_bars=0)
        sync_time = self._coerce_datetime(now)
        end_at = self._latest_released_close(asset_class="crypto", timeframe=timeframe, at=sync_time)
        if end_at is None:
            return CandleSyncSummary(asset_class="crypto", timeframe=timeframe, requested_symbols=tuple(symbols), upserted_bars=0, skipped_reason="awaiting_candle_close")
        if not self._has_incremental_gap(asset_class="crypto", symbols=symbols, timeframe=timeframe, close_at=end_at):
            return CandleSyncSummary(asset_class="crypto", timeframe=timeframe, requested_symbols=tuple(symbols), upserted_bars=0, skipped_reason="awaiting_next_close")
        adapter = self.registry.kraken_market_data()
        total = 0
        interval = timeframe_to_timedelta(timeframe)
        for symbol in symbols:
            state = get_sync_state(self.db, asset_class="crypto", symbol=symbol, timeframe=timeframe)
            since_at = self._coerce_datetime(state.last_candle_at) - interval if state is not None and state.last_candle_at is not None else end_at - (interval * self.settings.crypto_default_backfill_bars)
            symbol_bars = adapter.fetch_ohlcv(symbol=symbol, timeframe=timeframe, since=int(since_at.timestamp()))
            if symbol_bars:
                total += persist_ohlcv_batch(self.db, writer_name=SINGLE_CANDLE_WRITER, asset_class="crypto", venue="kraken", source="kraken_market_data", bars=symbol_bars, synced_at=sync_time)
            else:
                mark_symbol_sync_result(self.db, asset_class="crypto", venue="kraken", symbol=symbol, timeframe=timeframe, synced_at=sync_time, last_status="no_data")
        logger.info("crypto_incremental_completed", extra={"symbols": symbols, "timeframe": timeframe, "upserted_bars": total, "end": end_at.isoformat()})
        return CandleSyncSummary(asset_class="crypto", timeframe=timeframe, requested_symbols=tuple(symbols), upserted_bars=total)

    def _resolve_backfill_window(self, *, timeframe: str, default_bars: int, now: datetime, start: datetime | None, end: datetime | None) -> SyncWindow:
        end_at = self._coerce_datetime(end) if end is not None else now
        start_at = end_at - (timeframe_to_timedelta(timeframe) * default_bars) if start is None else self._coerce_datetime(start)
        return SyncWindow(start=start_at, end=end_at)

    def _stock_incremental_start(self, *, symbol: str, timeframe: str, now: datetime) -> datetime:
        state = get_sync_state(self.db, asset_class="stock", symbol=symbol, timeframe=timeframe)
        interval = timeframe_to_timedelta(timeframe)
        if state is None or state.last_candle_at is None:
            return now - (interval * self.settings.stock_default_backfill_bars)
        return self._coerce_datetime(state.last_candle_at) - interval

    def _is_stock_incremental_window_open(self, *, timeframe: str, at: datetime) -> bool:
        if timeframe == "1d":
            return True
        local = at.astimezone(self._nyse_tz)
        if local.weekday() >= 5:
            return False
        local_time = local.time().replace(tzinfo=None)
        return time(9, 30) <= local_time <= time(16, 0, 20)

    def _is_before_first_stock_close(self, *, timeframe: str, close_at: datetime) -> bool:
        if timeframe == "1d":
            return False
        local_close = close_at.astimezone(self._nyse_tz)
        return local_close <= local_close.replace(hour=9, minute=30, second=0, microsecond=0)

    def _has_incremental_gap(self, *, asset_class: str, symbols: list[str], timeframe: str, close_at: datetime) -> bool:
        interval = timeframe_to_timedelta(timeframe)
        for symbol in symbols:
            state = get_sync_state(self.db, asset_class=asset_class, symbol=symbol, timeframe=timeframe)
            if state is None or state.last_candle_at is None:
                return True
            if self._coerce_datetime(state.last_candle_at) + interval < close_at:
                return True
        return False

    def _latest_released_close(self, *, asset_class: str, timeframe: str, at: datetime) -> datetime | None:
        timezone = self._nyse_tz if asset_class == "stock" else UTC
        local_time = at.astimezone(timezone)
        boundary = self._floor_close_boundary(local_time, timeframe)
        if local_time < (boundary + INCREMENTAL_RELEASE_DELAY):
            boundary -= timeframe_to_timedelta(timeframe)
        return boundary.astimezone(UTC)

    @staticmethod
    def _floor_close_boundary(at: datetime, timeframe: str) -> datetime:
        if timeframe == "1m":
            return at.replace(second=0, microsecond=0)
        if timeframe == "5m":
            return at.replace(minute=(at.minute // 5) * 5, second=0, microsecond=0)
        if timeframe == "15m":
            return at.replace(minute=(at.minute // 15) * 15, second=0, microsecond=0)
        if timeframe == "30m":
            return at.replace(minute=(at.minute // 30) * 30, second=0, microsecond=0)
        if timeframe == "1h":
            return at.replace(minute=0, second=0, microsecond=0)
        if timeframe == "4h":
            return at.replace(hour=(at.hour // 4) * 4, minute=0, second=0, microsecond=0)
        if timeframe == "1d":
            return at.replace(hour=0, minute=0, second=0, microsecond=0)
        raise ValueError(f"Unsupported incremental timeframe: {timeframe}")

    @staticmethod
    def _coerce_datetime(value: datetime | None) -> datetime:
        return ensure_utc(value) or datetime.now(UTC)
