from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, time as clock_time
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings, get_settings
from backend.app.db.session import get_session_factory
from backend.app.services.operator_service import create_system_event
from backend.app.services.universe_service import list_universe_symbols, trading_date_for_now
from backend.app.workers.candle_worker import SingleCandleWorker
from backend.app.workers.ci_crypto_regime_worker import CiCryptoRegimeWorker
from backend.app.workers.feature_worker import FeatureWorker
from backend.app.workers.regime_worker import RegimeWorker
from backend.app.workers.strategy_worker import StrategyWorker
from backend.app.workers.universe_worker import UniverseWorker

logger = logging.getLogger(__name__)
SCHEDULER_ADVISORY_LOCK_KEY = 631241
DEFAULT_POLL_SECONDS = 5.0


@dataclass(slots=True, frozen=True)
class ScheduledStageSummary:
    status: str
    skipped_reason: str | None = None
    upserted_bars: int = 0
    computed_snapshots: int = 0
    regime: str | None = None
    entry_policy: str | None = None
    symbol_count: int = 0
    evaluated_rows: int = 0
    blocked_rows: int = 0
    ready_rows: int = 0


@dataclass(slots=True, frozen=True)
class ScheduledPipelineSummary:
    asset_class: str
    timeframe: str
    close_at: datetime
    candle: ScheduledStageSummary
    feature: ScheduledStageSummary
    regime: ScheduledStageSummary
    strategy: ScheduledStageSummary
    skipped_reason: str | None = None

    @property
    def pipeline_status(self) -> str:
        return "skipped" if self.skipped_reason is not None else "executed"

    @property
    def upserted_bars(self) -> int:
        return self.candle.upserted_bars

    @property
    def evaluated_rows(self) -> int:
        return self.strategy.evaluated_rows

    @property
    def blocked_rows(self) -> int:
        return self.strategy.blocked_rows

    @property
    def ready_rows(self) -> int:
        return self.strategy.ready_rows


