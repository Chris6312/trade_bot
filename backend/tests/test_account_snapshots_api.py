def test_account_snapshot_can_be_recorded_and_read(client) -> None:
    create_response = client.post(
        "/api/v1/account-snapshots",
        json={
            "account_scope": "total",
            "venue": "paper",
            "mode": "mixed",
            "equity": "500.00",
            "cash": "420.00",
            "buying_power": "420.00",
            "realized_pnl": "5.00",
            "unrealized_pnl": "1.25",
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["account_scope"] == "total"

    latest_response = client.get("/api/v1/account-snapshots/latest/total")
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["equity"] == "500.0000"


from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.app.common.adapters.models import AccountState
from backend.app.core.config import Settings


class _RecordingAdapter:
    def __init__(self, account_state: AccountState) -> None:
        self.account_state = account_state
        self.closed = False

    def get_account_state(self) -> AccountState:
        return self.account_state

    def close(self) -> None:
        self.closed = True


class _FakeRegistry:
    def __init__(self, settings) -> None:
        self.settings = settings

    def alpaca_stock_paper(self):
        return _RecordingAdapter(
            AccountState(
                venue="alpaca",
                asset_class="stock",
                mode="paper",
                account_id="paper-stock",
                currency="USD",
                equity=Decimal("125.50"),
                cash=Decimal("120.25"),
                buying_power=Decimal("120.25"),
            )
        )

    def alpaca_crypto_paper(self):
        return _RecordingAdapter(
            AccountState(
                venue="alpaca",
                asset_class="crypto",
                mode="paper",
                account_id="paper-crypto",
                currency="USD",
                equity=Decimal("88.75"),
                cash=Decimal("80.10"),
                buying_power=Decimal("80.10"),
            )
        )


def test_account_snapshot_latest_returns_null_when_no_snapshot_or_broker_fallback(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.api.routes import account_snapshots as route_module

    class _EmptyRegistry:
        def __init__(self, settings) -> None:
            self.settings = settings

        def alpaca_stock_paper(self):
            raise RuntimeError("not configured")

    monkeypatch.setattr(route_module, "AdapterRegistry", _EmptyRegistry)
    monkeypatch.setattr(route_module, "get_settings", lambda: Settings(default_mode="paper", stock_execution_mode="paper"))

    response = client.get("/api/v1/account-snapshots/latest/stock")
    assert response.status_code == 200
    assert response.json() is None


def test_account_snapshot_latest_uses_live_paper_broker_data_when_db_row_is_missing(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.api.routes import account_snapshots as route_module

    monkeypatch.setattr(route_module, "AdapterRegistry", _FakeRegistry)
    monkeypatch.setattr(
        route_module,
        "get_settings",
        lambda: Settings(default_mode="paper", stock_execution_mode="paper", crypto_execution_mode="paper"),
    )

    stock_response = client.get("/api/v1/account-snapshots/latest/stock")
    assert stock_response.status_code == 200
    stock_payload = stock_response.json()
    assert stock_payload["venue"] == "alpaca"
    assert stock_payload["mode"] == "paper"
    assert stock_payload["equity"] == "125.50"

    total_response = client.get("/api/v1/account-snapshots/latest/total")
    assert total_response.status_code == 200
    total_payload = total_response.json()
    assert total_payload["venue"] == "aggregate"
    assert total_payload["mode"] == "paper"
    assert total_payload["equity"] == "214.25"
    assert total_payload["cash"] == "200.35"
