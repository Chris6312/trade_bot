from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.models.core import Candle
from backend.app.services.candle_service import ensure_utc
from backend.app.services.feature_service import (
    get_feature_sync_state,
    get_latest_feature_snapshot,
    list_feature_snapshots,
)
from backend.app.services.universe_service import UniverseSymbolRecord, persist_universe_run
from backend.app.workers.feature_worker import FeatureWorker


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase6_feature_worker.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def worker_settings() -> Settings:
    return Settings(
        database_url="sqlite:///phase6_feature_worker.db",
        stock_feature_timeframes="1h",
        crypto_feature_timeframes="1h",
    )


def test_stock_feature_generation_persists_timestamped_queryable_rows(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbol="AAPL")
    _seed_candles(db_session, asset_class="stock", venue="alpaca", symbol="AAPL", timeframe="1h", bars=25)
    worker = FeatureWorker(db_session, settings=worker_settings)
    computed_at = datetime(2026, 3, 14, 14, 0, tzinfo=UTC)

    summary = worker.build_stock_features(timeframe="1h", now=computed_at)

    assert summary.computed_snapshots == 6
    assert summary.computed_symbols == ("AAPL",)
    snapshots = list_feature_snapshots(db_session, asset_class="stock", symbol="AAPL", timeframe="1h")
    assert len(snapshots) == 6
    latest = get_latest_feature_snapshot(db_session, asset_class="stock", symbol="AAPL", timeframe="1h")
    assert latest is not None
    assert ensure_utc(latest.computed_at) == computed_at
    assert ensure_utc(latest.candle_timestamp) == datetime(2026, 3, 14, 13, 30, tzinfo=UTC)
    assert float(latest.sma_20) > 0
    assert float(latest.relative_volume_20) > 1.0
    assert float(latest.momentum_20) > 0
    assert float(latest.trend_slope_20) > 0


def test_crypto_feature_generation_updates_sync_state(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    _seed_universe(db_session, asset_class="crypto", venue="kraken", symbol="XBTUSD")
    _seed_candles(db_session, asset_class="crypto", venue="kraken", symbol="XBTUSD", timeframe="1h", bars=25)
    worker = FeatureWorker(db_session, settings=worker_settings)

    summary = worker.build_crypto_features(timeframe="1h", now=datetime(2026, 3, 14, 15, 0, tzinfo=UTC))

    assert summary.computed_snapshots == 6
    assert summary.computed_symbols == ("XBTUSD",)
    state = get_feature_sync_state(db_session, asset_class="crypto", symbol="XBTUSD", timeframe="1h")
    assert state is not None
    assert state.last_status == "synced"
    assert state.feature_count == 6
    assert ensure_utc(state.last_candle_at) == datetime(2026, 3, 14, 13, 30, tzinfo=UTC)


def test_feature_computations_are_repeatable_from_fixed_inputs(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbol="AAPL")
    _seed_candles(db_session, asset_class="stock", venue="alpaca", symbol="AAPL", timeframe="1h", bars=25)
    worker = FeatureWorker(db_session, settings=worker_settings)
    computed_at = datetime(2026, 3, 14, 15, 30, tzinfo=UTC)

    first = worker.build_stock_features(timeframe="1h", now=computed_at)
    first_rows = _feature_value_tuples(db_session, asset_class="stock", symbol="AAPL", timeframe="1h")
    second = worker.build_stock_features(timeframe="1h", now=computed_at)
    second_rows = _feature_value_tuples(db_session, asset_class="stock", symbol="AAPL", timeframe="1h")

    assert first.computed_snapshots == second.computed_snapshots == 6
    assert first_rows == second_rows


def test_feature_recalculation_updates_existing_latest_snapshot(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbol="AAPL")
    candles = _seed_candles(db_session, asset_class="stock", venue="alpaca", symbol="AAPL", timeframe="1h", bars=25)
    worker = FeatureWorker(db_session, settings=worker_settings)
    first_run_at = datetime(2026, 3, 14, 16, 0, tzinfo=UTC)
    second_run_at = datetime(2026, 3, 14, 16, 5, tzinfo=UTC)

    first = worker.build_stock_features(timeframe="1h", now=first_run_at)
    before = get_latest_feature_snapshot(db_session, asset_class="stock", symbol="AAPL", timeframe="1h")
    assert before is not None
    before_dollar_volume = float(before.dollar_volume)

    latest_candle = candles[-1]
    latest_candle.close = Decimal("130")
    latest_candle.high = Decimal("131")
    latest_candle.low = Decimal("128")
    latest_candle.volume = Decimal("2500")
    db_session.commit()

    second = worker.build_stock_features(timeframe="1h", now=second_run_at)
    after = get_latest_feature_snapshot(db_session, asset_class="stock", symbol="AAPL", timeframe="1h")
    state = get_feature_sync_state(db_session, asset_class="stock", symbol="AAPL", timeframe="1h")

    assert first.computed_snapshots == second.computed_snapshots == 6
    assert after is not None
    assert len(list_feature_snapshots(db_session, asset_class="stock", symbol="AAPL", timeframe="1h")) == 6
    assert ensure_utc(after.computed_at) == second_run_at
    assert float(after.close) == 130.0
    assert float(after.dollar_volume) == 325000.0
    assert float(after.dollar_volume) != before_dollar_volume
    assert state is not None
    assert state.feature_count == 6
    assert state.last_status == "synced"



def _seed_universe(db: Session, *, asset_class: str, venue: str, symbol: str) -> None:
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
                rank=1,
                source="test",
                venue=venue,
                asset_class=asset_class,
                selection_reason="test_seed",
                payload={},
            )
        ],
        resolved_at=datetime(2026, 3, 14, 9, 0, tzinfo=UTC),
        payload={"seeded": True},
    )



def _seed_candles(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    symbol: str,
    timeframe: str,
    bars: int,
) -> list[Candle]:
    start = datetime(2026, 3, 13, 13, 30, tzinfo=UTC)
    candles: list[Candle] = []
    for index in range(bars):
        close = Decimal(str(100 + index))
        candle = Candle(
            asset_class=asset_class,
            venue=venue,
            source="test_seed",
            symbol=symbol,
            timeframe=timeframe,
            timestamp=start + timedelta(hours=index),
            open=close - Decimal("0.5"),
            high=close + Decimal("1.0"),
            low=close - Decimal("1.0"),
            close=close,
            volume=Decimal(str(1000 + (index * 25))),
            vwap=close - Decimal("0.2"),
            trade_count=100 + index,
        )
        candles.append(candle)
        db.add(candle)
    db.commit()
    return candles



def _feature_value_tuples(db: Session, *, asset_class: str, symbol: str, timeframe: str) -> list[tuple]:
    snapshots = list_feature_snapshots(db, asset_class=asset_class, symbol=symbol, timeframe=timeframe)
    return [
        (
            row.candle_timestamp,
            float(row.sma_20),
            float(row.ema_20),
            float(row.momentum_20),
            float(row.relative_volume_20),
            float(row.atr_14),
            float(row.realized_volatility_20),
            float(row.trend_slope_20),
        )
        for row in snapshots
    ]
