from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.core.config import get_settings
from backend.app.schemas.core import (
    LiveRolloutChecklistRead,
    PostTradeReviewRead,
    StockPaperContractReviewRead,
    StockPaperContractSummaryRead,
    SystemEventRead,
    ValidationRequest,
    ValidationResultRead,
)
from backend.app.services.operator_service import (
    VALID_ASSET_CLASSES,
    build_live_rollout_checklist,
    build_post_trade_reviews,
    list_trade_audit_events,
    validate_circuit_breaker,
    validate_kill_switch,
)
from backend.app.services.stock_paper_contract_service import build_stock_paper_contract_reviews, build_stock_paper_contract_summary

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/live-rollout/checklist", response_model=LiveRolloutChecklistRead)
def get_live_rollout_checklist(
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> LiveRolloutChecklistRead:
    return build_live_rollout_checklist(db, settings=get_settings(), timeframe=timeframe)


@router.post("/validations/kill-switch", response_model=ValidationResultRead)
def run_kill_switch_validation(
    payload: ValidationRequest,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> ValidationResultRead:
    return validate_kill_switch(db, settings=get_settings(), timeframe=timeframe, note=payload.note)


@router.post("/validations/circuit-breakers/{asset_class}", response_model=ValidationResultRead)
def run_circuit_breaker_validation(
    asset_class: str,
    payload: ValidationRequest,
    timeframe: str = Query(default="1h"),
    db: Session = Depends(get_db),
) -> ValidationResultRead:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
    return validate_circuit_breaker(db, asset_class=asset_class, timeframe=timeframe, note=payload.note)


@router.get("/trade-audit", response_model=list[SystemEventRead])
def get_trade_audit_events(
    limit: int = Query(default=100, ge=1, le=200),
    asset_class: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[SystemEventRead]:
    if asset_class is not None and asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
    rows = list_trade_audit_events(db, limit=limit, asset_class=asset_class, symbol=symbol, mode=mode)
    return [SystemEventRead.model_validate(row) for row in rows]


@router.get("/post-trade-review", response_model=list[PostTradeReviewRead])
def get_post_trade_review(
    limit: int = Query(default=25, ge=1, le=100),
    asset_class: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[PostTradeReviewRead]:
    if asset_class is not None and asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
    return build_post_trade_reviews(db, asset_class=asset_class, symbol=symbol, timeframe=timeframe, limit=limit)




@router.get("/stock-paper-contract-summary", response_model=StockPaperContractSummaryRead)
def get_stock_paper_contract_summary(
    trade_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> StockPaperContractSummaryRead:
    return build_stock_paper_contract_summary(db, trade_date=trade_date)


@router.get("/stock-paper-contract-review", response_model=list[StockPaperContractReviewRead])
def get_stock_paper_contract_review(
    trade_date: date | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[StockPaperContractReviewRead]:
    return build_stock_paper_contract_reviews(db, trade_date=trade_date, symbol=symbol, limit=limit)
