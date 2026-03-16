from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.db.session import get_session_factory
from backend.app.models.core import Candle, UniverseConstituent, UniverseRun
from backend.app.services.universe_service import trading_date_for_now


def test_phase17_stock_universe_change_pct_uses_previous_daily_close(client) -> None:
    with get_session_factory()() as db:
        now = datetime.now(UTC).replace(minute=35, second=0, microsecond=0)
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
                selection_reason="ranked first",
                payload={},
            )
        )
        db.add_all(
            [
                Candle(
                    asset_class="stock",
                    venue="alpaca",
                    source="test",
                    symbol="AAPL",
                    timeframe="1d",
                    timestamp=now - timedelta(days=1),
                    open=100,
                    high=106,
                    low=99,
                    close=105,
                    volume=1000,
                    vwap=105,
                    trade_count=10,
                ),
                Candle(
                    asset_class="stock",
                    venue="alpaca",
                    source="test",
                    symbol="AAPL",
                    timeframe="5m",
                    timestamp=now - timedelta(minutes=5),
                    open=109,
                    high=111,
                    low=108,
                    close=110,
                    volume=120,
                    vwap=110,
                    trade_count=12,
                ),
            ]
        )
        db.commit()

    response = client.get("/api/v1/universe/stock/current")
    assert response.status_code == 200
    payload = response.json()[0]["payload"]
    assert payload["last_price"] == 110.0
    assert round(payload["change_pct"], 4) == round(((110.0 - 105.0) / 105.0) * 100, 4)
    assert payload["change_window"] == "prev_close"
    assert payload["price_timeframe"] == "5m"


def test_phase17_crypto_universe_change_pct_uses_15m_rolling_24h(client) -> None:
    with get_session_factory()() as db:
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
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
                rank=1,
                source="static",
                selection_reason="top pair",
                payload={},
            )
        )
        db.add_all(
            [
                Candle(
                    asset_class="crypto",
                    venue="kraken",
                    source="test",
                    symbol="ETHUSD",
                    timeframe="15m",
                    timestamp=now - timedelta(hours=24),
                    open=2000,
                    high=2005,
                    low=1990,
                    close=2000,
                    volume=1000,
                    vwap=2000,
                    trade_count=100,
                ),
                Candle(
                    asset_class="crypto",
                    venue="kraken",
                    source="test",
                    symbol="ETHUSD",
                    timeframe="15m",
                    timestamp=now - timedelta(minutes=15),
                    open=2090,
                    high=2110,
                    low=2085,
                    close=2100,
                    volume=120,
                    vwap=2100,
                    trade_count=24,
                ),
                Candle(
                    asset_class="crypto",
                    venue="kraken",
                    source="test",
                    symbol="ETHUSD",
                    timeframe="1d",
                    timestamp=now - timedelta(days=1),
                    open=1900,
                    high=1950,
                    low=1890,
                    close=1940,
                    volume=5000,
                    vwap=1940,
                    trade_count=400,
                ),
            ]
        )
        db.commit()

    response = client.get("/api/v1/universe/crypto/current")
    assert response.status_code == 200
    payload = response.json()[0]["payload"]
    assert payload["last_price"] == 2100.0
    assert round(payload["change_pct"], 4) == 5.0
    assert payload["change_window"] == "24h_15m"
    assert payload["price_timeframe"] == "15m"


def test_phase17_crypto_universe_change_pct_is_null_without_15m_24h_baseline(client) -> None:
    with get_session_factory()() as db:
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
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
                rank=1,
                source="static",
                selection_reason="top pair",
                payload={},
            )
        )
        db.add_all(
            [
                Candle(
                    asset_class="crypto",
                    venue="kraken",
                    source="test",
                    symbol="ETHUSD",
                    timeframe="1d",
                    timestamp=now - timedelta(days=1),
                    open=1900,
                    high=1950,
                    low=1890,
                    close=1940,
                    volume=5000,
                    vwap=1940,
                    trade_count=400,
                ),
                Candle(
                    asset_class="crypto",
                    venue="kraken",
                    source="test",
                    symbol="ETHUSD",
                    timeframe="15m",
                    timestamp=now - timedelta(minutes=15),
                    open=2090,
                    high=2110,
                    low=2085,
                    close=2100,
                    volume=120,
                    vwap=2100,
                    trade_count=24,
                ),
            ]
        )
        db.commit()

    response = client.get("/api/v1/universe/crypto/current")
    assert response.status_code == 200
    payload = response.json()[0]["payload"]
    assert payload["last_price"] == 2100.0
    assert payload["change_pct"] is None
    assert payload["change_window"] is None
    assert payload["price_timeframe"] == "15m"