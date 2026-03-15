from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.common.adapters.models import AccountPosition, AccountState, OpenOrder, OrderRequest, OrderResult
from backend.app.db.base import Base
from backend.app.db.session import get_session_factory
from backend.app.models.core import AccountSnapshot, Candle, SystemEvent
from backend.app.services.execution_service import list_current_execution_orders
from backend.app.services.position_service import list_current_position_states
from backend.app.services.stop_service import list_current_stop_states
from backend.app.services.strategy_service import list_current_strategy_snapshots
from backend.app.services.universe_service import UniverseSymbolRecord, persist_universe_run, trading_date_for_now
from backend.app.workers.execution_worker import ExecutionWorker
from backend.app.workers.feature_worker import FeatureWorker
from backend.app.workers.position_worker import PositionWorker
from backend.app.workers.regime_worker import RegimeWorker
from backend.app.workers.risk_worker import RiskWorker
from backend.app.workers.stop_worker import StopWorker
from backend.app.workers.strategy_worker import StrategyWorker


PHASE16_STRATEGY_BEFORE_NOW = datetime(2026, 3, 14, 16, 0, tzinfo=UTC)
PHASE16_FEATURE_NOW = datetime(2026, 3, 14, 16, 1, tzinfo=UTC)
PHASE16_STRATEGY_MID_NOW = datetime(2026, 3, 14, 16, 2, tzinfo=UTC)
PHASE16_REGIME_NOW = datetime(2026, 3, 14, 16, 5, tzinfo=UTC)
PHASE16_STRATEGY_READY_NOW = datetime(2026, 3, 14, 16, 10, tzinfo=UTC)
PHASE16_RISK_NOW = datetime(2026, 3, 14, 16, 20, tzinfo=UTC)
PHASE16_EXECUTION_NOW = datetime(2026, 3, 14, 16, 21, tzinfo=UTC)
PHASE16_STOP_NOW = datetime(2026, 3, 14, 16, 25, tzinfo=UTC)
PHASE16_APPEND_PRICE_AT = datetime(2026, 3, 14, 16, 29, tzinfo=UTC)
PHASE16_POSITION_NOW = datetime(2026, 3, 14, 16, 30, tzinfo=UTC)
PHASE16_UNIVERSE_RESOLVED_AT = datetime(2026, 3, 14, 9, 0, tzinfo=UTC)
PHASE16_ACCOUNT_AS_OF = datetime(2026, 3, 14, 15, 0, tzinfo=UTC)


class RecordingExecutionAdapter:
    def __init__(self, *, fill_price: Decimal) -> None:
        self.fill_price = fill_price
        self.requests: list[OrderRequest] = []

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.requests.append(request)
        return OrderResult(
            venue="alpaca",
            asset_class="stock",
            order_id="paper-order-1",
            status="filled",
            raw={
                "filled_qty": str(request.quantity),
                "price": str(self.fill_price),
                "filled_at": "2026-03-14T16:21:00Z",
                "fill_id": "paper-fill-1",
            },
        )


class RecordingPositionSyncAdapter:
    def __init__(self, *, price: Decimal, quantity: Decimal) -> None:
        self.price = price
        self.quantity = quantity
        self.closed = False

    def get_account_state(self) -> AccountState:
        market_value = self.price * self.quantity
        cost_basis = Decimal("110") * self.quantity
        return AccountState(
            venue="alpaca",
            asset_class="stock",
            mode="paper",
            account_id="paper-stock",
            currency="USD",
            equity=Decimal("1004"),
            cash=Decimal("560"),
            buying_power=Decimal("560"),
            positions=(
                AccountPosition(
                    symbol="AAPL",
                    quantity=self.quantity,
                    market_value=market_value,
                    cost_basis=cost_basis,
                    average_entry_price=Decimal("110"),
                    asset_class="stock",
                ),
            ),
        )

    def list_open_orders(self) -> tuple[OpenOrder, ...]:
        return ()

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase16_validation.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_phase16_worker_dependency_order_requires_features_and_regime_before_routing(db_session: Session) -> None:
    _seed_stock_universe(db_session, symbols=("AAPL",))
    _seed_stock_ready_candles(db_session, symbol="AAPL")
    _seed_stock_accounts(db_session)

    strategy_before = StrategyWorker(db_session).build_stock_candidates(
        timeframe="1h",
        now=PHASE16_STRATEGY_BEFORE_NOW,
    )
    assert strategy_before.ready_rows == 0
    assert strategy_before.skipped_reason == "regime_unavailable"
    pre_rows = list_current_strategy_snapshots(db_session, asset_class="stock", timeframe="1h")
    assert all("missing_feature_snapshot" in (row.blocked_reasons or []) for row in pre_rows)

    feature_summary = FeatureWorker(db_session).build_stock_features(
        timeframe="1h",
        now=PHASE16_FEATURE_NOW,
    )
    assert feature_summary.computed_snapshots > 0

    strategy_without_regime = StrategyWorker(db_session).build_stock_candidates(
        timeframe="1h",
        now=PHASE16_STRATEGY_MID_NOW,
    )
    assert strategy_without_regime.ready_rows == 0
    assert strategy_without_regime.skipped_reason == "regime_unavailable"
    mid_rows = list_current_strategy_snapshots(db_session, asset_class="stock", timeframe="1h")
    assert any("regime_unavailable" in (row.blocked_reasons or []) for row in mid_rows)

    regime_summary = RegimeWorker(db_session).build_stock_regime(
        timeframe="1h",
        now=PHASE16_REGIME_NOW,
    )
    assert regime_summary.regime == "bull"

    strategy_after = StrategyWorker(db_session).build_stock_candidates(
        timeframe="1h",
        now=PHASE16_STRATEGY_READY_NOW,
    )
    assert strategy_after.ready_rows >= 1

    risk_summary = RiskWorker(db_session).build_stock_risk(
        timeframe="1h",
        now=PHASE16_RISK_NOW,
    )
    assert risk_summary.accepted_count == 1

    adapter = RecordingExecutionAdapter(fill_price=Decimal("110"))
    execution_summary = ExecutionWorker(
        db_session,
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
    ).route_stock_orders(timeframe="1h", now=PHASE16_EXECUTION_NOW)

    assert execution_summary.routed_count == 1
    assert execution_summary.fill_count == 1
    assert len(adapter.requests) == 1
    orders = list_current_execution_orders(db_session, asset_class="stock", timeframe="1h")
    assert len(orders) == 1
    assert orders[0].status == "filled"


