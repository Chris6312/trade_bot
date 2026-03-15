from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from backend.app.db.session import get_session_factory
from backend.app.models.core import Candle, CandleFreshness, CandleSyncState, FeatureSyncState, Setting, SystemEvent, UniverseConstituent, UniverseRun
from backend.app.services.universe_service import trading_date_for_now


def test_phase13_support_routes_expose_ui_state(client) -> None:
    with get_session_factory()() as db:
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        trade_date = trading_date_for_now(now)
        run = UniverseRun(asset_class="stock", venue="alpaca", trade_date=trade_date, source="ai", status="resolved", resolved_at=now, payload={"resolution": "ai"})
        db.add(run)
        db.flush()
        db.add_all([
            UniverseConstituent(universe_run_id=run.id, asset_class="stock", venue="alpaca", symbol="MSFT", rank=1, source="ai", selection_reason="ranked first", payload={"ai_rank_score": 0.95}),
            UniverseConstituent(universe_run_id=run.id, asset_class="stock", venue="alpaca", symbol="AAPL", rank=2, source="ai", selection_reason="ranked second", payload={"ai_rank_score": 0.91}),
        ])
        db.add_all([
            CandleSyncState(asset_class="stock", venue="alpaca", symbol="AAPL", timeframe="1h", last_synced_at=now, last_candle_at=now, last_status="synced", last_error=None),
            CandleFreshness(asset_class="stock", venue="alpaca", symbol="AAPL", timeframe="1h", last_synced_at=now, last_candle_at=now, fresh_through=now),
        ])
        db.add_all([
            Candle(asset_class="stock", venue="alpaca", source="test", symbol="AAPL", timeframe="1h", timestamp=now - timedelta(hours=26), open=99, high=101, low=98, close=100, volume=900, vwap=100, trade_count=9),
            Candle(asset_class="stock", venue="alpaca", source="test", symbol="AAPL", timeframe="1h", timestamp=now - timedelta(hours=2), open=100, high=102, low=99, close=101, volume=1000, vwap=101, trade_count=10),
            Candle(asset_class="stock", venue="alpaca", source="test", symbol="AAPL", timeframe="1h", timestamp=now - timedelta(hours=1), open=101, high=104, low=100, close=103, volume=1200, vwap=103, trade_count=12),
            Candle(asset_class="stock", venue="alpaca", source="test", symbol="AAPL", timeframe="5m", timestamp=now - timedelta(hours=25), open=99, high=101, low=98, close=100, volume=950, vwap=100, trade_count=9),
            Candle(asset_class="stock", venue="alpaca", source="test", symbol="AAPL", timeframe="5m", timestamp=now - timedelta(minutes=5), open=103, high=105, low=102, close=104, volume=1250, vwap=104, trade_count=13),
            Candle(asset_class="stock", venue="alpaca", source="test", symbol="MSFT", timeframe="1h", timestamp=now - timedelta(hours=25), open=198, high=201, low=197, close=200, volume=1100, vwap=200, trade_count=11),
            Candle(asset_class="stock", venue="alpaca", source="test", symbol="MSFT", timeframe="1h", timestamp=now - timedelta(hours=1), open=200, high=207, low=199, close=205, volume=1300, vwap=205, trade_count=13),
        ])
        db.add(FeatureSyncState(asset_class="stock", venue="alpaca", symbol="AAPL", timeframe="1h", last_computed_at=now, last_candle_at=now, feature_count=20, last_status="computed", last_error=None))
        db.add(Setting(key="controls.kill_switch_enabled", value="false", value_type="bool"))
        db.add(SystemEvent(event_type="control.refresh", severity="info", message="refresh complete", event_source="test"))
        db.commit()

    universe_response = client.get("/api/v1/universe/stock/current")
    assert universe_response.status_code == 200
    payload = universe_response.json()
    assert [row["symbol"] for row in payload] == ["MSFT", "AAPL"]
    assert payload[1]["payload"]["last_price"] == 104.0
    assert round(payload[1]["payload"]["change_pct"], 2) == 4.0
    assert payload[1]["payload"]["change_window"] == "24h"
    assert payload[1]["payload"]["price_timeframe"] == "5m"

    candle_response = client.get("/api/v1/data/candles/stock/sync-state")
    assert candle_response.status_code == 200
    assert candle_response.json()[0]["last_status"] == "synced"

    feature_response = client.get("/api/v1/data/features/stock/sync-state")
    assert feature_response.status_code == 200
    assert feature_response.json()[0]["feature_count"] == 20

    settings_response = client.get("/api/v1/settings")
    assert settings_response.status_code == 200
    assert settings_response.json()[0]["key"] == "controls.kill_switch_enabled"

    events_response = client.get("/api/v1/system-events")
    assert events_response.status_code == 200
    assert events_response.json()[0]["event_type"] == "control.refresh"


