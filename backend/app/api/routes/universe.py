from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models.core import UniverseRun
from backend.app.schemas.core import UniverseConstituentRead, UniverseRunRead
from backend.app.services.universe_service import get_universe_run, trading_date_for_now

router = APIRouter(prefix="/universe", tags=["universe"])
VALID_ASSET_CLASSES = {"stock", "crypto"}


@router.get("/{asset_class}/current", response_model=list[UniverseConstituentRead])
def get_current_universe(
    asset_class: str,
    trade_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[UniverseConstituentRead]:
    _validate_asset_class(asset_class)
    target_trade_date = trade_date or trading_date_for_now(None)
    record = get_universe_run(db, asset_class=asset_class, trade_date=target_trade_date)
    if record is None or record.status != "resolved":
        return []
    return [UniverseConstituentRead.model_validate(row) for row in record.constituents]


@router.get("/{asset_class}/run", response_model=UniverseRunRead)
def get_current_universe_run(
    asset_class: str,
    trade_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> UniverseRunRead:
    _validate_asset_class(asset_class)
    target_trade_date = trade_date or trading_date_for_now(None)
    record: UniverseRun | None = get_universe_run(db, asset_class=asset_class, trade_date=target_trade_date)
    if record is None:
        raise HTTPException(status_code=404, detail="Universe run not found")
    return UniverseRunRead.model_validate(record)


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
