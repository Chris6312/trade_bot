from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.core import RegimeSnapshotRead, RegimeSyncStateRead
from backend.app.services.regime_service import build_regime_current_snapshot, build_regime_sync_snapshot

router = APIRouter(prefix="/regime", tags=["regime"])
VALID_ASSET_CLASSES = {"stock", "crypto"}


@router.get("/{asset_class}/current", response_model=RegimeSnapshotRead)
def get_current_regime(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> RegimeSnapshotRead:
    _validate_asset_class(asset_class)
    snapshot = build_regime_current_snapshot(db, asset_class=asset_class, timeframe=timeframe)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Regime state not found")
    return RegimeSnapshotRead.model_validate(snapshot)


@router.get("/{asset_class}/sync-state", response_model=RegimeSyncStateRead)
def get_current_regime_sync_state(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> RegimeSyncStateRead:
    _validate_asset_class(asset_class)
    snapshot = build_regime_sync_snapshot(db, asset_class=asset_class, timeframe=timeframe)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Regime sync state not found")
    return RegimeSyncStateRead.model_validate(snapshot)


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
