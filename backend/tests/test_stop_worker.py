from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import get_session_factory
from backend.app.models.core import (
    Candle,
    ExecutionFill,
    ExecutionOrder,
    RiskSnapshot,
    StopState,
    StopSyncState,
    StopUpdateHistory,
)
from backend.app.services.stop_service import get_stop_sync_state
from backend.app.workers.stop_worker import StopWorker


class FailingUpdater:
    def sync_stop(self, request):
        raise RuntimeError("stop broker unavailable")


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase11_stop_worker.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_every_filled_position_receives_initial_fixed_stop_and_persists_state(db_session: Session) -> None:
    _seed_filled_execution_bundle(db_session, asset_class="stock", symbol="AAPL", venue="alpaca", mode="paper")

    summary = StopWorker(
        db_session,
        settings=Settings(stop_stock_style="fixed"),
    ).manage_stock_stops(timeframe="1h", now=datetime(2026, 3, 14, 16, 15, tzinfo=UTC))

    state = db_session.query(StopState).one()
    history = db_session.query(StopUpdateHistory).order_by(StopUpdateHistory.id.asc()).all()
    assert summary.created_count == 1
    assert summary.failed_count == 0
    assert state.stop_style == "fixed"
    assert float(state.initial_stop_price) == pytest.approx(98.0)
    assert float(state.current_stop_price) == pytest.approx(98.0)
    assert state.status == "protected"
    assert state.broker_stop_order_id == "alpaca_stock_paper-stop-1"
    assert len(history) == 2
    assert history[0].event_type == "initial_stop_created"
    assert history[1].event_type == "initial_stop_synced"


def test_trailing_stop_activates_and_raises_from_latest_candle(db_session: Session) -> None:
    _seed_filled_execution_bundle(
        db_session,
        asset_class="crypto",
        symbol="ETHUSD",
        venue="alpaca",
        mode="paper",
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
    )
    _seed_candle(db_session, asset_class="crypto", symbol="ETHUSD", timeframe="1h", close=Decimal("103"), high=Decimal("103"))

    summary = StopWorker(
        db_session,
        settings=Settings(
            stop_crypto_style="trailing",
            crypto_trailing_activation_pct=0.02,
            crypto_trailing_offset_pct=0.01,
        ),
    ).manage_crypto_stops(timeframe="1h", now=datetime(2026, 3, 14, 16, 16, tzinfo=UTC))

    state = db_session.query(StopState).one()
    assert summary.activated_count == 1
    assert summary.created_count == 1
    assert state.trailing_active is True
    assert state.status == "trailing_active"
    assert float(state.current_stop_price) == pytest.approx(101.97)
    assert state.trailing_activated_at is not None
    assert state.trailing_activated_at.replace(tzinfo=UTC) == datetime(2026, 3, 14, 16, 16, tzinfo=UTC)


def test_step_trailing_advances_explicit_levels(db_session: Session) -> None:
    _seed_filled_execution_bundle(
        db_session,
        asset_class="stock",
        symbol="MSFT",
        venue="alpaca",
        mode="paper",
        entry_price=Decimal("100"),
        stop_price=Decimal("98"),
    )
    _seed_candle(db_session, asset_class="stock", symbol="MSFT", timeframe="1h", close=Decimal("104.5"), high=Decimal("104.5"))

    summary = StopWorker(
        db_session,
        settings=Settings(
            stop_stock_style="step",
            stock_step_trigger_pct=0.02,
            stock_step_increment_pct=0.01,
        ),
    ).manage_stock_stops(timeframe="1h", now=datetime(2026, 3, 14, 16, 17, tzinfo=UTC))

    state = db_session.query(StopState).one()
    assert summary.activated_count == 1
    assert state.stop_style == "step"
    assert state.step_level == 2
    assert state.status == "step_active"
    assert float(state.current_stop_price) == pytest.approx(100.0)
    assert float(state.next_step_trigger_price) == pytest.approx(106.0)


