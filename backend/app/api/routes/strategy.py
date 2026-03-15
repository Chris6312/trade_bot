from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.core import StrategySnapshotRead, StrategySyncStateRead
from backend.app.services.strategy_service import (
    VALID_ASSET_CLASSES,
    get_strategy_sync_state,
    list_current_strategy_snapshots,
)

router = APIRouter(prefix="/strategy", tags=["strategy"])


@router.get("/{asset_class}/current", response_model=list[StrategySnapshotRead])
def get_current_strategy_rows(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> list[StrategySnapshotRead]:
    _validate_asset_class(asset_class)
    rows = list_current_strategy_snapshots(db, asset_class=asset_class, timeframe=timeframe)
    if not rows:
        return []
    return [StrategySnapshotRead.model_validate(row) for row in rows]


@router.get("/{asset_class}/sync-state", response_model=StrategySyncStateRead)
def get_current_strategy_sync_state(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> StrategySyncStateRead:
    _validate_asset_class(asset_class)
    record = get_strategy_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        raise HTTPException(status_code=404, detail="Strategy sync state not found")
    return StrategySyncStateRead.model_validate(record)



def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
