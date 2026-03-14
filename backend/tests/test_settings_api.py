def test_settings_can_be_created_and_read(client) -> None:
    put_response = client.put(
        "/api/v1/settings/default_mode",
        json={
            "value": "mixed",
            "value_type": "string",
            "description": "Execution mode",
            "is_secret": False,
        },
    )
    assert put_response.status_code == 200
    put_payload = put_response.json()
    assert put_payload["key"] == "default_mode"
    assert put_payload["value"] == "mixed"

    get_response = client.get("/api/v1/settings/default_mode")
    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["description"] == "Execution mode"


def test_runtime_snapshot_reads_environment_and_db_safely(client) -> None:
    override_response = client.put(
        "/api/v1/settings/backend_port",
        json={
            "value": "9201",
            "value_type": "integer",
            "description": "DB override",
            "is_secret": False,
        },
    )
    assert override_response.status_code == 200

    snapshot_response = client.get("/api/v1/settings/runtime/snapshot")
    assert snapshot_response.status_code == 200
    payload = snapshot_response.json()
    assert payload["app_name"] == "Small Account Multi-Asset Trading Bot"
    assert payload["backend_port"] == 9201
    assert payload["setting_sources"]["backend_port"] == "database"
    assert payload["setting_sources"]["app_name"] == "environment"
    assert payload["database_url_masked"].endswith("phase2_test.db")
