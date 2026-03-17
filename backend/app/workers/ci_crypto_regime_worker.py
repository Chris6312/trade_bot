from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.ci_crypto_regime_service import (
    CiCryptoRegimeRunSummary,
    resolve_ci_crypto_regime_settings,
    run_ci_crypto_regime_advisory,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class CiCryptoRegimeWorkerSummary:
    run_id: int | None
    status: str
    state: str | None
    confidence: float | None
    degraded: bool
    skipped_reason: str | None = None
    agreement_with_core: str | None = None
    advisory_action: str | None = None
    model_version: str | None = None


class CiCryptoRegimeWorker:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def run_if_due(
        self,
        *,
        timeframe: str,
        now: datetime | None = None,
    ) -> CiCryptoRegimeWorkerSummary:
        run_time = self._coerce_datetime(now)
        runtime = resolve_ci_crypto_regime_settings(self.db)
        if not runtime.enabled:
            return CiCryptoRegimeWorkerSummary(
                run_id=None,
                status="disabled",
                state=None,
                confidence=None,
                degraded=False,
                skipped_reason="disabled",
                model_version=runtime.model_version,
            )
        if timeframe != "15m":
            return CiCryptoRegimeWorkerSummary(
                run_id=None,
                status="skipped",
                state=None,
                confidence=None,
                degraded=False,
                skipped_reason="awaiting_ci_slot",
                model_version=runtime.model_version,
            )
        return self.run(now=run_time)

    def run(self, *, now: datetime | None = None) -> CiCryptoRegimeWorkerSummary:
        run_time = self._coerce_datetime(now)
        summary = run_ci_crypto_regime_advisory(self.db, now=run_time)
        logger.info(
            "ci_crypto_regime_worker_completed",
            extra={
                "run_id": summary.run_id,
                "status": summary.status,
                "state": summary.state,
                "confidence": summary.confidence,
                "degraded": summary.degraded,
                "skipped_reason": summary.skipped_reason,
                "agreement_with_core": summary.agreement_with_core,
                "advisory_action": summary.advisory_action,
            },
        )
        return self._to_worker_summary(summary)

    @staticmethod
    def _to_worker_summary(summary: CiCryptoRegimeRunSummary) -> CiCryptoRegimeWorkerSummary:
        return CiCryptoRegimeWorkerSummary(
            run_id=summary.run_id,
            status=summary.status,
            state=summary.state,
            confidence=summary.confidence,
            degraded=summary.degraded,
            skipped_reason=summary.skipped_reason,
            agreement_with_core=summary.agreement_with_core,
            advisory_action=summary.advisory_action,
            model_version=summary.model_version,
        )

    @staticmethod
    def _coerce_datetime(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
