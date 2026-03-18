from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.ci_crypto_regime_service import resolve_ci_regime_disagreements

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class CiDisagreementResolverSummary:
    status: str
    resolved: int
    skipped_reason: str | None = None


class CiDisagreementResolverWorker:
    def __init__(self, db: Session, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def run_if_due(self, *, timeframe: str, now: datetime | None = None) -> CiDisagreementResolverSummary:
        run_time = self._coerce_datetime(now)
        if timeframe != "15m":
            return CiDisagreementResolverSummary(status="skipped", resolved=0, skipped_reason="awaiting_ci_slot")
        if run_time.minute != 0:
            return CiDisagreementResolverSummary(status="skipped", resolved=0, skipped_reason="awaiting_resolution_slot")
        payload = resolve_ci_regime_disagreements(self.db, now=run_time)
        logger.info(
            "ci_disagreement_resolver_completed",
            extra={
                "status": payload.get("status"),
                "resolved": payload.get("resolved", 0),
                "skip_reason": payload.get("skip_reason"),
            },
        )
        return CiDisagreementResolverSummary(
            status=str(payload.get("status", "skipped")),
            resolved=int(payload.get("resolved", 0) or 0),
            skipped_reason=payload.get("skip_reason"),
        )

    @staticmethod
    def _coerce_datetime(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
