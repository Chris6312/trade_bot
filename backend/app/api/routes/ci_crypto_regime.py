from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.ci_crypto_regime import (
    CiCryptoRegimeCurrentRead,
    CiCryptoRegimeFeatureSnapshotRead,
    CiCryptoRegimeOrderbookSnapshotRead,
    CiCryptoRegimeHistoryRead,
    CiCryptoRegimeModelListRead,
    CiCryptoRegimeModelRegistryRead,
    CiCryptoRegimeRunDetailRead,
    CiCryptoRegimeRunRead,
    CiCryptoRegimeStateRead,
    CiRegimeDisagreementRead,
    CiRegimeScorecardRead,
    CiRegimeScorecardWindowRead,
)
from backend.app.services.ci_crypto_regime_service import (
    build_ci_crypto_regime_current_snapshot,
    build_ci_crypto_regime_run_detail,
    build_ci_regime_scorecard,
    ensure_default_ci_model_registry,
    list_ci_crypto_regime_history,
    list_ci_crypto_regime_models,
)

router = APIRouter(prefix="/ci/crypto-regime", tags=["ci-crypto-regime"])


@router.get("/current", response_model=CiCryptoRegimeCurrentRead)
def get_current_ci_crypto_regime(
    db: Session = Depends(get_db),
) -> CiCryptoRegimeCurrentRead:
    snapshot = build_ci_crypto_regime_current_snapshot(db)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="CI crypto regime advisory state not found")
    return CiCryptoRegimeCurrentRead.model_validate(snapshot)


@router.get("/history", response_model=CiCryptoRegimeHistoryRead)
def get_ci_crypto_regime_history(
    limit: int = Query(default=100, ge=1, le=500),
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    state: str | None = Query(default=None),
    agreement_with_core: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CiCryptoRegimeHistoryRead:
    rows = list_ci_crypto_regime_history(
        db,
        limit=limit,
        from_at=from_at,
        to_at=to_at,
        state=state,
        agreement_with_core=agreement_with_core,
    )
    return CiCryptoRegimeHistoryRead(items=[CiCryptoRegimeStateRead.model_validate(row) for row in rows])




@router.get("/scorecard", response_model=CiRegimeScorecardRead)
def get_ci_crypto_regime_scorecard(
    window: str = Query(default="30d", pattern="^(7d|30d|90d)$"),
    db: Session = Depends(get_db),
) -> CiRegimeScorecardRead:
    payload = build_ci_regime_scorecard(db, requested_window=window)
    return CiRegimeScorecardRead(
        requested_window=payload["requested_window"],
        windows=[CiRegimeScorecardWindowRead.model_validate(item) for item in payload["windows"]],
        recent=[CiRegimeDisagreementRead.model_validate(item) for item in payload["recent"]],
    )

@router.get("/runs/{run_id}", response_model=CiCryptoRegimeRunDetailRead)
def get_ci_crypto_regime_run(
    run_id: int,
    db: Session = Depends(get_db),
) -> CiCryptoRegimeRunDetailRead:
    detail = build_ci_crypto_regime_run_detail(db, run_id=run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="CI crypto regime run not found")
    return CiCryptoRegimeRunDetailRead(
        run=CiCryptoRegimeRunRead.model_validate(detail["run"]),
        state=CiCryptoRegimeStateRead.model_validate(detail["state"]) if detail["state"] is not None else None,
        features=[CiCryptoRegimeFeatureSnapshotRead.model_validate(item) for item in detail["features"]],
        orderbook_snapshots=[CiCryptoRegimeOrderbookSnapshotRead.model_validate(item) for item in detail["orderbook_snapshots"]],
    )


@router.get("/models", response_model=CiCryptoRegimeModelListRead)
def get_ci_crypto_regime_models(
    db: Session = Depends(get_db),
) -> CiCryptoRegimeModelListRead:
    ensure_default_ci_model_registry(db, commit=True)
    rows = list_ci_crypto_regime_models(db)
    active = next((row.model_version for row in rows if row.is_active), None)
    return CiCryptoRegimeModelListRead(
        active_model_version=active,
        items=[CiCryptoRegimeModelRegistryRead.model_validate(row) for row in rows],
    )
