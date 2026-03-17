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


def test_runtime_snapshot_includes_ci_crypto_regime_status(client) -> None:
    client.put(
        "/api/v1/settings/CI_CRYPTO_REGIME_ENABLED",
        json={
            "value": "true",
            "value_type": "bool",
            "description": "Enable CI advisory",
            "is_secret": False,
        },
    )
    client.put(
        "/api/v1/settings/CI_CRYPTO_REGIME_MODEL_VERSION",
        json={
            "value": "ci_rules_v1",
            "value_type": "string",
            "description": "CI model version",
            "is_secret": False,
        },
    )

    snapshot_response = client.get("/api/v1/settings/runtime/snapshot")
    assert snapshot_response.status_code == 200
    payload = snapshot_response.json()
    assert payload["ci_crypto_regime"]["enabled"] is True
    assert payload["ci_crypto_regime"]["model_version"] == "ci_rules_v1"
    assert payload["ci_crypto_regime"]["use_orderbook"] is True
    assert payload["ci_crypto_regime"]["use_defillama"] is False
    assert payload["ci_crypto_regime"]["use_hurst"] is True
    assert payload["ci_crypto_regime"]["degraded_reasons"] == []
