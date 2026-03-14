from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.strategy_service import (
    SINGLE_STRATEGY_WRITER,
    rebuild_strategy_snapshots_for_asset_class,
)
from backend.app.services.universe_service import list_universe_symbols, trading_date_for_now

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class StrategyComputationSummary:
    asset_class: str
    timeframe: str
    regime: str | None
    entry_policy: str | None
    requested_symbols: tuple[str, ...]
    evaluated_rows: int
    ready_rows: int
    blocked_rows: int
    skipped_reason: str | None = None


class StrategyWorker:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def build_stock_candidates(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> StrategyComputationSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="stock")
        symbols = self._require_universe_symbols(asset_class="stock", now=now)
        return self._build_candidates(
            asset_class="stock",
            venue="alpaca",
            timeframe=target_timeframe,
            symbols=symbols,
            now=now,
        )

    def build_crypto_candidates(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> StrategyComputationSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="crypto")
        symbols = self._require_universe_symbols(asset_class="crypto", now=now)
        return self._build_candidates(
            asset_class="crypto",
            venue="kraken",
            timeframe=target_timeframe,
            symbols=symbols,
            now=now,
        )

    def _build_candidates(
        self,
        *,
        asset_class: str,
        venue: str,
        timeframe: str,
        symbols: tuple[str, ...],
        now: datetime | None,
    ) -> StrategyComputationSummary:
        computed_time = self._coerce_datetime(now)
        summary = rebuild_strategy_snapshots_for_asset_class(
            self.db,
            writer_name=SINGLE_STRATEGY_WRITER,
            asset_class=asset_class,
            venue=venue,
            source="strategy_engine",
            symbols=symbols,
            timeframe=timeframe,
            computed_at=computed_time,
        )
        logger.info(
            "strategy_engine_completed",
            extra={
                "asset_class": asset_class,
                "timeframe": timeframe,
                "requested_symbols": list(symbols),
                "evaluated_rows": summary.evaluated_rows,
                "ready_rows": summary.ready_rows,
                "blocked_rows": summary.blocked_rows,
                "regime": summary.regime,
                "entry_policy": summary.entry_policy,
                "skipped_reason": summary.skipped_reason,
            },
        )
        return StrategyComputationSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            regime=summary.regime,
            entry_policy=summary.entry_policy,
            requested_symbols=symbols,
            evaluated_rows=summary.evaluated_rows,
            ready_rows=summary.ready_rows,
            blocked_rows=summary.blocked_rows,
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
