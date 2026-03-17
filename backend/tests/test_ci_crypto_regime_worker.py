from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from backend.app.core.config import Settings
from backend.app.db.session import get_session_factory
from backend.app.models.core import (
    CiCryptoRegimeRun,
    CiCryptoRegimeState,
    FeatureSnapshot,
    RegimeSnapshot,
    SystemEvent,
    UniverseConstituent,
    UniverseRun,
)
from backend.app.services.candle_service import CandleSyncSummary
from backend.app.services.settings_service import upsert_setting
from backend.app.workers.ci_crypto_regime_worker import CiCryptoRegimeWorker
from backend.app.workers.scheduler_worker import SchedulerWorker


def _seed_crypto_universe(db, *, trade_date: date) -> None:
    run = UniverseRun(
        asset_class="crypto",
        venue="kraken",
        trade_date=trade_date,
        source="static",
        status="resolved",
        resolved_at=datetime(2026, 3, 16, 16, 0, tzinfo=UTC),
        payload=None,
    )
    db.add(run)
    db.flush()
    for index, symbol in enumerate(("XBTUSD", "ETHUSD", "SOLUSD"), start=1):
        db.add(
            UniverseConstituent(
                universe_run_id=run.id,
                asset_class="crypto",
                venue="kraken",
                symbol=symbol,
                rank=index,
                source="static",
                selection_reason="seeded for ci tests",
                payload=None,
            )
        )
    db.flush()


def _seed_core_regime(db, *, regime: str, computed_at: datetime) -> None:
    db.add(
        RegimeSnapshot(
            asset_class="crypto",
            venue="kraken",
            source="regime_engine",
            timeframe="1h",
            regime_timestamp=computed_at,
            computed_at=computed_at,
            regime=regime,
            entry_policy="full" if regime == "bull" else "reduced",
            symbol_count=3,
            bull_score=Decimal("0.72") if regime == "bull" else Decimal("0.52"),
            breadth_ratio=Decimal("0.66"),
            benchmark_support_ratio=Decimal("1.00"),
            participation_ratio=Decimal("0.88"),
            volatility_support_ratio=Decimal("0.82"),
            payload={"seeded": True},
        )
    )
    db.flush()


def _seed_feature(
    db,
    *,
    symbol: str,
    timeframe: str,
    candle_timestamp: datetime,
    close: str,
    sma_20: str,
    ema_20: str,
    momentum_20: str,
    relative_volume_20: str,
    realized_volatility_20: str,
    trend_slope_20: str,
    price_return_1: str,
) -> None:
    db.add(
        FeatureSnapshot(
            asset_class="crypto",
            venue="kraken",
            source="feature_engine",
            symbol=symbol,
            timeframe=timeframe,
            candle_timestamp=candle_timestamp,
            computed_at=candle_timestamp,
            close=Decimal(close),
            volume=Decimal("1000"),
            price_return_1=Decimal(price_return_1),
            sma_20=Decimal(sma_20),
            ema_20=Decimal(ema_20),
            momentum_20=Decimal(momentum_20),
            volume_sma_20=Decimal("900"),
            relative_volume_20=Decimal(relative_volume_20),
            dollar_volume=Decimal("1000000"),
            dollar_volume_sma_20=Decimal("950000"),
            atr_14=Decimal("5"),
            realized_volatility_20=Decimal(realized_volatility_20),
            trend_slope_20=Decimal(trend_slope_20),
            payload=None,
        )
    )


def _seed_full_ci_ready_state(db, *, now: datetime) -> None:
    _seed_crypto_universe(db, trade_date=now.date())
    _seed_core_regime(db, regime="bull", computed_at=now.replace(minute=0, second=0, microsecond=0))
    timestamp_1h = datetime(2026, 3, 16, 16, 0, tzinfo=UTC)
    timestamp_4h = datetime(2026, 3, 16, 16, 0, tzinfo=UTC)
    for timeframe, ts in (("1h", timestamp_1h), ("4h", timestamp_4h)):
        _seed_feature(
            db,
            symbol="XBTUSD",
            timeframe=timeframe,
            candle_timestamp=ts,
            close="84000",
            sma_20="82000",
            ema_20="82500",
            momentum_20="0.03",
            relative_volume_20="1.12",
            realized_volatility_20="0.018",
            trend_slope_20="12",
            price_return_1="0.012",
        )
        _seed_feature(
            db,
            symbol="ETHUSD",
            timeframe=timeframe,
            candle_timestamp=ts,
            close="4300",
            sma_20="4200",
            ema_20="4225",
            momentum_20="0.025",
            relative_volume_20="1.08",
            realized_volatility_20="0.020",
            trend_slope_20="8",
            price_return_1="0.010",
        )
        _seed_feature(
            db,
            symbol="SOLUSD",
            timeframe=timeframe,
            candle_timestamp=ts,
            close="180",
            sma_20="170",
            ema_20="171",
            momentum_20="0.020",
            relative_volume_20="1.05",
            realized_volatility_20="0.028",
            trend_slope_20="3",
            price_return_1="0.008",
        )
    db.flush()


