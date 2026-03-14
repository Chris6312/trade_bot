
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.common.adapters.models import OrderRequest, OrderResult
from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import get_session_factory
from backend.app.models.core import ExecutionFill, ExecutionOrder, RiskSnapshot, Setting
from backend.app.services.execution_service import get_execution_sync_state, list_current_execution_orders
from backend.app.workers.execution_worker import ExecutionWorker


class RecordingAdapter:
    def __init__(self, result: OrderResult | None = None, error: Exception | None = None) -> None:
        self.result = result or OrderResult(venue="paper", asset_class="stock", order_id="order-1", status="submitted", raw={})
        self.error = error
        self.requests: list[OrderRequest] = []
        self.closed = False

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase10_execution_worker.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("asset_class", "mode", "expected_venue", "adapter_key", "method_name"),
    [
        ("stock", "live", "public", "public_trading", "route_stock_orders"),
        ("crypto", "live", "kraken", "kraken_trading", "route_crypto_orders"),
        ("stock", "paper", "alpaca", "alpaca_stock_paper", "route_stock_orders"),
        ("crypto", "paper", "alpaca", "alpaca_crypto_paper", "route_crypto_orders"),
    ],
)
def test_execution_engine_selects_correct_venue_by_asset_class_and_mode(
    db_session: Session,
    asset_class: str,
    mode: str,
    expected_venue: str,
    adapter_key: str,
    method_name: str,
) -> None:
    _seed_risk_row(db_session, asset_class=asset_class, symbol="AAPL" if asset_class == "stock" else "XBTUSD")
    adapter = RecordingAdapter(result=OrderResult(venue=expected_venue, asset_class=asset_class, order_id=f"{expected_venue}-1", status="submitted", raw={}))
    settings = Settings(default_mode=mode)

    worker = ExecutionWorker(
        db_session,
        settings=settings,
        adapter_resolver=_mapping_resolver({adapter_key: adapter}),
    )
    summary = getattr(worker, method_name)(timeframe="1h", now=datetime(2026, 3, 14, 16, 0, tzinfo=UTC))

    assert summary.routed_count == 1
    rows = list_current_execution_orders(db_session, asset_class=asset_class, timeframe="1h")
    assert len(rows) == 1
    assert rows[0].venue == expected_venue
    assert rows[0].mode == mode
    assert len(adapter.requests) == 1


def test_execution_engine_uses_asset_specific_modes_when_default_mode_is_mixed(db_session: Session) -> None:
    _seed_setting(db_session, key="execution.default_mode", value="mixed")
    _seed_setting(db_session, key="execution.stock.mode", value="live")
    _seed_risk_row(db_session, asset_class="stock", symbol="MSFT")
    adapter = RecordingAdapter(result=OrderResult(venue="public", asset_class="stock", order_id="public-2", status="submitted", raw={}))

    summary = ExecutionWorker(
        db_session,
        settings=Settings(default_mode="mixed", stock_execution_mode="paper"),
        adapter_resolver=_mapping_resolver({"public_trading": adapter}),
    ).route_stock_orders(timeframe="1h", now=datetime(2026, 3, 14, 16, 1, tzinfo=UTC))

    assert summary.mode == "live"
    row = list_current_execution_orders(db_session, asset_class="stock", timeframe="1h")[0]
    assert row.venue == "public"
    assert row.mode == "live"


def test_execution_engine_prevents_duplicate_submission_for_same_risk_row(db_session: Session) -> None:
    _seed_risk_row(db_session, asset_class="stock", symbol="NVDA")
    adapter = RecordingAdapter(result=OrderResult(venue="alpaca", asset_class="stock", order_id="alpaca-1", status="submitted", raw={}))
    worker = ExecutionWorker(
        db_session,
        settings=Settings(default_mode="paper"),
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
    )

    first = worker.route_stock_orders(timeframe="1h", now=datetime(2026, 3, 14, 16, 2, tzinfo=UTC))
    second = worker.route_stock_orders(timeframe="1h", now=datetime(2026, 3, 14, 16, 3, tzinfo=UTC))

    assert first.routed_count == 1
    assert second.duplicate_count == 1
    assert len(adapter.requests) == 1
    assert db_session.query(ExecutionOrder).count() == 1


