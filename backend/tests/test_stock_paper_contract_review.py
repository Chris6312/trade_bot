from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.app.db.session import get_session_factory
from backend.app.models.core import AiResearchPick, ExecutionFill, ExecutionOrder, PositionState, RiskSnapshot, StockPaperContractLedger, StrategySnapshot


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



def test_stock_paper_contract_summary_counts_closed_wins_and_skipped_ready_rows(client) -> None:
    candidate_at = datetime(2026, 3, 19, 15, 5, tzinfo=UTC)
    with get_session_factory()() as db:
        db.add_all([
            AiResearchPick(
                trade_date="2026-03-19",
                scanned_at=datetime(2026, 3, 19, 12, 30, tzinfo=UTC),
                symbol="AAPL",
                catalyst="Ready now with strong HTF alignment.",
                approximate_price=Decimal("210.00"),
                entry_zone_low=None,
                entry_zone_high=None,
                stop_loss=None,
                take_profit_primary=None,
                take_profit_stretch=None,
                use_trail_stop=False,
                position_size_dollars=None,
                risk_reward_note="Tight pullback only.",
                is_bonus_pick=False,
                account_cash_at_scan=Decimal("8000.00"),
                venue="alpaca",
                raw_payload={
                    "bucket": "ready_now",
                    "quality_1h": "high",
                    "quality_15m": "high",
                    "reclaim_state": "fresh",
                },
            ),
            AiResearchPick(
                trade_date="2026-03-19",
                scanned_at=datetime(2026, 3, 19, 12, 35, tzinfo=UTC),
                symbol="MSFT",
                catalyst="Ready now but never routed.",
                approximate_price=Decimal("420.00"),
                entry_zone_low=None,
                entry_zone_high=None,
                stop_loss=None,
                take_profit_primary=None,
                take_profit_stretch=None,
                use_trail_stop=False,
                position_size_dollars=None,
                risk_reward_note="Do not chase.",
                is_bonus_pick=False,
                account_cash_at_scan=Decimal("8000.00"),
                venue="alpaca",
                raw_payload={
                    "bucket": "ready_now",
                    "quality_1h": "high",
                    "quality_15m": "medium",
                    "reclaim_state": "fresh",
                },
            ),
        ])
        db.add_all([
            StrategySnapshot(
                asset_class="stock",
                venue="alpaca",
                source="strategy_engine",
                symbol="AAPL",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                computed_at=datetime(2026, 3, 19, 15, 5, 10, tzinfo=UTC),
                regime="bull",
                entry_policy="full",
                status="ready",
                readiness_score=Decimal("0.9100"),
                composite_score=Decimal("0.9100"),
                threshold_score=Decimal("0.6500"),
                trend_score=Decimal("0.9500"),
                participation_score=Decimal("0.8700"),
                liquidity_score=Decimal("0.9300"),
                stability_score=Decimal("0.7600"),
                blocked_reasons=[],
                decision_reason=None,
                payload={
                    "bias_pass": True,
                    "setup_pass": True,
                    "trigger_pass": True,
                    "selected_pairs": {
                        "1h": {"fast_type": "sma", "fast_length": 60, "slow_type": "sma", "slow_length": 90},
                        "15m": {"fast_type": "sma", "fast_length": 30, "slow_type": "sma", "slow_length": 80},
                    },
                },
            ),
            StrategySnapshot(
                asset_class="stock",
                venue="alpaca",
                source="strategy_engine",
                symbol="MSFT",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                computed_at=datetime(2026, 3, 19, 15, 5, 10, tzinfo=UTC),
                regime="bull",
                entry_policy="full",
                status="ready",
                readiness_score=Decimal("0.7900"),
                composite_score=Decimal("0.7900"),
                threshold_score=Decimal("0.6500"),
                trend_score=Decimal("0.8800"),
                participation_score=Decimal("0.7600"),
                liquidity_score=Decimal("0.9000"),
                stability_score=Decimal("0.7000"),
                blocked_reasons=[],
                decision_reason=None,
                payload={
                    "bias_pass": True,
                    "setup_pass": True,
                    "trigger_pass": True,
                    "selected_pairs": {
                        "1h": {"fast_type": "ema", "fast_length": 30, "slow_type": "ema", "slow_length": 100},
                        "15m": {"fast_type": "sma", "fast_length": 40, "slow_type": "sma", "slow_length": 50},
                    },
                },
            ),
        ])
        db.add_all([
            RiskSnapshot(
                asset_class="stock",
                venue="alpaca",
                source="risk_engine",
                symbol="AAPL",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                computed_at=datetime(2026, 3, 19, 15, 5, 20, tzinfo=UTC),
                status="accepted",
                risk_profile="moderate",
                decision_reason="passed_contract_gate",
                blocked_reasons=[],
                account_equity=Decimal("8000.00"),
                account_cash=Decimal("3000.00"),
                entry_price=Decimal("210.00"),
                stop_price=Decimal("207.00"),
                take_profit_price=Decimal("214.50"),
                stop_distance=Decimal("3.00"),
                stop_distance_pct=Decimal("0.0143"),
                quantity=Decimal("10"),
                notional_value=Decimal("2100.00"),
                deployment_pct=Decimal("0.2625"),
                cumulative_deployment_pct=Decimal("0.2625"),
                requested_risk_pct=Decimal("0.0125"),
                effective_risk_pct=Decimal("0.0100"),
                max_risk_pct=Decimal("0.0200"),
                risk_budget_amount=Decimal("100.00"),
                projected_loss_amount=Decimal("30.00"),
                projected_loss_pct=Decimal("0.0038"),
                fee_pct=Decimal("0.0005"),
                slippage_pct=Decimal("0.0005"),
                estimated_fees=Decimal("1.05"),
                estimated_slippage=Decimal("1.05"),
                strategy_readiness_score=Decimal("0.9100"),
                strategy_composite_score=Decimal("0.9100"),
                strategy_threshold_score=Decimal("0.6500"),
                payload={"seeded": True},
            ),
            RiskSnapshot(
                asset_class="stock",
                venue="alpaca",
                source="risk_engine",
                symbol="MSFT",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                computed_at=datetime(2026, 3, 19, 15, 5, 20, tzinfo=UTC),
                status="accepted",
                risk_profile="moderate",
                decision_reason="passed_contract_gate",
                blocked_reasons=[],
                account_equity=Decimal("8000.00"),
                account_cash=Decimal("3000.00"),
                entry_price=Decimal("420.00"),
                stop_price=Decimal("415.00"),
                take_profit_price=Decimal("427.50"),
                stop_distance=Decimal("5.00"),
                stop_distance_pct=Decimal("0.0119"),
                quantity=Decimal("5"),
                notional_value=Decimal("2100.00"),
                deployment_pct=Decimal("0.2625"),
                cumulative_deployment_pct=Decimal("0.5250"),
                requested_risk_pct=Decimal("0.0125"),
                effective_risk_pct=Decimal("0.0100"),
                max_risk_pct=Decimal("0.0200"),
                risk_budget_amount=Decimal("100.00"),
                projected_loss_amount=Decimal("25.00"),
                projected_loss_pct=Decimal("0.0031"),
                fee_pct=Decimal("0.0005"),
                slippage_pct=Decimal("0.0005"),
                estimated_fees=Decimal("1.05"),
                estimated_slippage=Decimal("1.05"),
                strategy_readiness_score=Decimal("0.7900"),
                strategy_composite_score=Decimal("0.7900"),
                strategy_threshold_score=Decimal("0.6500"),
                payload={"seeded": True},
            ),
        ])
        db.flush()
        aapl_risk = db.query(RiskSnapshot).filter(RiskSnapshot.symbol == "AAPL").one()
        db.add(
            ExecutionOrder(
                risk_snapshot_id=aapl_risk.id,
                asset_class="stock",
                venue="alpaca",
                mode="paper",
                source="execution_engine",
                symbol="AAPL",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                routed_at=datetime(2026, 3, 19, 15, 5, 30, tzinfo=UTC),
                client_order_id="aapl-paper-1",
                broker_order_id="alpaca-aapl-1",
                status="filled",
                order_type="market",
                side="buy",
                quantity=Decimal("10"),
                notional_value=Decimal("2100.00"),
                limit_price=None,
                stop_price=Decimal("207.00"),
                fill_count=1,
                decision_reason="paper_contract_trade",
                error_message=None,
                payload={"seeded": True},
            )
        )
        db.flush()
        order = db.query(ExecutionOrder).filter(ExecutionOrder.symbol == "AAPL").one()
        db.add(
            PositionState(
                asset_class="stock",
                venue="alpaca",
                mode="paper",
                source="position_engine",
                symbol="AAPL",
                timeframe="5m",
                side="long",
                status="closed",
                reconciliation_status="matched",
                quantity=Decimal("0"),
                broker_quantity=Decimal("0"),
                internal_quantity=Decimal("0"),
                quantity_delta=Decimal("0"),
                average_entry_price=Decimal("210.00"),
                broker_average_entry_price=Decimal("210.00"),
                internal_average_entry_price=Decimal("210.00"),
                cost_basis=Decimal("0"),
                market_value=Decimal("0"),
                current_price=Decimal("214.50"),
                realized_pnl=Decimal("42.50"),
                unrealized_pnl=Decimal("0"),
                last_fill_at=datetime(2026, 3, 19, 15, 25, 0, tzinfo=UTC),
                synced_at=datetime(2026, 3, 19, 15, 25, 30, tzinfo=UTC),
                mismatch_reason=None,
                payload={"seeded": True},
            )
        )
        db.add(
            ExecutionFill(
                execution_order_id=order.id,
                asset_class="stock",
                venue="alpaca",
                mode="paper",
                symbol="AAPL",
                timeframe="5m",
                fill_timestamp=datetime(2026, 3, 19, 15, 5, 31, tzinfo=UTC),
                status="filled",
                quantity=Decimal("10"),
                fill_price=Decimal("210.00"),
                notional_value=Decimal("2100.00"),
                fee_amount=Decimal("1.05"),
                venue_fill_id="fill-aapl-1",
                payload={"seeded": True},
            )
        )
        db.commit()

    summary_response = client.get("/api/v1/operations/stock-paper-contract-summary", params={"trade_date": "2026-03-19"})
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["trade_date"] == "2026-03-19"
    assert summary["shortlist_count"] == 2
    assert summary["ready_now_count"] == 2
    assert summary["indicator_approved_count"] == 2
    assert summary["risk_accepted_count"] == 2
    assert summary["trades_taken_count"] == 1
    assert summary["closed_outcomes_count"] == 1
    assert summary["skipped_ready_count"] == 1
    assert summary["winners_count"] == 1
    assert summary["losers_count"] == 0

    review_response = client.get("/api/v1/operations/stock-paper-contract-review", params={"trade_date": "2026-03-19", "symbol": "AAPL", "limit": 5})
    assert review_response.status_code == 200
    row = review_response.json()[0]
    assert row["risk_status"] == "accepted"
    assert row["trade_status"] == "filled"
    assert row["position_status"] == "closed"
    assert row["outcome"] == "closed_win"
    assert row["realized_pnl"] == "42.50000000"
    assert Decimal(row["unrealized_pnl"]) == Decimal("0")
    assert row["filled_at"] is not None