@pytest.mark.parametrize(
    ("asset_class", "mode", "venue", "symbol", "expected_route_key", "method_name"),
    [
        ("stock", "live", "public", "AAPL", "public_live", "manage_stock_stops"),
        ("stock", "paper", "alpaca", "AAPL", "alpaca_stock_paper", "manage_stock_stops"),
        ("crypto", "live", "kraken", "XBTUSD", "kraken_live", "manage_crypto_stops"),
        ("crypto", "paper", "alpaca", "ETHUSD", "alpaca_crypto_paper", "manage_crypto_stops"),
    ],
)
def test_stop_manager_uses_broker_specific_update_path(
    db_session: Session,
    asset_class: str,
    mode: str,
    venue: str,
    symbol: str,
    expected_route_key: str,
    method_name: str,
) -> None:
    _seed_filled_execution_bundle(db_session, asset_class=asset_class, symbol=symbol, venue=venue, mode=mode)
    worker = StopWorker(db_session, settings=Settings(default_mode=mode))

    getattr(worker, method_name)(timeframe="1h", now=datetime(2026, 3, 14, 16, 18, tzinfo=UTC))

    state = db_session.query(StopState).one()
    assert state.payload is not None
    assert state.payload["broker_sync"]["route_key"] == expected_route_key


def test_stop_manager_persists_failures_and_sync_state(db_session: Session) -> None:
    _seed_filled_execution_bundle(db_session, asset_class="crypto", symbol="SOLUSD", venue="alpaca", mode="paper")

    summary = StopWorker(
        db_session,
        settings=Settings(stop_crypto_style="fixed"),
        updater_resolver=lambda route: FailingUpdater(),
    ).manage_crypto_stops(timeframe="1h", now=datetime(2026, 3, 14, 16, 19, tzinfo=UTC))

    state = db_session.query(StopState).one()
    sync_state = get_stop_sync_state(db_session, asset_class="crypto", timeframe="1h")
    failure_event = (
        db_session.query(StopUpdateHistory)
        .filter(StopUpdateHistory.event_type == "stop_update_failed")
        .one()
    )
    assert summary.failed_count == 1
    assert state.status == "update_failed"
    assert state.last_error == "stop broker unavailable"
    assert sync_state is not None
    assert sync_state.last_status == "partial_failure"
    assert failure_event.status == "failed"


def test_stop_api_exposes_state_updates_and_sync_summary(client) -> None:
    session = get_session_factory()()
    try:
        _seed_filled_execution_bundle(session, asset_class="stock", symbol="NVDA", venue="alpaca", mode="paper")
        _seed_candle(session, asset_class="stock", symbol="NVDA", timeframe="1h", close=Decimal("102"), high=Decimal("102"))
        StopWorker(
            session,
            settings=Settings(stop_stock_style="trailing", stock_trailing_activation_pct=0.01, stock_trailing_offset_pct=0.005),
        ).manage_stock_stops(timeframe="1h", now=datetime(2026, 3, 14, 16, 20, tzinfo=UTC))
    finally:
        session.close()

    states_response = client.get("/api/v1/stops/stock/current", params={"timeframe": "1h"})
    assert states_response.status_code == 200
    states_payload = states_response.json()
    assert len(states_payload) == 1
    assert states_payload[0]["symbol"] == "NVDA"

    updates_response = client.get("/api/v1/stops/stock/updates", params={"timeframe": "1h"})
    assert updates_response.status_code == 200
    updates_payload = updates_response.json()
    assert updates_payload[0]["event_type"] in {"initial_stop_synced", "trailing_stop_activated", "stop_raised"}

    sync_response = client.get("/api/v1/stops/stock/sync-state", params={"timeframe": "1h"})
    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["created_count"] == 1
    assert sync_payload["filled_count"] == 1


