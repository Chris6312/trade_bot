from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.core import (
    CiCryptoRegimeFeatureSnapshot,
    CiCryptoRegimeModelRegistry,
    CiCryptoRegimeRun,
    CiCryptoRegimeState,
    RegimeSnapshot,
)
from backend.app.services.settings_service import resolve_bool_setting, resolve_str_setting

CI_CRYPTO_REGIME_SETTINGS_DEFAULTS: dict[str, Any] = {
    "CI_CRYPTO_REGIME_ENABLED": False,
    "CI_CRYPTO_REGIME_ADVISORY_ONLY": True,
    "CI_CRYPTO_REGIME_MODEL_VERSION": "",
    "CI_CRYPTO_REGIME_MODE": "hybrid_rules_plus_gmm",
    "CI_CRYPTO_REGIME_USE_ORDERBOOK": True,
    "CI_CRYPTO_REGIME_USE_DEFILLAMA": False,
    "CI_CRYPTO_REGIME_USE_HURST": True,
    "CI_CRYPTO_REGIME_RUN_INTERVAL_MINUTES": 15,
    "CI_CRYPTO_REGIME_STALE_AFTER_SECONDS": 1200,
    "CI_CRYPTO_REGIME_MIN_BARS_4H": 120,
    "CI_CRYPTO_REGIME_MIN_BARS_1H": 240,
    "CI_CRYPTO_REGIME_MIN_BOOK_SNAPSHOTS": 20,
    "CI_CRYPTO_REGIME_PROMOTE_TO_RUNTIME": False,
}


@dataclass(slots=True, frozen=True)
class CiCryptoRegimeSettingsSnapshot:
    enabled: bool
    advisory_only: bool
    model_version: str | None


@dataclass(slots=True, frozen=True)
class CoreCryptoRegimeReference:
    state: str | None
    timeframe: str | None


def get_ci_crypto_regime_settings_snapshot(db: Session) -> CiCryptoRegimeSettingsSnapshot:
    configured_model_version = resolve_str_setting(
        db,
        "CI_CRYPTO_REGIME_MODEL_VERSION",
        default=str(CI_CRYPTO_REGIME_SETTINGS_DEFAULTS["CI_CRYPTO_REGIME_MODEL_VERSION"]),
    ).strip()
    return CiCryptoRegimeSettingsSnapshot(
        enabled=resolve_bool_setting(
            db,
            "CI_CRYPTO_REGIME_ENABLED",
            default=bool(CI_CRYPTO_REGIME_SETTINGS_DEFAULTS["CI_CRYPTO_REGIME_ENABLED"]),
        ),
        advisory_only=resolve_bool_setting(
            db,
            "CI_CRYPTO_REGIME_ADVISORY_ONLY",
            default=bool(CI_CRYPTO_REGIME_SETTINGS_DEFAULTS["CI_CRYPTO_REGIME_ADVISORY_ONLY"]),
        ),
        model_version=configured_model_version or None,
    )


def list_ci_crypto_regime_models(db: Session) -> list[CiCryptoRegimeModelRegistry]:
    return (
        db.query(CiCryptoRegimeModelRegistry)
        .order_by(
            CiCryptoRegimeModelRegistry.is_active.desc(),
            CiCryptoRegimeModelRegistry.created_at.desc(),
            CiCryptoRegimeModelRegistry.id.desc(),
        )
        .all()
    )


def get_active_ci_crypto_regime_model(db: Session) -> CiCryptoRegimeModelRegistry | None:
    return (
        db.query(CiCryptoRegimeModelRegistry)
        .filter(CiCryptoRegimeModelRegistry.is_active.is_(True))
        .order_by(CiCryptoRegimeModelRegistry.updated_at.desc(), CiCryptoRegimeModelRegistry.id.desc())
        .first()
    )


def get_ci_crypto_regime_run(db: Session, *, run_id: int) -> CiCryptoRegimeRun | None:
    return db.query(CiCryptoRegimeRun).filter(CiCryptoRegimeRun.id == run_id).one_or_none()


def get_ci_crypto_regime_state_for_run(db: Session, *, run_id: int) -> CiCryptoRegimeState | None:
    return (
        db.query(CiCryptoRegimeState)
        .filter(CiCryptoRegimeState.run_id == run_id)
        .one_or_none()
    )


