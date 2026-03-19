from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from backend.app.core.config import Settings
from backend.app.db.session import get_session_factory
from backend.app.models.core import SystemEvent
from backend.app.services.candle_service import CandleSyncSummary
from backend.app.workers.scheduler_worker import SchedulerWorker
from backend.app.workers.universe_worker import UniverseResolutionSummary


class _FakeCandleWorker:
    def __init__(self, db, *, settings):
        self.db = db
        self.settings = settings

    def sync_crypto_incremental(self, *, symbols, timeframe, now):
        return CandleSyncSummary(
            asset_class="crypto",
            timeframe=timeframe,
            requested_symbols=tuple(symbols),
            upserted_bars=0,
            skipped_reason=None,
        )

    def sync_stock_incremental(self, *, symbols, timeframe, now):  # pragma: no cover
        raise AssertionError("stock path should not be used in this test")


class _ForbiddenFeatureWorker:
    def __init__(self, db, *, settings):
        self.db = db
        self.settings = settings

    def build_crypto_features(self, *, timeframe, now):
        raise AssertionError("feature worker should not run when no closed bars were persisted")

    def build_stock_features(self, *, timeframe, now):  # pragma: no cover
        raise AssertionError("stock feature worker should not run in this test")


class _ForbiddenRegimeWorker:
    def __init__(self, db, *, settings):
        self.db = db
        self.settings = settings

    def build_crypto_regime(self, *, timeframe, now):
        raise AssertionError("regime worker should not run when no closed bars were persisted")

    def build_stock_regime(self, *, timeframe, now):  # pragma: no cover
        raise AssertionError("stock regime worker should not run in this test")


class _ForbiddenStrategyWorker:
    def __init__(self, db, *, settings):
        self.db = db
        self.settings = settings

    def build_crypto_candidates(self, *, timeframe, now):
        raise AssertionError("strategy worker should not run when no closed bars were persisted")

    def build_stock_candidates(self, *, timeframe, now):  # pragma: no cover
        raise AssertionError("stock strategy worker should not run in this test")


