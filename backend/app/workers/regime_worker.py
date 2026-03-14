from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.regime_service import (
    SINGLE_REGIME_WRITER,
    rebuild_regime_snapshot_for_asset_class,
)
from backend.app.services.universe_service import list_universe_symbols, trading_date_for_now

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class RegimeComputationSummary:
    asset_class: str
    timeframe: str
    regime: str | None
    entry_policy: str | None
    requested_symbols: tuple[str, ...]
    symbol_count: int
    computed_snapshots: int
    skipped_reason: str | None = None


class RegimeWorker:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def build_stock_regime(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> RegimeComputationSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="stock")
        symbols = self._require_universe_symbols(asset_class="stock", now=now)
        return self._build_regime(
            asset_class="stock",
            venue="alpaca",
            timeframe=target_timeframe,
            symbols=symbols,
            now=now,
        )

    def build_crypto_regime(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> RegimeComputationSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="crypto")
        symbols = self._require_universe_symbols(asset_class="crypto", now=now)
        return self._build_regime(
            asset_class="crypto",
            venue="kraken",
            timeframe=target_timeframe,
            symbols=symbols,
            now=now,
        )

    def _build_regime(
        self,
        *,
        asset_class: str,
        venue: str,
        timeframe: str,
        symbols: tuple[str, ...],
        now: datetime | None,
    ) -> RegimeComputationSummary:
        computed_time = self._coerce_datetime(now)
        summary = rebuild_regime_snapshot_for_asset_class(
            self.db,
            writer_name=SINGLE_REGIME_WRITER,
            asset_class=asset_class,
            venue=venue,
            source="regime_engine",
            symbols=symbols,
            timeframe=timeframe,
            computed_at=computed_time,
        )
        logger.info(
            "regime_engine_completed",
            extra={
                "asset_class": asset_class,
                "timeframe": timeframe,
                "requested_symbols": list(symbols),
                "symbol_count": summary.symbol_count,
                "regime": summary.regime,
                "entry_policy": summary.entry_policy,
                "skipped_reason": summary.skipped_reason,
            },
        )
        return RegimeComputationSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            regime=summary.regime,
            entry_policy=summary.entry_policy,
            requested_symbols=symbols,
            symbol_count=summary.symbol_count,
            computed_snapshots=summary.snapshot_count,
            skipped_reason=summary.skipped_reason,
        )

    def _require_universe_symbols(self, *, asset_class: str, now: datetime | None) -> tuple[str, ...]:
        trade_date = trading_date_for_now(now)
        symbols = tuple(item.symbol for item in list_universe_symbols(self.db, asset_class=asset_class, trade_date=trade_date))
        if not symbols:
            raise RuntimeError(f"{asset_class}_universe_unresolved")
        return symbols

    def _default_timeframe(self, *, asset_class: str) -> str:
        if asset_class == "stock":
            timeframes = self.settings.stock_feature_timeframe_list
        else:
            timeframes = self.settings.crypto_feature_timeframe_list
        return timeframes[0] if timeframes else "1h"

    @staticmethod
    def _coerce_datetime(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
