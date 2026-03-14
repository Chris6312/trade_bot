from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models.core import CandleFreshness, CandleSyncState, FeatureSyncState
from backend.app.schemas.core import CandleFreshnessRead, CandleSyncStateRead, FeatureSyncStateRead

router = APIRouter(prefix="/data", tags=["data"])
VALID_ASSET_CLASSES = {"stock", "crypto"}


@router.get("/candles/{asset_class}/sync-state", response_model=list[CandleSyncStateRead])
def list_candle_sync_states(
    asset_class: str,
    timeframe: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CandleSyncStateRead]:
    _validate_asset_class(asset_class)
    query = db.query(CandleSyncState).filter(CandleSyncState.asset_class == asset_class)
    if timeframe:
        query = query.filter(CandleSyncState.timeframe == timeframe)
    rows = query.order_by(CandleSyncState.timeframe.asc(), CandleSyncState.symbol.asc()).all()
    return [CandleSyncStateRead.model_validate(row) for row in rows]


@router.get("/candles/{asset_class}/freshness", response_model=list[CandleFreshnessRead])
def list_candle_freshness(
    asset_class: str,
    timeframe: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CandleFreshnessRead]:
    _validate_asset_class(asset_class)
    query = db.query(CandleFreshness).filter(CandleFreshness.asset_class == asset_class)
    if timeframe:
        query = query.filter(CandleFreshness.timeframe == timeframe)
    rows = query.order_by(CandleFreshness.timeframe.asc(), CandleFreshness.symbol.asc()).all()
    return [CandleFreshnessRead.model_validate(row) for row in rows]


@router.get("/features/{asset_class}/sync-state", response_model=list[FeatureSyncStateRead])
def list_feature_sync_states(
    asset_class: str,
    timeframe: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[FeatureSyncStateRead]:
    _validate_asset_class(asset_class)
    query = db.query(FeatureSyncState).filter(FeatureSyncState.asset_class == asset_class)
    if timeframe:
        query = query.filter(FeatureSyncState.timeframe == timeframe)
    rows = query.order_by(FeatureSyncState.timeframe.asc(), FeatureSyncState.symbol.asc()).all()
    return [FeatureSyncStateRead.model_validate(row) for row in rows]


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
