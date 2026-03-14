def test_root_endpoint(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["health"] == "/health"
    assert "backend is running" in payload["message"]


def test_health_endpoint(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["backend_port"] == 8101


def test_versioned_health_endpoint(client) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["api_prefix"] == "/api/v1"
