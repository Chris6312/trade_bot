from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from backend.app.common.adapters.models import OrderBookLevel, OrderBookSnapshot
from backend.app.crypto.data.defillama_enrichment import DefiLlamaMarketSnapshot
from backend.app.core.config import Settings
from backend.app.db.session import get_session_factory
from backend.app.models.core import (
    CiCryptoRegimeDisagreement,
    CiCryptoRegimeFeatureSnapshot,
    CiCryptoRegimeOrderbookSnapshot,
    CiCryptoRegimeRun,
    CiCryptoRegimeState,
    Candle,
    FeatureSnapshot,
    RegimeSnapshot,
    SystemEvent,
    UniverseConstituent,
    UniverseRun,
)
from backend.app.services.candle_service import CandleSyncSummary
from backend.app.services.ci_crypto_regime_service import resolve_ci_regime_disagreements
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




def _seed_hurst_candles(db, *, symbol: str, timeframe: str, end_at: datetime, bars: int, start_price: Decimal, step: Decimal) -> None:
    for index in range(bars):
        offset = bars - index
        if timeframe == "1h":
            timestamp = end_at - timedelta(hours=offset)
        else:
            timestamp = end_at - timedelta(hours=offset * 4)
        close = start_price + (step * Decimal(index))
        db.add(
            Candle(
                asset_class="crypto",
                venue="kraken",
                source="seed",
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                open=close - Decimal("1"),
                high=close + Decimal("2"),
                low=close - Decimal("2"),
                close=close,
                volume=Decimal("1000"),
                vwap=close,
                trade_count=100,
            )
        )



