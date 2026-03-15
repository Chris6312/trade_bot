from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.core import (
    OpenOrderStateRead,
    PositionStateRead,
    PositionSyncStateRead,
    ReconciliationMismatchRead,
)
from backend.app.services.position_service import (
    get_position_sync_state,
    list_active_reconciliation_mismatches,
    list_current_open_orders,
    list_current_position_states,
)
from backend.app.services.strategy_service import VALID_ASSET_CLASSES

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("/{asset_class}/current", response_model=list[PositionStateRead])
def get_current_positions(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> list[PositionStateRead]:
    _validate_asset_class(asset_class)
    rows = list_current_position_states(db, asset_class=asset_class, timeframe=timeframe)
    if not rows:
        return []
    return [PositionStateRead.model_validate(row) for row in rows]


@router.get("/{asset_class}/open-orders", response_model=list[OpenOrderStateRead])
def get_current_open_orders(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> list[OpenOrderStateRead]:
    _validate_asset_class(asset_class)
    rows = list_current_open_orders(db, asset_class=asset_class, timeframe=timeframe)
    if not rows:
        raise HTTPException(status_code=404, detail="Open order state not found")
    return [OpenOrderStateRead.model_validate(row) for row in rows]


@router.get("/{asset_class}/mismatches", response_model=list[ReconciliationMismatchRead])
def get_active_reconciliation_mismatches(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> list[ReconciliationMismatchRead]:
    _validate_asset_class(asset_class)
    rows = list_active_reconciliation_mismatches(db, asset_class=asset_class, timeframe=timeframe)
    if not rows:
        raise HTTPException(status_code=404, detail="Reconciliation mismatches not found")
    return [ReconciliationMismatchRead.model_validate(row) for row in rows]


@router.get("/{asset_class}/sync-state", response_model=PositionSyncStateRead)
def get_current_position_sync_state(
    asset_class: str,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> PositionSyncStateRead:
    _validate_asset_class(asset_class)
    record = get_position_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        raise HTTPException(status_code=404, detail="Position sync state not found")
    return PositionSyncStateRead.model_validate(record)


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=422, detail=f"Invalid asset class: {asset_class}")