def test_phase16_stock_paper_trade_chain_reaches_stop_and_position_sync(db_session: Session) -> None:
    _run_stock_chain(db_session)

    _append_stock_price(db_session, symbol="AAPL", close=Decimal("111"), timestamp=PHASE16_APPEND_PRICE_AT)
    stop_summary = StopWorker(db_session).manage_stock_stops(
        timeframe="1h",
        now=PHASE16_STOP_NOW,
    )
    assert stop_summary.created_count == 1
    stop_rows = list_current_stop_states(db_session, asset_class="stock", timeframe="1h")
    assert len(stop_rows) == 1
    assert stop_rows[0].status in {"protected", "synced", "virtual_synced"}

    sync_adapter = RecordingPositionSyncAdapter(price=Decimal("111"), quantity=Decimal("4"))
    position_summary = PositionWorker(
        db_session,
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": sync_adapter}),
    ).sync_stock_positions(timeframe="1h", now=PHASE16_POSITION_NOW)

    assert position_summary.position_count == 1
    assert position_summary.mismatch_count == 0
    assert sync_adapter.closed is True
    positions = list_current_position_states(db_session, asset_class="stock", timeframe="1h")
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"
    assert positions[0].reconciliation_status == "matched"
    assert positions[0].unrealized_pnl == Decimal("4")


def test_phase16_operator_ui_smoke_routes_cover_core_control_surfaces(client) -> None:
    session = get_session_factory()()
    try:
        _run_stock_chain(session)
        _append_stock_price(session, symbol="AAPL", close=Decimal("111"), timestamp=PHASE16_APPEND_PRICE_AT)
        StopWorker(session).manage_stock_stops(timeframe="1h", now=PHASE16_STOP_NOW)
        PositionWorker(
            session,
            adapter_resolver=_mapping_resolver(
                {"alpaca_stock_paper": RecordingPositionSyncAdapter(price=Decimal("111"), quantity=Decimal("4"))}
            ),
        ).sync_stock_positions(timeframe="1h", now=PHASE16_POSITION_NOW)
        session.add(SystemEvent(event_type="phase16.smoke", severity="info", message="operator smoke seeded", event_source="tests"))
        session.commit()
    finally:
        session.close()

    responses = {
        "health": client.get("/health"),
        "controls": client.get("/api/v1/controls/snapshot"),
        "runtime": client.get("/api/v1/settings/runtime/snapshot"),
        "universe": client.get("/api/v1/universe/stock/current"),
        "candle_sync": client.get("/api/v1/data/candles/stock/sync-state"),
        "feature_sync": client.get("/api/v1/data/features/stock/sync-state"),
        "strategy": client.get("/api/v1/strategy/stock/current", params={"timeframe": "1h"}),
        "risk": client.get("/api/v1/risk/stock/current", params={"timeframe": "1h"}),
        "execution": client.get("/api/v1/execution/stock/current", params={"timeframe": "1h"}),
        "stops": client.get("/api/v1/stops/stock/current", params={"timeframe": "1h"}),
        "positions": client.get("/api/v1/positions/stock/current", params={"timeframe": "1h"}),
        "account": client.get("/api/v1/account-snapshots/latest/stock"),
        "events": client.get("/api/v1/system-events"),
    }

    assert all(response.status_code == 200 for response in responses.values())
    assert responses["health"].json()["status"] == "ok"
    assert responses["controls"].json()["kill_switch_enabled"] is False
    assert responses["universe"].json()[0]["symbol"] == "AAPL"

    strategy_rows = responses["strategy"].json()
    risk_rows = responses["risk"].json()
    execution_rows = responses["execution"].json()

    assert all(row["symbol"] == "AAPL" for row in strategy_rows)
    assert any(row["status"] == "accepted" for row in risk_rows)
    assert execution_rows[0]["status"] == "filled"
    assert responses["positions"].json()[0]["reconciliation_status"] == "matched"
    assert responses["events"].json()[0]["event_type"] == "phase16.smoke"