def _seed_filled_execution_bundle(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    venue: str,
    mode: str,
    timeframe: str = "1h",
    entry_price: Decimal = Decimal("100"),
    stop_price: Decimal = Decimal("98"),
    quantity: Decimal = Decimal("1"),
) -> None:
    risk = RiskSnapshot(
        asset_class=asset_class,
        venue=venue,
        source="risk_engine",
        symbol=symbol,
        strategy_name="baseline_long",
        direction="long",
        timeframe=timeframe,
        candidate_timestamp=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
        computed_at=datetime(2026, 3, 14, 15, 1, tzinfo=UTC),
        status="accepted",
        risk_profile="moderate",
        decision_reason="risk_accepted",
        blocked_reasons=[],
        account_equity=Decimal("1000"),
        account_cash=Decimal("1000"),
        entry_price=entry_price,
        stop_price=stop_price,
        stop_distance=entry_price - stop_price,
        stop_distance_pct=(entry_price - stop_price) / entry_price,
        quantity=quantity,
        notional_value=entry_price * quantity,
        deployment_pct=Decimal("0.10"),
        cumulative_deployment_pct=Decimal("0.10"),
        requested_risk_pct=Decimal("0.0125"),
        effective_risk_pct=Decimal("0.0125"),
        max_risk_pct=Decimal("0.02"),
        risk_budget_amount=Decimal("12.5"),
        projected_loss_amount=Decimal("2"),
        projected_loss_pct=Decimal("0.002"),
        fee_pct=Decimal("0.001"),
        slippage_pct=Decimal("0.001"),
        estimated_fees=Decimal("0.10"),
        estimated_slippage=Decimal("0.10"),
        strategy_readiness_score=Decimal("0.75"),
        strategy_composite_score=Decimal("0.75"),
        strategy_threshold_score=Decimal("0.60"),
        payload={"seeded": True},
    )
    db.add(risk)
    db.flush()

    order = ExecutionOrder(
        risk_snapshot_id=risk.id,
        asset_class=asset_class,
        venue=venue,
        mode=mode,
        source="execution_engine",
        symbol=symbol,
        strategy_name="baseline_long",
        direction="long",
        timeframe=timeframe,
        candidate_timestamp=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
        routed_at=datetime(2026, 3, 14, 15, 2, tzinfo=UTC),
        client_order_id=f"{symbol.lower()}-entry-1",
        broker_order_id=f"{symbol.lower()}-broker-1",
        status="filled",
        order_type="market",
        side="buy",
        quantity=quantity,
        notional_value=entry_price * quantity,
        limit_price=None,
        stop_price=stop_price,
        fill_count=1,
        decision_reason="execution_routed",
        error_message=None,
        payload={"seeded": True},
    )
    db.add(order)
    db.flush()

    fill = ExecutionFill(
        execution_order_id=order.id,
        asset_class=asset_class,
        venue=venue,
        mode=mode,
        symbol=symbol,
        timeframe=timeframe,
        fill_timestamp=datetime(2026, 3, 14, 15, 3, tzinfo=UTC),
        status="filled",
        quantity=quantity,
        fill_price=entry_price,
        notional_value=entry_price * quantity,
        fee_amount=Decimal("0.10"),
        venue_fill_id=f"{symbol.lower()}-fill-1",
        payload={"seeded": True},
    )
    db.add(fill)
    db.commit()


def _seed_candle(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
    close: Decimal,
    high: Decimal,
) -> None:
    db.add(
        Candle(
            asset_class=asset_class,
            venue="alpaca" if asset_class == "stock" else "kraken",
            source="candle_worker",
            symbol=symbol,
            timeframe=timeframe,
            timestamp=datetime(2026, 3, 14, 16, 0, tzinfo=UTC),
            open=close,
            high=high,
            low=close,
            close=close,
            volume=Decimal("1000"),
            vwap=close,
            trade_count=100,
        )
    )
    db.commit()
