from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.position_service import (
    SINGLE_POSITION_WRITER,
    AdapterResolver,
    PositionSyncSummary,
    rebuild_position_sync_for_asset_class,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PositionWorkerSummary:
    asset_class: str
    timeframe: str
    position_count: int
    open_order_count: int
    mismatch_count: int
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    venue: str | None
    mode: str | None
    last_status: str
    last_error: str | None
    skipped_reason: str | None = None


class PositionWorker:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        adapter_resolver: AdapterResolver | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.adapter_resolver = adapter_resolver

    def sync_stock_positions(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> PositionWorkerSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="stock")
        return self._sync_positions(asset_class="stock", timeframe=target_timeframe, now=now)

    def sync_crypto_positions(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> PositionWorkerSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="crypto")
        return self._sync_positions(asset_class="crypto", timeframe=target_timeframe, now=now)

    def _sync_positions(
        self,
        *,
        asset_class: str,
        timeframe: str,
        now: datetime | None,
    ) -> PositionWorkerSummary:
        synced_at = self._coerce_datetime(now)
        summary: PositionSyncSummary = rebuild_position_sync_for_asset_class(
            self.db,
            writer_name=SINGLE_POSITION_WRITER,
            asset_class=asset_class,
            timeframe=timeframe,
            synced_at=synced_at,
            settings=self.settings,
            adapter_resolver=self.adapter_resolver,
        )
        logger.info(
            "position_sync_completed",
            extra={
                "asset_class": asset_class,
                "timeframe": timeframe,
                "position_count": summary.position_count,
                "open_order_count": summary.open_order_count,
                "mismatch_count": summary.mismatch_count,
                "realized_pnl": str(summary.realized_pnl),
                "unrealized_pnl": str(summary.unrealized_pnl),
                "venue": summary.venue,
                "mode": summary.mode,
                "last_status": summary.last_status,
                "last_error": summary.last_error,
            },
        )
        return PositionWorkerSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            position_count=summary.position_count,
            open_order_count=summary.open_order_count,
            mismatch_count=summary.mismatch_count,
            realized_pnl=summary.realized_pnl,
            unrealized_pnl=summary.unrealized_pnl,
            venue=summary.venue,
            mode=summary.mode,
            last_status=summary.last_status,
            last_error=summary.last_error,
            skipped_reason=summary.skipped_reason,
        )

    def _default_timeframe(self, *, asset_class: str) -> str:
        if asset_class == "stock":
            timeframes = self.settings.stock_strategy_timeframe_list
        else:
            timeframes = self.settings.crypto_strategy_timeframe_list
        return timeframes[0] if timeframes else "1h"

    @staticmethod
    def _coerce_datetime(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
