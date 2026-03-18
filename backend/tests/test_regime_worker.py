from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import get_session_factory
from backend.app.models.core import FeatureSnapshot
from backend.app.services.regime_service import (
    get_latest_regime_snapshot,
    get_regime_sync_state,
    list_regime_snapshots,
)
from backend.app.services.universe_service import UniverseSymbolRecord, persist_universe_run
from backend.app.workers.regime_worker import RegimeWorker


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase7_regime_worker.db'}")
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
        database_url="sqlite:///phase7_regime_worker.db",
        stock_feature_timeframes="1h",
        crypto_feature_timeframes="1h",
    )


def test_stock_regime_classification_persists_timestamped_queryable_rows(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbols=("SPY", "QQQ", "AAPL"))
    _seed_feature_snapshots(
        db_session,
        asset_class="stock",
        venue="alpaca",
        timeframe="1h",
        rows={
            "SPY": {"close": 105, "sma": 100, "ema": 101, "momentum": 0.05, "rv": 1.15, "vol": 0.01, "slope": 0.02},
            "QQQ": {"close": 110, "sma": 103, "ema": 104, "momentum": 0.04, "rv": 1.05, "vol": 0.012, "slope": 0.018},
            "AAPL": {"close": 208, "sma": 202, "ema": 203, "momentum": 0.03, "rv": 0.98, "vol": 0.011, "slope": 0.014},
        },
    )
    worker = RegimeWorker(db_session, settings=worker_settings)
    computed_at = datetime(2026, 3, 14, 14, 30, tzinfo=UTC)

    summary = worker.build_stock_regime(timeframe="1h", now=computed_at)

    assert summary.computed_snapshots == 1
    assert summary.regime == "bull"
    assert summary.entry_policy == "full"
    latest = get_latest_regime_snapshot(db_session, asset_class="stock", timeframe="1h")
    assert latest is not None
    assert latest.regime == "bull"
    assert latest.entry_policy == "full"
    assert latest.symbol_count == 3
    assert float(latest.breadth_ratio) == 1.0
    assert float(latest.benchmark_support_ratio) == 1.0
    assert float(latest.participation_ratio) == 1.0
    state = get_regime_sync_state(db_session, asset_class="stock", timeframe="1h")
    assert state is not None
    assert state.last_status == "synced"
    assert state.regime == "bull"



