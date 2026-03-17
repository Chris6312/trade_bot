
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.execution_service import (
    SINGLE_EXECUTION_WRITER,
    AdapterResolver,
    rebuild_execution_for_asset_class,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ExecutionRoutingSummary:
    asset_class: str
    timeframe: str
    candidate_count: int
    routed_count: int
    duplicate_count: int
    blocked_count: int
    failed_count: int
    fill_count: int
    venue: str | None
    mode: str | None
    last_status: str
    last_error: str | None
    skipped_reason: str | None = None


class ExecutionWorker:
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

    def route_stock_orders(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> ExecutionRoutingSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="stock")
        return self._route_orders(asset_class="stock", timeframe=target_timeframe, now=now)

    def route_crypto_orders(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> ExecutionRoutingSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="crypto")
        return self._route_orders(asset_class="crypto", timeframe=target_timeframe, now=now)

    def _route_orders(
        self,
        *,
        asset_class: str,
        timeframe: str,
        now: datetime | None,
    ) -> ExecutionRoutingSummary:
        routed_time = self._coerce_datetime(now)
        summary = rebuild_execution_for_asset_class(
            self.db,
            writer_name=SINGLE_EXECUTION_WRITER,
            asset_class=asset_class,
            timeframe=timeframe,
            routed_at=routed_time,
            settings=self.settings,
            adapter_resolver=self.adapter_resolver,
        )
        logger.info(
            "execution_engine_completed",
            extra={
                "asset_class": asset_class,
                "timeframe": timeframe,
                "candidate_count": summary.candidate_count,
                "routed_count": summary.routed_count,
                "duplicate_count": summary.duplicate_count,
                "blocked_count": summary.blocked_count,
                "failed_count": summary.failed_count,
                "fill_count": summary.fill_count,
                "venue": summary.venue,
                "mode": summary.mode,
                "last_status": summary.last_status,
                "last_error": summary.last_error,
            },
        )
        return ExecutionRoutingSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            candidate_count=summary.candidate_count,
            routed_count=summary.routed_count,
            duplicate_count=summary.duplicate_count,
            blocked_count=summary.blocked_count,
            failed_count=summary.failed_count,
            fill_count=summary.fill_count,
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
