import base64
import logging

import httpx

from backend.app.core.config import get_settings
from backend.app.crypto.brokers.kraken_trading import KrakenTradingAdapter


def test_kraken_account_state_fetches_balance_and_trade_balance(monkeypatch) -> None:
    secret = base64.b64encode(b"kraken-secret-bytes").decode("utf-8")
    monkeypatch.setenv("KRAKEN_API_KEY", "kraken_live_key_12345678")
    monkeypatch.setenv("KRAKEN_API_SECRET", secret)
    monkeypatch.setenv("KRAKEN_API_BASE_URL", "https://api.kraken.test")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["API-Key"] == "kraken_live_key_12345678"
        if request.url.path == "/private/Balance":
            return httpx.Response(200, json={"error": [], "result": {"ZUSD": "120.50", "XXBT": "0.10", "ETH": "0"}})
        if request.url.path == "/private/TradeBalance":
            return httpx.Response(200, json={"error": [], "result": {"eb": "640.25", "tb": "500.00", "mf": "450.00"}})
        raise AssertionError(f"Unexpected path {request.url.path}")

    adapter = KrakenTradingAdapter(get_settings(), transport=httpx.MockTransport(handler))
    state = adapter.get_account_state()

    assert state.venue == "kraken"
    assert str(state.equity) == "640.25"
    assert str(state.cash) == "120.50"
    assert len(state.positions) == 1
    assert state.positions[0].symbol == "XXBT"


def test_kraken_http_errors_are_logged(monkeypatch, caplog) -> None:
    secret = base64.b64encode(b"kraken-secret-bytes").decode("utf-8")
    monkeypatch.setenv("KRAKEN_API_KEY", "kraken_live_key_12345678")
    monkeypatch.setenv("KRAKEN_API_SECRET", secret)
    monkeypatch.setenv("KRAKEN_API_BASE_URL", "https://api.kraken.test")
    get_settings.cache_clear()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": ["EGeneral:Temporary lockout"]})

    adapter = KrakenTradingAdapter(get_settings(), transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.ERROR):
        try:
            adapter.get_account_state()
        except Exception:
            pass

    assert "kraken_trading request failed with status 500" in caplog.text