def test_stock_paper_contract_ledger_sync_persists_and_reads_closed_rows(client) -> None:
    candidate_at = datetime(2026, 3, 19, 15, 5, tzinfo=UTC)
    with get_session_factory()() as db:
        db.add(
            AiResearchPick(
                trade_date="2026-03-19",
                scanned_at=datetime(2026, 3, 19, 12, 30, tzinfo=UTC),
                symbol="AAPL",
                catalyst="Ready now with strong HTF alignment.",
                approximate_price=Decimal("210.00"),
                entry_zone_low=None,
                entry_zone_high=None,
                stop_loss=None,
                take_profit_primary=None,
                take_profit_stretch=None,
                use_trail_stop=False,
                position_size_dollars=None,
                risk_reward_note="Tight pullback only.",
                is_bonus_pick=False,
                account_cash_at_scan=Decimal("8000.00"),
                venue="alpaca",
                raw_payload={
                    "bucket": "ready_now",
                    "quality_1h": "high",
                    "quality_15m": "high",
                    "reclaim_state": "fresh",
                },
            )
        )
        db.add(
            StrategySnapshot(
                asset_class="stock",
                venue="alpaca",
                source="strategy_engine",
                symbol="AAPL",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                computed_at=datetime(2026, 3, 19, 15, 5, 10, tzinfo=UTC),
                regime="bull",
                entry_policy="full",
                status="ready",
                readiness_score=Decimal("0.9100"),
                composite_score=Decimal("0.9100"),
                threshold_score=Decimal("0.6500"),
                trend_score=Decimal("0.9500"),
                participation_score=Decimal("0.8700"),
                liquidity_score=Decimal("0.9300"),
                stability_score=Decimal("0.7600"),
                blocked_reasons=[],
                decision_reason=None,
                payload={
                    "bias_pass": True,
                    "setup_pass": True,
                    "trigger_pass": True,
                    "selected_pairs": {
                        "1h": {"fast_type": "sma", "fast_length": 60, "slow_type": "sma", "slow_length": 90},
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
                symbol="AAPL",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                computed_at=datetime(2026, 3, 19, 15, 5, 20, tzinfo=UTC),
                status="accepted",
                risk_profile="moderate",
                decision_reason="passed_contract_gate",
                blocked_reasons=[],
                account_equity=Decimal("8000.00"),
                account_cash=Decimal("3000.00"),
                entry_price=Decimal("210.00"),
                stop_price=Decimal("207.00"),
                take_profit_price=Decimal("214.50"),
                stop_distance=Decimal("3.00"),
                stop_distance_pct=Decimal("0.0143"),
                quantity=Decimal("10"),
                notional_value=Decimal("2100.00"),
                deployment_pct=Decimal("0.2625"),
                cumulative_deployment_pct=Decimal("0.2625"),
                requested_risk_pct=Decimal("0.0125"),
                effective_risk_pct=Decimal("0.0100"),
                max_risk_pct=Decimal("0.0200"),
                risk_budget_amount=Decimal("100.00"),
                projected_loss_amount=Decimal("30.00"),
                projected_loss_pct=Decimal("0.0038"),
                fee_pct=Decimal("0.0005"),
                slippage_pct=Decimal("0.0005"),
                estimated_fees=Decimal("1.05"),
                estimated_slippage=Decimal("1.05"),
                strategy_readiness_score=Decimal("0.9100"),
                strategy_composite_score=Decimal("0.9100"),
                strategy_threshold_score=Decimal("0.6500"),
                payload={"seeded": True},
            )
        )
        db.flush()
        risk_row = db.query(RiskSnapshot).filter(RiskSnapshot.symbol == "AAPL").one()
        db.add(
            ExecutionOrder(
                risk_snapshot_id=risk_row.id,
                asset_class="stock",
                venue="alpaca",
                mode="paper",
                source="execution_engine",
                symbol="AAPL",
                strategy_name="htf_reclaim_long",
                direction="long",
                timeframe="5m",
                candidate_timestamp=candidate_at,
                routed_at=datetime(2026, 3, 19, 15, 5, 30, tzinfo=UTC),
                client_order_id="aapl-paper-1",
                broker_order_id="alpaca-aapl-1",
                status="filled",
                order_type="market",
                side="buy",
                quantity=Decimal("10"),
                notional_value=Decimal("2100.00"),
                limit_price=None,
                stop_price=Decimal("207.00"),
                fill_count=1,
                decision_reason="paper_contract_trade",
                error_message=None,
                payload={"seeded": True},
            )
        )
        db.flush()
        order = db.query(ExecutionOrder).filter(ExecutionOrder.symbol == "AAPL").one()
        db.add(
            PositionState(
                asset_class="stock",
                venue="alpaca",
                mode="paper",
                source="position_engine",
                symbol="AAPL",
                timeframe="5m",
                side="long",
                status="closed",
                reconciliation_status="matched",
                quantity=Decimal("0"),
                broker_quantity=Decimal("0"),
                internal_quantity=Decimal("0"),
                quantity_delta=Decimal("0"),
                average_entry_price=Decimal("210.00"),
                broker_average_entry_price=Decimal("210.00"),
                internal_average_entry_price=Decimal("210.00"),
                cost_basis=Decimal("0"),
                market_value=Decimal("0"),
                current_price=Decimal("214.50"),
                realized_pnl=Decimal("42.50"),
                unrealized_pnl=Decimal("0"),
                last_fill_at=datetime(2026, 3, 19, 15, 25, 0, tzinfo=UTC),
                synced_at=datetime(2026, 3, 19, 15, 25, 30, tzinfo=UTC),
                mismatch_reason=None,
                payload={"seeded": True},
            )
        )
        db.add(
            ExecutionFill(
                execution_order_id=order.id,
                asset_class="stock",
                venue="alpaca",
                mode="paper",
                symbol="AAPL",
                timeframe="5m",
                fill_timestamp=datetime(2026, 3, 19, 15, 5, 31, tzinfo=UTC),
                status="filled",
                quantity=Decimal("10"),
                fill_price=Decimal("210.00"),
                notional_value=Decimal("2100.00"),
                fee_amount=Decimal("1.05"),
                venue_fill_id="fill-aapl-1",
                payload={"seeded": True},
            )
        )
        db.commit()

    sync_response = client.post("/api/v1/operations/stock-paper-contract-ledger/sync", params={"trade_date": "2026-03-19", "limit": 10})
    assert sync_response.status_code == 200
    payload = sync_response.json()
    assert len(payload) == 1
    row = payload[0]
    assert row["symbol"] == "AAPL"
    assert row["outcome"] == "closed_win"
    assert row["closed_at"] is not None
    assert row["trade_status"] == "filled"
    assert row["pair_1h_used"] == "sma60/sma90"
    assert row["last_synced_at"] is not None

    read_response = client.get(
        "/api/v1/operations/stock-paper-contract-ledger",
        params={"trade_date": "2026-03-19", "symbol": "AAPL", "limit": 10},
    )
    assert read_response.status_code == 200
    ledger_row = read_response.json()[0]
    assert ledger_row["symbol"] == "AAPL"
    assert ledger_row["realized_pnl"] == "42.50000000"
    assert any("Realized PnL" in note for note in ledger_row["notes"])



def test_stock_paper_contract_ledger_sync_updates_existing_row_without_duplicates(client) -> None:
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

    first_sync = client.post(
        "/api/v1/operations/stock-paper-contract-ledger/sync",
        params={"trade_date": "2026-03-19", "symbol": "NVDA", "limit": 5},
    )
    assert first_sync.status_code == 200
    first_row = first_sync.json()[0]
    assert first_row["outcome"] == "open"
    assert first_row["closed_at"] is None

    with get_session_factory()() as db:
        position = db.query(PositionState).filter(PositionState.symbol == "NVDA").one()
        position.status = "closed"
        position.quantity = Decimal("0")
        position.broker_quantity = Decimal("0")
        position.internal_quantity = Decimal("0")
        position.cost_basis = Decimal("0")
        position.market_value = Decimal("0")
        position.realized_pnl = Decimal("25.00")
        position.unrealized_pnl = Decimal("0")
        position.synced_at = datetime(2026, 3, 19, 15, 10, 0, tzinfo=UTC)
        db.commit()

    second_sync = client.post(
        "/api/v1/operations/stock-paper-contract-ledger/sync",
        params={"trade_date": "2026-03-19", "symbol": "NVDA", "limit": 5},
    )
    assert second_sync.status_code == 200
    second_row = second_sync.json()[0]
    assert second_row["outcome"] == "closed_win"
    assert second_row["closed_at"] is not None
    assert second_row["first_seen_at"] == first_row["first_seen_at"]

    with get_session_factory()() as db:
        rows = db.query(StockPaperContractLedger).filter(StockPaperContractLedger.symbol == "NVDA").all()
        assert len(rows) == 1
