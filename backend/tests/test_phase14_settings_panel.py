from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.common.adapters.models import OrderRequest, OrderResult
from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.models.core import AccountSnapshot, AiResearchPick, Candle, FeatureSnapshot, RegimeSnapshot, RiskSnapshot, Setting, StrategySnapshot
from backend.app.services import universe_service
from backend.app.services.execution_service import get_execution_sync_state, list_current_execution_orders
from backend.app.services.risk_service import list_current_risk_snapshots
from backend.app.services.strategy_service import list_current_strategy_snapshots
from backend.app.workers.execution_worker import ExecutionWorker
from backend.app.workers.risk_worker import RiskWorker
from backend.app.workers.strategy_worker import StrategyWorker
from backend.app.workers.universe_worker import UniverseWorker


class FakeScreenerAdapter:
    def __init__(self, rows: list[dict], assets: dict[str, dict]) -> None:
        self.rows = rows
        self.assets = assets

    def fetch_most_active(self, *, top: int = 50, by: str = "volume") -> list[dict]:
        return self.rows

    def fetch_asset(self, *, symbol: str) -> dict:
        return self.assets.get(symbol, {})


class FakeRegistry:
    def __init__(self, screener: FakeScreenerAdapter) -> None:
        self._screener = screener

    def alpaca_stock_screener(self) -> FakeScreenerAdapter:
        return self._screener


class FakeAIService:
    def __init__(self, rankings: list[dict] | None = None) -> None:
        self.rankings = rankings or []
        self.calls = 0

    def rank_candidates(self, candidates: list[dict]) -> list[dict]:
        self.calls += 1
        return self.rankings


class RecordingAdapter:
    def __init__(self, result: OrderResult | None = None) -> None:
        self.result = result or OrderResult(venue="alpaca", asset_class="stock", order_id="ord-1", status="submitted", raw={})
        self.requests: list[OrderRequest] = []

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.requests.append(request)
        return self.result


