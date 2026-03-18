from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.base import Base
from backend.app.db.session import get_session_factory
from backend.app.models.core import Candle, FeatureSnapshot, RegimeSnapshot, Setting
from backend.app.services.strategy_service import get_strategy_sync_state, list_current_strategy_snapshots
from backend.app.services.universe_service import UniverseSymbolRecord, persist_universe_run
from backend.app.workers.strategy_worker import StrategyWorker


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase8_strategy_worker.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()



def test_stock_strategy_candidate_generation_persists_ready_and_blocked_rows(db_session: Session) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbols=("AAPL", "TSLA"))
    _seed_stock_ready_symbol(db_session, symbol="AAPL")
    _seed_stock_blocked_symbol(db_session, symbol="TSLA")
    _seed_regime(db_session, asset_class="stock", venue="alpaca", timeframe="1h", regime="bull", entry_policy="full")

    worker = StrategyWorker(db_session)
    summary = worker.build_stock_candidates(timeframe="1h", now=datetime(2026, 3, 14, 14, 0, tzinfo=UTC))

    assert summary.evaluated_rows == 6
    assert summary.ready_rows >= 1
    assert summary.blocked_rows >= 1

    rows = list_current_strategy_snapshots(db_session, asset_class="stock", timeframe="1h")
    assert len(rows) == 6

    aapl_trend = _row(rows, symbol="AAPL", strategy_name="trend_pullback_long")
    assert aapl_trend.status == "ready"
    assert float(aapl_trend.readiness_score) >= 0.60
    assert float(aapl_trend.composite_score) >= float(aapl_trend.threshold_score)

    tsla_trend = _row(rows, symbol="TSLA", strategy_name="trend_pullback_long")
    assert tsla_trend.status == "blocked"
    assert "momentum_too_weak" in (tsla_trend.blocked_reasons or [])

    state = get_strategy_sync_state(db_session, asset_class="stock", timeframe="1h")
    assert state is not None
    assert state.last_status == "synced"
    assert state.ready_count == summary.ready_rows
    assert state.blocked_count == summary.blocked_rows



def test_crypto_strategy_candidate_generation_respects_enable_disable_settings(db_session: Session) -> None:
    _seed_universe(db_session, asset_class="crypto", venue="kraken", symbols=("XBTUSD",))
    _seed_crypto_ready_symbol(db_session, symbol="XBTUSD")
    _seed_regime(db_session, asset_class="crypto", venue="kraken", timeframe="1h", regime="bull", entry_policy="full")
    db_session.add(
        Setting(
            key="strategy_enabled.crypto.breakout_long",
            value="false",
            value_type="bool",
            description="test disable breakout strategy",
            is_secret=False,
        )
    )
    db_session.commit()

    worker = StrategyWorker(db_session)
    summary = worker.build_crypto_candidates(timeframe="1h", now=datetime(2026, 3, 14, 14, 15, tzinfo=UTC))

    assert summary.evaluated_rows == 4
    assert summary.ready_rows >= 1

    rows = list_current_strategy_snapshots(db_session, asset_class="crypto", timeframe="1h")
    breakout_row = _row(rows, symbol="XBTUSD", strategy_name="breakout_long")
    assert breakout_row.status == "blocked"
    assert "strategy_disabled" in (breakout_row.blocked_reasons or [])

    trend_row = _row(rows, symbol="XBTUSD", strategy_name="trend_continuation_long")
    assert trend_row.status == "ready"
    assert float(trend_row.trend_score) > 0.7
    assert float(trend_row.readiness_score) >= 0.61



def test_strategy_engine_respects_persisted_regime_restrictions(db_session: Session) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbols=("AAPL",))
    _seed_stock_ready_symbol(db_session, symbol="AAPL")
    _seed_regime(db_session, asset_class="stock", venue="alpaca", timeframe="1h", regime="risk_off", entry_policy="blocked")

    worker = StrategyWorker(db_session)
    summary = worker.build_stock_candidates(timeframe="1h", now=datetime(2026, 3, 14, 14, 30, tzinfo=UTC))

    assert summary.ready_rows == 0
    assert summary.blocked_rows == 3
    rows = list_current_strategy_snapshots(db_session, asset_class="stock", timeframe="1h")
    assert all("regime_blocked" in (row.blocked_reasons or []) for row in rows)

    state = get_strategy_sync_state(db_session, asset_class="stock", timeframe="1h")
    assert state is not None
    assert state.regime == "risk_off"
    assert state.entry_policy == "blocked"



