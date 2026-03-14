from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.feature_service import (
    SINGLE_FEATURE_WRITER,
    rebuild_feature_snapshots_for_symbol,
)
from backend.app.services.universe_service import list_universe_symbols, trading_date_for_now

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class FeatureComputationSummary:
    asset_class: str
    timeframe: str
    requested_symbols: tuple[str, ...]
    computed_snapshots: int
    computed_symbols: tuple[str, ...]
    skipped_symbols: tuple[str, ...]
    skipped_reason: str | None = None


class FeatureWorker:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def build_stock_features(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> FeatureComputationSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="stock")
        symbols = self._require_universe_symbols(asset_class="stock", now=now)
        return self._build_features(
            asset_class="stock",
            venue="alpaca",
            timeframe=target_timeframe,
            symbols=symbols,
            now=now,
        )

    def build_crypto_features(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> FeatureComputationSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="crypto")
        symbols = self._require_universe_symbols(asset_class="crypto", now=now)
        return self._build_features(
            asset_class="crypto",
            venue="kraken",
            timeframe=target_timeframe,
            symbols=symbols,
            now=now,
        )

    def _build_features(
        self,
        *,
        asset_class: str,
        venue: str,
        timeframe: str,
        symbols: tuple[str, ...],
        now: datetime | None,
    ) -> FeatureComputationSummary:
        computed_time = self._coerce_datetime(now)
        computed_snapshots = 0
        computed_symbols: list[str] = []
        skipped_symbols: list[str] = []

        for symbol in symbols:
            summary = rebuild_feature_snapshots_for_symbol(
                self.db,
                writer_name=SINGLE_FEATURE_WRITER,
                asset_class=asset_class,
                venue=venue,
                source="feature_engine",
                symbol=symbol,
                timeframe=timeframe,
                computed_at=computed_time,
            )
            computed_snapshots += summary.upserted_rows
            if summary.skipped_reason is None:
                computed_symbols.append(symbol)
            else:
                skipped_symbols.append(symbol)

        logger.info(
            "feature_engine_completed",
            extra={
                "asset_class": asset_class,
                "timeframe": timeframe,
                "requested_symbols": list(symbols),
                "computed_snapshots": computed_snapshots,
                "computed_symbols": computed_symbols,
                "skipped_symbols": skipped_symbols,
            },
        )
        return FeatureComputationSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            requested_symbols=symbols,
            computed_snapshots=computed_snapshots,
            computed_symbols=tuple(computed_symbols),
            skipped_symbols=tuple(skipped_symbols),
            skipped_reason=None if computed_symbols else "no_symbols_computed",
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