@pytest.fixture()
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase14_settings_panel.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(universe_service, "PROJECT_ROOT", tmp_path)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_settings_batch_endpoint_persists_multiple_runtime_controls(client) -> None:
    response = client.post(
        "/api/v1/settings/batch",
        json={
            "items": [
                {"key": "execution.default_mode", "value": "mixed", "value_type": "string", "description": "default mode"},
                {"key": "execution.stock.mode", "value": "live", "value_type": "string", "description": "stock mode"},
                {"key": "risk.default_per_trade_pct", "value": "0.01", "value_type": "float", "description": "risk"},
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    keys = {row["key"] for row in payload}
    assert "execution.stock.mode" in keys

    listing = client.get("/api/v1/settings")
    assert listing.status_code == 200
    listed_keys = {row["key"] for row in listing.json()}
    assert {"execution.default_mode", "execution.stock.mode", "risk.default_per_trade_pct"}.issubset(listed_keys)


def test_stock_universe_uses_persisted_settings_without_restart(db_session: Session) -> None:
    """DB settings override constructor defaults at resolve time (no restart needed).

    Constructor has ai_enabled=False + source=fallback.  DB settings flip both
    to ai/enabled and cap max_size=2.  Seeded AI research picks prove the worker
    reads DB settings live and routes to ai_research rather than the screener.
    """
    trade_date = "2026-03-14"
    # Pre-seed AI research picks (NVDA, MSFT, AAPL — ordered by rank)
    for rank, symbol in enumerate(["NVDA", "MSFT", "AAPL"], start=1):
        db_session.add(AiResearchPick(
            trade_date=trade_date,
            scanned_at=datetime(2026, 3, 14, 13, 0, tzinfo=UTC),
            symbol=symbol,
            catalyst=f"{symbol} catalyst",
            approximate_price=Decimal("100.00"),
            stop_loss=Decimal("95.00"),
            take_profit_primary=Decimal("110.00"),
            use_trail_stop=False,
            is_bonus_pick=False,
            venue="alpaca",
        ))
    db_session.commit()

    screener = FakeScreenerAdapter(rows=[], assets={})  # should not be called
    # Worker constructed with ai_enabled=False, source=fallback — DB overrides both
    worker = UniverseWorker(
        db_session,
        registry=FakeRegistry(screener),
        settings=Settings(
            stock_universe_source="fallback",
            stock_universe_max_size=5,
            ai_enabled=False,
            ai_run_once_daily=False,
        ),
    )

    # DB settings override constructor: enable AI + set source=ai + cap size=2
    db_session.add_all([
        Setting(key="stock_universe_source", value="ai", value_type="string"),
        Setting(key="stock_universe_max_size", value="2", value_type="int"),
        Setting(key="ai_enabled", value="true", value_type="bool"),
        Setting(key="ai_run_once_daily", value="false", value_type="bool"),
    ])
    db_session.commit()

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 17, 0, tzinfo=UTC), force=True)

    # DB overrides took effect: ai_research used, max_size=2 enforced
    assert summary.source == "ai_research"
    assert summary.symbols == ("NVDA", "MSFT")
    # Screener was never called (no rows seeded, would raise if it tried)


def test_strategy_toggle_setting_blocks_runtime_candidates(db_session: Session) -> None:
    _seed_regime(db_session, asset_class="stock", venue="alpaca", timeframe="1h", regime="bull", entry_policy="full")
    _seed_feature(db_session, asset_class="stock", symbol="AAPL", close=Decimal("100"), atr=Decimal("0.2"))
    _seed_stock_strategy_input(db_session, symbol="AAPL")
    db_session.add(Setting(key="strategy_enabled.stock.trend_pullback_long", value="false", value_type="bool"))
    db_session.commit()

    summary = StrategyWorker(db_session).build_stock_candidates(timeframe="1h", now=datetime(2026, 3, 14, 17, 5, tzinfo=UTC))

    assert summary.evaluated_rows == 3
    row = next(row for row in list_current_strategy_snapshots(db_session, asset_class="stock", timeframe="1h") if row.strategy_name == "trend_pullback_long")
    assert row.status == "blocked"
    assert "strategy_disabled" in (row.blocked_reasons or [])


def test_execution_engine_respects_asset_trading_toggle(db_session: Session) -> None:
    _seed_risk_row(db_session, asset_class="stock", symbol="AAPL")
    db_session.add(Setting(key="controls.stock.trading_enabled", value="false", value_type="bool"))
    db_session.commit()
    adapter = RecordingAdapter()

    summary = ExecutionWorker(
        db_session,
        settings=Settings(default_mode="paper"),
        adapter_resolver=_mapping_resolver({"alpaca_stock_paper": adapter}),
    ).route_stock_orders(timeframe="1h", now=datetime(2026, 3, 14, 17, 10, tzinfo=UTC))

    state = get_execution_sync_state(db_session, asset_class="stock", timeframe="1h")
    assert summary.blocked_count == 1
    assert summary.last_status == "stock_trading_disabled"
    assert state is not None
    assert state.last_status == "stock_trading_disabled"
    assert len(adapter.requests) == 0
    assert list_current_execution_orders(db_session, asset_class="stock", timeframe="1h") == []


def test_execution_engine_uses_persisted_broker_mode_toggle(db_session: Session) -> None:
    _seed_risk_row(db_session, asset_class="stock", symbol="MSFT")
    db_session.add_all([
        Setting(key="execution.default_mode", value="mixed", value_type="string"),
        Setting(key="execution.stock.mode", value="live", value_type="string"),
    ])
    db_session.commit()
    adapter = RecordingAdapter(result=OrderResult(venue="public", asset_class="stock", order_id="public-1", status="submitted", raw={}))

    summary = ExecutionWorker(
        db_session,
        settings=Settings(default_mode="paper", stock_execution_mode="paper"),
        adapter_resolver=_mapping_resolver({"public_trading": adapter}),
    ).route_stock_orders(timeframe="1h", now=datetime(2026, 3, 14, 17, 11, tzinfo=UTC))

    assert summary.mode == "live"
    row = list_current_execution_orders(db_session, asset_class="stock", timeframe="1h")[0]
    assert row.mode == "live"
    assert row.venue == "public"


def test_risk_engine_uses_persisted_circuit_breaker_settings(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=1000, realized_pnl=-10, unrealized_pnl=-6)
    _seed_feature(db_session, asset_class="stock", symbol="AAPL", close=Decimal("100"), atr=Decimal("0.2"))
    _seed_ready_strategy(db_session, asset_class="stock", symbol="AAPL", strategy_name="trend_pullback_long")
    db_session.add(Setting(key="risk.stock.hard_stop_pct", value="-0.015", value_type="float"))
    db_session.commit()

    summary = RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 17, 15, tzinfo=UTC))

    assert summary.blocked_count == 1
    row = next(row for row in list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h") if row.symbol == "AAPL")
    assert row.status == "blocked"
    assert "stock_circuit_breaker_hard" in (row.blocked_reasons or [])


def test_kill_switch_toggle_updates_control_snapshot(client) -> None:
    before = client.get("/api/v1/controls/snapshot")
    assert before.status_code == 200
    assert before.json()["kill_switch_enabled"] is False

    toggle = client.post("/api/v1/controls/kill-switch/toggle", json={"enabled": True})
    assert toggle.status_code == 200

    after = client.get("/api/v1/controls/snapshot")
    assert after.status_code == 200
    assert after.json()["kill_switch_enabled"] is True


def _seed_regime(db: Session, *, asset_class: str, venue: str, timeframe: str, regime: str, entry_policy: str) -> None:
    db.add(
        RegimeSnapshot(
            asset_class=asset_class,
            venue=venue,
            source="test",
            timeframe=timeframe,
            regime_timestamp=datetime(2026, 3, 14, 16, 0, tzinfo=UTC),
            computed_at=datetime(2026, 3, 14, 16, 0, tzinfo=UTC),
            regime=regime,
            entry_policy=entry_policy,
            symbol_count=1,
            bull_score=Decimal("0.8"),
            breadth_ratio=Decimal("0.8"),
            benchmark_support_ratio=Decimal("0.8"),
            participation_ratio=Decimal("0.8"),
            volatility_support_ratio=Decimal("0.8"),
            payload={},
        )
    )
    db.commit()


def _seed_feature(db: Session, *, asset_class: str, symbol: str, close: Decimal, atr: Decimal) -> None:
    db.add(
        FeatureSnapshot(
            asset_class=asset_class,
            venue="alpaca" if asset_class == "stock" else "kraken",
            source="test",
            symbol=symbol,
            timeframe="1h",
            candle_timestamp=datetime(2026, 3, 14, 16, 0, tzinfo=UTC),
            computed_at=datetime(2026, 3, 14, 16, 0, tzinfo=UTC),
            close=close,
            volume=Decimal("1000000"),
            price_return_1=Decimal("0.02"),
            sma_20=close - Decimal("1"),
            ema_20=close - Decimal("0.5"),
            momentum_20=Decimal("0.03"),
            volume_sma_20=Decimal("900000"),
            relative_volume_20=Decimal("1.2"),
            dollar_volume=close * Decimal("1000000"),
            dollar_volume_sma_20=close * Decimal("900000"),
            atr_14=atr,
            realized_volatility_20=Decimal("0.01"),
            trend_slope_20=Decimal("0.02"),
            payload={"vwap": float(close - Decimal("0.25")), "open": float(close - Decimal("1.0")), "high": float(close + Decimal("0.5")), "rsi_14": 48},
        )
    )
    db.commit()


def _seed_stock_strategy_input(db: Session, *, symbol: str) -> None:
    _seed_universe(db, asset_class="stock", venue="alpaca", symbols=(symbol,))
    closes = [100, 100.8, 101.4, 102.0, 102.8, 103.6, 104.2, 104.9, 105.5, 106.0, 106.4, 106.8, 107.1, 107.3, 107.5, 107.7, 107.9, 108.1, 108.3, 108.5, 108.6, 108.8, 109.0, 107.8, 110.0]
    for index, close in enumerate(closes):
        db.add(
            Candle(
                asset_class="stock",
                venue="alpaca",
                symbol=symbol,
                timeframe="1h",
                source="test",
                timestamp=datetime(2026, 3, 13, 16, 0, tzinfo=UTC) + timedelta(hours=index),
                open=Decimal(str(close - 0.4)),
                high=Decimal(str(close + 0.6)),
                low=Decimal(str(close - 0.7)),
                close=Decimal(str(close)),
                volume=Decimal(str(1000 + (index * 50))),
                vwap=Decimal(str(close - 0.2)),
                trade_count=100 + index,
            )
        )
    db.commit()


def _seed_universe(db: Session, *, asset_class: str, venue: str, symbols: tuple[str, ...]) -> None:
    from backend.app.services.universe_service import UniverseSymbolRecord, persist_universe_run

    persist_universe_run(
        db,
        asset_class=asset_class,
        venue=venue,
        trade_date=universe_service.trading_date_for_now(datetime(2026, 3, 14, 16, 0, tzinfo=UTC)),
        source="test",
        status="resolved",
        symbols=[UniverseSymbolRecord(asset_class=asset_class, venue=venue, symbol=symbol, rank=index + 1, source="test") for index, symbol in enumerate(symbols)],
        resolved_at=datetime(2026, 3, 14, 16, 0, tzinfo=UTC),
        payload={"resolution": "test"},
    )


def _seed_total_account(db: Session, *, equity: int | float, cash: int | float, realized_pnl: int | float = 0, unrealized_pnl: int | float = 0) -> None:
    db.add(AccountSnapshot(account_scope="total", venue="aggregate", mode="aggregate", equity=Decimal(str(equity)), cash=Decimal(str(cash)), buying_power=Decimal(str(cash)), realized_pnl=Decimal(str(realized_pnl)), unrealized_pnl=Decimal(str(unrealized_pnl)), as_of=datetime(2026, 3, 14, 16, 0, tzinfo=UTC)))
    db.commit()


def _seed_asset_account(db: Session, *, asset_class: str, equity: int | float, cash: int | float, realized_pnl: int | float = 0, unrealized_pnl: int | float = 0) -> None:
    venue = "alpaca" if asset_class == "stock" else "kraken"
    db.add(AccountSnapshot(account_scope=asset_class, venue=venue, mode="paper", equity=Decimal(str(equity)), cash=Decimal(str(cash)), buying_power=Decimal(str(cash)), realized_pnl=Decimal(str(realized_pnl)), unrealized_pnl=Decimal(str(unrealized_pnl)), as_of=datetime(2026, 3, 14, 16, 0, tzinfo=UTC)))
    db.commit()


def _seed_ready_strategy(db: Session, *, asset_class: str, symbol: str, strategy_name: str) -> None:
    db.add(StrategySnapshot(asset_class=asset_class, venue="alpaca" if asset_class == "stock" else "kraken", source="test", symbol=symbol, strategy_name=strategy_name, direction="long", timeframe="1h", candidate_timestamp=datetime(2026, 3, 14, 16, 0, tzinfo=UTC), computed_at=datetime(2026, 3, 14, 16, 0, tzinfo=UTC), regime="bull", entry_policy="full", status="ready", readiness_score=Decimal("0.8"), composite_score=Decimal("0.8"), threshold_score=Decimal("0.6"), trend_score=Decimal("0.8"), participation_score=Decimal("0.8"), liquidity_score=Decimal("0.8"), stability_score=Decimal("0.8"), blocked_reasons=[], decision_reason="ready", payload={}))
    db.commit()


def _seed_risk_row(db: Session, *, asset_class: str, symbol: str) -> None:
    db.add(RiskSnapshot(asset_class=asset_class, venue="alpaca" if asset_class == "stock" else "kraken", source="test", symbol=symbol, strategy_name="trend_pullback_long", direction="long", timeframe="1h", candidate_timestamp=datetime(2026, 3, 14, 16, 0, tzinfo=UTC), computed_at=datetime(2026, 3, 14, 16, 0, tzinfo=UTC), status="accepted", risk_profile="moderate", decision_reason="accepted", blocked_reasons=[], account_equity=Decimal("1000"), account_cash=Decimal("1000"), entry_price=Decimal("100"), stop_price=Decimal("99"), stop_distance=Decimal("1"), stop_distance_pct=Decimal("0.01"), quantity=Decimal("1"), notional_value=Decimal("100"), deployment_pct=Decimal("0.1"), cumulative_deployment_pct=Decimal("0.1"), requested_risk_pct=Decimal("0.0125"), effective_risk_pct=Decimal("0.0125"), max_risk_pct=Decimal("0.02"), risk_budget_amount=Decimal("12.5"), projected_loss_amount=Decimal("1"), projected_loss_pct=Decimal("0.01"), fee_pct=Decimal("0.0005"), slippage_pct=Decimal("0.0005"), estimated_fees=Decimal("0.05"), estimated_slippage=Decimal("0.05"), strategy_readiness_score=Decimal("0.8"), strategy_composite_score=Decimal("0.8"), strategy_threshold_score=Decimal("0.6"), payload={}))
    db.commit()


def _mapping_resolver(mapping: dict[str, RecordingAdapter]):
    def _resolve(route):
        return mapping[route.adapter_key]

    return _resolve
