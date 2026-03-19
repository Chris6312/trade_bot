from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Iterable

from sqlalchemy.orm import Session

from backend.app.models.core import AiResearchPick, ExecutionFill, ExecutionOrder, PositionState, RiskSnapshot, StrategySnapshot
from backend.app.schemas.core import StockPaperContractReviewRead, StockPaperContractSummaryRead
from backend.app.services.universe_service import trading_date_for_now

STOCK_PAPER_CONTRACT_STRATEGY = "htf_reclaim_long"
STOCK_PAPER_CONTRACT_TIMEFRAME = "5m"


@dataclass(frozen=True, slots=True)
class _StrategyContext:
    row: StrategySnapshot | None
    pair_1h: str | None
    pair_15m: str | None
    bias_pass: bool | None
    setup_pass: bool | None
    trigger_pass: bool | None


def build_stock_paper_contract_reviews(
    db: Session,
    *,
    trade_date: date | None = None,
    symbol: str | None = None,
    limit: int = 25,
) -> list[StockPaperContractReviewRead]:
    target_trade_date = trade_date or _latest_trade_date(db) or trading_date_for_now(datetime.now(UTC))
    query = db.query(AiResearchPick).filter(AiResearchPick.trade_date == target_trade_date.isoformat())
    if symbol is not None:
        query = query.filter(AiResearchPick.symbol == symbol.upper())
    picks = (
        query
        .order_by(AiResearchPick.scanned_at.desc(), AiResearchPick.id.asc())
        .limit(max(1, min(limit, 100)))
        .all()
    )

    reviews: list[StockPaperContractReviewRead] = []
    for pick in picks:
        strategy_context = _latest_strategy_context(db, symbol=pick.symbol)
        risk_row = _latest_risk_row(db, symbol=pick.symbol)
        order = _matching_order(db, risk_row=risk_row, symbol=pick.symbol)
        fill = _latest_fill(db, order=order)
        position = _latest_position(db, symbol=pick.symbol)

        trade_taken = order is not None
        outcome = _resolve_outcome(strategy_context=strategy_context, risk_row=risk_row, order=order, position=position)
        notes = _build_notes(pick=pick, strategy_context=strategy_context, risk_row=risk_row, order=order, fill=fill, position=position)

        reviews.append(
            StockPaperContractReviewRead(
                trade_date=target_trade_date,
                symbol=pick.symbol,
                ai_named=True,
                ai_bucket=_payload_value(pick, "bucket"),
                ai_reason=pick.catalyst,
                ai_quality_1h=_payload_value(pick, "quality_1h"),
                ai_quality_15m=_payload_value(pick, "quality_15m"),
                ai_reclaim_state=_payload_value(pick, "reclaim_state"),
                ai_risk_note=pick.risk_reward_note,
                ai_scanned_at=_ensure_utc(pick.scanned_at),
                strategy_status=strategy_context.row.status if strategy_context.row is not None else None,
                candidate_timestamp=_ensure_utc(strategy_context.row.candidate_timestamp) if strategy_context.row is not None else None,
                pair_1h_used=strategy_context.pair_1h,
                pair_15m_used=strategy_context.pair_15m,
                bias_pass_1h=strategy_context.bias_pass,
                setup_pass_15m=strategy_context.setup_pass,
                trigger_pass_5m=strategy_context.trigger_pass,
                indicator_approved=(strategy_context.row.status == "ready") if strategy_context.row is not None else None,
                risk_status=risk_row.status if risk_row is not None else None,
                risk_decision_reason=risk_row.decision_reason if risk_row is not None else None,
                entry_price=risk_row.entry_price if risk_row is not None else None,
                stop_price=risk_row.stop_price if risk_row is not None else None,
                target_price=risk_row.take_profit_price if risk_row is not None else None,
                trade_taken=trade_taken,
                trade_status=_trade_status_label(strategy_context=strategy_context, risk_row=risk_row, order=order),
                filled_at=_ensure_utc(fill.fill_timestamp) if fill is not None else None,
                position_status=position.status if position is not None else None,
                realized_pnl=position.realized_pnl if position is not None else None,
                unrealized_pnl=position.unrealized_pnl if position is not None else None,
                outcome=outcome,
                notes=notes,
            )
        )
    return reviews