class SchedulerWorker:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        settings: Settings | None = None,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()
        self.settings = settings or get_settings()
        self.poll_seconds = max(2.0, float(poll_seconds))
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started = threading.Event()
        self._lock_session: Session | None = None
        self._has_advisory_lock = False
        self._last_processed_close: dict[tuple[str, str], datetime] = {}
        self._last_daily_stock_universe_date = None
        self._ny_tz = ZoneInfo("America/New_York")
        self._loop_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="trade-bot-scheduler", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
        self._started.clear()

    def _run_loop(self) -> None:
        try:
            self._lock_session = self.session_factory()
            if not self._try_acquire_advisory_lock(self._lock_session):
                logger.info("scheduler_worker_not_started_lock_unavailable")
                return
            self._has_advisory_lock = True
            self._emit_event(
                self._lock_session,
                event_type="scheduler.started",
                severity="info",
                message="Background scheduler worker started.",
                payload={"poll_seconds": self.poll_seconds},
                commit=True,
            )
            self._started.set()

            while not self._stop_event.wait(self.poll_seconds):
                try:
                    with self._loop_lock:
                        self.run_cycle()
                except Exception as exc:  # pragma: no cover
                    logger.exception("scheduler_worker_cycle_failed")
                    self._emit_failure_event(exc)
        finally:
            if self._lock_session is not None:
                if self._has_advisory_lock:
                    try:
                        self._emit_event(
                            self._lock_session,
                            event_type="scheduler.stopped",
                            severity="info",
                            message="Background scheduler worker stopped.",
                            payload=None,
                            commit=True,
                        )
                    except Exception:  # pragma: no cover
                        logger.exception("scheduler_worker_stop_event_failed")
                    self._release_advisory_lock(self._lock_session)
                    self._has_advisory_lock = False
                self._lock_session.close()
                self._lock_session = None

    def run_cycle(self, now: datetime | None = None) -> None:
        cycle_time = now or datetime.now(UTC)
        self._ensure_universe_ready(cycle_time)
        self._run_daily_stock_universe_if_due(cycle_time)
        self._run_incremental_pipelines_if_due(cycle_time)

    def _ensure_universe_ready(self, now: datetime) -> None:
        with self.session_factory() as db:
            worker = UniverseWorker(db, settings=self.settings)
            stock_date = trading_date_for_now(now)
            stock_symbols = list_universe_symbols(db, asset_class="stock", trade_date=stock_date)
            crypto_symbols = list_universe_symbols(db, asset_class="crypto", trade_date=stock_date)
            created: list[str] = []

            if not stock_symbols:
                worker.resolve_stock_universe(now=now, force=False)
                created.append("stock")

            if not crypto_symbols:
                worker.resolve_crypto_universe(now=now, force=False)
                created.append("crypto")

            if created:
                self._emit_event(
                    db,
                    event_type="scheduler.universe_bootstrap",
                    severity="info",
                    message="Scheduler restored missing universe state.",
                    payload={"asset_classes": created},
                    commit=True,
                )

    def _run_daily_stock_universe_if_due(self, now: datetime) -> None:
        local_now = now.astimezone(self._ny_tz)
        if local_now.weekday() >= 5:
            return

        trigger_time = self._parse_daily_trigger_time()
        if local_now.time().replace(tzinfo=None) < trigger_time:
            return

        trigger_date = local_now.date()
        if self._last_daily_stock_universe_date == trigger_date:
            return

        with self.session_factory() as db:
            universe_worker = UniverseWorker(db, settings=self.settings)
            stock_summary = universe_worker.resolve_stock_universe(now=now, force=True)
            payload = {
                "asset_class": "stock",
                "trade_date": stock_summary.trade_date,
                "source": stock_summary.source,
                "symbol_count": len(stock_summary.symbols),
            }
            self._emit_event(
                db,
                event_type="scheduler.stock_universe_daily_refresh",
                severity="info",
                message="Daily stock universe refresh executed.",
                payload=payload,
                commit=True,
            )

        pipeline_summaries = self._run_stock_post_universe_refresh_pipeline(now=now)
        self._emit_stock_post_universe_refresh_event(
            trade_date=stock_summary.trade_date,
            source=stock_summary.source,
            summaries=pipeline_summaries,
        )
        self._last_daily_stock_universe_date = trigger_date

    def _run_incremental_pipelines_if_due(self, now: datetime) -> None:
        for asset_class, timeframes in (
            ("stock", self.settings.stock_feature_timeframe_list),
            ("crypto", self.settings.crypto_feature_timeframe_list),
        ):
            for timeframe in timeframes:
                close_at = self._resolve_due_close(asset_class=asset_class, timeframe=timeframe, now=now)
                if close_at is None:
                    continue

                key = (asset_class, timeframe)
                if self._last_processed_close.get(key) == close_at:
                    continue

                summary = self._run_timeframe_pipeline(
                    asset_class=asset_class,
                    timeframe=timeframe,
                    close_at=close_at,
                    now=now,
                )
                self._last_processed_close[key] = close_at
                self._emit_pipeline_event(summary)

    def _run_stock_post_universe_refresh_pipeline(self, *, now: datetime) -> list[ScheduledPipelineSummary]:
        with self.session_factory() as db:
            candle_worker = SingleCandleWorker(db, settings=self.settings)
            feature_worker = FeatureWorker(db, settings=self.settings)
            regime_worker = RegimeWorker(db, settings=self.settings)
            strategy_worker = StrategyWorker(db, settings=self.settings)
            trade_date = trading_date_for_now(now)
            symbols = [
                row.symbol
                for row in list_universe_symbols(
                    db,
                    asset_class="stock",
                    trade_date=trade_date,
                )
            ]

            summaries: list[ScheduledPipelineSummary] = []
            for timeframe in self.settings.stock_feature_timeframe_list:
                close_at = self._resolve_due_close(asset_class="stock", timeframe=timeframe, now=now) or now
                if not symbols:
                    reason = "universe_unavailable"
                    summaries.append(
                        ScheduledPipelineSummary(
                            asset_class="stock",
                            timeframe=timeframe,
                            close_at=close_at,
                            candle=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            feature=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            regime=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            strategy=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            skipped_reason=reason,
                        )
                    )
                    continue

                candle_summary = candle_worker.sync_stock_backfill(
                    symbols=symbols,
                    timeframe=timeframe,
                    now=now,
                )
                candle_stage = ScheduledStageSummary(
                    status="executed" if candle_summary.skipped_reason is None else "skipped",
                    skipped_reason=candle_summary.skipped_reason,
                    upserted_bars=int(candle_summary.upserted_bars or 0),
                )
                if candle_summary.skipped_reason is not None:
                    reason = candle_summary.skipped_reason
                    summaries.append(
                        ScheduledPipelineSummary(
                            asset_class="stock",
                            timeframe=timeframe,
                            close_at=close_at,
                            candle=candle_stage,
                            feature=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            regime=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            strategy=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            skipped_reason=reason,
                        )
                    )
                    continue

                if candle_stage.upserted_bars <= 0:
                    reason = "no_closed_bars_persisted"
                    summaries.append(
                        ScheduledPipelineSummary(
                            asset_class="stock",
                            timeframe=timeframe,
                            close_at=close_at,
                            candle=candle_stage,
                            feature=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            regime=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            strategy=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                            skipped_reason=reason,
                        )
                    )
                    continue

                feature_summary = feature_worker.build_stock_features(timeframe=timeframe, now=now)
                feature_reason = getattr(feature_summary, "skipped_reason", None)
                feature_stage = ScheduledStageSummary(
                    status="executed" if feature_reason is None else "skipped",
                    skipped_reason=feature_reason,
                    computed_snapshots=int(getattr(feature_summary, "computed_snapshots", 0) or 0),
                )
                if feature_reason is not None:
                    summaries.append(
                        ScheduledPipelineSummary(
                            asset_class="stock",
                            timeframe=timeframe,
                            close_at=close_at,
                            candle=candle_stage,
                            feature=feature_stage,
                            regime=ScheduledStageSummary(status="skipped", skipped_reason=feature_reason),
                            strategy=ScheduledStageSummary(status="skipped", skipped_reason=feature_reason),
                            skipped_reason=feature_reason,
                        )
                    )
                    continue

                regime_summary = regime_worker.build_stock_regime(timeframe=timeframe, now=now)
                regime_reason = getattr(regime_summary, "skipped_reason", None)
                regime_stage = ScheduledStageSummary(
                    status="executed" if regime_reason is None else "skipped",
                    skipped_reason=regime_reason,
                    computed_snapshots=int(getattr(regime_summary, "computed_snapshots", 0) or 0),
                    regime=getattr(regime_summary, "regime", None),
                    entry_policy=getattr(regime_summary, "entry_policy", None),
                    symbol_count=int(getattr(regime_summary, "symbol_count", 0) or 0),
                )
                if regime_reason is not None:
                    summaries.append(
                        ScheduledPipelineSummary(
                            asset_class="stock",
                            timeframe=timeframe,
                            close_at=close_at,
                            candle=candle_stage,
                            feature=feature_stage,
                            regime=regime_stage,
                            strategy=ScheduledStageSummary(status="skipped", skipped_reason=regime_reason),
                            skipped_reason=regime_reason,
                        )
                    )
                    continue

                strategy_summary = strategy_worker.build_stock_candidates(timeframe=timeframe, now=now)
                strategy_reason = getattr(strategy_summary, "skipped_reason", None)
                strategy_stage = ScheduledStageSummary(
                    status="executed" if strategy_reason is None else "skipped",
                    skipped_reason=strategy_reason,
                    regime=getattr(strategy_summary, "regime", None),
                    entry_policy=getattr(strategy_summary, "entry_policy", None),
                    evaluated_rows=int(getattr(strategy_summary, "evaluated_rows", 0) or 0),
                    blocked_rows=int(getattr(strategy_summary, "blocked_rows", 0) or 0),
                    ready_rows=int(getattr(strategy_summary, "ready_rows", 0) or 0),
                )
                summaries.append(
                    ScheduledPipelineSummary(
                        asset_class="stock",
                        timeframe=timeframe,
                        close_at=close_at,
                        candle=candle_stage,
                        feature=feature_stage,
                        regime=regime_stage,
                        strategy=strategy_stage,
                        skipped_reason=strategy_reason,
                    )
                )

                due_close = self._resolve_due_close(asset_class="stock", timeframe=timeframe, now=now)
                if due_close is not None:
                    self._last_processed_close[("stock", timeframe)] = due_close

            return summaries

    def _run_timeframe_pipeline(
        self,
        *,
        asset_class: str,
        timeframe: str,
        close_at: datetime,
        now: datetime,
    ) -> ScheduledPipelineSummary:
        with self.session_factory() as db:
            candle_worker = SingleCandleWorker(db, settings=self.settings)
            feature_worker = FeatureWorker(db, settings=self.settings)
            regime_worker = RegimeWorker(db, settings=self.settings)
            strategy_worker = StrategyWorker(db, settings=self.settings)

            symbols = [
                row.symbol
                for row in list_universe_symbols(
                    db,
                    asset_class=asset_class,
                    trade_date=trading_date_for_now(now),
                )
            ]
            if not symbols:
                reason = "universe_unavailable"
                return ScheduledPipelineSummary(
                    asset_class=asset_class,
                    timeframe=timeframe,
                    close_at=close_at,
                    candle=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    feature=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    regime=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    strategy=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    skipped_reason=reason,
                )

            if asset_class == "stock":
                candle_summary = candle_worker.sync_stock_incremental(
                    symbols=symbols,
                    timeframe=timeframe,
                    now=now,
                )
            else:
                candle_summary = candle_worker.sync_crypto_incremental(
                    symbols=symbols,
                    timeframe=timeframe,
                    now=now,
                )

            candle_stage = ScheduledStageSummary(
                status="executed" if candle_summary.skipped_reason is None else "skipped",
                skipped_reason=candle_summary.skipped_reason,
                upserted_bars=int(candle_summary.upserted_bars or 0),
            )

            if candle_summary.skipped_reason is not None:
                reason = candle_summary.skipped_reason
                return ScheduledPipelineSummary(
                    asset_class=asset_class,
                    timeframe=timeframe,
                    close_at=close_at,
                    candle=candle_stage,
                    feature=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    regime=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    strategy=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    skipped_reason=reason,
                )

            if candle_stage.upserted_bars <= 0:
                reason = "no_closed_bars_persisted"
                return ScheduledPipelineSummary(
                    asset_class=asset_class,
                    timeframe=timeframe,
                    close_at=close_at,
                    candle=candle_stage,
                    feature=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    regime=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    strategy=ScheduledStageSummary(status="skipped", skipped_reason=reason),
                    skipped_reason=reason,
                )

            if asset_class == "stock":
                feature_summary = feature_worker.build_stock_features(timeframe=timeframe, now=now)
            else:
                feature_summary = feature_worker.build_crypto_features(timeframe=timeframe, now=now)

            feature_reason = getattr(feature_summary, "skipped_reason", None)
            feature_stage = ScheduledStageSummary(
                status="executed" if feature_reason is None else "skipped",
                skipped_reason=feature_reason,
                computed_snapshots=int(getattr(feature_summary, "computed_snapshots", 0) or 0),
            )
            if feature_reason is not None:
                return ScheduledPipelineSummary(
                    asset_class=asset_class,
                    timeframe=timeframe,
                    close_at=close_at,
                    candle=candle_stage,
                    feature=feature_stage,
                    regime=ScheduledStageSummary(status="skipped", skipped_reason=feature_reason),
                    strategy=ScheduledStageSummary(status="skipped", skipped_reason=feature_reason),
                    skipped_reason=feature_reason,
                )

            if asset_class == "stock":
                regime_summary = regime_worker.build_stock_regime(timeframe=timeframe, now=now)
            else:
                regime_summary = regime_worker.build_crypto_regime(timeframe=timeframe, now=now)

            regime_reason = getattr(regime_summary, "skipped_reason", None)
            regime_stage = ScheduledStageSummary(
                status="executed" if regime_reason is None else "skipped",
                skipped_reason=regime_reason,
                computed_snapshots=int(getattr(regime_summary, "computed_snapshots", 0) or 0),
                regime=getattr(regime_summary, "regime", None),
                entry_policy=getattr(regime_summary, "entry_policy", None),
                symbol_count=int(getattr(regime_summary, "symbol_count", 0) or 0),
            )
            if regime_reason is not None:
                return ScheduledPipelineSummary(
                    asset_class=asset_class,
                    timeframe=timeframe,
                    close_at=close_at,
                    candle=candle_stage,
                    feature=feature_stage,
                    regime=regime_stage,
                    strategy=ScheduledStageSummary(status="skipped", skipped_reason=regime_reason),
                    skipped_reason=regime_reason,
                )

            if asset_class == "crypto":
                self._run_ci_crypto_regime_advisory(db=db, timeframe=timeframe, now=now)

            if asset_class == "stock":
                strategy_summary = strategy_worker.build_stock_candidates(timeframe=timeframe, now=now)
            else:
                strategy_summary = strategy_worker.build_crypto_candidates(timeframe=timeframe, now=now)

            strategy_reason = getattr(strategy_summary, "skipped_reason", None)
            strategy_stage = ScheduledStageSummary(
                status="executed" if strategy_reason is None else "skipped",
                skipped_reason=strategy_reason,
                regime=getattr(strategy_summary, "regime", None),
                entry_policy=getattr(strategy_summary, "entry_policy", None),
                evaluated_rows=int(getattr(strategy_summary, "evaluated_rows", 0) or 0),
                blocked_rows=int(getattr(strategy_summary, "blocked_rows", 0) or 0),
                ready_rows=int(getattr(strategy_summary, "ready_rows", 0) or 0),
            )

            return ScheduledPipelineSummary(
                asset_class=asset_class,
                timeframe=timeframe,
                close_at=close_at,
                candle=candle_stage,
                feature=feature_stage,
                regime=regime_stage,
                strategy=strategy_stage,
                skipped_reason=strategy_reason,
            )

    def _emit_pipeline_event(self, summary: ScheduledPipelineSummary) -> None:
        event_type = "scheduler.pipeline_executed"
        severity = "info"
        message = f"Scheduled {summary.asset_class} {summary.timeframe} pipeline executed."

        if summary.skipped_reason is not None:
            event_type = "scheduler.pipeline_skipped"
            severity = self._skip_severity(summary.skipped_reason)
            message = f"Scheduled {summary.asset_class} {summary.timeframe} pipeline skipped."

        with self.session_factory() as db:
            self._emit_event(
                db,
                event_type=event_type,
                severity=severity,
                message=message,
                payload={
                    "asset_class": summary.asset_class,
                    "timeframe": summary.timeframe,
                    "close_at": summary.close_at.isoformat(),
                    "pipeline_status": summary.pipeline_status,
                    "upserted_bars": summary.upserted_bars,
                    "evaluated_rows": summary.evaluated_rows,
                    "blocked_rows": summary.blocked_rows,
                    "ready_rows": summary.ready_rows,
                    "skipped_reason": summary.skipped_reason,
                    "candle": self._stage_payload(summary.candle),
                    "feature": self._stage_payload(summary.feature),
                    "regime": self._stage_payload(summary.regime),
                    "strategy": self._stage_payload(summary.strategy),
                },
                commit=True,
            )

    def _emit_stock_post_universe_refresh_event(
        self,
        *,
        trade_date: str,
        source: str,
        summaries: list[ScheduledPipelineSummary],
    ) -> None:
        overall_status = "executed"
        severity = "info"
        if summaries and all(summary.skipped_reason is not None for summary in summaries):
            overall_status = "skipped"
            severity = "warning"
        elif any(summary.skipped_reason is not None for summary in summaries):
            overall_status = "partial"

        with self.session_factory() as db:
            self._emit_event(
                db,
                event_type="scheduler.stock_universe_backfill_and_strategy_refresh",
                severity=severity,
                message="Stock universe post-refresh candle backfill and strategy pipeline executed.",
                payload={
                    "asset_class": "stock",
                    "trade_date": trade_date,
                    "source": source,
                    "pipeline_status": overall_status,
                    "timeframes": [
                        {
                            "timeframe": summary.timeframe,
                            "close_at": summary.close_at.isoformat(),
                            "pipeline_status": summary.pipeline_status,
                            "upserted_bars": summary.upserted_bars,
                            "evaluated_rows": summary.evaluated_rows,
                            "blocked_rows": summary.blocked_rows,
                            "ready_rows": summary.ready_rows,
                            "skipped_reason": summary.skipped_reason,
                            "candle": self._stage_payload(summary.candle),
                            "feature": self._stage_payload(summary.feature),
                            "regime": self._stage_payload(summary.regime),
                            "strategy": self._stage_payload(summary.strategy),
                        }
                        for summary in summaries
                    ],
                },
                commit=True,
            )

    def _emit_failure_event(self, exc: Exception) -> None:
        with self.session_factory() as db:
            self._emit_event(
                db,
                event_type="scheduler.error",
                severity="error",
                message="Background scheduler cycle failed.",
                payload={"error": f"{type(exc).__name__}: {exc}"},
                commit=True,
            )

    def _run_ci_crypto_regime_advisory(self, *, db: Session, timeframe: str, now: datetime) -> None:
        try:
            worker = CiCryptoRegimeWorker(db, settings=self.settings)
            worker.run_if_due(timeframe=timeframe, now=now)
        except Exception as exc:  # pragma: no cover
            logger.exception("scheduler_ci_crypto_regime_failed")
            self._emit_event(
                db,
                event_type="scheduler.ci_crypto_regime_non_blocking_failure",
                severity="warning",
                message="CI crypto regime advisory worker failed, but the main pipeline continued.",
                payload={"timeframe": timeframe, "error": f"{type(exc).__name__}: {exc}"},
                commit=True,
            )

    def _resolve_due_close(self, *, asset_class: str, timeframe: str, now: datetime) -> datetime | None:
        with self.session_factory() as db:
            worker = SingleCandleWorker(db, settings=self.settings)
            if asset_class == "stock" and not worker._is_stock_incremental_window_open(timeframe=timeframe, at=now):
                return None
            close_at = worker._latest_released_close(asset_class=asset_class, timeframe=timeframe, at=now)
            if close_at is None:
                return None
            return close_at

    def _parse_daily_trigger_time(self) -> clock_time:
        raw = str(self.settings.ai_premarket_time_et or "08:40")
        try:
            hours, minutes = raw.split(":", 1)
            return clock_time(hour=int(hours), minute=int(minutes))
        except Exception:
            return clock_time(hour=8, minute=40)

    @staticmethod
    def _stage_payload(stage: ScheduledStageSummary) -> dict[str, object]:
        return {
            "status": stage.status,
            "skipped_reason": stage.skipped_reason,
            "upserted_bars": stage.upserted_bars,
            "computed_snapshots": stage.computed_snapshots,
            "regime": stage.regime,
            "entry_policy": stage.entry_policy,
            "symbol_count": stage.symbol_count,
            "evaluated_rows": stage.evaluated_rows,
            "blocked_rows": stage.blocked_rows,
            "ready_rows": stage.ready_rows,
        }

    @staticmethod
    def _skip_severity(reason: str) -> str:
        if reason in {"no_closed_bars_persisted", "universe_unavailable"}:
            return "warning"
        return "info"

    @staticmethod
    def _emit_event(
        db: Session,
        *,
        event_type: str,
        severity: str,
        message: str,
        payload: dict[str, object] | None,
        commit: bool,
    ) -> None:
        create_system_event(
            db,
            event_type=event_type,
            severity=severity,
            message=message,
            event_source="scheduler_worker",
            payload=payload,
            commit=commit,
        )

    @staticmethod
    def _try_acquire_advisory_lock(db: Session) -> bool:
        bind = db.get_bind()
        if bind is None or bind.dialect.name == "sqlite":
            return True
        acquired = db.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": SCHEDULER_ADVISORY_LOCK_KEY},
        ).scalar()
        return bool(acquired)

    @staticmethod
    def _release_advisory_lock(db: Session) -> None:
        bind = db.get_bind()
        if bind is None or bind.dialect.name == "sqlite":
            return
        db.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": SCHEDULER_ADVISORY_LOCK_KEY},
        )
        db.commit()