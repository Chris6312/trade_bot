from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.risk_service import SINGLE_RISK_WRITER, rebuild_risk_snapshots_for_asset_class

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class RiskComputationSummary:
    asset_class: str
    timeframe: str
    candidate_count: int
    accepted_count: int
    blocked_count: int
    deployment_pct: float
    breaker_status: str | None
    skipped_reason: str | None = None


class RiskWorker:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def build_stock_risk(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> RiskComputationSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="stock")
        return self._build_risk(asset_class="stock", venue="alpaca", timeframe=target_timeframe, now=now)

    def build_crypto_risk(
        self,
        *,
        timeframe: str | None = None,
        now: datetime | None = None,
    ) -> RiskComputationSummary:
        target_timeframe = timeframe or self._default_timeframe(asset_class="crypto")
        return self._build_risk(asset_class="crypto", venue="kraken", timeframe=target_timeframe, now=now)

    def _build_risk(
        self,
        *,
        asset_class: str,
        venue: str,
        timeframe: str,
        now: datetime | None,
    ) -> RiskComputationSummary:
        computed_time = self._coerce_datetime(now)
        summary = rebuild_risk_snapshots_for_asset_class(
            self.db,
            writer_name=SINGLE_RISK_WRITER,
            asset_class=asset_class,
            venue=venue,
            source="risk_engine",
            timeframe=timeframe,
            computed_at=computed_time,
            settings=self.settings,
        )
        logger.info(
            "risk_engine_completed",
            extra={
                "asset_class": asset_class,
                "timeframe": timeframe,
                "candidate_count": summary.candidate_count,
                "accepted_count": summary.accepted_count,
                "blocked_count": summary.blocked_count,
                "deployment_pct": summary.deployment_pct,
                "breaker_status": summary.breaker_status,
                "skipped_reason": summary.skipped_reason,
            },
        )
        return RiskComputationSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            candidate_count=summary.candidate_count,
            accepted_count=summary.accepted_count,
            blocked_count=summary.blocked_count,
            deployment_pct=summary.deployment_pct,
            breaker_status=summary.breaker_status,
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
