from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backend.app.db.session import get_session_factory
from backend.app.models.core import (
    CiCryptoRegimeFeatureSnapshot,
    CiCryptoRegimeModelRegistry,
    CiCryptoRegimeRun,
    CiCryptoRegimeState,
    RegimeSnapshot,
    Setting,
)


def test_ci_crypto_regime_current_endpoint_uses_latest_state_and_settings(client) -> None:
    with _db() as db:
        now = datetime(2026, 3, 16, 16, 45, 30, tzinfo=UTC)
        db.add_all(
            [
                Setting(key="CI_CRYPTO_REGIME_ENABLED", value="true", value_type="bool"),
                Setting(key="CI_CRYPTO_REGIME_ADVISORY_ONLY", value="true", value_type="bool"),
                Setting(key="CI_CRYPTO_REGIME_MODEL_VERSION", value="ci_gmm_v1", value_type="string"),
                CiCryptoRegimeModelRegistry(
                    model_version="ci_gmm_v1",
                    feature_set_version="ci_crypto_regime_feature_set_v1",
                    scaler_version="scaler_v1",
                    model_type="hybrid_rules_plus_gmm",
                    label_map_json={"0": "bull", "1": "neutral", "2": "risk_off"},
                    training_window_start_at=now - timedelta(days=30),
                    training_window_end_at=now - timedelta(hours=1),
                    training_notes="locked contract v1",
                    is_active=True,
                    created_by="chatgpt",
                ),
                RegimeSnapshot(
                    asset_class="crypto",
                    venue="kraken",
                    source="regime_engine",
                    timeframe="4h",
                    regime_timestamp=now - timedelta(minutes=15),
                    computed_at=now - timedelta(minutes=14),
                    regime="bull",
                    entry_policy="full",
                    symbol_count=15,
                    bull_score=Decimal("0.81"),
                    breadth_ratio=Decimal("0.70"),
                    benchmark_support_ratio=Decimal("1.0"),
                    participation_ratio=Decimal("0.72"),
                    volatility_support_ratio=Decimal("0.64"),
                    payload={"source": "core"},
                ),
            ]
        )
        run = CiCryptoRegimeRun(
            run_started_at=now - timedelta(seconds=12),
            run_completed_at=now - timedelta(seconds=4),
            status="success",
            model_version="ci_gmm_v1",
            feature_set_version="ci_crypto_regime_feature_set_v1",
            used_orderbook=True,
            used_defillama=False,
            used_hurst=True,
            data_window_end_at=now - timedelta(minutes=1),
            degraded=False,
        )
        db.add(run)
        db.flush()
        db.add(
            CiCryptoRegimeState(
                run_id=run.id,
                as_of_at=now,
                state="neutral",
                confidence=Decimal("0.74215"),
                cluster_id=1,
                cluster_prob_bull=Decimal("0.18000"),
                cluster_prob_neutral=Decimal("0.74215"),
                cluster_prob_risk_off=Decimal("0.07785"),
                agreement_with_core="disagree",
                advisory_action="tighten",
                core_regime_state="bull",
                degraded=False,
                reason_codes_json=["btc_trend_mixed", "orderbook_bid_support_weak"],
                summary_json={"notes": "advisory only"},
            )
        )
        db.commit()

    response = client.get("/api/v1/ci/crypto-regime/current")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["advisory_only"] is True
    assert payload["state"] == "neutral"
    assert payload["core_regime_state"] == "bull"
    assert payload["agreement_with_core"] == "disagree"
    assert payload["advisory_action"] == "tighten"
    assert payload["model_version"] == "ci_gmm_v1"
    assert payload["feature_set_version"] == "ci_crypto_regime_feature_set_v1"
    assert payload["reason_codes"] == ["btc_trend_mixed", "orderbook_bid_support_weak"]
    assert payload["core_regime_timeframe"] == "4h"
    assert payload["last_run_status"] == "success"


