from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.core import (
    ExecutionFill,
    ExecutionOrder,
    ExecutionSyncState,
    PositionState,
    RiskSyncState,
    Setting,
    StopState,
    SystemEvent,
)
from backend.app.schemas.core import (
    ExecutionFillRead,
    ExecutionOrderRead,
    LiveRolloutChecklistItemRead,
    LiveRolloutChecklistRead,
    PositionStateRead,
    PostTradeReviewRead,
    StopStateRead,
    SystemEventRead,
    ValidationResultRead,
)
from backend.app.services.settings_service import resolve_bool_setting, resolve_str_setting

VALID_ASSET_CLASSES = {"stock", "crypto"}
DEFAULT_TIMEFRAME = "1h"


@dataclass(slots=True, frozen=True)
class ControlState:
    default_mode: str
    stock_mode: str
    crypto_mode: str
    kill_switch_enabled: bool
    stock_trading_enabled: bool
    crypto_trading_enabled: bool


def create_system_event(
    db: Session,
    *,
    event_type: str,
    severity: str,
    message: str,
    event_source: str | None = None,
    payload: dict[str, Any] | None = None,
    commit: bool = False,
) -> SystemEvent:
    record = SystemEvent(
        event_type=event_type,
        severity=severity,
        message=message,
        event_source=event_source,
        payload=payload,
    )
    db.add(record)
    if commit:
        db.commit()
        db.refresh(record)
    return record


def create_audit_event(
    db: Session,
    *,
    event_type: str,
    severity: str,
    message: str,
    payload: dict[str, Any] | None = None,
    commit: bool = False,
) -> SystemEvent:
    normalized_type = event_type if event_type.startswith("audit.") else f"audit.{event_type}"
    return create_system_event(
        db,
        event_type=normalized_type,
        severity=severity,
        message=message,
        event_source="operator_audit",
        payload=payload,
        commit=commit,
    )


def get_control_state(db: Session, *, settings: Settings) -> ControlState:
    default_mode = resolve_str_setting(db, "execution.default_mode", default=settings.default_mode).lower()
    stock_mode = resolve_str_setting(db, "execution.stock.mode", default=settings.stock_execution_mode).lower()
    crypto_mode = resolve_str_setting(db, "execution.crypto.mode", default=settings.crypto_execution_mode).lower()
    return ControlState(
        default_mode=default_mode,
        stock_mode=stock_mode if stock_mode in {"paper", "live"} else "paper",
        crypto_mode=crypto_mode if crypto_mode in {"paper", "live"} else "paper",
        kill_switch_enabled=resolve_bool_setting(db, "controls.kill_switch_enabled", default=settings.execution_kill_switch_enabled),
        stock_trading_enabled=resolve_bool_setting(db, "controls.stock.trading_enabled", default=True),
        crypto_trading_enabled=resolve_bool_setting(db, "controls.crypto.trading_enabled", default=True),
    )


def list_trade_audit_events(
    db: Session,
    *,
    limit: int = 100,
    asset_class: str | None = None,
    symbol: str | None = None,
    mode: str | None = None,
) -> list[SystemEvent]:
    rows = (
        db.query(SystemEvent)
        .order_by(SystemEvent.created_at.desc(), SystemEvent.id.desc())
        .limit(max(20, min(limit * 6, 500)))
        .all()
    )

    filtered: list[SystemEvent] = []
    normalized_symbol = symbol.upper() if symbol else None
    for row in rows:
        if not str(row.event_type).startswith("audit."):
            continue
        payload = row.payload or {}
        if asset_class and str(payload.get("asset_class") or "").lower() != asset_class.lower():
            continue
        if normalized_symbol and str(payload.get("symbol") or "").upper() != normalized_symbol:
            continue
        if mode and str(payload.get("mode") or "").lower() != mode.lower():
            continue
        filtered.append(row)
        if len(filtered) >= limit:
            break
    return filtered


