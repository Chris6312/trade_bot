from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.base import Base
from backend.app.db.session import get_session_factory
from backend.app.models.core import AccountSnapshot, FeatureSnapshot, Setting, StrategySnapshot
from backend.app.services.risk_service import get_risk_sync_state, list_current_risk_snapshots
from backend.app.workers.risk_worker import RiskWorker


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase9_risk_worker.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()



def test_risk_engine_applies_default_moderate_profile(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=1000)
    _seed_feature(db_session, asset_class="stock", symbol="AAPL", close=100, atr=0.2)
    _seed_strategy(db_session, asset_class="stock", symbol="AAPL", strategy_name="trend_pullback_long")

    summary = RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 30, tzinfo=UTC))

    assert summary.accepted_count == 1
    row = _row(list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h"), symbol="AAPL", strategy_name="trend_pullback_long")
    assert row.status == "accepted"
    assert row.risk_profile == "moderate"
    assert float(row.effective_risk_pct) == pytest.approx(0.0125, abs=1e-9)



def test_risk_engine_enforces_max_risk_per_trade_cap(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=1000)
    _seed_setting(db_session, key="risk.default_per_trade_pct", value="0.03")
    _seed_feature(db_session, asset_class="stock", symbol="MSFT", close=100, atr=0.2)
    _seed_strategy(db_session, asset_class="stock", symbol="MSFT", strategy_name="trend_pullback_long")

    RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 31, tzinfo=UTC))

    row = _row(list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h"), symbol="MSFT", strategy_name="trend_pullback_long")
    assert row.status == "accepted"
    assert float(row.effective_risk_pct) == pytest.approx(0.02, abs=1e-9)
    assert float(row.projected_loss_pct) <= 0.02



def test_risk_engine_enforces_max_deployment(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=1000)
    for symbol in ("AAPL", "MSFT"):
        _seed_feature(db_session, asset_class="stock", symbol=symbol, close=100, atr=0.2)
        _seed_strategy(db_session, asset_class="stock", symbol=symbol, strategy_name=f"strategy_{symbol.lower()}")

    summary = RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 32, tzinfo=UTC))

    rows = list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h")
    accepted = [row for row in rows if row.status == "accepted"]
    blocked = [row for row in rows if row.status == "blocked"]
    assert summary.accepted_count == 1
    assert len(accepted) == 1
    assert len(blocked) == 1
    assert float(accepted[0].deployment_pct) <= 0.90
    assert "deployment_cap_reached" in (blocked[0].blocked_reasons or [])