def test_ci_worker_persists_run_and_api_routes(client) -> None:
    now = datetime(2026, 3, 16, 16, 15, 30, tzinfo=UTC)

    with get_session_factory()() as db:
        upsert_setting(db, key="CI_CRYPTO_REGIME_ENABLED", value="true", value_type="bool")
        _seed_full_ci_ready_state(db, now=now)
        db.commit()

    with get_session_factory()() as db:
        summary = CiCryptoRegimeWorker(db).run(now=now)
        assert summary.status == "success"
        assert summary.run_id is not None
        assert summary.state == "bull"
        assert summary.agreement_with_core == "agree"
        assert summary.advisory_action == "allow"

    current = client.get("/api/v1/ci/crypto-regime/current")
    assert current.status_code == 200
    assert current.json()["state"] == "bull"
    assert current.json()["agreement_with_core"] == "agree"
    assert current.json()["model_version"] == "ci_rules_v1"

    history = client.get("/api/v1/ci/crypto-regime/history?limit=5")
    assert history.status_code == 200
    assert history.json()["items"][0]["state"] == "bull"

    run_id = history.json()["items"][0]["run_id"]
    detail = client.get(f"/api/v1/ci/crypto-regime/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "success"
    assert len(detail.json()["features"]) >= 9

    models = client.get("/api/v1/ci/crypto-regime/models")
    assert models.status_code == 200
    assert models.json()["active_model_version"] == "ci_rules_v1"
    assert models.json()["items"][0]["feature_set_version"] == "ci_crypto_regime_feature_set_v1"

    with get_session_factory()() as db:
        run = db.query(CiCryptoRegimeRun).order_by(CiCryptoRegimeRun.id.desc()).first()
        state = db.query(CiCryptoRegimeState).order_by(CiCryptoRegimeState.id.desc()).first()
        events = db.query(SystemEvent).filter(SystemEvent.event_source == "ci_crypto_regime_worker").all()
        assert run is not None and run.status == "success"
        assert state is not None and state.state == "bull"
        assert {event.event_type for event in events} >= {"ci_crypto_regime.run_started", "ci_crypto_regime.inference_complete"}


def test_ci_worker_marks_stale_feature_data_unavailable(client) -> None:
    now = datetime(2026, 3, 16, 16, 15, 30, tzinfo=UTC)

    with get_session_factory()() as db:
        upsert_setting(db, key="CI_CRYPTO_REGIME_ENABLED", value="true", value_type="bool")
        _seed_full_ci_ready_state(db, now=now)
        db.commit()

    stale_now = datetime(2026, 3, 16, 16, 30, 30, tzinfo=UTC)
    with get_session_factory()() as db:
        summary = CiCryptoRegimeWorker(db).run(now=stale_now)
        assert summary.status == "partial"
        assert summary.state == "unavailable"
        assert summary.degraded is True
        assert summary.advisory_action == "ignore"


def test_scheduler_ci_failure_does_not_block_strategy_pipeline(client, monkeypatch) -> None:
    now = datetime(2026, 3, 16, 17, 15, 20, tzinfo=UTC)

    class _ExecutedCandleWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def sync_crypto_incremental(self, *, symbols, timeframe, now):
            return CandleSyncSummary(
                asset_class="crypto",
                timeframe=timeframe,
                requested_symbols=tuple(symbols),
                upserted_bars=4,
                skipped_reason=None,
            )

        def sync_stock_incremental(self, *, symbols, timeframe, now):  # pragma: no cover
            raise AssertionError("stock path should not be used in this test")

    class _ExecutedFeatureWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def build_crypto_features(self, *, timeframe, now):
            return SimpleNamespace(computed_snapshots=4, skipped_reason=None)

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
                symbol_count=1,
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
                evaluated_rows=3,
                blocked_rows=2,
                ready_rows=1,
                skipped_reason=None,
            )

        def build_stock_candidates(self, *, timeframe, now):  # pragma: no cover
            raise AssertionError("stock path should not be used in this test")

    class _ExplodingCiWorker:
        def __init__(self, db, *, settings):
            self.db = db
            self.settings = settings

        def run_if_due(self, *, timeframe, now):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "backend.app.workers.scheduler_worker.list_universe_symbols",
        lambda db, *, asset_class, trade_date: [SimpleNamespace(symbol="ETHUSD")] if asset_class == "crypto" else [],
    )
    monkeypatch.setattr("backend.app.workers.scheduler_worker.SingleCandleWorker", _ExecutedCandleWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.FeatureWorker", _ExecutedFeatureWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.RegimeWorker", _ExecutedRegimeWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.StrategyWorker", _ExecutedStrategyWorker)
    monkeypatch.setattr("backend.app.workers.scheduler_worker.CiCryptoRegimeWorker", _ExplodingCiWorker)

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
        lambda *, asset_class, timeframe, now: datetime(2026, 3, 16, 17, 0, tzinfo=UTC)
        if asset_class == "crypto" and timeframe == "15m"
        else None,
    )

    worker.run_cycle(now)

    with get_session_factory()() as db:
        pipeline_event = (
            db.query(SystemEvent)
            .filter(SystemEvent.event_type == "scheduler.pipeline_executed")
            .order_by(SystemEvent.id.desc())
            .first()
        )
        failure_event = (
            db.query(SystemEvent)
            .filter(SystemEvent.event_type == "scheduler.ci_crypto_regime_non_blocking_failure")
            .order_by(SystemEvent.id.desc())
            .first()
        )
        assert pipeline_event is not None
        assert pipeline_event.payload["ready_rows"] == 1
        assert failure_event is not None
        assert failure_event.payload["timeframe"] == "15m"