def test_phase13_universe_change_pct_ignores_stale_intraday_baseline(client) -> None:
    with get_session_factory()() as db:
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        trade_date = trading_date_for_now(now)
        run = UniverseRun(asset_class="crypto", venue="kraken", trade_date=trade_date, source="static", status="resolved", resolved_at=now, payload={"resolution": "static"})
        db.add(run)
        db.flush()
        db.add(UniverseConstituent(universe_run_id=run.id, asset_class="crypto", venue="kraken", symbol="XBTUSD", rank=1, source="static", selection_reason="top pair", payload={}))
        db.add_all([
            Candle(asset_class="crypto", venue="kraken", source="test", symbol="XBTUSD", timeframe="15m", timestamp=now - timedelta(days=3), open=95000, high=96000, low=94000, close=95500, volume=900, vwap=95500, trade_count=90),
            Candle(asset_class="crypto", venue="kraken", source="test", symbol="XBTUSD", timeframe="15m", timestamp=now - timedelta(minutes=15), open=100000, high=101000, low=99500, close=100500, volume=1200, vwap=100500, trade_count=120),
        ])
        db.commit()

    response = client.get("/api/v1/universe/crypto/current")
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["payload"]["last_price"] == 100500.0
    assert payload[0]["payload"]["change_pct"] is None


def test_phase13_control_snapshot_and_toggle(client) -> None:
    snapshot_before = client.get("/api/v1/controls/snapshot")
    assert snapshot_before.status_code == 200
    assert snapshot_before.json()["kill_switch_enabled"] is False

    toggle_response = client.post("/api/v1/controls/kill-switch/toggle", json={"enabled": True})
    assert toggle_response.status_code == 200
    assert toggle_response.json()["status"] == "completed"

    snapshot_after = client.get("/api/v1/controls/snapshot")
    assert snapshot_after.status_code == 200
    assert snapshot_after.json()["kill_switch_enabled"] is True