def test_execution_engine_persists_fill_when_broker_reports_fill(db_session: Session) -> None:
    _seed_risk_row(db_session, asset_class="crypto", symbol="ETHUSD", quantity=Decimal("0.25"), entry_price=Decimal("2500"))
    adapter = RecordingAdapter(
        result=OrderResult(
            venue="alpaca",
            asset_class="crypto",
            order_id="fill-1",
            status="filled",
            raw={
                "filled_qty": "0.25",
                "filled_avg_price": "2501.50",
                "filled_fee": "0.35",
                "filled_at": "2026-03-14T16:04:00+00:00",
                "fill_id": "venue-fill-1",
            },
        )
    )

    summary = ExecutionWorker(
        db_session,
        settings=Settings(default_mode="paper"),
        adapter_resolver=_mapping_resolver({"alpaca_crypto_paper": adapter}),
    ).route_crypto_orders(timeframe="1h", now=datetime(2026, 3, 14, 16, 4, tzinfo=UTC))

    assert summary.fill_count == 1
    fill = db_session.query(ExecutionFill).one()
    assert float(fill.quantity) == pytest.approx(0.25)
    assert float(fill.fill_price) == pytest.approx(2501.50)
    assert fill.venue_fill_id == "venue-fill-1"


def test_execution_engine_persists_route_failures_and_sync_state(db_session: Session) -> None:
    _seed_risk_row(db_session, asset_class="stock", symbol="AMD")
    adapter = RecordingAdapter(error=RuntimeError("broker offline"))

    summary = ExecutionWorker(
        db_session,
        settings=Settings(default_mode="paper"),
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
    ).route_stock_orders(timeframe="1h", now=datetime(2026, 3, 14, 16, 5, tzinfo=UTC))

    state = get_execution_sync_state(db_session, asset_class="stock", timeframe="1h")
    order = db_session.query(ExecutionOrder).one()
    assert summary.failed_count == 1
    assert state is not None
    assert state.last_status == "route_failed"
    assert order.status == "route_failed"
    assert order.error_message == "broker offline"


def test_execution_engine_ignores_blocked_risk_rows(db_session: Session) -> None:
    _seed_risk_row(db_session, asset_class="stock", symbol="TSLA", status="blocked", decision_reason="long_only_until_2500", blocked_reasons=["long_only_until_2500"])
    adapter = RecordingAdapter()

    summary = ExecutionWorker(
        db_session,
        settings=Settings(default_mode="paper"),
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
    ).route_stock_orders(timeframe="1h", now=datetime(2026, 3, 14, 16, 6, tzinfo=UTC))

    assert summary.candidate_count == 0
    assert summary.skipped_reason == "risk_unavailable"
    assert len(adapter.requests) == 0
    assert db_session.query(ExecutionOrder).count() == 0


def test_execution_engine_respects_kill_switch(db_session: Session) -> None:
    _seed_setting(db_session, key="controls.kill_switch_enabled", value="true")
    _seed_risk_row(db_session, asset_class="crypto", symbol="SOLUSD")
    adapter = RecordingAdapter()

    summary = ExecutionWorker(
        db_session,
        settings=Settings(default_mode="paper"),
        adapter_resolver=_mapping_resolver({"alpaca_crypto_paper": adapter}),
    ).route_crypto_orders(timeframe="1h", now=datetime(2026, 3, 14, 16, 7, tzinfo=UTC))

    state = get_execution_sync_state(db_session, asset_class="crypto", timeframe="1h")
    assert summary.blocked_count == 1
    assert summary.last_status == "kill_switch_blocked"
    assert state is not None
    assert state.last_status == "kill_switch_blocked"
    assert len(adapter.requests) == 0


