from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.adapter_registry import AdapterRegistry
from backend.app.services.candle_service import (
    SINGLE_CANDLE_WRITER,
    CandleSyncSummary,
    ensure_utc,
    get_sync_state,
    mark_symbol_sync_result,
    persist_ohlcv_batch,
    timeframe_to_timedelta,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class SyncWindow:
    start: datetime
    end: datetime


class SingleCandleWorker:
    def __init__(
        self,
        db: Session,
        *,
        registry: AdapterRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.registry = registry or AdapterRegistry(self.settings)
        self._nyse_tz = ZoneInfo("America/New_York")

    def sync_stock_backfill(
        self,
        *,
        symbols: list[str],
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        adjustment: str = "raw",
        feed: str | None = None,
        now: datetime | None = None,
    ) -> CandleSyncSummary:
        if not symbols:
            return CandleSyncSummary(asset_class="stock", timeframe=timeframe, requested_symbols=(), upserted_bars=0)

        sync_time = self._coerce_datetime(now)
        window = self._resolve_backfill_window(
            timeframe=timeframe,
            default_bars=self.settings.stock_default_backfill_bars,
            now=sync_time,
            start=start,
            end=end,
        )
        adapter = self.registry.alpaca_stock_ohlcv()
        bars_by_symbol = adapter.fetch_ohlcv(
            symbols=symbols,
            timeframe=timeframe,
            start=window.start.isoformat().replace("+00:00", "Z"),
            end=window.end.isoformat().replace("+00:00", "Z"),
            limit=limit,
            adjustment=adjustment,
            feed=feed,
        )

        total = 0
        for symbol in symbols:
            symbol_bars = bars_by_symbol.get(symbol, [])
            if symbol_bars:
                total += persist_ohlcv_batch(
                    self.db,
                    writer_name=SINGLE_CANDLE_WRITER,
                    asset_class="stock",
                    venue="alpaca",
                    source="alpaca_stock_ohlcv",
                    bars=symbol_bars,
                    synced_at=sync_time,
                )
            else:
                mark_symbol_sync_result(
                    self.db,
                    asset_class="stock",
                    venue="alpaca",
                    symbol=symbol,
                    timeframe=timeframe,
                    synced_at=sync_time,
                    last_status="no_data",
                )

        logger.info(
            "stock_backfill_completed",
            extra={
                "symbols": symbols,
                "timeframe": timeframe,
                "upserted_bars": total,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
            },
        )
        return CandleSyncSummary(
            asset_class="stock",
            timeframe=timeframe,
            requested_symbols=tuple(symbols),
            upserted_bars=total,
        )

    def sync_stock_incremental(
        self,
        *,
        symbols: list[str],
        timeframe: str,
        now: datetime | None = None,
        adjustment: str = "raw",
        feed: str | None = None,
    ) -> CandleSyncSummary:
        if not symbols:
            return CandleSyncSummary(asset_class="stock", timeframe=timeframe, requested_symbols=(), upserted_bars=0)

        sync_time = self._coerce_datetime(now)
        if not self._is_nyse_session_open(sync_time):
            logger.info(
                "stock_incremental_skipped_outside_nyse_hours",
                extra={"symbols": symbols, "timeframe": timeframe, "at": sync_time.isoformat()},
            )
            return CandleSyncSummary(
                asset_class="stock",
                timeframe=timeframe,
                requested_symbols=tuple(symbols),
                upserted_bars=0,
                skipped_reason="outside_nyse_hours",
            )

        start = min(self._stock_incremental_start(symbol=symbol, timeframe=timeframe, now=sync_time) for symbol in symbols)
        return self.sync_stock_backfill(
            symbols=symbols,
            timeframe=timeframe,
            start=start,
            end=sync_time,
            adjustment=adjustment,
            feed=feed,
            now=sync_time,
        )

    def sync_crypto_backfill(
        self,
        *,
        symbols: list[str],
        timeframe: str,
        since: datetime | None = None,
        now: datetime | None = None,
    ) -> CandleSyncSummary:
        if not symbols:
            return CandleSyncSummary(asset_class="crypto", timeframe=timeframe, requested_symbols=(), upserted_bars=0)

        sync_time = self._coerce_datetime(now)
        start = self._coerce_datetime(since) if since is not None else sync_time - (
            timeframe_to_timedelta(timeframe) * self.settings.crypto_default_backfill_bars
        )
        adapter = self.registry.kraken_market_data()
        total = 0
        for symbol in symbols:
            symbol_bars = adapter.fetch_ohlcv(symbol=symbol, timeframe=timeframe, since=int(start.timestamp()))
            if symbol_bars:
                total += persist_ohlcv_batch(
                    self.db,
                    writer_name=SINGLE_CANDLE_WRITER,
                    asset_class="crypto",
                    venue="kraken",
                    source="kraken_market_data",
                    bars=symbol_bars,
                    synced_at=sync_time,
                )
            else:
                mark_symbol_sync_result(
                    self.db,
                    asset_class="crypto",
                    venue="kraken",
                    symbol=symbol,
                    timeframe=timeframe,
                    synced_at=sync_time,
                    last_status="no_data",
                )

        logger.info(
            "crypto_backfill_completed",
            extra={
                "symbols": symbols,
                "timeframe": timeframe,
                "upserted_bars": total,
                "since": start.isoformat(),
            },
        )
        return CandleSyncSummary(
            asset_class="crypto",
            timeframe=timeframe,
            requested_symbols=tuple(symbols),
            upserted_bars=total,
        )

    def sync_crypto_incremental(
        self,
        *,
        symbols: list[str],
        timeframe: str,
        now: datetime | None = None,
    ) -> CandleSyncSummary:
        if not symbols:
            return CandleSyncSummary(asset_class="crypto", timeframe=timeframe, requested_symbols=(), upserted_bars=0)

        sync_time = self._coerce_datetime(now)
        adapter = self.registry.kraken_market_data()
        total = 0
        interval = timeframe_to_timedelta(timeframe)
        for symbol in symbols:
            state = get_sync_state(self.db, asset_class="crypto", symbol=symbol, timeframe=timeframe)
            if state is not None and state.last_candle_at is not None:
                since_at = self._coerce_datetime(state.last_candle_at) - interval
            else:
                since_at = sync_time - (interval * self.settings.crypto_default_backfill_bars)

            symbol_bars = adapter.fetch_ohlcv(symbol=symbol, timeframe=timeframe, since=int(since_at.timestamp()))
            if symbol_bars:
                total += persist_ohlcv_batch(
                    self.db,
                    writer_name=SINGLE_CANDLE_WRITER,
                    asset_class="crypto",
                    venue="kraken",
                    source="kraken_market_data",
                    bars=symbol_bars,
                    synced_at=sync_time,
                )
            else:
                mark_symbol_sync_result(
                    self.db,
                    asset_class="crypto",
                    venue="kraken",
                    symbol=symbol,
                    timeframe=timeframe,
                    synced_at=sync_time,
                    last_status="no_data",
                )

        logger.info(
            "crypto_incremental_completed",
            extra={"symbols": symbols, "timeframe": timeframe, "upserted_bars": total},
        )
        return CandleSyncSummary(
            asset_class="crypto",
            timeframe=timeframe,
            requested_symbols=tuple(symbols),
            upserted_bars=total,
        )

    def _resolve_backfill_window(
        self,
        *,
        timeframe: str,
        default_bars: int,
        now: datetime,
        start: datetime | None,
        end: datetime | None,
    ) -> SyncWindow:
        end_at = self._coerce_datetime(end) if end is not None else now
        if start is None:
            start_at = end_at - (timeframe_to_timedelta(timeframe) * default_bars)
        else:
            start_at = self._coerce_datetime(start)
        return SyncWindow(start=start_at, end=end_at)

    def _stock_incremental_start(self, *, symbol: str, timeframe: str, now: datetime) -> datetime:
        state = get_sync_state(self.db, asset_class="stock", symbol=symbol, timeframe=timeframe)
        interval = timeframe_to_timedelta(timeframe)
        if state is None or state.last_candle_at is None:
            return now - (interval * self.settings.stock_default_backfill_bars)
        return self._coerce_datetime(state.last_candle_at) - interval

    def _is_nyse_session_open(self, at: datetime) -> bool:
        local = at.astimezone(self._nyse_tz)
        if local.weekday() >= 5:
            return False
        local_time = local.time().replace(tzinfo=None)
        return time(9, 30) <= local_time <= time(16, 0)

    @staticmethod
    def _coerce_datetime(value: datetime | None) -> datetime:
        return ensure_utc(value) or datetime.now(UTC)