def build_live_rollout_checklist(db: Session, *, settings: Settings, timeframe: str = DEFAULT_TIMEFRAME) -> LiveRolloutChecklistRead:
    generated_at = datetime.now(UTC)
    control = get_control_state(db, settings=settings)
    stock_risk = _get_risk_sync_state(db, asset_class="stock", timeframe=timeframe)
    crypto_risk = _get_risk_sync_state(db, asset_class="crypto", timeframe=timeframe)
    stock_execution = _get_execution_sync_state(db, asset_class="stock", timeframe=timeframe)
    crypto_execution = _get_execution_sync_state(db, asset_class="crypto", timeframe=timeframe)
    audit_events = list_trade_audit_events(db, limit=20)
    reviewable_trades = _list_reviewable_orders(db, timeframe=timeframe, limit=10)

    items = [
        _build_mode_item(control),
        _build_route_item(
            asset_class="stock",
            mode=control.stock_mode,
            trading_enabled=control.stock_trading_enabled,
            kill_switch_enabled=control.kill_switch_enabled,
            execution_state=stock_execution,
        ),
        _build_route_item(
            asset_class="crypto",
            mode=control.crypto_mode,
            trading_enabled=control.crypto_trading_enabled,
            kill_switch_enabled=control.kill_switch_enabled,
            execution_state=crypto_execution,
        ),
        _build_kill_switch_item(control),
        _build_breaker_item(asset_class="stock", state=stock_risk),
        _build_breaker_item(asset_class="crypto", state=crypto_risk),
        _build_audit_item(audit_events),
        _build_review_item(reviewable_trades),
    ]

    overall_status = "ready"
    statuses = {item.status for item in items}
    if any(status in {"blocked", "tripped"} for status in statuses):
        overall_status = "blocked"
    elif "attention" in statuses:
        overall_status = "attention"
    elif control.stock_mode == "paper" and control.crypto_mode == "paper":
        overall_status = "paper_default"

    live_asset_count = int(control.stock_mode == "live") + int(control.crypto_mode == "live")
    return LiveRolloutChecklistRead(
        generated_at=generated_at,
        overall_status=overall_status,
        default_mode=control.default_mode,
        stock_mode=control.stock_mode,
        crypto_mode=control.crypto_mode,
        live_asset_count=live_asset_count,
        items=items,
    )


def validate_kill_switch(
    db: Session,
    *,
    settings: Settings,
    timeframe: str = DEFAULT_TIMEFRAME,
    note: str | None = None,
) -> ValidationResultRead:
    created_at = datetime.now(UTC)
    control = get_control_state(db, settings=settings)
    stock_execution = _get_execution_sync_state(db, asset_class="stock", timeframe=timeframe)
    crypto_execution = _get_execution_sync_state(db, asset_class="crypto", timeframe=timeframe)
    blocked_assets = [
        state.asset_class
        for state in (stock_execution, crypto_execution)
        if state is not None and state.last_status == "kill_switch_blocked"
    ]

    if control.kill_switch_enabled and blocked_assets:
        status = "passed"
        message = f"Kill switch is enabled and execution blocking has been observed for {', '.join(blocked_assets)}."
        severity = "info"
    elif control.kill_switch_enabled:
        status = "attention"
        message = "Kill switch is enabled, but no execution block has been observed yet in the latest sync state."
        severity = "warning"
    else:
        status = "attention"
        message = "Kill switch is not enabled, so route blocking cannot be verified yet."
        severity = "warning"

    details = {
        "kill_switch_enabled": control.kill_switch_enabled,
        "observed_blocked_assets": blocked_assets,
        "stock_execution_status": stock_execution.last_status if stock_execution else None,
        "crypto_execution_status": crypto_execution.last_status if crypto_execution else None,
        "timeframe": timeframe,
        "note": note,
    }
    create_audit_event(
        db,
        event_type="audit.kill_switch_validation",
        severity=severity,
        message=message,
        payload=details,
    )
    db.commit()
    return ValidationResultRead(
        validation_type="kill_switch",
        asset_class=None,
        status=status,
        message=message,
        details=details,
        created_at=created_at,
    )


