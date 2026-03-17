from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.core import (
    CiCryptoRegimeCurrentRead,
    CiCryptoRegimeModelsResponse,
    CiCryptoRegimeRunDetailRead,
    CiCryptoRegimeFeatureSnapshotRead,
    CiCryptoRegimeModelRegistryRead,
    CiCryptoRegimeRunRead,
    CiCryptoRegimeStateRead,
)
from backend.app.services.ci_crypto_regime_service import (
    build_ci_crypto_regime_current_payload,
    get_active_ci_crypto_regime_model,
    get_ci_crypto_regime_run,
    get_ci_crypto_regime_state_for_run,
    list_ci_crypto_regime_feature_snapshots_for_run,
    list_ci_crypto_regime_models,
    list_ci_crypto_regime_states,
)

router = APIRouter(prefix="/ci/crypto-regime", tags=["ci-crypto-regime"])


@router.get("/current", response_model=CiCryptoRegimeCurrentRead)
def get_current_ci_crypto_regime(db: Session = Depends(get_db)) -> CiCryptoRegimeCurrentRead:
    payload = build_ci_crypto_regime_current_payload(db)
    return CiCryptoRegimeCurrentRead(**payload)


@router.get("/history", response_model=list[CiCryptoRegimeStateRead])
def get_ci_crypto_regime_history(
    limit: int = Query(default=100, ge=1, le=500),
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    state: str | None = Query(default=None),
    agreement_with_core: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CiCryptoRegimeStateRead]:
    rows = list_ci_crypto_regime_states(
        db,
        limit=limit,
        from_at=from_at,
        to_at=to_at,
        state=state,
        agreement_with_core=agreement_with_core,
    )
    return [CiCryptoRegimeStateRead.model_validate(row) for row in rows]


@router.get("/runs/{run_id}", response_model=CiCryptoRegimeRunDetailRead)
def get_ci_crypto_regime_run_detail(run_id: int, db: Session = Depends(get_db)) -> CiCryptoRegimeRunDetailRead:
    run = get_ci_crypto_regime_run(db, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="CI crypto regime run not found")

    state = get_ci_crypto_regime_state_for_run(db, run_id=run_id)
    features = list_ci_crypto_regime_feature_snapshots_for_run(db, run_id=run_id)

    return CiCryptoRegimeRunDetailRead(
        run=CiCryptoRegimeRunRead.model_validate(run),
        state=CiCryptoRegimeStateRead.model_validate(state) if state is not None else None,
        features=[CiCryptoRegimeFeatureSnapshotRead.model_validate(row) for row in features],
    )


@router.get("/models", response_model=CiCryptoRegimeModelsResponse)
def get_ci_crypto_regime_models(db: Session = Depends(get_db)) -> CiCryptoRegimeModelsResponse:
    rows = list_ci_crypto_regime_models(db)
    active_model = get_active_ci_crypto_regime_model(db)
    return CiCryptoRegimeModelsResponse(
        active_model=CiCryptoRegimeModelRegistryRead.model_validate(active_model) if active_model is not None else None,
        models=[CiCryptoRegimeModelRegistryRead.model_validate(row) for row in rows],
    )