def _seed_btc_resolution_candle(db, *, timestamp: datetime, close: str) -> None:
    db.add(
        Candle(
            asset_class="crypto",
            venue="kraken",
            source="seed",
            symbol="XBTUSD",
            timeframe="15m",
            timestamp=timestamp,
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            volume=Decimal("1000"),
            vwap=Decimal(close),
            trade_count=100,
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
    _seed_hurst_candles(db, symbol="XBTUSD", timeframe="1h", end_at=timestamp_1h, bars=240, start_price=Decimal("83000"), step=Decimal("4"))
    _seed_hurst_candles(db, symbol="ETHUSD", timeframe="1h", end_at=timestamp_1h, bars=240, start_price=Decimal("4100"), step=Decimal("0.8"))
    _seed_hurst_candles(db, symbol="XBTUSD", timeframe="4h", end_at=timestamp_4h, bars=120, start_price=Decimal("79000"), step=Decimal("15"))
    _seed_hurst_candles(db, symbol="ETHUSD", timeframe="4h", end_at=timestamp_4h, bars=120, start_price=Decimal("3800"), step=Decimal("2.5"))
    db.flush()


def _fake_orderbook(symbol: str, depth: int) -> OrderBookSnapshot:
    assert depth == 25
    base_price = Decimal("84000") if symbol == "XBTUSD" else Decimal("4300")
    bid_size = Decimal("0.40") if symbol == "XBTUSD" else Decimal("3.00")
    ask_size = Decimal("0.38") if symbol == "XBTUSD" else Decimal("2.90")
    timestamp = datetime(2026, 3, 16, 16, 15, tzinfo=UTC)
    bids = []
    asks = []
    for index in range(25):
        bids.append(
            OrderBookLevel(
                price=base_price - Decimal(str(index)),
                volume=bid_size,
                timestamp=timestamp,
            )
        )
        asks.append(
            OrderBookLevel(
                price=base_price + Decimal("2") + Decimal(str(index)),
                volume=ask_size,
                timestamp=timestamp,
            )
        )
    return OrderBookSnapshot(symbol=symbol, as_of=timestamp, bids=tuple(bids), asks=tuple(asks), raw={"test": True})




def _fake_defillama_snapshot() -> DefiLlamaMarketSnapshot:
    return DefiLlamaMarketSnapshot(
        funding_bias=0.0042,
        open_interest_total=1_250_000_000.0,
        defi_tvl_total=121_000_000_000.0,
        defi_tvl_prev_24h=118_000_000_000.0,
        derivatives_change_1d=6.8,
        as_of_at=datetime(2026, 3, 16, 16, 15, 30, tzinfo=UTC),
        raw={"matched_perps": 4},
    )

def test_ci_worker_persists_run_orderbook_and_api_routes(client) -> None:
    now = datetime(2026, 3, 16, 16, 15, 30, tzinfo=UTC)

    with get_session_factory()() as db:
        upsert_setting(db, key="CI_CRYPTO_REGIME_ENABLED", value="true", value_type="bool")
        upsert_setting(db, key="CI_CRYPTO_REGIME_MIN_BOOK_SNAPSHOTS", value="1", value_type="integer")
        upsert_setting(db, key="CI_CRYPTO_REGIME_MIN_BOOK_SNAPSHOTS_READY", value="1", value_type="integer")
        upsert_setting(db, key="CI_CRYPTO_REGIME_BOOK_WINDOW_SNAPSHOTS", value="1", value_type="integer")
        _seed_full_ci_ready_state(db, now=now)
        db.commit()

    with get_session_factory()() as db:
        summary = CiCryptoRegimeWorker(db, orderbook_fetcher=_fake_orderbook).run(now=now)
        assert summary.status == "success"
        assert summary.run_id is not None
        assert summary.state == "bull"
        assert summary.agreement_with_core == "agree"
        assert summary.advisory_action == "allow"

    current = client.get("/api/v1/ci/crypto-regime/current")
    assert current.status_code == 200
    current_payload = current.json()
    assert current_payload["state"] == "bull"
    assert current_payload["agreement_with_core"] == "agree"
    assert current_payload["model_version"] == "ci_rules_v1"
    assert current_payload["last_run_used_orderbook"] is True
    assert current_payload["orderbook_status"] == "ready"
    assert current_payload["orderbook_ready"] is True
    assert current_payload["last_run_used_hurst"] is True
    assert current_payload["hurst_status"] == "ready"
    assert current_payload["hurst_ready"] is True

    history = client.get("/api/v1/ci/crypto-regime/history?limit=5")
    assert history.status_code == 200
    assert history.json()["items"][0]["state"] == "bull"

    run_id = history.json()["items"][0]["run_id"]
    detail = client.get(f"/api/v1/ci/crypto-regime/runs/{run_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["run"]["status"] == "success"
    assert len(detail_payload["features"]) >= 20
    assert len(detail_payload["orderbook_snapshots"]) == 2
    assert {row["symbol"] for row in detail_payload["orderbook_snapshots"]} == {"XBTUSD", "ETHUSD"}

    with get_session_factory()() as db:
        run = db.query(CiCryptoRegimeRun).order_by(CiCryptoRegimeRun.id.desc()).first()
        state = db.query(CiCryptoRegimeState).order_by(CiCryptoRegimeState.id.desc()).first()
        events = db.query(SystemEvent).filter(SystemEvent.event_source == "ci_crypto_regime_worker").all()
        orderbook_rows = db.query(CiCryptoRegimeOrderbookSnapshot).order_by(CiCryptoRegimeOrderbookSnapshot.id.asc()).all()
        feature_names = {
            row.feature_name
            for row in db.query(CiCryptoRegimeFeatureSnapshot).filter(CiCryptoRegimeFeatureSnapshot.run_id == run.id).all()
        }
        assert run is not None and run.status == "success" and run.used_orderbook is True and run.used_hurst is True
        assert state is not None and state.state == "bull"
        assert len(orderbook_rows) == 2
        assert "microstructure_support_score" in feature_names
        assert {event.event_type for event in events} >= {"ci_crypto_regime.run_started", "ci_crypto_regime.features_built", "ci_crypto_regime.inference_complete"}




def test_ci_worker_uses_defillama_enrichment_when_enabled(client) -> None:
    now = datetime(2026, 3, 16, 16, 15, 30, tzinfo=UTC)

    with get_session_factory()() as db:
        upsert_setting(db, key="CI_CRYPTO_REGIME_ENABLED", value="true", value_type="bool")
        upsert_setting(db, key="CI_CRYPTO_REGIME_USE_DEFILLAMA", value="true", value_type="bool")
        upsert_setting(db, key="CI_CRYPTO_REGIME_MIN_BOOK_SNAPSHOTS", value="1", value_type="integer")
        upsert_setting(db, key="CI_CRYPTO_REGIME_MIN_BOOK_SNAPSHOTS_READY", value="1", value_type="integer")
        upsert_setting(db, key="CI_CRYPTO_REGIME_BOOK_WINDOW_SNAPSHOTS", value="1", value_type="integer")
        _seed_full_ci_ready_state(db, now=now)
        db.commit()

    with get_session_factory()() as db:
        summary = CiCryptoRegimeWorker(
            db,
            orderbook_fetcher=_fake_orderbook,
            defillama_snapshot_fetcher=_fake_defillama_snapshot,
        ).run(now=now)
        assert summary.status == "success"
        assert summary.state == "bull"

    current = client.get("/api/v1/ci/crypto-regime/current")
    assert current.status_code == 200
    current_payload = current.json()
    assert current_payload["last_run_used_defillama"] is True
    assert current_payload["defillama_status"] == "ready"
    assert current_payload["defillama_ready"] is True

    with get_session_factory()() as db:
        run = db.query(CiCryptoRegimeRun).order_by(CiCryptoRegimeRun.id.desc()).first()
        state = db.query(CiCryptoRegimeState).order_by(CiCryptoRegimeState.id.desc()).first()
        feature_names = {
            row.feature_name
            for row in db.query(CiCryptoRegimeFeatureSnapshot).filter(CiCryptoRegimeFeatureSnapshot.run_id == run.id).all()
        }
        assert run is not None and run.used_defillama is True
        assert state is not None and state.summary_json["defillama_status"] == "ready"
        assert {"market_funding_bias", "market_open_interest_z", "market_oi_change_24h", "market_defi_tvl_change_24h"}.issubset(feature_names)

def test_ci_worker_falls_back_when_orderbook_is_unavailable(client) -> None:
    now = datetime(2026, 3, 16, 16, 15, 30, tzinfo=UTC)

    with get_session_factory()() as db:
        upsert_setting(db, key="CI_CRYPTO_REGIME_ENABLED", value="true", value_type="bool")
        upsert_setting(db, key="CI_CRYPTO_REGIME_MIN_BOOK_SNAPSHOTS", value="1", value_type="integer")
        upsert_setting(db, key="CI_CRYPTO_REGIME_MIN_BOOK_SNAPSHOTS_READY", value="1", value_type="integer")
        upsert_setting(db, key="CI_CRYPTO_REGIME_BOOK_WINDOW_SNAPSHOTS", value="1", value_type="integer")
        _seed_full_ci_ready_state(db, now=now)
        db.commit()

    def _boom(symbol: str, depth: int) -> OrderBookSnapshot:  # pragma: no cover - invoked by worker
        raise RuntimeError(f"order book unavailable for {symbol} at depth {depth}")

    with get_session_factory()() as db:
        summary = CiCryptoRegimeWorker(db, orderbook_fetcher=_boom).run(now=now)
        assert summary.status == "partial"
        assert summary.state == "bull"
        assert summary.degraded is True

    with get_session_factory()() as db:
        run = db.query(CiCryptoRegimeRun).order_by(CiCryptoRegimeRun.id.desc()).first()
        state = db.query(CiCryptoRegimeState).order_by(CiCryptoRegimeState.id.desc()).first()
        events = db.query(SystemEvent).filter(SystemEvent.event_source == "ci_crypto_regime_worker").all()
        assert run is not None and run.used_orderbook is False and run.status == "partial"
        assert state is not None and state.summary_json["orderbook_status"] == "unavailable"
        event_types = {event.event_type for event in events}
        assert "ci_crypto_regime.orderbook_unavailable" in event_types
        assert "ci_crypto_regime.run_degraded" in event_types


def test_ci_worker_keeps_hourly_inputs_fresh_until_next_expected_close_plus_buffer(client) -> None:
    now = datetime(2026, 3, 16, 16, 15, 30, tzinfo=UTC)

    with get_session_factory()() as db:
        upsert_setting(db, key="CI_CRYPTO_REGIME_ENABLED", value="true", value_type="bool")
        upsert_setting(db, key="CI_CRYPTO_REGIME_USE_ORDERBOOK", value="false", value_type="bool")
        _seed_full_ci_ready_state(db, now=now)
        db.commit()

    within_window = datetime(2026, 3, 16, 16, 30, 30, tzinfo=UTC)
    with get_session_factory()() as db:
        summary = CiCryptoRegimeWorker(db).run(now=within_window)
        assert summary.status == "success"
        assert summary.state == "bull"
        assert summary.degraded is False
        assert summary.advisory_action == "allow"


def test_ci_worker_marks_stale_feature_data_unavailable_after_timeframe_window_expires(client) -> None:
    now = datetime(2026, 3, 16, 16, 15, 30, tzinfo=UTC)

    with get_session_factory()() as db:
        upsert_setting(db, key="CI_CRYPTO_REGIME_ENABLED", value="true", value_type="bool")
        upsert_setting(db, key="CI_CRYPTO_REGIME_USE_ORDERBOOK", value="false", value_type="bool")
        _seed_full_ci_ready_state(db, now=now)
        db.commit()

    stale_now = datetime(2026, 3, 16, 17, 21, 0, tzinfo=UTC)
    with get_session_factory()() as db:
        summary = CiCryptoRegimeWorker(db).run(now=stale_now)
        assert summary.status == "partial"
        assert summary.state == "unavailable"
        assert summary.degraded is True
        assert summary.advisory_action == "unavailable"




def test_ci_disagreement_scorecard_resolves_after_btc_follow_through(client) -> None:
    from backend.app.services.ci_crypto_regime_service import build_ci_regime_scorecard

    now = datetime(2026, 3, 16, 16, 15, 30, tzinfo=UTC)

    with get_session_factory()() as db:
        upsert_setting(db, key="CI_CRYPTO_REGIME_ENABLED", value="true", value_type="bool")
        upsert_setting(db, key="CI_CRYPTO_REGIME_USE_ORDERBOOK", value="false", value_type="bool")
        _seed_full_ci_ready_state(db, now=now)
        db.query(RegimeSnapshot).delete()
        _seed_core_regime(db, regime="risk_off", computed_at=now.replace(minute=0, second=0, microsecond=0))
        _seed_btc_resolution_candle(db, timestamp=datetime(2026, 3, 16, 16, 15, tzinfo=UTC), close="84000")
        _seed_btc_resolution_candle(db, timestamp=datetime(2026, 3, 16, 20, 15, tzinfo=UTC), close="86000")
        db.commit()

    resolver_now = datetime(2026, 3, 16, 20, 20, tzinfo=UTC)
    with get_session_factory()() as db:
        summary = CiCryptoRegimeWorker(db).run(now=now)
        assert summary.status == "success"
        assert summary.state == "bull"

        disagreement = db.query(CiCryptoRegimeDisagreement).order_by(CiCryptoRegimeDisagreement.id.desc()).first()
        assert disagreement is not None
        assert disagreement.outcome is None

        resolver_summary = resolve_ci_regime_disagreements(db, now=resolver_now)
        db.commit()
        assert resolver_summary["resolved"] == 1

        db.refresh(disagreement)
        assert disagreement.outcome in {"ci_correct", "core_correct", "inconclusive"}
        assert disagreement.resolution_timeframe in {"1h", "4h"}

        scorecard_payload = build_ci_regime_scorecard(db, requested_window="30d", now=resolver_now)
        windows = {item["window"]: item for item in scorecard_payload["windows"]}
        assert windows["30d"]["total_disagreements"] >= 1
        assert (
            windows["30d"]["ci_correct_count"]
            + windows["30d"]["core_correct_count"]
            + windows["30d"]["inconclusive_count"]
            + windows["30d"]["open_count"]
        ) >= 1

    scorecard = client.get("/api/v1/ci/crypto-regime/scorecard?window=30d")
    assert scorecard.status_code == 200
    windows = {item["window"]: item for item in scorecard.json()["windows"]}
    assert windows["30d"]["total_disagreements"] >= 1

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
        assert pipeline_event.id < failure_event.id
