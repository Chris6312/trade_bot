def test_system_event_can_be_created(client) -> None:
    response = client.post(
        "/api/v1/system-events",
        json={
            "event_type": "startup",
            "severity": "info",
            "message": "Backend initialized",
            "event_source": "backend",
            "payload": {"phase": 2},
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["event_type"] == "startup"
    assert payload["payload"]["phase"] == 2