def validate_circuit_breaker(
    db: Session,
    *,
    asset_class: str,
    timeframe: str = DEFAULT_TIMEFRAME,
    note: str | None = None,
) -> ValidationResultRead:
    if asset_class not in VALID_ASSET_CLASSES:
        raise ValueError(f"Unsupported asset class: {asset_class}")

    created_at = datetime.now(UTC)
    state = _get_risk_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    breaker_status = state.breaker_status if state is not None else None
    if breaker_status:
        status = "passed"
        message = f"{asset_class.title()} circuit breaker has been observed in runtime as {breaker_status}."
        severity = "error" if "hard" in breaker_status or "total" in breaker_status else "warning"
    elif state is not None:
        status = "attention"
        message = f"{asset_class.title()} circuit breaker settings are present, but no live runtime breaker event has been observed yet."
        severity = "warning"
    else:
        status = "attention"
        message = f"{asset_class.title()} risk sync state is not available yet, so breaker validation is incomplete."
        severity = "warning"

    details = {
        "asset_class": asset_class,
        "timeframe": timeframe,
        "breaker_status": breaker_status,
        "risk_last_status": state.last_status if state is not None else None,
        "note": note,
    }
    create_audit_event(
        db,
        event_type="audit.circuit_breaker_validation",
        severity=severity,
        message=message,
        payload=details,
    )
    db.commit()
    return ValidationResultRead(
        validation_type="circuit_breaker",
        asset_class=asset_class,
        status=status,
        message=message,
        details=details,
        created_at=created_at,
    )


def build_post_trade_reviews(
    db: Session,
    *,
    asset_class: str | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = 25,
) -> list[PostTradeReviewRead]:
    orders = _list_reviewable_orders(db, asset_class=asset_class, symbol=symbol, timeframe=timeframe, limit=limit)
    recent_events = list_trade_audit_events(db, limit=200, asset_class=asset_class, symbol=symbol)
    reviews: list[PostTradeReviewRead] = []

    for order in orders:
        fill = (
            db.query(ExecutionFill)
            .filter(ExecutionFill.execution_order_id == order.id)
            .order_by(ExecutionFill.fill_timestamp.desc(), ExecutionFill.id.desc())
            .first()
        )
        stop = db.query(StopState).filter(StopState.execution_order_id == order.id).one_or_none()
        position = (
            db.query(PositionState)
            .filter(
                PositionState.asset_class == order.asset_class,
                PositionState.venue == order.venue,
                PositionState.mode == order.mode,
                PositionState.symbol == order.symbol,
                PositionState.timeframe == order.timeframe,
            )
            .order_by(PositionState.synced_at.desc(), PositionState.id.desc())
            .first()
        )
        related_events = _match_related_events(order=order, fill=fill, recent_events=recent_events)
        review_notes = _build_review_notes(order=order, fill=fill, stop=stop, position=position, related_events=related_events)
        reviews.append(
            PostTradeReviewRead(
                asset_class=order.asset_class,
                symbol=order.symbol,
                venue=order.venue,
                mode=order.mode,
                strategy_name=order.strategy_name,
                timeframe=order.timeframe,
                order_status=order.status,
                fill_status=fill.status if fill is not None else None,
                stop_status=stop.status if stop is not None else None,
                position_status=position.status if position is not None else None,
                reconciliation_status=position.reconciliation_status if position is not None else None,
                candidate_timestamp=order.candidate_timestamp,
                routed_at=order.routed_at,
                fill_timestamp=fill.fill_timestamp if fill is not None else None,
                audit_event_count=len(related_events),
                review_notes=review_notes,
                order=ExecutionOrderRead.model_validate(order),
                fill=ExecutionFillRead.model_validate(fill) if fill is not None else None,
                stop=StopStateRead.model_validate(stop) if stop is not None else None,
                position=PositionStateRead.model_validate(position) if position is not None else None,
                related_events=[SystemEventRead.model_validate(event) for event in related_events],
            )
        )
    return reviews


