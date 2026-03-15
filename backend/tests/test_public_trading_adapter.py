import httpx

from backend.app.core.config import get_settings
from backend.app.stocks.brokers.public_trading import PublicTradingAdapter


def test_public_account_state_uses_portfolio_v2(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_API_SECRET", "public-secret")
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://api.public.test")
    monkeypatch.setenv("PUBLIC_ACCOUNT_ID", "pub-acct-1")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/userapiauthservice/personal/access-tokens":
            return httpx.Response(200, json={"accessToken": "token-123"})
        if request.url.path == "/userapigateway/trading/account":
            return httpx.Response(200, json={"accounts": [{"accountId": "pub-acct-1", "accountType": "BROKERAGE"}]})
        if request.url.path == "/userapigateway/trading/pub-acct-1/portfolio/v2":
            return httpx.Response(
                200,
                json={
                    "accountId": "pub-acct-1",
                    "buyingPower": {"availableToTrade": "221.55", "amount": "221.55"},
                    "equity": [
                        {"label": "total", "amount": "498.80"},
                        {"label": "cash", "amount": "221.55"},
                    ],
                    "positions": [
                        {
                            "instrument": {"symbol": "NVDA", "type": "EQUITY"},
                            "quantity": "1.25",
                            "marketValue": {"amount": "277.25"},
                            "costBasis": {"amount": "250.00"},
                            "averagePrice": {"amount": "200.00"},
                        }
                    ],
                    "orders": [],
                },
            )
        raise AssertionError(f"Unexpected path {request.url.path}")

    adapter = PublicTradingAdapter(get_settings(), transport=httpx.MockTransport(handler))
    state = adapter.get_account_state()

    assert state.venue == "public"
    assert state.account_id == "pub-acct-1"
    assert str(state.equity) == "498.80"
    assert str(state.cash) == "221.55"
    assert state.positions[0].symbol == "NVDA"


def test_public_adapter_reuses_cached_access_token_within_ttl(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_API_SECRET", "public-secret")
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://api.public.test")
    monkeypatch.setenv("PUBLIC_ACCOUNT_ID", "pub-acct-1")
    get_settings.cache_clear()

    auth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if request.url.path == "/userapiauthservice/personal/access-tokens":
            auth_calls += 1
            return httpx.Response(200, json={"accessToken": "token-123"})
        if request.url.path == "/userapigateway/trading/pub-acct-1/portfolio/v2":
            return httpx.Response(
                200,
                json={
                    "accountId": "pub-acct-1",
                    "buyingPower": {"availableToTrade": "100.00", "amount": "100.00"},
                    "equity": [
                        {"label": "total", "amount": "500.00"},
                        {"label": "cash", "amount": "100.00"},
                    ],
                    "positions": [],
                    "orders": [],
                },
            )
        if request.url.path == "/userapigateway/trading/pub-acct-1/order":
            return httpx.Response(200, json={"orderId": "ord-1", "status": "submitted"})
        raise AssertionError(f"Unexpected path {request.url.path}")

    adapter = PublicTradingAdapter(get_settings(), transport=httpx.MockTransport(handler))
    adapter.get_account_state()
    adapter.list_open_orders()

    assert auth_calls == 1
