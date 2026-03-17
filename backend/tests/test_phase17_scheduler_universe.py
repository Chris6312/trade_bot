from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backend.app.db.session import get_session_factory
from backend.app.models.core import StrategySnapshot, UniverseConstituent, UniverseRun
from backend.app.services.universe_service import trading_date_for_now


def test_phase17_universe_route_uses_best_strategy_scores_for_drawer(client) -> None:
    with get_session_factory()() as db:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        trade_date = trading_date_for_now(now)
        run = UniverseRun(
            asset_class="crypto",
            venue="kraken",
            trade_date=trade_date,
            source="static",
            status="resolved",
            resolved_at=now,
            payload={"resolution": "static"},
        )
        db.add(run)
        db.flush()
        db.add(
            UniverseConstituent(
                universe_run_id=run.id,
                asset_class="crypto",
                venue="kraken",
                symbol="ETHUSD",
                rank=2,
                source="static",
                selection_reason="hard_coded_top_15",
                payload={"display_symbol": "ETH/USD", "display_name": "Ethereum", "kraken_pair": "ETHUSD"},
            )
        )
        db.add_all([
            StrategySnapshot(
                asset_class="crypto",
                venue="kraken",
                source="strategy_engine",
                symbol="ETHUSD",
                strategy_name="trend_continuation_long",
                direction="long",
                timeframe="4h",
                candidate_timestamp=now - timedelta(hours=1),
                computed_at=now - timedelta(hours=1),
                regime="bull",
                entry_policy="full",
                status="ready",
                readiness_score=Decimal("0.82"),
                composite_score=Decimal("0.79"),
                threshold_score=Decimal("0.70"),
                trend_score=Decimal("0.88"),
                participation_score=Decimal("0.76"),
                liquidity_score=Decimal("0.81"),
                stability_score=Decimal("0.74"),
                blocked_reasons=[],
                decision_reason=None,
                payload={"thresholds_passed": ["trend", "liquidity"]},
            ),
            StrategySnapshot(
                asset_class="crypto",
                venue="kraken",
                source="strategy_engine",
                symbol="ETHUSD",
                strategy_name="vwap_reclaim_long",
                direction="long",
                timeframe="15m",
                candidate_timestamp=now - timedelta(minutes=15),
                computed_at=now - timedelta(minutes=15),
                regime="neutral",
                entry_policy="moderate",
                status="blocked",
                readiness_score=Decimal("0.51"),
                composite_score=Decimal("0.60"),
                threshold_score=Decimal("0.70"),
                trend_score=Decimal("0.55"),
                participation_score=Decimal("0.58"),
                liquidity_score=Decimal("0.61"),
                stability_score=Decimal("0.57"),
                blocked_reasons=["regime_blocked"],
                decision_reason="regime_blocked",
                payload={"thresholds_failed": ["regime_blocked"]},
            ),
        ])
        db.commit()

    response = client.get("/api/v1/universe/crypto/current")
    assert response.status_code == 200
    payload = response.json()[0]["payload"]
    assert payload["eligibility"] == "Eligible"
    assert payload["composite_score"] == 0.79
    assert payload["liquidity_score"] == 0.81
    assert payload["participation_score"] == 0.76
    assert payload["trend_score"] == 0.88
    assert payload["best_strategy_timeframe"] == "4h"


def test_phase17_universe_route_marks_symbol_blocked_when_all_strategies_blocked(client) -> None:
    with get_session_factory()() as db:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        trade_date = trading_date_for_now(now)
        run = UniverseRun(
            asset_class="stock",
            venue="alpaca",
            trade_date=trade_date,
            source="fallback",
            status="resolved",
            resolved_at=now,
            payload={"resolution": "fallback"},
        )
        db.add(run)
        db.flush()
        db.add(
            UniverseConstituent(
                universe_run_id=run.id,
                asset_class="stock",
                venue="alpaca",
                symbol="AAPL",
                rank=1,
                source="fallback",
                selection_reason="screened",
                payload={},
            )
        )
        db.add(
            StrategySnapshot(
                asset_class="stock",
                venue="alpaca",
                source="strategy_engine",
                symbol="AAPL",
                strategy_name="trend_pullback_long",
                direction="long",
                timeframe="15m",
                candidate_timestamp=now - timedelta(minutes=15),
                computed_at=now - timedelta(minutes=15),
                regime="risk_off",
                entry_policy="blocked",
                status="blocked",
                readiness_score=Decimal("0.52"),
                composite_score=Decimal("0.58"),
                threshold_score=Decimal("0.68"),
                trend_score=Decimal("0.59"),
                participation_score=Decimal("0.55"),
                liquidity_score=Decimal("0.62"),
                stability_score=Decimal("0.60"),
                blocked_reasons=["regime_blocked", "composite_below_threshold"],
                decision_reason="regime_blocked",
                payload={"thresholds_failed": ["regime_blocked"]},
            )
        )
        db.commit()

    response = client.get("/api/v1/universe/stock/current")
    assert response.status_code == 200
    payload = response.json()[0]["payload"]
    assert payload["eligibility"] == "Blocked"
    assert "regime_blocked" in payload["block_reason"]


def test_phase17_strategy_route_filters_to_current_universe_symbols(client) -> None:
    with get_session_factory()() as db:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        trade_date = trading_date_for_now(now)
        run = UniverseRun(
            asset_class="stock",
            venue="alpaca",
            trade_date=trade_date,
            source="ai",
            status="resolved",
            resolved_at=now,
            payload={"resolution": "ai"},
        )
        db.add(run)
        db.flush()
        db.add(
            UniverseConstituent(
                universe_run_id=run.id,
                asset_class="stock",
                venue="alpaca",
                symbol="AAPL",
                rank=1,
                source="ai",
                selection_reason="selected",
                payload={},
            )
        )
        db.add_all([
            StrategySnapshot(
                asset_class="stock",
                venue="alpaca",
                source="strategy_engine",
                symbol="AAPL",
                strategy_name="trend_pullback_long",
                direction="long",
                timeframe="15m",
                candidate_timestamp=now - timedelta(minutes=15),
                computed_at=now - timedelta(minutes=15),
                regime="neutral",
                entry_policy="moderate",
                status="blocked",
                readiness_score=Decimal("0.61"),
                composite_score=Decimal("0.64"),
                threshold_score=Decimal("0.60"),
                trend_score=Decimal("0.66"),
                participation_score=Decimal("0.58"),
                liquidity_score=Decimal("0.73"),
                stability_score=Decimal("0.62"),
                blocked_reasons=["momentum_too_weak"],
                decision_reason="momentum_too_weak",
                payload={},
            ),
            StrategySnapshot(
                asset_class="stock",
                venue="alpaca",
                source="strategy_engine",
                symbol="MSFT",
                strategy_name="trend_pullback_long",
                direction="long",
                timeframe="15m",
                candidate_timestamp=now - timedelta(minutes=15),
                computed_at=now - timedelta(minutes=15),
                regime="neutral",
                entry_policy="moderate",
                status="ready",
                readiness_score=Decimal("0.81"),
                composite_score=Decimal("0.79"),
                threshold_score=Decimal("0.78"),
                trend_score=Decimal("0.84"),
                participation_score=Decimal("0.76"),
                liquidity_score=Decimal("0.82"),
                stability_score=Decimal("0.80"),
                blocked_reasons=[],
                decision_reason=None,
                payload={},
            ),
        ])
        db.commit()

    response = client.get("/api/v1/strategy/stock/current?timeframe=15m")
    assert response.status_code == 200
    payload = response.json()
    assert [row["symbol"] for row in payload] == ["AAPL"]