def test_phase13_run_once_controls_are_wired(client, monkeypatch) -> None:
    from backend.app.api.routes import controls as controls_route

    monkeypatch.setattr(controls_route.UniverseWorker, "resolve_stock_universe", lambda self, force=False: SimpleNamespace(asset_class="stock", source="ai", symbols=("AAPL",)))
    monkeypatch.setattr(controls_route.UniverseWorker, "resolve_crypto_universe", lambda self, force=False: SimpleNamespace(asset_class="crypto", source="static", symbols=("BTCUSD",)))
    monkeypatch.setattr(controls_route.SingleCandleWorker, "sync_stock_backfill", lambda self, symbols, timeframe: SimpleNamespace(requested_symbols=tuple(symbols), upserted_bars=25, skipped_reason=None))
    monkeypatch.setattr(controls_route.SingleCandleWorker, "sync_crypto_incremental", lambda self, symbols, timeframe: SimpleNamespace(requested_symbols=tuple(symbols), upserted_bars=12, skipped_reason=None))
    monkeypatch.setattr(controls_route.RegimeWorker, "build_stock_regime", lambda self, timeframe=None: SimpleNamespace(regime="bull", entry_policy="full", symbol_count=8))
    monkeypatch.setattr(controls_route.FeatureWorker, "build_stock_features", lambda self, timeframe=None: SimpleNamespace(computed_snapshots=8))
    monkeypatch.setattr(controls_route.FeatureWorker, "build_crypto_features", lambda self, timeframe=None: SimpleNamespace(computed_snapshots=6))
    monkeypatch.setattr(controls_route.RegimeWorker, "build_crypto_regime", lambda self, timeframe=None: SimpleNamespace(regime="bull", entry_policy="full", symbol_count=6))
    monkeypatch.setattr(controls_route.StrategyWorker, "build_stock_candidates", lambda self, timeframe=None: SimpleNamespace(evaluated_rows=8, ready_rows=3, blocked_rows=5))
    monkeypatch.setattr(controls_route.StrategyWorker, "build_crypto_candidates", lambda self, timeframe=None: SimpleNamespace(evaluated_rows=6, ready_rows=2, blocked_rows=4))

    universe_response = client.post("/api/v1/controls/universe/run-once", json={"asset_class": "all"})
    assert universe_response.status_code == 200
    assert universe_response.json()["action"] == "refresh_universe"

    backfill_response = client.post("/api/v1/controls/candles/backfill", json={"asset_class": "stock", "symbols": ["AAPL"], "timeframe": "1h"})
    assert backfill_response.status_code == 200
    assert backfill_response.json()["details"][0]["upserted_bars"] == 25

    incremental_response = client.post("/api/v1/controls/candles/incremental", json={"asset_class": "crypto", "symbols": ["BTCUSD"], "timeframe": "1h"})
    assert incremental_response.status_code == 200
    assert incremental_response.json()["details"][0]["upserted_bars"] == 12

    regime_response = client.post("/api/v1/controls/regime/run-once", json={"asset_class": "stock"})
    assert regime_response.status_code == 200
    assert regime_response.json()["details"][0]["regime"] == "bull"

    strategy_response = client.post("/api/v1/controls/strategy/run-once", json={"asset_class": "stock"})
    assert strategy_response.status_code == 200
    assert strategy_response.json()["details"][0]["ready_rows"] == 3

    flatten_response = client.post("/api/v1/controls/flatten/all", json={"engage_kill_switch": True})
    assert flatten_response.status_code == 200
    assert flatten_response.json()["status"] == "queued_manual_action"


def test_phase13_controls_expand_to_configured_timeframes_when_unspecified(client, monkeypatch) -> None:
    from backend.app.api.routes import controls as controls_route

    seen_candle_timeframes: list[str] = []
    seen_strategy_timeframes: list[str] = []

    monkeypatch.setattr(controls_route, "get_settings", lambda: SimpleNamespace(stock_feature_timeframe_list=["1h", "15m", "5m", "1d"], crypto_feature_timeframe_list=["4h", "1h", "15m", "1d"], execution_kill_switch_enabled=False, default_mode="mixed", stock_execution_mode="paper", crypto_execution_mode="paper"))
    monkeypatch.setattr(controls_route.SingleCandleWorker, "sync_stock_backfill", lambda self, symbols, timeframe: seen_candle_timeframes.append(timeframe) or SimpleNamespace(requested_symbols=tuple(symbols), upserted_bars=5, skipped_reason=None))
    monkeypatch.setattr(controls_route.FeatureWorker, "build_stock_features", lambda self, timeframe=None: seen_strategy_timeframes.append(timeframe) or SimpleNamespace(computed_snapshots=8))
    monkeypatch.setattr(controls_route.RegimeWorker, "build_stock_regime", lambda self, timeframe=None: SimpleNamespace(regime="bull", entry_policy="full", symbol_count=8))
    monkeypatch.setattr(controls_route.StrategyWorker, "build_stock_candidates", lambda self, timeframe=None: SimpleNamespace(evaluated_rows=8, ready_rows=3, blocked_rows=5))

    backfill_response = client.post("/api/v1/controls/candles/backfill", json={"asset_class": "stock", "symbols": ["AAPL"]})
    assert backfill_response.status_code == 200
    assert seen_candle_timeframes == ["1h", "15m", "5m", "1d"]
    assert [item["timeframe"] for item in backfill_response.json()["details"]] == ["1h", "15m", "5m", "1d"]

    strategy_response = client.post("/api/v1/controls/strategy/run-once", json={"asset_class": "stock"})
    assert strategy_response.status_code == 200
    assert seen_strategy_timeframes == ["1h", "15m", "5m", "1d"]
    assert [item["timeframe"] for item in strategy_response.json()["details"]] == ["1h", "15m", "5m", "1d"]
