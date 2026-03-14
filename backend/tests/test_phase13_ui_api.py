from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from backend.app.db.session import get_session_factory
from backend.app.models.core import (
    CandleFreshness,
    CandleSyncState,
    FeatureSyncState,
    Setting,
    SystemEvent,
    UniverseConstituent,
    UniverseRun,
)
from backend.app.services.universe_service import trading_date_for_now


def test_phase13_support_routes_expose_ui_state(client) -> None:
    with get_session_factory()() as db:
        now = datetime.now(UTC)
        run = UniverseRun(
            asset_class="stock",
            venue="alpaca",
            trade_date=trading_date_for_now(now),
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
                selection_reason="ranked by ai",
                payload={"ai_rank_score": 0.91},
            )
        )
        db.add(
            CandleSyncState(
                asset_class="stock",
                venue="alpaca",
                symbol="AAPL",
                timeframe="1h",
                last_synced_at=now,
                last_candle_at=now,
                last_status="synced",
                last_error=None,
            )
        )
        db.add(
            CandleFreshness(
                asset_class="stock",
                venue="alpaca",
                symbol="AAPL",
                timeframe="1h",
                last_synced_at=now,
                last_candle_at=now,
                fresh_through=now,
            )
        )
        db.add(
            FeatureSyncState(
                asset_class="stock",
                venue="alpaca",
                symbol="AAPL",
                timeframe="1h",
                last_computed_at=now,
                last_candle_at=now,
                feature_count=20,
                last_status="computed",
                last_error=None,
            )
        )
        db.add(Setting(key="controls.kill_switch_enabled", value="false", value_type="bool"))
        db.add(SystemEvent(event_type="control.refresh", severity="info", message="refresh complete", event_source="test"))
        db.commit()

    universe_response = client.get("/api/v1/universe/stock/current")
    assert universe_response.status_code == 200
    assert universe_response.json()[0]["symbol"] == "AAPL"

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

    monkeypatch.setattr(
        controls_route.UniverseWorker,
        "resolve_stock_universe",
        lambda self, force=False: SimpleNamespace(asset_class="stock", source="ai", symbols=("AAPL",)),
    )
    monkeypatch.setattr(
        controls_route.UniverseWorker,
        "resolve_crypto_universe",
        lambda self, force=False: SimpleNamespace(asset_class="crypto", source="static", symbols=("BTCUSD",)),
    )
    monkeypatch.setattr(
        controls_route.SingleCandleWorker,
        "sync_stock_backfill",
        lambda self, symbols, timeframe: SimpleNamespace(requested_symbols=tuple(symbols), upserted_bars=25, skipped_reason=None),
    )
    monkeypatch.setattr(
        controls_route.SingleCandleWorker,
        "sync_crypto_incremental",
        lambda self, symbols, timeframe: SimpleNamespace(requested_symbols=tuple(symbols), upserted_bars=12, skipped_reason=None),
    )
    monkeypatch.setattr(
        controls_route.RegimeWorker,
        "build_stock_regime",
        lambda self, timeframe=None: SimpleNamespace(regime="bull", entry_policy="full", symbol_count=8),
    )
    monkeypatch.setattr(
        controls_route.FeatureWorker,
        "build_stock_features",
        lambda self, timeframe=None: SimpleNamespace(computed_snapshots=8),
    )
    monkeypatch.setattr(
        controls_route.StrategyWorker,
        "build_stock_candidates",
        lambda self, timeframe=None: SimpleNamespace(evaluated_rows=8, ready_rows=3, blocked_rows=5),
    )

    universe_response = client.post("/api/v1/controls/universe/run-once", json={"asset_class": "all"})
    assert universe_response.status_code == 200
    assert universe_response.json()["action"] == "refresh_universe"

    backfill_response = client.post(
        "/api/v1/controls/candles/backfill",
        json={"asset_class": "stock", "symbols": ["AAPL"], "timeframe": "1h"},
    )
    assert backfill_response.status_code == 200
    assert backfill_response.json()["details"][0]["upserted_bars"] == 25

    incremental_response = client.post(
        "/api/v1/controls/candles/incremental",
        json={"asset_class": "crypto", "symbols": ["BTCUSD"], "timeframe": "1h"},
    )
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