def test_execution_api_exposes_current_orders_fills_and_sync_state(client) -> None:
    session = get_session_factory()()
    try:
        _seed_risk_row(session, asset_class="stock", symbol="AAPL")
        adapter = RecordingAdapter(
            result=OrderResult(
                venue="alpaca",
                asset_class="stock",
                order_id="fill-2",
                status="filled",
                raw={
                    "filled_qty": "1",
                    "filled_avg_price": "100.25",
                    "filled_fee": "0.05",
                    "filled_at": "2026-03-14T16:08:00+00:00",
                    "fill_id": "venue-fill-2",
                },
            )
        )
        ExecutionWorker(
            session,
            settings=Settings(default_mode="paper"),
            adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
        ).route_stock_orders(timeframe="1h", now=datetime(2026, 3, 14, 16, 8, tzinfo=UTC))
    finally:
        session.close()

    orders_response = client.get("/api/v1/execution/stock/current", params={"timeframe": "1h"})
    assert orders_response.status_code == 200
    orders_payload = orders_response.json()
    assert len(orders_payload) == 1
    assert orders_payload[0]["symbol"] == "AAPL"
    assert orders_payload[0]["status"] == "filled"

    fills_response = client.get("/api/v1/execution/stock/fills", params={"timeframe": "1h"})
    assert fills_response.status_code == 200
    fills_payload = fills_response.json()
    assert len(fills_payload) == 1
    assert fills_payload[0]["venue_fill_id"] == "venue-fill-2"

    sync_response = client.get("/api/v1/execution/stock/sync-state", params={"timeframe": "1h"})
    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["routed_count"] == 1
    assert sync_payload["fill_count"] == 1


def _mapping_resolver(mapping: dict[str, RecordingAdapter]):
    def resolve(route):
        return mapping[route.adapter_key]

    return resolve


def _seed_risk_row(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str = "1h",
    status: str = "accepted",
    decision_reason: str | None = "risk_accepted",
    blocked_reasons: list[str] | None = None,
    quantity: Decimal = Decimal("1"),
    entry_price: Decimal = Decimal("100"),
) -> None:
    db.add(
        RiskSnapshot(
            asset_class=asset_class,
            venue="alpaca" if asset_class == "stock" else "kraken",
            source="risk_engine",
            symbol=symbol,
            strategy_name="baseline_long",
            direction="long",
            timeframe=timeframe,
            candidate_timestamp=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
            computed_at=datetime(2026, 3, 14, 15, 1, tzinfo=UTC),
            status=status,
            risk_profile="moderate",
            decision_reason=decision_reason,
            blocked_reasons=blocked_reasons or ([] if status == "accepted" else [decision_reason or "blocked"]),
            account_equity=Decimal("1000"),
            account_cash=Decimal("1000"),
            entry_price=entry_price,
            stop_price=entry_price * Decimal("0.99"),
            stop_distance=entry_price * Decimal("0.01"),
            stop_distance_pct=Decimal("0.01"),
            quantity=quantity,
            notional_value=entry_price * quantity,
            deployment_pct=Decimal("0.10"),
            cumulative_deployment_pct=Decimal("0.10"),
            requested_risk_pct=Decimal("0.0125"),
            effective_risk_pct=Decimal("0.0125"),
            max_risk_pct=Decimal("0.02"),
            risk_budget_amount=Decimal("12.5"),
            projected_loss_amount=Decimal("10"),
            projected_loss_pct=Decimal("0.01"),
            fee_pct=Decimal("0.001"),
            slippage_pct=Decimal("0.001"),
            estimated_fees=Decimal("0.10"),
            estimated_slippage=Decimal("0.10"),
            strategy_readiness_score=Decimal("0.75"),
            strategy_composite_score=Decimal("0.75"),
            strategy_threshold_score=Decimal("0.60"),
            payload={"seeded": True},
        )
    )
    db.commit()


def _seed_setting(db: Session, *, key: str, value: str) -> None:
    db.add(Setting(key=key, value=value, value_type="string", description="test setting", is_secret=False))
    db.commit()