def _list_reviewable_orders(
    db: Session,
    *,
    asset_class: str | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int,
) -> list[ExecutionOrder]:
    query = db.query(ExecutionOrder)
    if asset_class is not None:
        query = query.filter(ExecutionOrder.asset_class == asset_class)
    if symbol is not None:
        query = query.filter(ExecutionOrder.symbol == symbol.upper())
    if timeframe is not None:
        query = query.filter(ExecutionOrder.timeframe == timeframe)
    return (
        query
        .order_by(ExecutionOrder.routed_at.desc(), ExecutionOrder.id.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )


def _build_mode_item(control: ControlState) -> LiveRolloutChecklistItemRead:
    if control.default_mode == "mixed":
        detail = f"Default mode is mixed, with stocks on {control.stock_mode} and crypto on {control.crypto_mode}."
        status = "attention" if "live" in {control.stock_mode, control.crypto_mode} else "paper"
    else:
        detail = f"Default mode is {control.default_mode}."
        status = "attention" if control.default_mode == "live" else "paper"
    return LiveRolloutChecklistItemRead(
        key="mode_guard",
        label="Mode guard",
        status=status,
        detail=detail,
        action_required="Confirm live asset routing stays intentional and reversible." if status == "attention" else None,
    )


def _build_route_item(
    *,
    asset_class: str,
    mode: str,
    trading_enabled: bool,
    kill_switch_enabled: bool,
    execution_state: ExecutionSyncState | None,
) -> LiveRolloutChecklistItemRead:
    if mode != "live":
        return LiveRolloutChecklistItemRead(
            key=f"{asset_class}_route",
            label=f"{asset_class.title()} live route",
            status="paper",
            detail=f"{asset_class.title()} execution is still in paper mode.",
            action_required="Promote only after the checklist is green." if asset_class == "stock" else None,
        )
    if not trading_enabled:
        return LiveRolloutChecklistItemRead(
            key=f"{asset_class}_route",
            label=f"{asset_class.title()} live route",
            status="blocked",
            detail=f"{asset_class.title()} live mode is selected, but trading is disabled.",
            action_required="Re-enable trading only after preflight checks are complete.",
        )
    if kill_switch_enabled:
        return LiveRolloutChecklistItemRead(
            key=f"{asset_class}_route",
            label=f"{asset_class.title()} live route",
            status="blocked",
            detail=f"{asset_class.title()} live mode is selected, but the master kill switch is engaged.",
            action_required="Release the kill switch only after validation is complete.",
        )
    detail = f"{asset_class.title()} live routing is enabled."
    if execution_state is not None and execution_state.last_status:
        detail = f"{detail} Latest execution status: {execution_state.last_status}."
    return LiveRolloutChecklistItemRead(
        key=f"{asset_class}_route",
        label=f"{asset_class.title()} live route",
        status="ready",
        detail=detail,
        action_required=None,
    )


def _build_kill_switch_item(control: ControlState) -> LiveRolloutChecklistItemRead:
    if control.kill_switch_enabled:
        return LiveRolloutChecklistItemRead(
            key="kill_switch",
            label="Master kill switch",
            status="blocked",
            detail="Kill switch is engaged. New entries are blocked.",
            action_required="Validate the block and release only when you are ready to trade.",
        )
    return LiveRolloutChecklistItemRead(
        key="kill_switch",
        label="Master kill switch",
        status="ready",
        detail="Kill switch is disengaged and ready to be used if needed.",
        action_required="Run a validation before the first live session.",
    )


def _build_breaker_item(*, asset_class: str, state: RiskSyncState | None) -> LiveRolloutChecklistItemRead:
    if state is None:
        return LiveRolloutChecklistItemRead(
            key=f"{asset_class}_circuit_breaker",
            label=f"{asset_class.title()} circuit breaker",
            status="attention",
            detail="Risk sync state is not available yet.",
            action_required="Run the risk pipeline before relying on live breaker state.",
        )
    if state.breaker_status:
        severity_status = "tripped" if "hard" in state.breaker_status or "total" in state.breaker_status else "attention"
        return LiveRolloutChecklistItemRead(
            key=f"{asset_class}_circuit_breaker",
            label=f"{asset_class.title()} circuit breaker",
            status=severity_status,
            detail=f"Latest breaker observation: {state.breaker_status}.",
            action_required="Review losses before re-enabling new entries.",
        )
    return LiveRolloutChecklistItemRead(
        key=f"{asset_class}_circuit_breaker",
        label=f"{asset_class.title()} circuit breaker",
        status="ready",
        detail=f"{asset_class.title()} risk sync is healthy and no breaker is currently tripped.",
        action_required="Capture one validation event before switching meaningful size live.",
    )


def _build_audit_item(events: list[SystemEvent]) -> LiveRolloutChecklistItemRead:
    if not events:
        return LiveRolloutChecklistItemRead(
            key="audit_trail",
            label="Trade audit trail",
            status="attention",
            detail="No audit events have been recorded yet.",
            action_required="Record a kill-switch or breaker validation before the first live day.",
        )
    latest = events[0]
    return LiveRolloutChecklistItemRead(
        key="audit_trail",
        label="Trade audit trail",
        status="ready",
        detail=f"{len(events)} recent audit event(s) recorded. Latest: {latest.event_type}.",
        action_required=None,
    )


def _build_review_item(orders: list[ExecutionOrder]) -> LiveRolloutChecklistItemRead:
    if not orders:
        return LiveRolloutChecklistItemRead(
            key="post_trade_review",
            label="Post-trade review workflow",
            status="attention",
            detail="No reviewable trades are available yet.",
            action_required="After the next paper or live fill, inspect the post-trade review endpoint.",
        )
    latest = orders[0]
    return LiveRolloutChecklistItemRead(
        key="post_trade_review",
        label="Post-trade review workflow",
        status="ready",
        detail=f"{len(orders)} reviewable trade(s) available. Latest: {latest.symbol} {latest.status}.",
        action_required=None,
    )


def _get_risk_sync_state(db: Session, *, asset_class: str, timeframe: str) -> RiskSyncState | None:
    return (
        db.query(RiskSyncState)
        .filter(RiskSyncState.asset_class == asset_class, RiskSyncState.timeframe == timeframe)
        .one_or_none()
    )


def _get_execution_sync_state(db: Session, *, asset_class: str, timeframe: str) -> ExecutionSyncState | None:
    return (
        db.query(ExecutionSyncState)
        .filter(ExecutionSyncState.asset_class == asset_class, ExecutionSyncState.timeframe == timeframe)
        .one_or_none()
    )


def _match_related_events(
    *,
    order: ExecutionOrder,
    fill: ExecutionFill | None,
    recent_events: Iterable[SystemEvent],
) -> list[SystemEvent]:
    matched: list[SystemEvent] = []
    for event in recent_events:
        payload = event.payload or {}
        same_asset = str(payload.get("asset_class") or "").lower() == order.asset_class.lower()
        same_symbol = str(payload.get("symbol") or "").upper() == order.symbol.upper()
        if not (same_asset and same_symbol):
            continue
        if payload.get("client_order_id") and payload.get("client_order_id") != order.client_order_id:
            continue
        if fill is not None and payload.get("venue_fill_id") and payload.get("venue_fill_id") != fill.venue_fill_id:
            continue
        matched.append(event)
        if len(matched) >= 8:
            break
    return matched


def _build_review_notes(
    *,
    order: ExecutionOrder,
    fill: ExecutionFill | None,
    stop: StopState | None,
    position: PositionState | None,
    related_events: list[SystemEvent],
) -> list[str]:
    notes = [
        f"Route: {order.asset_class} {order.mode} via {order.venue} is currently {order.status}.",
    ]
    if fill is not None:
        notes.append(f"Fill persisted at {fill.fill_price} for {fill.quantity} units with status {fill.status}.")
    else:
        notes.append("No persisted fill was found for this order yet.")
    if stop is not None:
        notes.append(f"Protective stop is {stop.status} at {stop.current_stop_price} using {stop.stop_style} logic.")
    else:
        notes.append("No protective stop snapshot is attached yet.")
    if position is not None:
        notes.append(
            f"Position state is {position.status} with reconciliation {position.reconciliation_status} and unrealized P/L {position.unrealized_pnl}."
        )
    else:
        notes.append("No position snapshot is attached yet.")
    if related_events:
        notes.append(f"Audit trail includes {len(related_events)} related event(s) for this trade.")
    else:
        notes.append("No related audit events were matched for this trade yet.")
    return notes