def test_risk_engine_sizes_stocks_from_available_cash(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=180)
    _seed_feature(db_session, asset_class="stock", symbol="NVDA", close=100, atr=0.2)
    _seed_strategy(db_session, asset_class="stock", symbol="NVDA", strategy_name="trend_pullback_long")

    RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 33, tzinfo=UTC))

    row = _row(list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h"), symbol="NVDA", strategy_name="trend_pullback_long")
    assert row.status == "accepted"
    assert float(row.quantity) == 1.0
    assert float(row.notional_value) <= 180.0



def test_risk_engine_blocks_fee_burdened_trade(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=1000)
    _seed_setting(db_session, key="risk.stock.fee_pct", value="0.02")
    _seed_feature(db_session, asset_class="stock", symbol="AMD", close=100, atr=0.2)
    _seed_strategy(db_session, asset_class="stock", symbol="AMD", strategy_name="trend_pullback_long")

    RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 34, tzinfo=UTC))

    row = _row(list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h"), symbol="AMD", strategy_name="trend_pullback_long")
    assert row.status == "blocked"
    assert "fees_too_high" in (row.blocked_reasons or [])



def test_risk_engine_blocks_slippage_burdened_trade(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=1000)
    _seed_setting(db_session, key="risk.stock.slippage_pct", value="0.02")
    _seed_feature(db_session, asset_class="stock", symbol="META", close=100, atr=0.2)
    _seed_strategy(db_session, asset_class="stock", symbol="META", strategy_name="trend_pullback_long")

    RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 35, tzinfo=UTC))

    row = _row(list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h"), symbol="META", strategy_name="trend_pullback_long")
    assert row.status == "blocked"
    assert "slippage_too_high" in (row.blocked_reasons or [])



def test_risk_engine_enforces_long_only_until_2500(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=1000)
    _seed_feature(db_session, asset_class="stock", symbol="TSLA", close=100, atr=0.2)
    _seed_strategy(db_session, asset_class="stock", symbol="TSLA", strategy_name="trend_pullback_long", direction="short")

    RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 36, tzinfo=UTC))

    row = _row(list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h"), symbol="TSLA", strategy_name="trend_pullback_long")
    assert row.status == "blocked"
    assert "long_only_until_2500" in (row.blocked_reasons or [])



def test_risk_engine_blocks_new_stock_entries_when_stock_breaker_is_hit(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=1000, realized_pnl=-40, unrealized_pnl=-20)
    _seed_feature(db_session, asset_class="stock", symbol="AAPL", close=100, atr=0.2)
    _seed_strategy(db_session, asset_class="stock", symbol="AAPL", strategy_name="trend_pullback_long")

    summary = RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 37, tzinfo=UTC))

    row = _row(list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h"), symbol="AAPL", strategy_name="trend_pullback_long")
    assert row.status == "blocked"
    assert "stock_circuit_breaker_hard" in (row.blocked_reasons or [])
    assert summary.breaker_status == "stock_circuit_breaker_hard"



def test_risk_engine_blocks_new_crypto_entries_when_crypto_breaker_is_hit(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000)
    _seed_asset_account(db_session, asset_class="crypto", equity=1000, cash=1000, realized_pnl=-45, unrealized_pnl=-25)
    _seed_feature(db_session, asset_class="crypto", symbol="XBTUSD", close=30000, atr=150)
    _seed_strategy(db_session, asset_class="crypto", symbol="XBTUSD", strategy_name="trend_continuation_long", venue="kraken")

    summary = RiskWorker(db_session).build_crypto_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 38, tzinfo=UTC))

    row = _row(list_current_risk_snapshots(db_session, asset_class="crypto", timeframe="1h"), symbol="XBTUSD", strategy_name="trend_continuation_long")
    assert row.status == "blocked"
    assert "crypto_circuit_breaker_hard" in (row.blocked_reasons or [])
    assert summary.breaker_status == "crypto_circuit_breaker_hard"



def test_risk_engine_blocks_new_entries_when_total_account_breaker_is_hit(db_session: Session) -> None:
    _seed_total_account(db_session, equity=1000, cash=1000, realized_pnl=-50, unrealized_pnl=-30)
    _seed_asset_account(db_session, asset_class="stock", equity=1000, cash=1000)
    _seed_feature(db_session, asset_class="stock", symbol="AAPL", close=100, atr=0.2)
    _seed_strategy(db_session, asset_class="stock", symbol="AAPL", strategy_name="trend_pullback_long")

    summary = RiskWorker(db_session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 39, tzinfo=UTC))

    row = _row(list_current_risk_snapshots(db_session, asset_class="stock", timeframe="1h"), symbol="AAPL", strategy_name="trend_pullback_long")
    state = get_risk_sync_state(db_session, asset_class="stock", timeframe="1h")
    assert row.status == "blocked"
    assert "total_account_circuit_breaker_hard" in (row.blocked_reasons or [])
    assert summary.breaker_status == "total_account_circuit_breaker_hard"
    assert state is not None
    assert state.last_status == "circuit_breaker_blocked"