def test_ci_crypto_regime_history_models_and_run_detail_endpoints(client) -> None:
    with _db() as db:
        base_time = datetime(2026, 3, 16, 17, 0, tzinfo=UTC)
        active_model = CiCryptoRegimeModelRegistry(
            model_version="ci_rules_v1",
            feature_set_version="ci_crypto_regime_feature_set_v1",
            scaler_version=None,
            model_type="rules_only",
            label_map_json={"rules": "fixed"},
            training_window_start_at=base_time - timedelta(days=10),
            training_window_end_at=base_time - timedelta(hours=2),
            training_notes="advisory baseline",
            is_active=True,
            created_by="chatgpt",
        )
        inactive_model = CiCryptoRegimeModelRegistry(
            model_version="ci_gmm_v0",
            feature_set_version="ci_crypto_regime_feature_set_v0",
            scaler_version="scaler_v0",
            model_type="gmm_only",
            label_map_json={"0": "bull"},
            training_window_start_at=base_time - timedelta(days=20),
            training_window_end_at=base_time - timedelta(days=11),
            training_notes="old model",
            is_active=False,
            created_by="chatgpt",
        )
        db.add_all([active_model, inactive_model])
        db.flush()

        older_run = CiCryptoRegimeRun(
            run_started_at=base_time - timedelta(hours=1),
            run_completed_at=base_time - timedelta(hours=1, minutes=-1),
            status="partial",
            skip_reason=None,
            model_version="ci_rules_v1",
            feature_set_version="ci_crypto_regime_feature_set_v1",
            used_orderbook=False,
            used_defillama=False,
            used_hurst=True,
            data_window_end_at=base_time - timedelta(hours=1),
            error_message=None,
            degraded=True,
        )
        newer_run = CiCryptoRegimeRun(
            run_started_at=base_time - timedelta(minutes=10),
            run_completed_at=base_time - timedelta(minutes=9),
            status="success",
            model_version="ci_rules_v1",
            feature_set_version="ci_crypto_regime_feature_set_v1",
            used_orderbook=True,
            used_defillama=False,
            used_hurst=True,
            data_window_end_at=base_time - timedelta(minutes=10),
            degraded=False,
        )
        db.add_all([older_run, newer_run])
        db.flush()

        db.add_all(
            [
                CiCryptoRegimeState(
                    run_id=older_run.id,
                    as_of_at=base_time - timedelta(hours=1),
                    state="risk_off",
                    confidence=Decimal("0.65000"),
                    cluster_id=None,
                    cluster_prob_bull=None,
                    cluster_prob_neutral=None,
                    cluster_prob_risk_off=None,
                    agreement_with_core="agree",
                    advisory_action="block",
                    core_regime_state="risk_off",
                    degraded=True,
                    reason_codes_json=["stale_internal_data"],
                    summary_json={"status": "degraded"},
                ),
                CiCryptoRegimeState(
                    run_id=newer_run.id,
                    as_of_at=base_time - timedelta(minutes=5),
                    state="bull",
                    confidence=Decimal("0.81234"),
                    cluster_id=0,
                    cluster_prob_bull=Decimal("0.81234"),
                    cluster_prob_neutral=Decimal("0.12000"),
                    cluster_prob_risk_off=Decimal("0.06766"),
                    agreement_with_core="disagree",
                    advisory_action="allow",
                    core_regime_state="neutral",
                    degraded=False,
                    reason_codes_json=["bid_support_strong"],
                    summary_json={"status": "healthy"},
                ),
                CiCryptoRegimeFeatureSnapshot(
                    run_id=newer_run.id,
                    symbol_scope="BTC/USD",
                    timeframe="4h",
                    feature_name="btc_hurst_4h",
                    feature_value=Decimal("0.61234"),
                    feature_status="ok",
                    source="derived",
                    as_of_at=base_time - timedelta(minutes=5),
                ),
                CiCryptoRegimeFeatureSnapshot(
                    run_id=newer_run.id,
                    symbol_scope="market",
                    timeframe=None,
                    feature_name="microstructure_support_score",
                    feature_value=Decimal("0.42000"),
                    feature_status="ok",
                    source="kraken",
                    as_of_at=base_time - timedelta(minutes=5),
                ),
            ]
        )
        db.commit()
        newer_run_id = newer_run.id

    history = client.get("/api/v1/ci/crypto-regime/history", params={"agreement_with_core": "disagree", "limit": 10})
    assert history.status_code == 200
    history_payload = history.json()
    assert len(history_payload) == 1
    assert history_payload[0]["state"] == "bull"
    assert history_payload[0]["agreement_with_core"] == "disagree"

    models = client.get("/api/v1/ci/crypto-regime/models")
    assert models.status_code == 200
    models_payload = models.json()
    assert models_payload["active_model"]["model_version"] == "ci_rules_v1"
    assert [row["model_version"] for row in models_payload["models"]] == ["ci_rules_v1", "ci_gmm_v0"]

    detail = client.get(f"/api/v1/ci/crypto-regime/runs/{newer_run_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["run"]["status"] == "success"
    assert detail_payload["state"]["state"] == "bull"
    feature_names = {row["feature_name"] for row in detail_payload["features"]}
    assert feature_names == {"btc_hurst_4h", "microstructure_support_score"}


def _db():
    return get_session_factory()()
