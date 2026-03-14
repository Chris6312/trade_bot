from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.core import RegimeSnapshotRead, RegimeSyncStateRead
from backend.app.services.regime_service import get_latest_regime_snapshot, get_regime_sync_state

router = APIRouter(prefix="/regime", tags=["regime"])
VALID_ASSET_CLASSES = {"stock", "crypto"}


@router.get("/{asset_class}/current", response_model=RegimeSnapshotRead)
def get_current_regime(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> RegimeSnapshotRead:
    _validate_asset_class(asset_class)
    record = get_latest_regime_snapshot(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        raise HTTPException(status_code=404, detail="Regime state not found")
    return RegimeSnapshotRead.model_validate(record)


@router.get("/{asset_class}/sync-state", response_model=RegimeSyncStateRead)
def get_current_regime_sync_state(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> RegimeSyncStateRead:
    _validate_asset_class(asset_class)
    record = get_regime_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        raise HTTPException(status_code=404, detail="Regime sync state not found")
    return RegimeSyncStateRead.model_validate(record)


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
