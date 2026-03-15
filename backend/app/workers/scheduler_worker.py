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
from backend.app.workers.feature_worker import FeatureWorker
from backend.app.workers.regime_worker import RegimeWorker
from backend.app.workers.strategy_worker import StrategyWorker
from backend.app.workers.universe_worker import UniverseWorker

logger = logging.getLogger(__name__)
SCHEDULER_ADVISORY_LOCK_KEY = 631241
DEFAULT_POLL_SECONDS = 5.0


@dataclass(slots=True, frozen=True)
class ScheduledPipelineSummary:
    asset_class: str
    timeframe: str
    close_at: datetime
    upserted_bars: int
    evaluated_rows: int
    blocked_rows: int
    ready_rows: int
    skipped_reason: str | None = None


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
                except Exception as exc:  # pragma: no cover - defensive logging path
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
                    except Exception:  # pragma: no cover - shutdown logging guard
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
            self._last_daily_stock_universe_date = trigger_date
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
                summary = self._run_timeframe_pipeline(asset_class=asset_class, timeframe=timeframe, close_at=close_at, now=now)
                self._last_processed_close[key] = close_at
                if summary is None:
                    continue
                self._emit_pipeline_event(summary)

    def _run_timeframe_pipeline(
        self,
        *,
        asset_class: str,
        timeframe: str,
        close_at: datetime,
        now: datetime,
    ) -> ScheduledPipelineSummary | None:
        with self.session_factory() as db:
            candle_worker = SingleCandleWorker(db, settings=self.settings)
            feature_worker = FeatureWorker(db, settings=self.settings)
            regime_worker = RegimeWorker(db, settings=self.settings)
            strategy_worker = StrategyWorker(db, settings=self.settings)
            symbols = [row.symbol for row in list_universe_symbols(db, asset_class=asset_class, trade_date=trading_date_for_now(now))]
            if not symbols:
                return None

            if asset_class == "stock":
                candle_summary = candle_worker.sync_stock_incremental(symbols=symbols, timeframe=timeframe, now=now)
            else:
                candle_summary = candle_worker.sync_crypto_incremental(symbols=symbols, timeframe=timeframe, now=now)

            skipped_reason = candle_summary.skipped_reason
            if skipped_reason in {"awaiting_next_close", "outside_nyse_hours"}:
                return None

            if asset_class == "stock":
                feature_worker.build_stock_features(timeframe=timeframe, now=now)
                regime_worker.build_stock_regime(timeframe=timeframe, now=now)
                strategy_summary = strategy_worker.build_stock_candidates(timeframe=timeframe, now=now)
            else:
                feature_worker.build_crypto_features(timeframe=timeframe, now=now)
                regime_worker.build_crypto_regime(timeframe=timeframe, now=now)
                strategy_summary = strategy_worker.build_crypto_candidates(timeframe=timeframe, now=now)

            return ScheduledPipelineSummary(
                asset_class=asset_class,
                timeframe=timeframe,
                close_at=close_at,
                upserted_bars=candle_summary.upserted_bars,
                evaluated_rows=strategy_summary.evaluated_rows,
                blocked_rows=strategy_summary.blocked_rows,
                ready_rows=strategy_summary.ready_rows,
                skipped_reason=skipped_reason,
            )

    def _emit_pipeline_event(self, summary: ScheduledPipelineSummary) -> None:
        with self.session_factory() as db:
            self._emit_event(
                db,
                event_type="scheduler.pipeline_executed",
                severity="info",
                message=f"Scheduled {summary.asset_class} {summary.timeframe} pipeline executed.",
                payload={
                    "asset_class": summary.asset_class,
                    "timeframe": summary.timeframe,
                    "close_at": summary.close_at.isoformat(),
                    "upserted_bars": summary.upserted_bars,
                    "evaluated_rows": summary.evaluated_rows,
                    "blocked_rows": summary.blocked_rows,
                    "ready_rows": summary.ready_rows,
                    "skipped_reason": summary.skipped_reason,
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
        acquired = db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": SCHEDULER_ADVISORY_LOCK_KEY}).scalar()
        return bool(acquired)

    @staticmethod
    def _release_advisory_lock(db: Session) -> None:
        bind = db.get_bind()
        if bind is None or bind.dialect.name == "sqlite":
            return
        db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SCHEDULER_ADVISORY_LOCK_KEY})
        db.commit()
