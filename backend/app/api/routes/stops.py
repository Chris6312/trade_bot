from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.core import StopStateRead, StopSyncStateRead, StopUpdateHistoryRead
from backend.app.services.stop_service import (
    get_stop_sync_state,
    list_current_stop_states,
    list_recent_stop_updates,
)
from backend.app.services.strategy_service import VALID_ASSET_CLASSES

router = APIRouter(prefix="/stops", tags=["stops"])


@router.get("/{asset_class}/current", response_model=list[StopStateRead])
def get_current_stop_states(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> list[StopStateRead]:
    _validate_asset_class(asset_class)
    rows = list_current_stop_states(db, asset_class=asset_class, timeframe=timeframe)
    if not rows:
        raise HTTPException(status_code=404, detail="Stop state not found")
    return [StopStateRead.model_validate(row) for row in rows]


@router.get("/{asset_class}/updates", response_model=list[StopUpdateHistoryRead])
def get_recent_stop_updates(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> list[StopUpdateHistoryRead]:
    _validate_asset_class(asset_class)
    rows = list_recent_stop_updates(db, asset_class=asset_class, timeframe=timeframe)
    if not rows:
        raise HTTPException(status_code=404, detail="Stop updates not found")
    return [StopUpdateHistoryRead.model_validate(row) for row in rows]


@router.get("/{asset_class}/sync-state", response_model=StopSyncStateRead)
def get_current_stop_sync_state(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> StopSyncStateRead:
    _validate_asset_class(asset_class)
    record = get_stop_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        raise HTTPException(status_code=404, detail="Stop sync state not found")
    return StopSyncStateRead.model_validate(record)


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
