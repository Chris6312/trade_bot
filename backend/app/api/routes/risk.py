from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.core import RiskSnapshotRead, RiskSyncStateRead
from backend.app.services.risk_service import VALID_ASSET_CLASSES, get_risk_sync_state, list_current_risk_snapshots

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/{asset_class}/current", response_model=list[RiskSnapshotRead])
def get_current_risk_rows(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> list[RiskSnapshotRead]:
    _validate_asset_class(asset_class)
    rows = list_current_risk_snapshots(db, asset_class=asset_class, timeframe=timeframe)
    if not rows:
        return []
    return [RiskSnapshotRead.model_validate(row) for row in rows]


@router.get("/{asset_class}/sync-state", response_model=RiskSyncStateRead)
def get_current_risk_sync_state(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> RiskSyncStateRead:
    _validate_asset_class(asset_class)
    record = get_risk_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        raise HTTPException(status_code=404, detail="Risk sync state not found")
    return RiskSyncStateRead.model_validate(record)


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