def test_scheduler_emits_skipped_event_when_due_slot_has_no_closed_bars(client, monkeypatch) -> None:
    now = datetime(2026, 3, 15, 17, 15, 20, tzinfo=UTC)

    monkeypatch.setattr(
        "backend.app.workers.scheduler_worker.list_universe_symbols",
        lambda db, *, asset_class, trade_date: [SimpleNamespace(symbol="ETHUSD")] if asset_class == "crypto" else [],
    )
    monkeypatch.setattr("backend.app.workers.scheduler_worker.SingleCandleWorker", _FakeCandleWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.FeatureWorker", _ForbiddenFeatureWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.RegimeWorker", _ForbiddenRegimeWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.StrategyWorker", _ForbiddenStrategyWorker)

    settings = Settings(
        database_url="sqlite:///unused.db",
        stock_feature_timeframes="",
        crypto_feature_timeframes="15m",
    )
    worker = SchedulerWorker(session_factory=get_session_factory(), settings=settings)
    monkeypatch.setattr(worker, "_ensure_universe_ready", lambda cycle_time: None)
    monkeypatch.setattr(worker, "_run_daily_stock_universe_if_due", lambda cycle_time: None)
    monkeypatch.setattr(
        worker,
        "_resolve_due_close",
        lambda *, asset_class, timeframe, now: datetime(2026, 3, 15, 17, 0, tzinfo=UTC)
        if asset_class == "crypto" and timeframe == "15m"
        else None,
    )

    worker.run_cycle(now)

    with get_session_factory()() as db:
        event = (
            db.query(SystemEvent)
            .filter(SystemEvent.event_type == "scheduler.pipeline_skipped")
            .order_by(SystemEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.payload["asset_class"] == "crypto"
        assert event.payload["timeframe"] == "15m"
        assert event.payload["close_at"] == "2026-03-15T13:00:00-04:00"
        assert event.payload["skipped_reason"] == "no_closed_bars_persisted"


def test_scheduler_emits_nested_stage_payload_for_executed_pipeline(client, monkeypatch) -> None:
    now = datetime(2026, 3, 15, 17, 30, 20, tzinfo=UTC)

    class _ExecutedCandleWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def sync_crypto_incremental(self, *, symbols, timeframe, now):
            return CandleSyncSummary(
                asset_class="crypto",
                timeframe=timeframe,
                requested_symbols=tuple(symbols),
                upserted_bars=12,
                skipped_reason=None,
            )

        def sync_stock_incremental(self, *, symbols, timeframe, now):  # pragma: no cover
            raise AssertionError("stock path should not be used in this test")

    class _ExecutedFeatureWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def build_crypto_features(self, *, timeframe, now):
            return SimpleNamespace(computed_snapshots=6, skipped_reason=None)

        def build_stock_features(self, *, timeframe, now):  # pragma: no cover
            raise AssertionError("stock path should not be used in this test")

    class _ExecutedRegimeWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def build_crypto_regime(self, *, timeframe, now):
            return SimpleNamespace(
                computed_snapshots=1,
                regime="neutral",
                entry_policy="reduced",
                symbol_count=6,
                skipped_reason=None,
            )

        def build_stock_regime(self, *, timeframe, now):  # pragma: no cover
            raise AssertionError("stock path should not be used in this test")

    class _ExecutedStrategyWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def build_crypto_candidates(self, *, timeframe, now):
            return SimpleNamespace(
                regime="neutral",
                entry_policy="reduced",
                evaluated_rows=6,
                blocked_rows=4,
                ready_rows=2,
                skipped_reason=None,
            )

        def build_stock_candidates(self, *, timeframe, now):  # pragma: no cover
            raise AssertionError("stock path should not be used in this test")

    monkeypatch.setattr(
        "backend.app.workers.scheduler_worker.list_universe_symbols",
        lambda db, *, asset_class, trade_date: [SimpleNamespace(symbol="ETHUSD")] if asset_class == "crypto" else [],
    )
    monkeypatch.setattr("backend.app.workers.scheduler_worker.SingleCandleWorker", _ExecutedCandleWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.FeatureWorker", _ExecutedFeatureWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.RegimeWorker", _ExecutedRegimeWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.StrategyWorker", _ExecutedStrategyWorker)

    settings = Settings(
        database_url="sqlite:///unused.db",
        stock_feature_timeframes="",
        crypto_feature_timeframes="15m",
    )
    worker = SchedulerWorker(session_factory=get_session_factory(), settings=settings)
    monkeypatch.setattr(worker, "_ensure_universe_ready", lambda cycle_time: None)
    monkeypatch.setattr(worker, "_run_daily_stock_universe_if_due", lambda cycle_time: None)
    monkeypatch.setattr(
        worker,
        "_resolve_due_close",
        lambda *, asset_class, timeframe, now: datetime(2026, 3, 15, 17, 15, tzinfo=UTC)
        if asset_class == "crypto" and timeframe == "15m"
        else None,
    )

    worker.run_cycle(now)

    with get_session_factory()() as db:
        event = (
            db.query(SystemEvent)
            .filter(SystemEvent.event_type == "scheduler.pipeline_executed")
            .order_by(SystemEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.payload["asset_class"] == "crypto"
        assert event.payload["timeframe"] == "15m"
        assert event.payload["pipeline_status"] == "executed"
        assert event.payload["upserted_bars"] == 12
        assert event.payload["evaluated_rows"] == 6
        assert event.payload["blocked_rows"] == 4
        assert event.payload["ready_rows"] == 2

        candle = event.payload["candle"]
        feature = event.payload["feature"]
        regime = event.payload["regime"]
        strategy = event.payload["strategy"]

        assert candle["status"] == "executed"
        assert candle["upserted_bars"] == 12

        assert feature["status"] == "executed"
        assert feature["computed_snapshots"] == 6

        assert regime["status"] == "executed"
        assert regime["computed_snapshots"] == 1
        assert regime["regime"] == "neutral"
        assert regime["entry_policy"] == "reduced"
        assert regime["symbol_count"] == 6

        assert strategy["status"] == "executed"
        assert strategy["evaluated_rows"] == 6
        assert strategy["blocked_rows"] == 4
        assert strategy["ready_rows"] == 2
        assert strategy["regime"] == "neutral"
        assert strategy["entry_policy"] == "reduced"


def test_scheduler_daily_stock_universe_refresh_backfills_and_runs_strategy(client, monkeypatch) -> None:
    now = datetime(2026, 3, 16, 16, 40, 59, tzinfo=UTC)
    seen_backfill_timeframes: list[str] = []
    seen_strategy_timeframes: list[str] = []

    class _UniverseWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def resolve_stock_universe(self, *, now, force):
            assert force is True
            return UniverseResolutionSummary(
                asset_class="stock",
                trade_date="2026-03-16",
                source="ai",
                symbols=("AAPL", "MSFT"),
                snapshot_path=None,
            )

    class _BackfillCandleWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def sync_stock_backfill(self, *, symbols, timeframe, now):
            seen_backfill_timeframes.append(timeframe)
            assert tuple(symbols) == ("AAPL", "MSFT")
            return CandleSyncSummary(
                asset_class="stock",
                timeframe=timeframe,
                requested_symbols=tuple(symbols),
                upserted_bars=45,
                skipped_reason=None,
            )

        def _is_stock_incremental_window_open(self, *, timeframe, at):
            return True

        def _latest_released_close(self, *, asset_class, timeframe, at):
            return datetime(2026, 3, 16, 16, 30, tzinfo=UTC)

    class _FeatureWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def build_stock_features(self, *, timeframe, now):
            return SimpleNamespace(computed_snapshots=120, skipped_reason=None)

    class _RegimeWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def build_stock_regime(self, *, timeframe, now):
            return SimpleNamespace(
                computed_snapshots=1,
                regime="neutral",
                entry_policy="reduced",
                symbol_count=2,
                skipped_reason=None,
            )

    class _StrategyWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def build_stock_candidates(self, *, timeframe, now):
            seen_strategy_timeframes.append(timeframe)
            return SimpleNamespace(
                regime="neutral",
                entry_policy="reduced",
                evaluated_rows=8,
                blocked_rows=3,
                ready_rows=5,
                skipped_reason=None,
            )

    monkeypatch.setattr(
        "backend.app.workers.scheduler_worker.list_universe_symbols",
        lambda db, *, asset_class, trade_date: [SimpleNamespace(symbol="AAPL"), SimpleNamespace(symbol="MSFT")]
        if asset_class == "stock"
        else [],
    )
    class _NoOpAiResearchWorker:
        def __init__(self, db, *, settings): pass
        def run_if_due(self, *, now, force=False):
            from types import SimpleNamespace
            return SimpleNamespace(status="skipped", trade_date="2026-03-16", pick_count=0, venue="alpaca", error=None)

    monkeypatch.setattr("backend.app.workers.scheduler_worker.AiResearchWorker", _NoOpAiResearchWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.UniverseWorker", _UniverseWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.SingleCandleWorker", _BackfillCandleWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.FeatureWorker", _FeatureWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.RegimeWorker", _RegimeWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.StrategyWorker", _StrategyWorker)

    settings = Settings(
        database_url="sqlite:///unused.db",
        stock_feature_timeframes="1h,15m,5m,1d",
        crypto_feature_timeframes="",
        stock_strategy_timeframes="5m",
        crypto_strategy_timeframes="",
        ai_premarket_time_et="08:40",
    )
    worker = SchedulerWorker(session_factory=get_session_factory(), settings=settings)

    worker._run_daily_stock_universe_if_due(now)

    assert seen_backfill_timeframes == ["1h", "15m", "5m", "1d"]
    assert seen_strategy_timeframes == ["5m"]

    with get_session_factory()() as db:
        refresh_event = (
            db.query(SystemEvent)
            .filter(SystemEvent.event_type == "scheduler.stock_universe_daily_refresh")
            .order_by(SystemEvent.id.desc())
            .first()
        )
        assert refresh_event is not None
        assert refresh_event.payload["source"] == "ai"
        assert refresh_event.payload["symbol_count"] == 2

        pipeline_event = (
            db.query(SystemEvent)
            .filter(SystemEvent.event_type == "scheduler.stock_universe_backfill_and_strategy_refresh")
            .order_by(SystemEvent.id.desc())
            .first()
        )
        assert pipeline_event is not None
        assert pipeline_event.payload["pipeline_status"] == "executed"
        assert [item["timeframe"] for item in pipeline_event.payload["timeframes"]] == ["1h", "15m", "5m", "1d"]
        assert all(item["candle"]["upserted_bars"] == 45 for item in pipeline_event.payload["timeframes"])

        executed_strategy_rows = [
            item for item in pipeline_event.payload["timeframes"]
            if item["strategy"]["status"] == "executed"
        ]
        skipped_strategy_rows = [
            item for item in pipeline_event.payload["timeframes"]
            if item["strategy"]["status"] == "skipped"
        ]

        assert [item["timeframe"] for item in executed_strategy_rows] == ["5m"]
        assert [item["timeframe"] for item in skipped_strategy_rows] == ["1h", "15m", "1d"]
        assert all(item["strategy"]["evaluated_rows"] == 8 for item in executed_strategy_rows)
        assert all(item["strategy"]["ready_rows"] == 5 for item in executed_strategy_rows)
        assert all(item["strategy"]["skipped_reason"] == "filter_only_timeframe" for item in skipped_strategy_rows)