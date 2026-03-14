from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.common.adapters.models import AccountPosition, AccountState, OpenOrder
from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import get_session_factory
from backend.app.models.core import AccountSnapshot, Candle, ExecutionFill, ExecutionOrder, PositionState, ReconciliationMismatch, RiskSnapshot, Setting
from backend.app.services.position_service import (
    get_position_sync_state,
    list_active_reconciliation_mismatches,
    list_current_open_orders,
    list_current_position_states,
)
from backend.app.workers.position_worker import PositionWorker


class RecordingSyncAdapter:
    def __init__(
        self,
        *,
        account_state: AccountState,
        open_orders: tuple[OpenOrder, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.account_state = account_state
        self.open_orders = open_orders
        self.error = error
        self.closed = False

    def get_account_state(self) -> AccountState:
        if self.error is not None:
            raise self.error
        return self.account_state

    def list_open_orders(self) -> tuple[OpenOrder, ...]:
        if self.error is not None:
            raise self.error
        return self.open_orders

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase12_position_worker.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_position_sync_persists_positions_and_unrealized_pnl(db_session: Session) -> None:
    _seed_filled_order(
        db_session,
        asset_class="stock",
        symbol="AAPL",
        venue="alpaca",
        mode="paper",
        quantity=Decimal("2"),
        fill_price=Decimal("100"),
    )
    _seed_candle(db_session, asset_class="stock", symbol="AAPL", timeframe="1h", close=Decimal("105"))
    adapter = RecordingSyncAdapter(
        account_state=AccountState(
            venue="alpaca",
            asset_class="stock",
            mode="paper",
            account_id="paper-stock",
            currency="USD",
            equity=Decimal("1000"),
            cash=Decimal("800"),
            buying_power=Decimal("800"),
            positions=(
                AccountPosition(
                    symbol="AAPL",
                    quantity=Decimal("2"),
                    market_value=Decimal("210"),
                    cost_basis=Decimal("200"),
                    average_entry_price=Decimal("100"),
                    asset_class="stock",
                ),
            ),
        )
    )

    summary = PositionWorker(
        db_session,
        settings=Settings(default_mode="paper"),
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
    ).sync_stock_positions(timeframe="1h", now=datetime(2026, 3, 14, 16, 30, tzinfo=UTC))

    rows = list_current_position_states(db_session, asset_class="stock", timeframe="1h")
    latest_snapshot = _latest_account_snapshot(db_session, scope="stock")
    assert summary.position_count == 1
    assert summary.mismatch_count == 0
    assert len(rows) == 1
    assert rows[0].symbol == "AAPL"
    assert rows[0].reconciliation_status == "matched"
    assert rows[0].quantity == Decimal("2")
    assert rows[0].unrealized_pnl == Decimal("10")
    assert latest_snapshot is not None
    assert latest_snapshot.mode == "paper"
    assert latest_snapshot.unrealized_pnl == Decimal("10")


def test_position_sync_persists_open_orders_and_api_visibility(client) -> None:
    session = get_session_factory()()
    try:
        _seed_open_execution_order(
            session,
            asset_class="stock",
            symbol="MSFT",
            venue="alpaca",
            mode="paper",
            broker_order_id="broker-open-1",
            client_order_id="client-open-1",
        )
        adapter = RecordingSyncAdapter(
            account_state=AccountState(
                venue="alpaca",
                asset_class="stock",
                mode="paper",
                account_id="paper-stock",
                currency="USD",
                equity=Decimal("1000"),
                cash=Decimal("1000"),
                buying_power=Decimal("1000"),
                positions=(),
            ),
            open_orders=(
                OpenOrder(
                    symbol="MSFT",
                    order_id="broker-open-1",
                    client_order_id="client-open-1",
                    status="submitted",
                    side="buy",
                    order_type="limit",
                    quantity=Decimal("1"),
                    limit_price=Decimal("300"),
                    submitted_at=datetime(2026, 3, 14, 16, 31, tzinfo=UTC),
                    asset_class="stock",
                ),
            ),
        )
        PositionWorker(
            session,
            settings=Settings(default_mode="paper"),
            adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
        ).sync_stock_positions(timeframe="1h", now=datetime(2026, 3, 14, 16, 32, tzinfo=UTC))
    finally:
        session.close()

    positions_response = client.get("/api/v1/positions/stock/current", params={"timeframe": "1h"})
    assert positions_response.status_code == 404

    open_orders_response = client.get("/api/v1/positions/stock/open-orders", params={"timeframe": "1h"})
    assert open_orders_response.status_code == 200
    open_orders_payload = open_orders_response.json()
    assert len(open_orders_payload) == 1
    assert open_orders_payload[0]["broker_order_id"] == "broker-open-1"
    assert open_orders_payload[0]["reconciliation_status"] == "matched"

    sync_response = client.get("/api/v1/positions/stock/sync-state", params={"timeframe": "1h"})
    assert sync_response.status_code == 200
    assert sync_response.json()["open_order_count"] == 1

    stock_snapshot_response = client.get("/api/v1/account-snapshots/latest/stock")
    assert stock_snapshot_response.status_code == 200
    assert stock_snapshot_response.json()["mode"] == "paper"


def test_position_sync_computes_realized_pnl_for_closed_positions(db_session: Session) -> None:
    order_id = _seed_execution_order(
        db_session,
        asset_class="stock",
        symbol="NVDA",
        venue="alpaca",
        mode="paper",
        side="buy",
        status="filled",
    )
    _seed_fill(
        db_session,
        execution_order_id=order_id,
        asset_class="stock",
        symbol="NVDA",
        mode="paper",
        quantity=Decimal("1"),
        fill_price=Decimal("100"),
        fill_timestamp=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
    )
    sell_order_id = _seed_execution_order(
        db_session,
        asset_class="stock",
        symbol="NVDA",
        venue="alpaca",
        mode="paper",
        side="sell",
        status="filled",
        client_order_id="sell-client-1",
        broker_order_id="sell-broker-1",
    )
    _seed_fill(
        db_session,
        execution_order_id=sell_order_id,
        asset_class="stock",
        symbol="NVDA",
        mode="paper",
        quantity=Decimal("1"),
        fill_price=Decimal("110"),
        fill_timestamp=datetime(2026, 3, 14, 15, 30, tzinfo=UTC),
    )
    adapter = RecordingSyncAdapter(
        account_state=AccountState(
            venue="alpaca",
            asset_class="stock",
            mode="paper",
            account_id="paper-stock",
            currency="USD",
            equity=Decimal("1000"),
            cash=Decimal("1000"),
            buying_power=Decimal("1000"),
            positions=(),
        )
    )

    summary = PositionWorker(
        db_session,
        settings=Settings(default_mode="paper"),
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
    ).sync_stock_positions(timeframe="1h", now=datetime(2026, 3, 14, 16, 33, tzinfo=UTC))

    rows = list_current_position_states(db_session, asset_class="stock", timeframe="1h")
    assert summary.realized_pnl == Decimal("10")
    assert len(rows) == 1
    assert rows[0].status == "closed"
    assert rows[0].quantity == Decimal("0")
    assert rows[0].realized_pnl == Decimal("10")


def test_position_sync_separates_stock_crypto_and_total_pnl_with_mode_labels(db_session: Session) -> None:
    _seed_filled_order(
        db_session,
        asset_class="stock",
        symbol="AMD",
        venue="alpaca",
        mode="paper",
        quantity=Decimal("1"),
        fill_price=Decimal("100"),
    )
    _seed_candle(db_session, asset_class="stock", symbol="AMD", timeframe="1h", close=Decimal("110"))
    _seed_filled_order(
        db_session,
        asset_class="crypto",
        symbol="ETHUSD",
        venue="kraken",
        mode="live",
        quantity=Decimal("0.5"),
        fill_price=Decimal("200"),
    )
    _seed_candle(db_session, asset_class="crypto", symbol="ETHUSD", timeframe="1h", close=Decimal("220"))

    worker = PositionWorker(
        db_session,
        settings=Settings(default_mode="mixed", stock_execution_mode="paper", crypto_execution_mode="live"),
        adapter_resolver=_mapping_resolver(
            {
                "alpaca_stock_paper": RecordingSyncAdapter(
                    account_state=AccountState(
                        venue="alpaca",
                        asset_class="stock",
                        mode="paper",
                        account_id="paper-stock",
                        currency="USD",
                        equity=Decimal("1000"),
                        cash=Decimal("900"),
                        buying_power=Decimal("900"),
                        positions=(
                            AccountPosition(
                                symbol="AMD",
                                quantity=Decimal("1"),
                                market_value=Decimal("110"),
                                cost_basis=Decimal("100"),
                                average_entry_price=Decimal("100"),
                                asset_class="stock",
                            ),
                        ),
                    )
                ),
                "kraken_trading": RecordingSyncAdapter(
                    account_state=AccountState(
                        venue="kraken",
                        asset_class="crypto",
                        mode="live",
                        account_id="crypto-live",
                        currency="USD",
                        equity=Decimal("500"),
                        cash=Decimal("400"),
                        buying_power=Decimal("400"),
                        positions=(
                            AccountPosition(
                                symbol="ETHUSD",
                                quantity=Decimal("0.5"),
                                market_value=Decimal("110"),
                                cost_basis=Decimal("100"),
                                average_entry_price=Decimal("200"),
                                asset_class="crypto",
                            ),
                        ),
                    )
                ),
            }
        ),
    )

    stock_summary = worker.sync_stock_positions(timeframe="1h", now=datetime(2026, 3, 14, 16, 34, tzinfo=UTC))
    crypto_summary = worker.sync_crypto_positions(timeframe="1h", now=datetime(2026, 3, 14, 16, 35, tzinfo=UTC))
    stock_snapshot = _latest_account_snapshot(db_session, scope="stock")
    crypto_snapshot = _latest_account_snapshot(db_session, scope="crypto")
    total_snapshot = _latest_account_snapshot(db_session, scope="total")

    assert stock_summary.unrealized_pnl == Decimal("10")
    assert crypto_summary.unrealized_pnl == Decimal("10")
    assert stock_snapshot is not None and stock_snapshot.mode == "paper"
    assert crypto_snapshot is not None and crypto_snapshot.mode == "live"
    assert total_snapshot is not None
    assert total_snapshot.mode == "mixed"
    assert total_snapshot.unrealized_pnl == Decimal("20")
    assert total_snapshot.equity == Decimal("1500")


def test_position_sync_surfaces_reconciliation_mismatches(db_session: Session) -> None:
    _seed_filled_order(
        db_session,
        asset_class="stock",
        symbol="TSLA",
        venue="alpaca",
        mode="paper",
        quantity=Decimal("2"),
        fill_price=Decimal("100"),
    )
    adapter = RecordingSyncAdapter(
        account_state=AccountState(
            venue="alpaca",
            asset_class="stock",
            mode="paper",
            account_id="paper-stock",
            currency="USD",
            equity=Decimal("1000"),
            cash=Decimal("900"),
            buying_power=Decimal("900"),
            positions=(
                AccountPosition(
                    symbol="TSLA",
                    quantity=Decimal("1"),
                    market_value=Decimal("100"),
                    cost_basis=Decimal("100"),
                    average_entry_price=Decimal("100"),
                    asset_class="stock",
                ),
            ),
        )
    )

    summary = PositionWorker(
        db_session,
        settings=Settings(default_mode="paper"),
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
    ).sync_stock_positions(timeframe="1h", now=datetime(2026, 3, 14, 16, 36, tzinfo=UTC))

    mismatches = list_active_reconciliation_mismatches(db_session, asset_class="stock", timeframe="1h")
    sync_state = get_position_sync_state(db_session, asset_class="stock", timeframe="1h")
    assert summary.mismatch_count == 1
    assert sync_state is not None
    assert sync_state.last_status == "reconciled_with_mismatches"
    assert len(mismatches) == 1
    assert mismatches[0].mismatch_type == "position_quantity_delta"


def _mapping_resolver(mapping: dict[str, RecordingSyncAdapter]):
    def resolve(route):
        return mapping[route.adapter_key]

    return resolve


def _seed_filled_order(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    venue: str,
    mode: str,
    quantity: Decimal,
    fill_price: Decimal,
    timeframe: str = "1h",
) -> int:
    execution_order_id = _seed_execution_order(
        db,
        asset_class=asset_class,
        symbol=symbol,
        venue=venue,
        mode=mode,
        side="buy",
        status="filled",
    )
    _seed_fill(
        db,
        execution_order_id=execution_order_id,
        asset_class=asset_class,
        symbol=symbol,
        mode=mode,
        quantity=quantity,
        fill_price=fill_price,
        fill_timestamp=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
        timeframe=timeframe,
    )
    return execution_order_id


def _seed_execution_order(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    venue: str,
    mode: str,
    side: str,
    status: str,
    timeframe: str = "1h",
    client_order_id: str | None = None,
    broker_order_id: str | None = None,
) -> int:
    risk_offset = db.query(RiskSnapshot).count()
    order_offset = db.query(ExecutionOrder).count()
    risk_row = RiskSnapshot(
        asset_class=asset_class,
        venue=venue,
        source="risk_engine",
        symbol=symbol,
        strategy_name="baseline_long",
        direction="long",
        timeframe=timeframe,
        candidate_timestamp=datetime(2026, 3, 14, 14, 59, risk_offset, tzinfo=UTC),
        computed_at=datetime(2026, 3, 14, 15, 0, risk_offset, tzinfo=UTC),
        status="accepted",
        risk_profile="moderate",
        decision_reason="risk_accepted",
        blocked_reasons=[],
        account_equity=Decimal("1000"),
        account_cash=Decimal("1000"),
        entry_price=Decimal("100"),
        stop_price=Decimal("99"),
        stop_distance=Decimal("1"),
        stop_distance_pct=Decimal("0.01"),
        quantity=Decimal("1"),
        notional_value=Decimal("100"),
        deployment_pct=Decimal("0.1"),
        cumulative_deployment_pct=Decimal("0.1"),
        requested_risk_pct=Decimal("0.0125"),
        effective_risk_pct=Decimal("0.0125"),
        max_risk_pct=Decimal("0.02"),
        risk_budget_amount=Decimal("12.5"),
        projected_loss_amount=Decimal("10"),
        projected_loss_pct=Decimal("0.01"),
        fee_pct=Decimal("0.001"),
        slippage_pct=Decimal("0.001"),
        estimated_fees=Decimal("0"),
        estimated_slippage=Decimal("0"),
        strategy_readiness_score=Decimal("0.8"),
        strategy_composite_score=Decimal("0.8"),
        strategy_threshold_score=Decimal("0.6"),
        payload={"seeded": True},
    )
    db.add(risk_row)
    db.flush()
    order = ExecutionOrder(
        risk_snapshot_id=risk_row.id,
        asset_class=asset_class,
        venue=venue,
        mode=mode,
        source="execution_engine",
        symbol=symbol,
        strategy_name="baseline_long",
        direction="long",
        timeframe=timeframe,
        candidate_timestamp=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
        routed_at=datetime(2026, 3, 14, 15, 1, tzinfo=UTC),
        client_order_id=client_order_id or f"client-{symbol}-{side}-{status}-{order_offset+1}",
        broker_order_id=broker_order_id or f"broker-{symbol}-{side}-{status}-{order_offset+1}",
        status=status,
        order_type="market",
        side=side,
        quantity=Decimal("1"),
        notional_value=Decimal("100"),
        limit_price=None,
        stop_price=Decimal("99"),
        fill_count=1 if status == "filled" else 0,
        decision_reason="execution_seeded",
        error_message=None,
        payload={"seeded": True},
    )
    db.add(order)
    db.commit()
    return order.id


def _seed_fill(
    db: Session,
    *,
    execution_order_id: int,
    asset_class: str,
    symbol: str,
    mode: str,
    quantity: Decimal,
    fill_price: Decimal,
    fill_timestamp: datetime,
    timeframe: str = "1h",
) -> None:
    db.add(
        ExecutionFill(
            execution_order_id=execution_order_id,
            asset_class=asset_class,
            venue="alpaca" if asset_class == "stock" else "kraken",
            mode=mode,
            symbol=symbol,
            timeframe=timeframe,
            fill_timestamp=fill_timestamp,
            status="filled",
            quantity=quantity,
            fill_price=fill_price,
            notional_value=quantity * fill_price,
            fee_amount=Decimal("0"),
            venue_fill_id=f"fill-{symbol}-{execution_order_id}",
            payload={"seeded": True},
        )
    )
    db.commit()


def _seed_open_execution_order(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    venue: str,
    mode: str,
    broker_order_id: str,
    client_order_id: str,
    timeframe: str = "1h",
) -> int:
    return _seed_execution_order(
        db,
        asset_class=asset_class,
        symbol=symbol,
        venue=venue,
        mode=mode,
        side="buy",
        status="submitted",
        timeframe=timeframe,
        client_order_id=client_order_id,
        broker_order_id=broker_order_id,
    )


def _seed_candle(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
    close: Decimal,
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
            high=close,
            low=close,
            close=close,
            volume=Decimal("1000"),
            vwap=close,
            trade_count=1,
        )
    )
    db.commit()


def _latest_account_snapshot(db: Session, *, scope: str) -> AccountSnapshot | None:
    return (
        db.query(AccountSnapshot)
        .filter(AccountSnapshot.account_scope == scope)
        .order_by(AccountSnapshot.as_of.desc(), AccountSnapshot.id.desc())
        .first()
    )