def test_strategy_engine_handles_missing_upstream_feature_data(db_session: Session) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbols=("AAPL",))
    _seed_regime(db_session, asset_class="stock", venue="alpaca", timeframe="1h", regime="bull", entry_policy="full")

    worker = StrategyWorker(db_session)
    summary = worker.build_stock_candidates(timeframe="1h", now=datetime(2026, 3, 14, 14, 45, tzinfo=UTC))

    assert summary.evaluated_rows == 3
    assert summary.ready_rows == 0
    assert summary.skipped_reason == "no_features"

    rows = list_current_strategy_snapshots(db_session, asset_class="stock", timeframe="1h")
    assert len(rows) == 3
    assert all("missing_feature_snapshot" in (row.blocked_reasons or []) for row in rows)

    state = get_strategy_sync_state(db_session, asset_class="stock", timeframe="1h")
    assert state is not None
    assert state.last_status == "no_features"
    assert state.candidate_count == 3



def test_strategy_api_exposes_score_and_readiness_output(client) -> None:
    session = get_session_factory()()
    try:
        _seed_universe(session, asset_class="stock", venue="alpaca", symbols=("AAPL",))
        _seed_stock_ready_symbol(session, symbol="AAPL")
        _seed_regime(session, asset_class="stock", venue="alpaca", timeframe="1h", regime="bull", entry_policy="full")
        StrategyWorker(session).build_stock_candidates(timeframe="1h", now=datetime(2026, 3, 14, 15, 0, tzinfo=UTC))
    finally:
        session.close()

    response = client.get("/api/v1/strategy/stock/current", params={"timeframe": "1h"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    trend_row = next(item for item in payload if item["strategy_name"] == "trend_pullback_long")
    assert trend_row["symbol"] == "AAPL"
    assert trend_row["status"] == "ready"
    assert float(trend_row["readiness_score"]) >= 0.60
    assert "blocked_reasons" in trend_row

    sync_response = client.get("/api/v1/strategy/stock/sync-state", params={"timeframe": "1h"})
    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["candidate_count"] == 3
    assert sync_payload["ready_count"] >= 1



def test_strategy_api_uses_latest_resolved_universe_when_trade_date_is_not_today(client) -> None:
    session = get_session_factory()()
    try:
        _seed_universe(session, asset_class="stock", venue="alpaca", symbols=("AAPL",))
        _seed_stock_ready_symbol(session, symbol="AAPL")
        _seed_regime(session, asset_class="stock", venue="alpaca", timeframe="1h", regime="bull", entry_policy="full")
        StrategyWorker(session).build_stock_candidates(timeframe="1h", now=datetime(2026, 3, 14, 15, 0, tzinfo=UTC))
    finally:
        session.close()

    response = client.get("/api/v1/strategy/stock/current", params={"timeframe": "1h"})
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_strategy_api_returns_empty_list_when_no_current_rows(client) -> None:
    response = client.get("/api/v1/strategy/stock/current", params={"timeframe": "1h"})
    assert response.status_code == 200
    assert response.json() == []




def test_strategy_engine_treats_stale_regime_as_unavailable(db_session: Session) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbols=("AAPL",))
    _seed_stock_ready_symbol(db_session, symbol="AAPL")
    _seed_regime(db_session, asset_class="stock", venue="alpaca", timeframe="1h", regime="bull", entry_policy="full")

    stale_regime = db_session.query(RegimeSnapshot).filter(RegimeSnapshot.asset_class == "stock", RegimeSnapshot.timeframe == "1h").one()
    stale_regime.regime_timestamp = datetime(2026, 3, 14, 12, 30, tzinfo=UTC)
    stale_regime.computed_at = datetime(2026, 3, 14, 12, 35, tzinfo=UTC)
    db_session.commit()

    worker = StrategyWorker(db_session)
    summary = worker.build_stock_candidates(timeframe="1h", now=datetime(2026, 3, 14, 14, 50, tzinfo=UTC))

    assert summary.skipped_reason == "regime_stale"
    rows = list_current_strategy_snapshots(db_session, asset_class="stock", timeframe="1h")
    assert len(rows) == 3
    assert all("regime_unavailable" in (row.blocked_reasons or []) for row in rows)

    state = get_strategy_sync_state(db_session, asset_class="stock", timeframe="1h")
    assert state is not None
    assert state.last_status == "regime_stale"
    assert state.last_error == "features_newer_than_regime"

def _row(rows, *, symbol: str, strategy_name: str):
    return next(row for row in rows if row.symbol == symbol and row.strategy_name == strategy_name)



def _seed_universe(db: Session, *, asset_class: str, venue: str, symbols: tuple[str, ...]) -> None:
    persist_universe_run(
        db,
        asset_class=asset_class,
        venue=venue,
        trade_date=date(2026, 3, 14),
        source="test",
        status="resolved",
        symbols=[
            UniverseSymbolRecord(
                symbol=symbol,
                rank=index,
                source="test",
                venue=venue,
                asset_class=asset_class,
                selection_reason="test_seed",
                payload={},
            )
            for index, symbol in enumerate(symbols, start=1)
        ],
        resolved_at=datetime(2026, 3, 14, 9, 0, tzinfo=UTC),
        payload={"seeded": True},
    )



def _seed_regime(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    timeframe: str,
    regime: str,
    entry_policy: str,
) -> None:
    db.add(
        RegimeSnapshot(
            asset_class=asset_class,
            venue=venue,
            source="regime_engine",
            timeframe=timeframe,
            regime_timestamp=datetime(2026, 3, 14, 13, 30, tzinfo=UTC),
            computed_at=datetime(2026, 3, 14, 13, 35, tzinfo=UTC),
            regime=regime,
            entry_policy=entry_policy,
            symbol_count=3,
            bull_score=Decimal("0.80") if regime == "bull" else Decimal("0.20"),
            breadth_ratio=Decimal("0.75") if regime == "bull" else Decimal("0.10"),
            benchmark_support_ratio=Decimal("0.70") if regime == "bull" else Decimal("0.10"),
            participation_ratio=Decimal("0.78") if regime == "bull" else Decimal("0.15"),
            volatility_support_ratio=Decimal("0.74") if regime == "bull" else Decimal("0.20"),
            payload={"seeded": True},
        )
    )
    db.commit()



def _seed_stock_ready_symbol(db: Session, *, symbol: str) -> None:
    closes = [100, 100.8, 101.4, 102.0, 102.8, 103.6, 104.2, 104.9, 105.5, 106.0, 106.4, 106.8, 107.1, 107.3, 107.5, 107.7, 107.9, 108.1, 108.3, 108.5, 108.6, 108.8, 109.0, 107.8, 110.0]
    vwaps = [close - 0.4 for close in closes]
    vwaps[-2] = 108.0
    vwaps[-1] = 108.7
    _seed_candles(db, asset_class="stock", venue="alpaca", symbol=symbol, timeframe="1h", closes=closes, vwaps=vwaps)
    _seed_feature_snapshot(
        db,
        asset_class="stock",
        venue="alpaca",
        symbol=symbol,
        timeframe="1h",
        close=110.0,
        price_return_1=0.0204,
        sma=106.0,
        ema=108.9,
        momentum=0.030,
        rv=1.22,
        dollar_volume=1_500_000,
        dollar_volume_sma=1_250_000,
        atr=1.20,
        vol=0.012,
        slope=0.012,
    )



def _seed_stock_blocked_symbol(db: Session, *, symbol: str) -> None:
    closes = [110, 109.5, 109.0, 108.7, 108.4, 108.0, 107.7, 107.4, 107.1, 106.9, 106.7, 106.5, 106.2, 106.0, 105.9, 105.8, 105.7, 105.6, 105.5, 105.4, 105.2, 105.0, 104.8, 104.7, 104.5]
    vwaps = [close + 0.3 for close in closes]
    _seed_candles(db, asset_class="stock", venue="alpaca", symbol=symbol, timeframe="1h", closes=closes, vwaps=vwaps)
    _seed_feature_snapshot(
        db,
        asset_class="stock",
        venue="alpaca",
        symbol=symbol,
        timeframe="1h",
        close=104.5,
        price_return_1=-0.002,
        sma=105.8,
        ema=105.4,
        momentum=-0.010,
        rv=0.72,
        dollar_volume=220_000,
        dollar_volume_sma=250_000,
        atr=2.10,
        vol=0.042,
        slope=-0.006,
    )



def _seed_crypto_ready_symbol(db: Session, *, symbol: str) -> None:
    closes = [28000, 28100, 28250, 28400, 28600, 28750, 28900, 29000, 29150, 29300, 29420, 29540, 29680, 29800, 29950, 30080, 30150, 30220, 30280, 30340, 30380, 30410, 30430, 30320, 30520]
    vwaps = [close - 120 for close in closes]
    vwaps[-2] = 30370
    vwaps[-1] = 30410
    _seed_candles(db, asset_class="crypto", venue="kraken", symbol=symbol, timeframe="1h", closes=closes, vwaps=vwaps)
    _seed_feature_snapshot(
        db,
        asset_class="crypto",
        venue="kraken",
        symbol=symbol,
        timeframe="1h",
        close=30520.0,
        price_return_1=0.018,
        sma=29850.0,
        ema=30120.0,
        momentum=0.040,
        rv=1.15,
        dollar_volume=7_500_000,
        dollar_volume_sma=6_800_000,
        atr=420.0,
        vol=0.025,
        slope=0.015,
    )



def _seed_feature_snapshot(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    symbol: str,
    timeframe: str,
    close: float,
    price_return_1: float,
    sma: float,
    ema: float,
    momentum: float,
    rv: float,
    dollar_volume: float,
    dollar_volume_sma: float,
    atr: float,
    vol: float,
    slope: float,
) -> None:
    db.add(
        FeatureSnapshot(
            asset_class=asset_class,
            venue=venue,
            source="feature_engine",
            symbol=symbol,
            timeframe=timeframe,
            candle_timestamp=datetime(2026, 3, 14, 13, 30, tzinfo=UTC),
            computed_at=datetime(2026, 3, 14, 13, 35, tzinfo=UTC),
            close=Decimal(str(close)),
            volume=Decimal("1000"),
            price_return_1=Decimal(str(price_return_1)),
            sma_20=Decimal(str(sma)),
            ema_20=Decimal(str(ema)),
            momentum_20=Decimal(str(momentum)),
            volume_sma_20=Decimal("900"),
            relative_volume_20=Decimal(str(rv)),
            dollar_volume=Decimal(str(dollar_volume)),
            dollar_volume_sma_20=Decimal(str(dollar_volume_sma)),
            atr_14=Decimal(str(atr)),
            realized_volatility_20=Decimal(str(vol)),
            trend_slope_20=Decimal(str(slope)),
            payload={"seeded": True},
        )
    )
    db.commit()



def _seed_candles(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    symbol: str,
    timeframe: str,
    closes: list[float],
    vwaps: list[float],
) -> None:
    start = datetime(2026, 3, 13, 13, 30, tzinfo=UTC)
    for index, close in enumerate(closes):
        candle = Candle(
            asset_class=asset_class,
            venue=venue,
            source="test_seed",
            symbol=symbol,
            timeframe=timeframe,
            timestamp=start + timedelta(hours=index),
            open=Decimal(str(close - 0.6)),
            high=Decimal(str(close + 0.9)),
            low=Decimal(str(close - 1.1)),
            close=Decimal(str(close)),
            volume=Decimal(str(1000 + (index * 50))),
            vwap=Decimal(str(vwaps[index])),
            trade_count=100 + index,
        )
        db.add(candle)
    db.commit()