def _run_stock_chain(db: Session) -> None:
    _seed_stock_universe(db, symbols=("AAPL",))
    _seed_stock_ready_candles(db, symbol="AAPL")
    _seed_stock_accounts(db)
    FeatureWorker(db).build_stock_features(timeframe="1h", now=PHASE16_FEATURE_NOW)
    RegimeWorker(db).build_stock_regime(timeframe="1h", now=PHASE16_REGIME_NOW)
    StrategyWorker(db).build_stock_candidates(timeframe="1h", now=PHASE16_STRATEGY_READY_NOW)
    RiskWorker(db).build_stock_risk(timeframe="1h", now=PHASE16_RISK_NOW)
    ExecutionWorker(
        db,
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": RecordingExecutionAdapter(fill_price=Decimal("110"))}),
    ).route_stock_orders(timeframe="1h", now=PHASE16_EXECUTION_NOW)


def _seed_stock_universe(db: Session, *, symbols: tuple[str, ...]) -> None:
    for trade_date in _phase16_trade_dates():
        persist_universe_run(
            db,
            asset_class="stock",
            venue="alpaca",
            trade_date=trade_date,
            source="phase16",
            status="resolved",
            symbols=[
                UniverseSymbolRecord(
                    symbol=symbol,
                    rank=index,
                    source="phase16",
                    venue="alpaca",
                    asset_class="stock",
                    selection_reason="validation_seed",
                    payload={"seeded": True},
                )
                for index, symbol in enumerate(symbols, start=1)
            ],
            resolved_at=PHASE16_UNIVERSE_RESOLVED_AT,
            payload={"seeded": True},
        )


def _phase16_trade_dates() -> tuple[date, ...]:
    ordered = [
        trading_date_for_now(PHASE16_STRATEGY_BEFORE_NOW),
        trading_date_for_now(None),
    ]
    deduped: list[date] = []
    for value in ordered:
        if value not in deduped:
            deduped.append(value)
    return tuple(deduped)


def _seed_stock_ready_candles(db: Session, *, symbol: str) -> None:
    closes = [100, 100.8, 101.4, 102.0, 102.8, 103.6, 104.2, 104.9, 105.5, 106.0, 106.4, 106.8, 107.1, 107.3, 107.5, 107.7, 107.9, 108.1, 108.3, 108.5, 108.6, 108.8, 109.0, 107.8, 110.0]
    vwaps = [close - 0.4 for close in closes]
    vwaps[-2] = 108.0
    vwaps[-1] = 108.7
    start = datetime(2026, 3, 13, 13, 30, tzinfo=UTC)
    for index, close in enumerate(closes):
        db.add(
            Candle(
                asset_class="stock",
                venue="alpaca",
                source="phase16_seed",
                symbol=symbol,
                timeframe="1h",
                timestamp=start + timedelta(hours=index),
                open=Decimal(str(close - 0.6)),
                high=Decimal(str(close + 0.9)),
                low=Decimal(str(close - 1.1)),
                close=Decimal(str(close)),
                volume=Decimal(str(1000 + (index * 50))),
                vwap=Decimal(str(vwaps[index])),
                trade_count=100 + index,
            )
        )
    db.commit()


def _append_stock_price(db: Session, *, symbol: str, close: Decimal, timestamp: datetime) -> None:
    db.add(
        Candle(
            asset_class="stock",
            venue="alpaca",
            source="phase16_seed",
            symbol=symbol,
            timeframe="1h",
            timestamp=timestamp,
            open=close - Decimal("0.4"),
            high=close + Decimal("0.6"),
            low=close - Decimal("0.8"),
            close=close,
            volume=Decimal("2600"),
            vwap=close - Decimal("0.2"),
            trade_count=180,
        )
    )
    db.commit()


def _seed_stock_accounts(db: Session) -> None:
    db.add(
        AccountSnapshot(
            account_scope="total",
            venue="aggregate",
            mode="paper",
            equity=Decimal("1000"),
            cash=Decimal("1000"),
            buying_power=Decimal("1000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            as_of=PHASE16_ACCOUNT_AS_OF,
        )
    )
    db.add(
        AccountSnapshot(
            account_scope="stock",
            venue="alpaca",
            mode="paper",
            equity=Decimal("1000"),
            cash=Decimal("1000"),
            buying_power=Decimal("1000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            as_of=PHASE16_ACCOUNT_AS_OF,
        )
    )
    db.commit()


def _mapping_resolver(mapping: dict[str, object]):
    def resolve(route):
        return mapping[route.adapter_key]

    return resolve