def list_ci_crypto_regime_feature_snapshots_for_run(db: Session, *, run_id: int) -> list[CiCryptoRegimeFeatureSnapshot]:
    return (
        db.query(CiCryptoRegimeFeatureSnapshot)
        .filter(CiCryptoRegimeFeatureSnapshot.run_id == run_id)
        .order_by(
            CiCryptoRegimeFeatureSnapshot.as_of_at.desc(),
            CiCryptoRegimeFeatureSnapshot.symbol_scope.asc(),
            CiCryptoRegimeFeatureSnapshot.feature_name.asc(),
        )
        .all()
    )


def get_latest_ci_crypto_regime_state(db: Session) -> CiCryptoRegimeState | None:
    return (
        db.query(CiCryptoRegimeState)
        .order_by(CiCryptoRegimeState.as_of_at.desc(), CiCryptoRegimeState.id.desc())
        .first()
    )


def list_ci_crypto_regime_states(
    db: Session,
    *,
    limit: int = 100,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    state: str | None = None,
    agreement_with_core: str | None = None,
) -> list[CiCryptoRegimeState]:
    query = db.query(CiCryptoRegimeState)
    if from_at is not None:
        query = query.filter(CiCryptoRegimeState.as_of_at >= _ensure_utc(from_at))
    if to_at is not None:
        query = query.filter(CiCryptoRegimeState.as_of_at <= _ensure_utc(to_at))
    if state:
        query = query.filter(CiCryptoRegimeState.state == state)
    if agreement_with_core:
        query = query.filter(CiCryptoRegimeState.agreement_with_core == agreement_with_core)
    return (
        query.order_by(CiCryptoRegimeState.as_of_at.desc(), CiCryptoRegimeState.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def get_ci_crypto_regime_run_for_state(db: Session, *, state_row: CiCryptoRegimeState) -> CiCryptoRegimeRun | None:
    return get_ci_crypto_regime_run(db, run_id=state_row.run_id)


def get_core_crypto_regime_reference(db: Session) -> CoreCryptoRegimeReference:
    row = (
        db.query(RegimeSnapshot)
        .filter(RegimeSnapshot.asset_class == "crypto")
        .order_by(
            RegimeSnapshot.regime_timestamp.desc(),
            RegimeSnapshot.computed_at.desc(),
            RegimeSnapshot.id.desc(),
        )
        .first()
    )
    if row is None:
        return CoreCryptoRegimeReference(state=None, timeframe=None)
    return CoreCryptoRegimeReference(state=row.regime, timeframe=row.timeframe)


def build_ci_crypto_regime_current_payload(db: Session) -> dict[str, Any]:
    settings = get_ci_crypto_regime_settings_snapshot(db)
    latest_state = get_latest_ci_crypto_regime_state(db)
    active_model = get_active_ci_crypto_regime_model(db)
    configured_model_version = settings.model_version or (active_model.model_version if active_model else None)
    core_reference = get_core_crypto_regime_reference(db)

    if latest_state is None:
        return {
            "enabled": settings.enabled,
            "advisory_only": settings.advisory_only,
            "as_of_at": None,
            "state": "unavailable",
            "confidence": Decimal("0"),
            "core_regime_state": core_reference.state,
            "agreement_with_core": "core_unavailable" if core_reference.state is None else None,
            "advisory_action": None,
            "model_version": configured_model_version,
            "feature_set_version": active_model.feature_set_version if active_model else None,
            "degraded": False,
            "reason_codes": ["no_ci_state"],
            "summary": None,
            "core_regime_timeframe": core_reference.timeframe,
            "last_run_status": None,
        }

    run = get_ci_crypto_regime_run_for_state(db, state_row=latest_state)
    model_row = None
    if run is not None and run.model_version:
        model_row = (
            db.query(CiCryptoRegimeModelRegistry)
            .filter(CiCryptoRegimeModelRegistry.model_version == run.model_version)
            .one_or_none()
        )

    return {
        "enabled": settings.enabled,
        "advisory_only": settings.advisory_only,
        "as_of_at": latest_state.as_of_at,
        "state": latest_state.state,
        "confidence": latest_state.confidence,
        "core_regime_state": latest_state.core_regime_state or core_reference.state,
        "agreement_with_core": latest_state.agreement_with_core,
        "advisory_action": latest_state.advisory_action,
        "model_version": run.model_version if run is not None else configured_model_version,
        "feature_set_version": run.feature_set_version if run is not None else (model_row.feature_set_version if model_row else None),
        "degraded": latest_state.degraded,
        "reason_codes": list(latest_state.reason_codes_json or []),
        "summary": latest_state.summary_json,
        "core_regime_timeframe": core_reference.timeframe,
        "last_run_status": run.status if run is not None else None,
    }


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