def test_crypto_regime_classification_updates_sync_state(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    _seed_universe(db_session, asset_class="crypto", venue="kraken", symbols=("XBTUSD", "ETHUSD", "SOLUSD"))
    _seed_feature_snapshots(
        db_session,
        asset_class="crypto",
        venue="kraken",
        timeframe="1h",
        rows={
            "XBTUSD": {"close": 94, "sma": 100, "ema": 99, "momentum": -0.06, "rv": 0.75, "vol": 0.08, "slope": -0.025},
            "ETHUSD": {"close": 91, "sma": 98, "ema": 97, "momentum": -0.05, "rv": 0.82, "vol": 0.07, "slope": -0.021},
            "SOLUSD": {"close": 88, "sma": 95, "ema": 94, "momentum": -0.07, "rv": 0.70, "vol": 0.09, "slope": -0.03},
        },
    )
    worker = RegimeWorker(db_session, settings=worker_settings)

    summary = worker.build_crypto_regime(timeframe="1h", now=datetime(2026, 3, 14, 15, 0, tzinfo=UTC))

    assert summary.computed_snapshots == 1
    assert summary.regime == "risk_off"
    assert summary.entry_policy == "blocked"
    state = get_regime_sync_state(db_session, asset_class="crypto", timeframe="1h")
    assert state is not None
    assert state.last_status == "synced"
    assert state.regime == "risk_off"
    assert state.entry_policy == "blocked"
    assert state.symbol_count == 3



def test_regime_computations_are_repeatable_from_fixed_inputs(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbols=("SPY", "QQQ", "AAPL"))
    _seed_feature_snapshots(
        db_session,
        asset_class="stock",
        venue="alpaca",
        timeframe="1h",
        rows={
            "SPY": {"close": 102, "sma": 100, "ema": 100.5, "momentum": 0.02, "rv": 1.0, "vol": 0.011, "slope": 0.01},
            "QQQ": {"close": 100, "sma": 99, "ema": 99.2, "momentum": 0.01, "rv": 0.95, "vol": 0.013, "slope": 0.008},
            "AAPL": {"close": 99, "sma": 99, "ema": 98.5, "momentum": 0.005, "rv": 0.91, "vol": 0.015, "slope": 0.004},
        },
    )
    worker = RegimeWorker(db_session, settings=worker_settings)
    computed_at = datetime(2026, 3, 14, 16, 0, tzinfo=UTC)

    first = worker.build_stock_regime(timeframe="1h", now=computed_at)
    first_snapshot = get_latest_regime_snapshot(db_session, asset_class="stock", timeframe="1h")
    second = worker.build_stock_regime(timeframe="1h", now=computed_at)
    second_snapshot = get_latest_regime_snapshot(db_session, asset_class="stock", timeframe="1h")

    assert first.computed_snapshots == second.computed_snapshots == 1
    assert len(list_regime_snapshots(db_session, asset_class="stock", timeframe="1h")) == 1
    assert first_snapshot is not None
    assert second_snapshot is not None
    assert (
        first_snapshot.regime,
        float(first_snapshot.bull_score),
        float(first_snapshot.breadth_ratio),
        float(first_snapshot.benchmark_support_ratio),
        float(first_snapshot.participation_ratio),
        float(first_snapshot.volatility_support_ratio),
    ) == (
        second_snapshot.regime,
        float(second_snapshot.bull_score),
        float(second_snapshot.breadth_ratio),
        float(second_snapshot.benchmark_support_ratio),
        float(second_snapshot.participation_ratio),
        float(second_snapshot.volatility_support_ratio),
    )



def test_regime_api_exposes_current_state(client) -> None:
    session = get_session_factory()()
    try:
        _seed_universe(session, asset_class="stock", venue="alpaca", symbols=("SPY", "QQQ", "AAPL"))
        _seed_feature_snapshots(
            session,
            asset_class="stock",
            venue="alpaca",
            timeframe="1h",
            rows={
                "SPY": {"close": 105, "sma": 100, "ema": 101, "momentum": 0.05, "rv": 1.1, "vol": 0.01, "slope": 0.02},
                "QQQ": {"close": 107, "sma": 103, "ema": 104, "momentum": 0.04, "rv": 1.0, "vol": 0.012, "slope": 0.015},
                "AAPL": {"close": 210, "sma": 205, "ema": 206, "momentum": 0.03, "rv": 0.96, "vol": 0.013, "slope": 0.012},
            },
        )
        worker = RegimeWorker(session)
        worker.build_stock_regime(timeframe="1h", now=datetime(2026, 3, 14, 17, 0, tzinfo=UTC))
    finally:
        session.close()

    response = client.get("/api/v1/regime/stock/current", params={"timeframe": "1h"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_class"] == "stock"
    assert payload["regime"] == "bull"
    assert payload["entry_policy"] == "full"
    assert payload["symbol_count"] == 3
    assert payload["payload"]["benchmark_symbols"] == ["QQQ", "SPY"]



def test_regime_worker_handles_missing_upstream_feature_data(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    _seed_universe(db_session, asset_class="stock", venue="alpaca", symbols=("SPY", "QQQ"))
    worker = RegimeWorker(db_session, settings=worker_settings)

    summary = worker.build_stock_regime(timeframe="1h", now=datetime(2026, 3, 14, 18, 0, tzinfo=UTC))

    assert summary.computed_snapshots == 0
    assert summary.skipped_reason == "no_features"
    state = get_regime_sync_state(db_session, asset_class="stock", timeframe="1h")
    assert state is not None
    assert state.last_status == "no_features"
    assert state.regime is None




def test_regime_api_marks_current_state_stale_when_features_are_newer(client) -> None:
    session = get_session_factory()()
    try:
        _seed_universe(session, asset_class="stock", venue="alpaca", symbols=("SPY", "QQQ", "AAPL"))
        _seed_feature_snapshots(
            session,
            asset_class="stock",
            venue="alpaca",
            timeframe="1h",
            rows={
                "SPY": {"close": 105, "sma": 100, "ema": 101, "momentum": 0.05, "rv": 1.1, "vol": 0.01, "slope": 0.02},
                "QQQ": {"close": 107, "sma": 103, "ema": 104, "momentum": 0.04, "rv": 1.0, "vol": 0.012, "slope": 0.015},
                "AAPL": {"close": 210, "sma": 205, "ema": 206, "momentum": 0.03, "rv": 0.96, "vol": 0.013, "slope": 0.012},
            },
        )
        worker = RegimeWorker(session)
        worker.build_stock_regime(timeframe="1h", now=datetime(2026, 3, 14, 17, 0, tzinfo=UTC))
        snapshot = get_latest_regime_snapshot(session, asset_class="stock", timeframe="1h")
        assert snapshot is not None
        snapshot.regime_timestamp = datetime(2026, 3, 14, 12, 30, tzinfo=UTC)
        snapshot.computed_at = datetime(2026, 3, 14, 12, 35, tzinfo=UTC)
        session.commit()
    finally:
        session.close()

    response = client.get("/api/v1/regime/stock/current", params={"timeframe": "1h"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_stale"] is True
    assert payload["stale_reason"] == "features_newer_than_regime"
    assert payload["latest_feature_at"] == "2026-03-14T13:30:00Z"
    assert payload["feature_lag_seconds"] == 3600

    sync_response = client.get("/api/v1/regime/stock/sync-state", params={"timeframe": "1h"})
    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["is_stale"] is True
    assert sync_payload["stale_reason"] == "features_newer_than_regime"

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



def _seed_feature_snapshots(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    timeframe: str,
    rows: dict[str, dict[str, float]],
) -> None:
    candle_timestamp = datetime(2026, 3, 14, 13, 30, tzinfo=UTC)
    computed_at = datetime(2026, 3, 14, 13, 35, tzinfo=UTC)
    for symbol, metrics in rows.items():
        db.add(
            FeatureSnapshot(
                asset_class=asset_class,
                venue=venue,
                source="feature_engine",
                symbol=symbol,
                timeframe=timeframe,
                candle_timestamp=candle_timestamp,
                computed_at=computed_at,
                close=Decimal(str(metrics["close"])),
                volume=Decimal("1000"),
                price_return_1=Decimal("0.01"),
                sma_20=Decimal(str(metrics["sma"])),
                ema_20=Decimal(str(metrics["ema"])),
                momentum_20=Decimal(str(metrics["momentum"])),
                volume_sma_20=Decimal("900"),
                relative_volume_20=Decimal(str(metrics["rv"])),
                dollar_volume=Decimal("100000"),
                dollar_volume_sma_20=Decimal("95000"),
                atr_14=Decimal("1.5"),
                realized_volatility_20=Decimal(str(metrics["vol"])),
                trend_slope_20=Decimal(str(metrics["slope"])),
                payload={"seeded": True},
            )
        )
    db.commit()