def test_risk_api_exposes_current_decisions_and_sync_state(client) -> None:
    session = get_session_factory()()
    try:
        _seed_total_account(session, equity=1000, cash=1000)
        _seed_asset_account(session, asset_class="stock", equity=1000, cash=1000)
        _seed_feature(session, asset_class="stock", symbol="AAPL", close=100, atr=0.2)
        _seed_strategy(session, asset_class="stock", symbol="AAPL", strategy_name="trend_pullback_long")
        RiskWorker(session).build_stock_risk(timeframe="1h", now=datetime(2026, 3, 14, 15, 40, tzinfo=UTC))
    finally:
        session.close()

    response = client.get("/api/v1/risk/stock/current", params={"timeframe": "1h"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["symbol"] == "AAPL"
    assert payload[0]["status"] == "accepted"
    assert float(payload[0]["effective_risk_pct"]) == pytest.approx(0.0125, abs=1e-9)

    sync_response = client.get("/api/v1/risk/stock/sync-state", params={"timeframe": "1h"})
    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["candidate_count"] == 1
    assert sync_payload["accepted_count"] == 1



def _row(rows, *, symbol: str, strategy_name: str):
    return next(row for row in rows if row.symbol == symbol and row.strategy_name == strategy_name)



def _seed_total_account(
    db: Session,
    *,
    equity: float,
    cash: float,
    realized_pnl: float = 0,
    unrealized_pnl: float = 0,
) -> None:
    _seed_account_snapshot(
        db,
        account_scope="total",
        equity=equity,
        cash=cash,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
    )



def _seed_asset_account(
    db: Session,
    *,
    asset_class: str,
    equity: float,
    cash: float,
    realized_pnl: float = 0,
    unrealized_pnl: float = 0,
) -> None:
    _seed_account_snapshot(
        db,
        account_scope=asset_class,
        equity=equity,
        cash=cash,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
    )



def _seed_account_snapshot(
    db: Session,
    *,
    account_scope: str,
    equity: float,
    cash: float,
    realized_pnl: float,
    unrealized_pnl: float,
) -> None:
    db.add(
        AccountSnapshot(
            account_scope=account_scope,
            venue="paper",
            mode="mixed",
            equity=Decimal(str(equity)),
            cash=Decimal(str(cash)),
            buying_power=Decimal(str(cash)),
            realized_pnl=Decimal(str(realized_pnl)),
            unrealized_pnl=Decimal(str(unrealized_pnl)),
            as_of=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
        )
    )
    db.commit()



def _seed_feature(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    close: float,
    atr: float,
    timeframe: str = "1h",
) -> None:
    venue = "alpaca" if asset_class == "stock" else "kraken"
    db.add(
        FeatureSnapshot(
            asset_class=asset_class,
            venue=venue,
            source="feature_engine",
            symbol=symbol,
            timeframe=timeframe,
            candle_timestamp=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
            computed_at=datetime(2026, 3, 14, 15, 1, tzinfo=UTC),
            close=Decimal(str(close)),
            volume=Decimal("1000000"),
            price_return_1=Decimal("0.02"),
            sma_20=Decimal(str(close * 0.99)),
            ema_20=Decimal(str(close * 0.995)),
            momentum_20=Decimal("0.03"),
            volume_sma_20=Decimal("1000000"),
            relative_volume_20=Decimal("1.2"),
            dollar_volume=Decimal(str(close * 1000000)),
            dollar_volume_sma_20=Decimal(str(close * 900000)),
            atr_14=Decimal(str(atr)),
            realized_volatility_20=Decimal("0.02") if asset_class == "stock" else Decimal("0.03"),
            trend_slope_20=Decimal("0.015"),
            payload={"seeded": True},
        )
    )
    db.commit()



def _seed_strategy(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    strategy_name: str,
    venue: str | None = None,
    direction: str = "long",
    status: str = "ready",
) -> None:
    db.add(
        StrategySnapshot(
            asset_class=asset_class,
            venue=venue or ("alpaca" if asset_class == "stock" else "kraken"),
            source="strategy_engine",
            symbol=symbol,
            strategy_name=strategy_name,
            direction=direction,
            timeframe="1h",
            candidate_timestamp=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
            computed_at=datetime(2026, 3, 14, 15, 2, tzinfo=UTC),
            regime="bull",
            entry_policy="full",
            status=status,
            readiness_score=Decimal("0.75"),
            composite_score=Decimal("0.75"),
            threshold_score=Decimal("0.60"),
            trend_score=Decimal("0.80"),
            participation_score=Decimal("0.72"),
            liquidity_score=Decimal("0.90"),
            stability_score=Decimal("0.68"),
            blocked_reasons=[] if status == "ready" else ["upstream_blocked"],
            decision_reason=None if status == "ready" else "upstream_blocked",
            payload={"seeded": True},
        )
    )
    db.commit()



def _seed_setting(db: Session, *, key: str, value: str) -> None:
    db.add(
        Setting(
            key=key,
            value=value,
            value_type="string",
            description="test setting",
            is_secret=False,
        )
    )
    db.commit()



def test_risk_api_returns_empty_list_when_no_current_rows(client) -> None:
    response = client.get("/api/v1/risk/stock/current", params={"timeframe": "1h"})
    assert response.status_code == 200
    assert response.json() == []