def build_stock_paper_contract_summary(
    db: Session,
    *,
    trade_date: date | None = None,
) -> StockPaperContractSummaryRead:
    target_trade_date = trade_date or _latest_trade_date(db) or trading_date_for_now(datetime.now(UTC))
    reviews = build_stock_paper_contract_reviews(db, trade_date=target_trade_date, limit=100)

    summary = StockPaperContractSummaryRead(
        trade_date=target_trade_date,
        shortlist_count=len(reviews),
        ready_now_count=sum(1 for row in reviews if (row.ai_bucket or "").lower() == "ready_now"),
        watchlist_count=sum(1 for row in reviews if (row.ai_bucket or "").lower() == "watchlist"),
        none_count=sum(1 for row in reviews if (row.ai_bucket or "").lower() == "none"),
        indicator_approved_count=sum(1 for row in reviews if row.indicator_approved is True),
        risk_accepted_count=sum(1 for row in reviews if (row.risk_status or "").lower() == "accepted"),
        trades_taken_count=sum(1 for row in reviews if row.trade_taken is True),
        open_outcomes_count=sum(1 for row in reviews if (row.outcome or "").lower() == "open"),
        closed_outcomes_count=sum(1 for row in reviews if (row.outcome or "").lower().startswith("closed_")),
        skipped_ready_count=sum(
            1
            for row in reviews
            if row.indicator_approved is True and (row.risk_status or "").lower() == "accepted" and row.trade_taken is not True
        ),
        winners_count=sum(1 for row in reviews if (row.outcome or "").lower() == "closed_win"),
        losers_count=sum(1 for row in reviews if (row.outcome or "").lower() == "closed_loss"),
        latest_ai_scan_at=max((_ensure_utc(row.ai_scanned_at) for row in reviews if row.ai_scanned_at is not None), default=None),
    )
    return summary


def _latest_trade_date(db: Session) -> date | None:
    row = (
        db.query(AiResearchPick.trade_date)
        .order_by(AiResearchPick.trade_date.desc())
        .first()
    )
    if row is None or not row[0]:
        return None
    return date.fromisoformat(str(row[0]))


def _latest_strategy_context(db: Session, *, symbol: str) -> _StrategyContext:
    row = (
        db.query(StrategySnapshot)
        .filter(
            StrategySnapshot.asset_class == "stock",
            StrategySnapshot.symbol == symbol.upper(),
            StrategySnapshot.strategy_name == STOCK_PAPER_CONTRACT_STRATEGY,
            StrategySnapshot.timeframe == STOCK_PAPER_CONTRACT_TIMEFRAME,
        )
        .order_by(StrategySnapshot.candidate_timestamp.desc(), StrategySnapshot.computed_at.desc(), StrategySnapshot.id.desc())
        .first()
    )
    if row is None:
        return _StrategyContext(None, None, None, None, None, None)

    payload = dict(row.payload or {})
    selected_pairs = payload.get("selected_pairs") or {}
    return _StrategyContext(
        row=row,
        pair_1h=_format_pair(selected_pairs.get("1h")),
        pair_15m=_format_pair(selected_pairs.get("15m")),
        bias_pass=_coerce_bool(payload.get("bias_pass")),
        setup_pass=_coerce_bool(payload.get("setup_pass")),
        trigger_pass=_coerce_bool(payload.get("trigger_pass")),
    )


def _latest_risk_row(db: Session, *, symbol: str) -> RiskSnapshot | None:
    return (
        db.query(RiskSnapshot)
        .filter(
            RiskSnapshot.asset_class == "stock",
            RiskSnapshot.symbol == symbol.upper(),
            RiskSnapshot.strategy_name == STOCK_PAPER_CONTRACT_STRATEGY,
            RiskSnapshot.timeframe == STOCK_PAPER_CONTRACT_TIMEFRAME,
        )
        .order_by(RiskSnapshot.candidate_timestamp.desc(), RiskSnapshot.computed_at.desc(), RiskSnapshot.id.desc())
        .first()
    )


def _matching_order(db: Session, *, risk_row: RiskSnapshot | None, symbol: str) -> ExecutionOrder | None:
    query = db.query(ExecutionOrder).filter(
        ExecutionOrder.asset_class == "stock",
        ExecutionOrder.symbol == symbol.upper(),
        ExecutionOrder.strategy_name == STOCK_PAPER_CONTRACT_STRATEGY,
        ExecutionOrder.timeframe == STOCK_PAPER_CONTRACT_TIMEFRAME,
    )
    if risk_row is not None:
        query = query.filter(ExecutionOrder.risk_snapshot_id == risk_row.id)
    return query.order_by(ExecutionOrder.routed_at.desc(), ExecutionOrder.id.desc()).first()




