from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.app.common.adapters.models import OrderRequest, OrderResult
from backend.app.db.session import get_session_factory
from backend.app.models.core import (
    ExecutionFill,
    ExecutionSyncState,
    PositionState,
    RiskSnapshot,
    RiskSyncState,
    Setting,
    StopState,
    SystemEvent,
)
from backend.app.services.execution_service import list_current_execution_orders
from backend.app.workers.execution_worker import ExecutionWorker


class RecordingAdapter:
    def __init__(self, result: OrderResult | None = None) -> None:
        self.result = result or OrderResult(venue="alpaca", asset_class="stock", order_id="order-1", status="submitted", raw={})
        self.requests: list[OrderRequest] = []

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.requests.append(request)
        return self.result


def _mapping_resolver(mapping: dict[str, RecordingAdapter]):
    def resolve(route):
        return mapping[route.adapter_key]

    return resolve


def _seed_setting(db, *, key: str, value: str, value_type: str = "string") -> None:
    db.add(Setting(key=key, value=value, value_type=value_type, description="seed", is_secret=False))
    db.commit()


def _seed_risk_row(
    db,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str = "1h",
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
            status="accepted",
            risk_profile="moderate",
            decision_reason="risk_accepted",
            blocked_reasons=[],
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


def test_phase17_live_rollout_checklist_exposes_guarded_state(client) -> None:
    with get_session_factory()() as db:
        _seed_setting(db, key="execution.default_mode", value="mixed")
        _seed_setting(db, key="execution.stock.mode", value="live")
        _seed_setting(db, key="execution.crypto.mode", value="paper")
        _seed_setting(db, key="controls.kill_switch_enabled", value="false", value_type="bool")
        _seed_setting(db, key="controls.stock.trading_enabled", value="true", value_type="bool")
        _seed_setting(db, key="controls.crypto.trading_enabled", value="true", value_type="bool")
        db.add(
            ExecutionSyncState(
                asset_class="stock",
                venue="public",
                mode="live",
                timeframe="1h",
                last_routed_at=datetime(2026, 3, 14, 16, 0, tzinfo=UTC),
                last_candidate_at=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
                candidate_count=1,
                routed_count=1,
                duplicate_count=0,
                blocked_count=0,
                failed_count=0,
                fill_count=0,
                last_status="completed",
                last_error=None,
            )
        )
        db.add(
            RiskSyncState(
                asset_class="stock",
                venue="alpaca",
                timeframe="1h",
                last_computed_at=datetime(2026, 3, 14, 15, 2, tzinfo=UTC),
                last_candidate_at=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
                candidate_count=2,
                accepted_count=1,
                blocked_count=1,
                deployment_pct=Decimal("0.10"),
                breaker_status=None,
                last_status="synced",
                last_error=None,
            )
        )
        db.add(SystemEvent(event_type="audit.kill_switch_validation", severity="info", message="seed audit", event_source="operator_audit", payload={"asset_class": "stock"}))
        db.commit()

    response = client.get("/api/v1/operations/live-rollout/checklist", params={"timeframe": "1h"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["live_asset_count"] == 1
    items = {item["key"]: item for item in payload["items"]}
    assert items["stock_route"]["status"] == "ready"
    assert items["kill_switch"]["status"] == "ready"
    assert items["audit_trail"]["status"] == "ready"


def test_phase17_kill_switch_validation_records_audit_event(client) -> None:
    with get_session_factory()() as db:
        _seed_setting(db, key="controls.kill_switch_enabled", value="true", value_type="bool")
        db.add(
            ExecutionSyncState(
                asset_class="stock",
                venue="public",
                mode="live",
                timeframe="1h",
                last_routed_at=datetime(2026, 3, 14, 16, 5, tzinfo=UTC),
                last_candidate_at=datetime(2026, 3, 14, 16, 4, tzinfo=UTC),
                candidate_count=1,
                routed_count=0,
                duplicate_count=0,
                blocked_count=1,
                failed_count=0,
                fill_count=0,
                last_status="kill_switch_blocked",
                last_error=None,
            )
        )
        db.commit()

    response = client.post("/api/v1/operations/validations/kill-switch", params={"timeframe": "1h"}, json={"note": "preflight"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "passed"
    assert payload["details"]["observed_blocked_assets"] == ["stock"]

    audit_response = client.get("/api/v1/operations/trade-audit", params={"limit": 10})
    assert audit_response.status_code == 200
    event_types = [item["event_type"] for item in audit_response.json()]
    assert "audit.kill_switch_validation" in event_types


def test_phase17_circuit_breaker_validation_records_audit_event(client) -> None:
    with get_session_factory()() as db:
        db.add(
            RiskSyncState(
                asset_class="crypto",
                venue="kraken",
                timeframe="1h",
                last_computed_at=datetime(2026, 3, 14, 16, 10, tzinfo=UTC),
                last_candidate_at=datetime(2026, 3, 14, 16, 9, tzinfo=UTC),
                candidate_count=2,
                accepted_count=0,
                blocked_count=2,
                deployment_pct=Decimal("0.00"),
                breaker_status="crypto_circuit_breaker_hard",
                last_status="circuit_breaker_blocked",
                last_error=None,
            )
        )
        db.commit()

    response = client.post(
        "/api/v1/operations/validations/circuit-breakers/crypto",
        params={"timeframe": "1h"},
        json={"note": "loss fence"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "passed"
    assert payload["details"]["breaker_status"] == "crypto_circuit_breaker_hard"

    audit_response = client.get("/api/v1/operations/trade-audit", params={"asset_class": "crypto", "limit": 10})
    assert audit_response.status_code == 200
    assert audit_response.json()[0]["event_type"] == "audit.circuit_breaker_validation"


def test_phase17_trade_audit_and_post_trade_review_follow_execution_chain(client) -> None:
    with get_session_factory()() as db:
        _seed_risk_row(db, asset_class="stock", symbol="AAPL")
        adapter = RecordingAdapter(
            result=OrderResult(
                venue="alpaca",
                asset_class="stock",
                order_id="fill-17",
                status="filled",
                raw={
                    "filled_qty": "1",
                    "filled_avg_price": "100.25",
                    "filled_fee": "0.05",
                    "filled_at": "2026-03-14T16:20:00+00:00",
                    "fill_id": "venue-fill-17",
                },
            )
        )
        ExecutionWorker(db, adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter})).route_stock_orders(
            timeframe="1h",
            now=datetime(2026, 3, 14, 16, 20, tzinfo=UTC),
        )
        order = list_current_execution_orders(db, asset_class="stock", timeframe="1h")[0]
        assert order.fill_count == 1
        execution_fill = db.query(ExecutionFill).filter(ExecutionFill.execution_order_id == order.id).one()
        db.add(
            StopState(
                execution_order_id=order.id,
                execution_fill_id=execution_fill.id,
                risk_snapshot_id=order.risk_snapshot_id,
                asset_class="stock",
                venue=order.venue,
                mode=order.mode,
                source="stop_engine",
                symbol=order.symbol,
                strategy_name=order.strategy_name,
                direction=order.direction,
                timeframe=order.timeframe,
                stop_style="fixed",
                status="synced",
                entry_price=Decimal("100.25"),
                initial_stop_price=Decimal("99.25"),
                current_stop_price=Decimal("99.25"),
                current_price=Decimal("100.25"),
                highest_price=Decimal("100.25"),
                trailing_active=False,
                step_level=0,
                protected_quantity=Decimal("1"),
                broker_stop_order_id="stop-17",
                last_fill_at=datetime(2026, 3, 14, 16, 20, tzinfo=UTC),
                last_evaluated_at=datetime(2026, 3, 14, 16, 21, tzinfo=UTC),
                last_updated_at=datetime(2026, 3, 14, 16, 21, tzinfo=UTC),
                update_count=1,
                last_error=None,
                payload={"seeded": True},
            )
        )
        db.add(
            PositionState(
                asset_class="stock",
                venue=order.venue,
                mode=order.mode,
                source="position_engine",
                symbol=order.symbol,
                timeframe=order.timeframe,
                side="long",
                status="open",
                reconciliation_status="matched",
                quantity=Decimal("1"),
                broker_quantity=Decimal("1"),
                internal_quantity=Decimal("1"),
                quantity_delta=Decimal("0"),
                average_entry_price=Decimal("100.25"),
                broker_average_entry_price=Decimal("100.25"),
                internal_average_entry_price=Decimal("100.25"),
                cost_basis=Decimal("100.25"),
                market_value=Decimal("101.00"),
                current_price=Decimal("101.00"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0.75"),
                last_fill_at=datetime(2026, 3, 14, 16, 20, tzinfo=UTC),
                synced_at=datetime(2026, 3, 14, 16, 22, tzinfo=UTC),
                mismatch_reason=None,
                payload={"seeded": True},
            )
        )
        db.commit()

    audit_response = client.get("/api/v1/operations/trade-audit", params={"asset_class": "stock", "symbol": "AAPL", "limit": 20})
    assert audit_response.status_code == 200
    event_types = [item["event_type"] for item in audit_response.json()]
    assert "audit.order_routed" in event_types
    assert "audit.order_filled" in event_types

    review_response = client.get("/api/v1/operations/post-trade-review", params={"asset_class": "stock", "symbol": "AAPL", "limit": 5})
    assert review_response.status_code == 200
    review = review_response.json()[0]
    assert review["symbol"] == "AAPL"
    assert review["fill_status"] == "filled"
    assert review["stop_status"] == "synced"
    assert review["position"]["reconciliation_status"] == "matched"
    assert any("Protective stop" in note for note in review["review_notes"])
