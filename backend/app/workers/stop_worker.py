from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.stop_service import (
    SINGLE_STOP_WRITER,
    StopManagementSummary,
    StopUpdaterResolver,
    rebuild_stop_manager_for_asset_class,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class StopWorkerSummary:
    asset_class: str
    timeframe: str
    filled_count: int
    created_count: int
    activated_count: int
    updated_count: int
    unchanged_count: int
    failed_count: int
    venue: str | None
    mode: str | None
    last_status: str
    last_error: str | None
    skipped_reason: str | None = None


class StopWorker:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        updater_resolver: StopUpdaterResolver | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.updater_resolver = updater_resolver

    def manage_stock_stops(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> StopWorkerSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="stock")
        return self._manage_stops(asset_class="stock", timeframe=target_timeframe, now=now)

    def manage_crypto_stops(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> StopWorkerSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="crypto")
        return self._manage_stops(asset_class="crypto", timeframe=target_timeframe, now=now)

    def _manage_stops(
        self,
        *,
        asset_class: str,
        timeframe: str,
        now: datetime | None,
    ) -> StopWorkerSummary:
        evaluated_at = self._coerce_datetime(now)
        summary: StopManagementSummary = rebuild_stop_manager_for_asset_class(
            self.db,
            writer_name=SINGLE_STOP_WRITER,
            asset_class=asset_class,
            timeframe=timeframe,
            evaluated_at=evaluated_at,
            settings=self.settings,
            updater_resolver=self.updater_resolver,
        )
        logger.info(
            "stop_manager_completed",
            extra={
                "asset_class": asset_class,
                "timeframe": timeframe,
                "filled_count": summary.filled_count,
                "created_count": summary.created_count,
                "activated_count": summary.activated_count,
                "updated_count": summary.updated_count,
                "unchanged_count": summary.unchanged_count,
                "failed_count": summary.failed_count,
                "venue": summary.venue,
                "mode": summary.mode,
                "last_status": summary.last_status,
                "last_error": summary.last_error,
            },
        )
        return StopWorkerSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            filled_count=summary.filled_count,
            created_count=summary.created_count,
            activated_count=summary.activated_count,
            updated_count=summary.updated_count,
            unchanged_count=summary.unchanged_count,
            failed_count=summary.failed_count,
            venue=summary.venue,
            mode=summary.mode,
            last_status=summary.last_status,
            last_error=summary.last_error,
            skipped_reason=summary.skipped_reason,
        )

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