def _latest_fill(db: Session, *, order: ExecutionOrder | None) -> ExecutionFill | None:
    if order is None:
        return None
    return (
        db.query(ExecutionFill)
        .filter(ExecutionFill.execution_order_id == order.id)
        .order_by(ExecutionFill.fill_timestamp.desc(), ExecutionFill.id.desc())
        .first()
    )

def _latest_position(db: Session, *, symbol: str) -> PositionState | None:
    return (
        db.query(PositionState)
        .filter(
            PositionState.asset_class == "stock",
            PositionState.symbol == symbol.upper(),
            PositionState.timeframe == STOCK_PAPER_CONTRACT_TIMEFRAME,
        )
        .order_by(PositionState.synced_at.desc(), PositionState.id.desc())
        .first()
    )


def _resolve_outcome(*, strategy_context: _StrategyContext, risk_row: RiskSnapshot | None, order: ExecutionOrder | None, position: PositionState | None) -> str | None:
    if order is None:
        if strategy_context.row is None:
            return "awaiting_indicator"
        if strategy_context.row.status != "ready":
            return "indicator_blocked"
        if risk_row is None:
            return "awaiting_risk"
        if risk_row.status != "accepted":
            return "risk_blocked"
        return "ready_not_routed"
    if position is None:
        if (order.status or "").lower() == "filled":
            return "awaiting_position_sync"
        return order.status
    if position.status == "open":
        return "open"
    if position.status == "closed":
        realized = position.realized_pnl or 0
        if realized > 0:
            return "closed_win"
        if realized < 0:
            return "closed_loss"
        return "closed_flat"
    return position.status




def _trade_status_label(*, strategy_context: _StrategyContext, risk_row: RiskSnapshot | None, order: ExecutionOrder | None) -> str | None:
    if order is not None:
        return order.status
    if strategy_context.row is None:
        return None
    if strategy_context.row.status != "ready":
        return "not_ready"
    if risk_row is None:
        return "awaiting_risk"
    if risk_row.status != "accepted":
        return "not_routed"
    return "skipped_ready"

def _build_notes(
    *,
    pick: AiResearchPick,
    strategy_context: _StrategyContext,
    risk_row: RiskSnapshot | None,
    order: ExecutionOrder | None,
    fill: ExecutionFill | None,
    position: PositionState | None,
) -> list[str]:
    notes: list[str] = []
    if pick.catalyst:
        notes.append(pick.catalyst)
    if pick.risk_reward_note:
        notes.append(f"AI risk note: {pick.risk_reward_note}")
    if strategy_context.row is None:
        notes.append("No persisted 5m HTF reclaim strategy evaluation found yet.")
    else:
        blocked = list(strategy_context.row.blocked_reasons or [])
        if blocked:
            notes.append("Strategy blockers: " + ", ".join(blocked[:4]))
    if risk_row is not None:
        risk_status = risk_row.status or "unknown"
        if risk_row.decision_reason:
            notes.append(f"Risk decision: {risk_status} ({risk_row.decision_reason})")
        else:
            notes.append(f"Risk decision: {risk_status}")
    else:
        notes.append("No persisted risk snapshot found for this symbol yet.")
    if order is None:
        notes.append("Trade taken: no")
    else:
        notes.append(f"Trade taken: yes ({order.status})")
    if fill is not None:
        notes.append(f"Latest fill: {fill.status} at {fill.fill_price}")
    if position is not None and position.status:
        notes.append(f"Position status: {position.status}")
        if position.status == "closed":
            notes.append(f"Realized PnL: {position.realized_pnl}")
        elif position.status == "open":
            notes.append(f"Unrealized PnL: {position.unrealized_pnl}")
    return notes


def _format_pair(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    fast_type = value.get("fast_type")
    fast_length = value.get("fast_length")
    slow_type = value.get("slow_type")
    slow_length = value.get("slow_length")
    if fast_type is None or fast_length is None or slow_type is None or slow_length is None:
        return None
    return f"{fast_type}{fast_length}/{slow_type}{slow_length}"


def _payload_value(pick: AiResearchPick, key: str) -> str | None:
    payload = dict(pick.raw_payload or {})
    value = payload.get(key)
    if value is None:
        return None
    return str(value)


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
