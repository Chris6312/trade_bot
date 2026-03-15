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



def test_account_snapshot_latest_returns_null_when_missing(client) -> None:
    latest_response = client.get("/api/v1/account-snapshots/latest/crypto")
    assert latest_response.status_code == 200
    assert latest_response.json() is None
