from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.app.db.session import get_session_factory
from backend.app.models.core import AiResearchPick, ExecutionOrder, PositionState, RiskSnapshot, StrategySnapshot


def test_stock_paper_contract_review_joins_ai_strategy_risk_and_execution(client) -> None:
    candidate_at = datetime(2026, 3, 19, 14, 35, tzinfo=UTC)
    with get_session_factory()() as db:
        db.add(
            AiResearchPick(
                trade_date="2026-03-19",
                scanned_at=datetime(2026, 3, 19, 12, 41, tzinfo=UTC),
                symbol="NVDA",
                catalyst="Strong 1h trend, strong 15m setup, waiting for clean 5m reclaim.",
                approximate_price=Decimal("905.25"),
                entry_zone_low=None,
                entry_zone_high=None,
                stop_loss=None,
                take_profit_primary=None,
                take_profit_stretch=None,
                use_trail_stop=False,
                position_size_dollars=None,
                risk_reward_note="Do not chase if the 5m reclaim is late.",
                is_bonus_pick=False,
                account_cash_at_scan=Decimal("12000.00"),
                venue="alpaca",
                raw_payload={
                    "bucket": "watchlist",
                    "quality_1h": "high",
                    "quality_15m": "high",
                    "reclaim_state": "reclaimable",
                    "contract_version": "paper_test_v1",
                    "ai_named": True,
                },
            )
        )
        db.add(
            StrategySnapshot(
                asset_class="stock",
                venue="alpaca",
                source="strategy_engine",
                symbol="NVDA",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                computed_at=datetime(2026, 3, 19, 14, 35, 10, tzinfo=UTC),
                regime="bull",
                entry_policy="full",
                status="ready",
                readiness_score=Decimal("0.8200"),
                composite_score=Decimal("0.8200"),
                threshold_score=Decimal("0.6500"),
                trend_score=Decimal("0.9000"),
                participation_score=Decimal("0.7600"),
                liquidity_score=Decimal("0.9200"),
                stability_score=Decimal("0.7000"),
                blocked_reasons=[],
                decision_reason=None,
                payload={
                    "bias_pass": True,
                    "setup_pass": True,
                    "trigger_pass": True,
                    "selected_pairs": {
                        "1h": {"fast_type": "sma", "fast_length": 60, "slow_type": "sma", "slow_length": 100},
                        "15m": {"fast_type": "sma", "fast_length": 30, "slow_type": "sma", "slow_length": 80},
                    },
                },
            )
        )
        db.add(
            RiskSnapshot(
                asset_class="stock",
                venue="alpaca",
                source="risk_engine",
                symbol="NVDA",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                computed_at=datetime(2026, 3, 19, 14, 35, 20, tzinfo=UTC),
                status="accepted",
                risk_profile="moderate",
                decision_reason="passed_contract_gate",
                blocked_reasons=[],
                account_equity=Decimal("12000.00"),
                account_cash=Decimal("5000.00"),
                entry_price=Decimal("906.00"),
                stop_price=Decimal("901.00"),
                take_profit_price=Decimal("913.50"),
                stop_distance=Decimal("5.00"),
                stop_distance_pct=Decimal("0.0055"),
                quantity=Decimal("10"),
                notional_value=Decimal("9060.00"),
                deployment_pct=Decimal("0.755"),
                cumulative_deployment_pct=Decimal("0.755"),
                requested_risk_pct=Decimal("0.0125"),
                effective_risk_pct=Decimal("0.0120"),
                max_risk_pct=Decimal("0.0200"),
                risk_budget_amount=Decimal("150.00"),
                projected_loss_amount=Decimal("50.00"),
                projected_loss_pct=Decimal("0.0042"),
                fee_pct=Decimal("0.0005"),
                slippage_pct=Decimal("0.0005"),
                estimated_fees=Decimal("4.53"),
                estimated_slippage=Decimal("4.53"),
                strategy_readiness_score=Decimal("0.8200"),
                strategy_composite_score=Decimal("0.8200"),
                strategy_threshold_score=Decimal("0.6500"),
                payload={"seeded": True},
            )
        )
        db.flush()
        risk_row = db.query(RiskSnapshot).filter(RiskSnapshot.symbol == "NVDA").one()
        db.add(
            ExecutionOrder(
                risk_snapshot_id=risk_row.id,
                asset_class="stock",
                venue="alpaca",
                mode="paper",
                source="execution_engine",
                symbol="NVDA",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                routed_at=datetime(2026, 3, 19, 14, 35, 30, tzinfo=UTC),
                client_order_id="nvda-paper-1",
                broker_order_id="alpaca-1",
                status="filled",
                order_type="market",
                side="buy",
                quantity=Decimal("10"),
                notional_value=Decimal("9060.00"),
                limit_price=None,
                stop_price=Decimal("901.00"),
                fill_count=1,
                decision_reason="paper_contract_trade",
                error_message=None,
                payload={"seeded": True},
            )
        )
        db.add(
            PositionState(
                asset_class="stock",
                venue="alpaca",
                mode="paper",
                source="position_engine",
                symbol="NVDA",
                timeframe="5m",
                side="long",
                status="open",
                reconciliation_status="matched",
                quantity=Decimal("10"),
                broker_quantity=Decimal("10"),
                internal_quantity=Decimal("10"),
                quantity_delta=Decimal("0"),
                average_entry_price=Decimal("906.00"),
                broker_average_entry_price=Decimal("906.00"),
                internal_average_entry_price=Decimal("906.00"),
                cost_basis=Decimal("9060.00"),
                market_value=Decimal("9095.00"),
                current_price=Decimal("909.50"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("35.00"),
                last_fill_at=datetime(2026, 3, 19, 14, 35, 30, tzinfo=UTC),
                synced_at=datetime(2026, 3, 19, 14, 36, 0, tzinfo=UTC),
                mismatch_reason=None,
                payload={"seeded": True},
            )
        )
        db.commit()

    response = client.get("/api/v1/operations/stock-paper-contract-review", params={"trade_date": "2026-03-19", "symbol": "NVDA", "limit": 5})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    row = payload[0]
    assert row["symbol"] == "NVDA"
    assert row["ai_named"] is True
    assert row["ai_bucket"] == "watchlist"
    assert row["pair_1h_used"] == "sma60/sma100"
    assert row["pair_15m_used"] == "sma30/sma80"
    assert row["bias_pass_1h"] is True
    assert row["setup_pass_15m"] is True
    assert row["trigger_pass_5m"] is True
    assert row["indicator_approved"] is True
    assert row["trade_taken"] is True
    assert row["trade_status"] == "filled"
    assert row["outcome"] == "open"
    assert row["entry_price"] == "906.00000000"
    assert row["stop_price"] == "901.00000000"
    assert row["target_price"] == "913.50000000"
    assert any("Trade taken: yes" in note for note in row["notes"])
