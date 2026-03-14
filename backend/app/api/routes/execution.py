
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.core import ExecutionFillRead, ExecutionOrderRead, ExecutionSyncStateRead
from backend.app.services.execution_service import (
    get_execution_sync_state,
    list_current_execution_orders,
    list_recent_execution_fills,
)
from backend.app.services.strategy_service import VALID_ASSET_CLASSES

router = APIRouter(prefix="/execution", tags=["execution"])


@router.get("/{asset_class}/current", response_model=list[ExecutionOrderRead])
def get_current_execution_rows(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> list[ExecutionOrderRead]:
    _validate_asset_class(asset_class)
    rows = list_current_execution_orders(db, asset_class=asset_class, timeframe=timeframe)
    if not rows:
        raise HTTPException(status_code=404, detail="Execution state not found")
    return [ExecutionOrderRead.model_validate(row) for row in rows]


@router.get("/{asset_class}/fills", response_model=list[ExecutionFillRead])
def get_recent_execution_fills(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> list[ExecutionFillRead]:
    _validate_asset_class(asset_class)
    rows = list_recent_execution_fills(db, asset_class=asset_class, timeframe=timeframe)
    if not rows:
        raise HTTPException(status_code=404, detail="Execution fills not found")
    return [ExecutionFillRead.model_validate(row) for row in rows]


@router.get("/{asset_class}/sync-state", response_model=ExecutionSyncStateRead)
def get_current_execution_sync_state(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> ExecutionSyncStateRead:
    _validate_asset_class(asset_class)
    record = get_execution_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        raise HTTPException(status_code=404, detail="Execution sync state not found")
    return ExecutionSyncStateRead.model_validate(record)


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
