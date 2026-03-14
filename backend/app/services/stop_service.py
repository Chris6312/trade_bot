from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from math import floor
from typing import Any, Protocol

from sqlalchemy.orm import Session

from backend.app.common.adapters.utils import parse_optional_decimal
from backend.app.core.config import Settings, get_settings
from backend.app.models.core import (
    Candle,
    ExecutionFill,
    ExecutionOrder,
    RiskSnapshot,
    StopState,
    StopSyncState,
    StopUpdateHistory,
)
from backend.app.services.settings_service import get_setting
from backend.app.services.strategy_service import VALID_ASSET_CLASSES

SINGLE_STOP_WRITER = "stop_worker"
STOP_SOURCE = "stop_manager"
FILLED_ORDER_STATUSES = {"filled", "partially_filled"}
SUPPORTED_STOP_STYLES = {"fixed", "trailing", "step"}


@dataclass(slots=True, frozen=True)
class StopRouteTarget:
    asset_class: str
    mode: str
    venue: str
    route_key: str


@dataclass(slots=True, frozen=True)
class StopProfile:
    asset_class: str
    style: str
    fallback_stop_pct: Decimal
    trailing_activation_pct: Decimal
    trailing_offset_pct: Decimal
    step_trigger_pct: Decimal
    step_increment_pct: Decimal


@dataclass(slots=True, frozen=True)
class PriceReference:
    symbol: str
    timeframe: str
    reference_timestamp: datetime
    current_price: Decimal
    high_price: Decimal
    source: str
    candle_id: int | None = None


@dataclass(slots=True, frozen=True)
class StopDecision:
    stop_style: str
    current_price: Decimal
    high_price: Decimal
    desired_stop_price: Decimal
    trailing_active: bool
    activation_changed: bool
    step_level: int
    step_level_changed: bool
    next_step_trigger_price: Decimal | None


@dataclass(slots=True, frozen=True)
class StopSyncRequest:
    asset_class: str
    venue: str
    mode: str
    symbol: str
    timeframe: str
    quantity: Decimal
    stop_price: Decimal
    entry_price: Decimal
    current_price: Decimal
    broker_stop_order_id: str | None
    execution_order_id: int
    stop_style: str


@dataclass(slots=True, frozen=True)
class StopSyncResult:
    status: str
    action: str
    broker_stop_order_id: str
    message: str | None
    raw: dict[str, Any]


@dataclass(slots=True, frozen=True)
class StopManagementSummary:
    asset_class: str
    timeframe: str
    filled_count: int
    created_count: int
    activated_count: int
    updated_count: int
    unchanged_count: int
    failed_count: int
    last_fill_at: datetime | None
    last_evaluated_at: datetime
    venue: str | None
    mode: str | None
    last_status: str
    last_error: str | None
    skipped_reason: str | None = None


class StopUpdater(Protocol):
    def sync_stop(self, request: StopSyncRequest) -> StopSyncResult:
        ...


class StopUpdaterResolver(Protocol):
    def __call__(self, route: StopRouteTarget) -> StopUpdater:
        ...


class VirtualStopUpdater:
    def __init__(self, *, route_key: str, create_path: str, replace_path_template: str) -> None:
        self.route_key = route_key
        self.create_path = create_path
        self.replace_path_template = replace_path_template

    def sync_stop(self, request: StopSyncRequest) -> StopSyncResult:
        action = "replace" if request.broker_stop_order_id else "create"
        broker_stop_order_id = request.broker_stop_order_id or f"{self.route_key}-stop-{request.execution_order_id}"
        endpoint = (
            self.replace_path_template.format(broker_stop_order_id=broker_stop_order_id)
            if action == "replace"
            else self.create_path
        )
        raw = {
            "sync_mode": "virtual",
            "route_key": self.route_key,
            "endpoint": endpoint,
            "action": action,
            "symbol": request.symbol,
            "timeframe": request.timeframe,
            "stop_style": request.stop_style,
            "stop_price": str(request.stop_price),
            "quantity": str(request.quantity),
            "entry_price": str(request.entry_price),
            "current_price": str(request.current_price),
        }
        return StopSyncResult(
            status="virtual_synced",
            action=action,
            broker_stop_order_id=broker_stop_order_id,
            message=None,
            raw=raw,
        )


class DefaultVirtualStopUpdaterResolver:
    _mapping = {
        "public_live": VirtualStopUpdater(
            route_key="public_live",
            create_path="/userapigateway/trading/{account_id}/order",
            replace_path_template="/userapigateway/trading/{account_id}/order/{broker_stop_order_id}",
        ),
        "kraken_live": VirtualStopUpdater(
            route_key="kraken_live",
            create_path="/private/AddOrder",
            replace_path_template="/private/EditOrder/{broker_stop_order_id}",
        ),
        "alpaca_stock_paper": VirtualStopUpdater(
            route_key="alpaca_stock_paper",
            create_path="/v2/orders",
            replace_path_template="/v2/orders/{broker_stop_order_id}",
        ),
        "alpaca_crypto_paper": VirtualStopUpdater(
            route_key="alpaca_crypto_paper",
            create_path="/v2/orders",
            replace_path_template="/v2/orders/{broker_stop_order_id}",
        ),
    }

    def __call__(self, route: StopRouteTarget) -> StopUpdater:
        return self._mapping[route.route_key]


def ensure_single_stop_writer(writer_name: str) -> None:
    if writer_name != SINGLE_STOP_WRITER:
        raise PermissionError(
            f"{writer_name!r} is not allowed to write stop rows. "
            f"Only {SINGLE_STOP_WRITER!r} may persist stop decisions.",
        )


def list_current_stop_states(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[StopState]:
    return (
        db.query(StopState)
        .filter(
            StopState.asset_class == asset_class,
            StopState.timeframe == timeframe,
        )
        .order_by(StopState.symbol.asc(), StopState.last_evaluated_at.desc(), StopState.id.desc())
        .all()
    )


def list_recent_stop_updates(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[StopUpdateHistory]:
    return (
        db.query(StopUpdateHistory)
        .filter(
            StopUpdateHistory.asset_class == asset_class,
            StopUpdateHistory.timeframe == timeframe,
        )
        .order_by(StopUpdateHistory.event_timestamp.desc(), StopUpdateHistory.id.desc())
        .all()
    )


def get_stop_sync_state(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> StopSyncState | None:
    return (
        db.query(StopSyncState)
        .filter(
            StopSyncState.asset_class == asset_class,
            StopSyncState.timeframe == timeframe,
        )
        .one_or_none()
    )


def rebuild_stop_manager_for_asset_class(
    db: Session,
    *,
    writer_name: str,
    asset_class: str,
    timeframe: str,
    evaluated_at: datetime | None = None,
    settings: Settings | None = None,
    updater_resolver: StopUpdaterResolver | None = None,
) -> StopManagementSummary:
    ensure_single_stop_writer(writer_name)
    if asset_class not in VALID_ASSET_CLASSES:
        raise ValueError(f"Unsupported asset class: {asset_class}")

    runtime_settings = settings or get_settings()
    target_time = _ensure_utc(evaluated_at) or datetime.now(UTC)
    profile = _load_stop_profile(db, asset_class=asset_class, settings=runtime_settings)
    filled_orders = _list_filled_execution_orders(db, asset_class=asset_class, timeframe=timeframe)
    if not filled_orders:
        _upsert_stop_sync_state(
            db,
            asset_class=asset_class,
            venue="unprotected",
            mode=_resolve_default_mode(asset_class=asset_class, settings=runtime_settings),
            timeframe=timeframe,
            last_evaluated_at=target_time,
            last_fill_at=None,
            filled_count=0,
            created_count=0,
            activated_count=0,
            updated_count=0,
            unchanged_count=0,
            failed_count=0,
            last_status="fills_unavailable",
            last_error=None,
        )
        db.commit()
        return StopManagementSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            filled_count=0,
            created_count=0,
            activated_count=0,
            updated_count=0,
            unchanged_count=0,
            failed_count=0,
            last_fill_at=None,
            last_evaluated_at=target_time,
            venue=None,
            mode=_resolve_default_mode(asset_class=asset_class, settings=runtime_settings),
            last_status="fills_unavailable",
            last_error=None,
            skipped_reason="fills_unavailable",
        )

    created_count = 0
    activated_count = 0
    updated_count = 0
    unchanged_count = 0
    failed_count = 0
    last_error: str | None = None
    last_status = "synced"
    last_fill_at = max((_ensure_utc(fill.fill_timestamp) for _, fill in filled_orders), default=None)
    last_route: StopRouteTarget | None = None
    resolver = updater_resolver or DefaultVirtualStopUpdaterResolver()

    for order, fill in filled_orders:
        route = _resolve_stop_route(order)
        last_route = route
        updater = resolver(route)
        state = db.query(StopState).filter(StopState.execution_order_id == order.id).one_or_none()
        risk_row = db.query(RiskSnapshot).filter(RiskSnapshot.id == order.risk_snapshot_id).one_or_none()
        price_reference = _load_price_reference(
            db,
            asset_class=asset_class,
            symbol=order.symbol,
            timeframe=order.timeframe,
            fill=fill,
        )

        newly_created = False
        if state is None:
            newly_created = True
            state = _create_initial_stop_state(
                order=order,
                fill=fill,
                risk_row=risk_row,
                profile=profile,
                price_reference=price_reference,
                evaluated_at=target_time,
            )
            db.add(state)
            db.flush()
            created_count += 1
            _create_stop_update_history(
                db,
                state=state,
                event_timestamp=target_time,
                event_type="initial_stop_created",
                status="pending_sync",
                previous_stop_price=None,
                new_stop_price=state.current_stop_price,
                reference_price=price_reference.current_price,
                high_watermark=state.highest_price,
                step_level=state.step_level,
                broker_stop_order_id=None,
                message="Initial protective stop created from persisted fill and risk state.",
                payload=_json_safe({
                    "price_reference": asdict(price_reference),
                    "profile": asdict(profile),
                }),
            )

        decision = _evaluate_stop_state(
            state=state,
            profile=profile,
            price_reference=price_reference,
        )
        sync_required = state.broker_stop_order_id is None or decision.desired_stop_price > state.current_stop_price
        activated_now = decision.activation_changed
        if decision.activation_changed:
            activated_count += 1
        if decision.desired_stop_price > state.current_stop_price:
            updated_count += 1
        if not sync_required and not activated_now and not decision.step_level_changed:
            unchanged_count += 1

        state.current_price = decision.current_price
        state.highest_price = decision.high_price
        state.trailing_active = decision.trailing_active
        if decision.activation_changed and decision.trailing_active and state.trailing_activated_at is None:
            state.trailing_activated_at = target_time
        state.step_level = decision.step_level
        state.next_step_trigger_price = decision.next_step_trigger_price
        state.last_fill_at = _ensure_utc(fill.fill_timestamp)
        state.last_evaluated_at = target_time

        if decision.activation_changed:
            _create_stop_update_history(
                db,
                state=state,
                event_timestamp=target_time,
                event_type=("trailing_stop_activated" if state.stop_style == "trailing" else "step_stop_activated"),
                status="activated",
                previous_stop_price=state.current_stop_price,
                new_stop_price=decision.desired_stop_price,
                reference_price=decision.current_price,
                high_watermark=decision.high_price,
                step_level=decision.step_level,
                broker_stop_order_id=state.broker_stop_order_id,
                message="Stop logic activation threshold reached.",
                payload=_json_safe({"price_reference": asdict(price_reference)}),
            )

        if not sync_required:
            state.status = _resolved_state_status(state)
            continue

        request = StopSyncRequest(
            asset_class=state.asset_class,
            venue=state.venue,
            mode=state.mode,
            symbol=state.symbol,
            timeframe=state.timeframe,
            quantity=state.protected_quantity or Decimal("0"),
            stop_price=decision.desired_stop_price,
            entry_price=state.entry_price,
            current_price=decision.current_price,
            broker_stop_order_id=state.broker_stop_order_id,
            execution_order_id=state.execution_order_id,
            stop_style=state.stop_style,
        )
        try:
            sync_result = updater.sync_stop(request)
        except Exception as exc:  # pragma: no cover - covered by injected failing resolver tests
            failed_count += 1
            last_error = str(exc)
            last_status = "stop_update_failed"
            state.status = "update_failed"
            state.last_error = str(exc)
            _create_stop_update_history(
                db,
                state=state,
                event_timestamp=target_time,
                event_type="stop_update_failed",
                status="failed",
                previous_stop_price=state.current_stop_price,
                new_stop_price=decision.desired_stop_price,
                reference_price=decision.current_price,
                high_watermark=decision.high_price,
                step_level=decision.step_level,
                broker_stop_order_id=state.broker_stop_order_id,
                message=str(exc),
                payload=_json_safe({"price_reference": asdict(price_reference)}),
            )
            continue

        previous_stop = state.current_stop_price
        state.current_stop_price = decision.desired_stop_price
        state.broker_stop_order_id = sync_result.broker_stop_order_id
        state.last_updated_at = target_time
        state.update_count += 1
        state.last_error = None
        state.status = _resolved_state_status(state)
        state.payload = _json_safe({
            **(state.payload or {}),
            "price_reference": asdict(price_reference),
            "profile": asdict(profile),
            "broker_sync": sync_result.raw,
        })
        _create_stop_update_history(
            db,
            state=state,
            event_timestamp=target_time,
            event_type=("initial_stop_synced" if newly_created else "stop_raised"),
            status=sync_result.status,
            previous_stop_price=previous_stop,
            new_stop_price=state.current_stop_price,
            reference_price=decision.current_price,
            high_watermark=decision.high_price,
            step_level=decision.step_level,
            broker_stop_order_id=state.broker_stop_order_id,
            message=sync_result.message,
            payload=_json_safe(sync_result.raw),
        )

    if failed_count and (created_count or updated_count):
        last_status = "partial_failure"
    elif failed_count and not (created_count or updated_count):
        last_status = "stop_update_failed"

    _upsert_stop_sync_state(
        db,
        asset_class=asset_class,
        venue=last_route.venue if last_route else "unprotected",
        mode=last_route.mode if last_route else _resolve_default_mode(asset_class=asset_class, settings=runtime_settings),
        timeframe=timeframe,
        last_evaluated_at=target_time,
        last_fill_at=last_fill_at,
        filled_count=len(filled_orders),
        created_count=created_count,
        activated_count=activated_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        failed_count=failed_count,
        last_status=last_status,
        last_error=last_error,
    )
    db.commit()
    return StopManagementSummary(
        asset_class=asset_class,
        timeframe=timeframe,
        filled_count=len(filled_orders),
        created_count=created_count,
        activated_count=activated_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        failed_count=failed_count,
        last_fill_at=last_fill_at,
        last_evaluated_at=target_time,
        venue=last_route.venue if last_route else None,
        mode=last_route.mode if last_route else _resolve_default_mode(asset_class=asset_class, settings=runtime_settings),
        last_status=last_status,
        last_error=last_error,
    )


def _list_filled_execution_orders(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[tuple[ExecutionOrder, ExecutionFill]]:
    orders = (
        db.query(ExecutionOrder)
        .filter(
            ExecutionOrder.asset_class == asset_class,
            ExecutionOrder.timeframe == timeframe,
            ExecutionOrder.fill_count > 0,
        )
        .order_by(ExecutionOrder.candidate_timestamp.asc(), ExecutionOrder.id.asc())
        .all()
    )
    rows: list[tuple[ExecutionOrder, ExecutionFill]] = []
    for order in orders:
        fill = (
            db.query(ExecutionFill)
            .filter(ExecutionFill.execution_order_id == order.id)
            .order_by(ExecutionFill.fill_timestamp.desc(), ExecutionFill.id.desc())
            .first()
        )
        if fill is None:
            continue
        if str(order.status or "").lower() not in FILLED_ORDER_STATUSES and str(fill.status or "").lower() not in FILLED_ORDER_STATUSES:
            continue
        rows.append((order, fill))
    return rows


def _create_initial_stop_state(
    *,
    order: ExecutionOrder,
    fill: ExecutionFill,
    risk_row: RiskSnapshot | None,
    profile: StopProfile,
    price_reference: PriceReference,
    evaluated_at: datetime,
) -> StopState:
    entry_price = parse_optional_decimal(fill.fill_price) or parse_optional_decimal(order.limit_price) or Decimal("0")
    if entry_price <= 0:
        entry_price = Decimal("1")
    initial_stop_price = parse_optional_decimal(risk_row.stop_price if risk_row is not None else None)
    if initial_stop_price is None or initial_stop_price <= 0:
        initial_stop_price = _quantize_price(entry_price * (Decimal("1") - profile.fallback_stop_pct))

    quantity = parse_optional_decimal(fill.quantity) or parse_optional_decimal(order.quantity) or Decimal("0")
    current_price = price_reference.current_price
    high_price = max(entry_price, price_reference.high_price, current_price)
    trailing_activation_price = None
    trailing_active = False
    step_trigger_pct = None
    step_increment_pct = None
    next_step_trigger_price = None

    if profile.style == "trailing":
        trailing_activation_price = _quantize_price(entry_price * (Decimal("1") + profile.trailing_activation_pct))
    if profile.style == "step":
        step_trigger_pct = profile.step_trigger_pct
        step_increment_pct = profile.step_increment_pct
        next_step_trigger_price = _quantize_price(entry_price * (Decimal("1") + profile.step_trigger_pct))

    return StopState(
        execution_order_id=order.id,
        execution_fill_id=fill.id,
        risk_snapshot_id=order.risk_snapshot_id,
        asset_class=order.asset_class,
        venue=order.venue,
        mode=order.mode,
        source=STOP_SOURCE,
        symbol=order.symbol,
        strategy_name=order.strategy_name,
        direction=order.direction,
        timeframe=order.timeframe,
        stop_style=profile.style,
        status="pending_sync",
        entry_price=entry_price,
        initial_stop_price=initial_stop_price,
        current_stop_price=initial_stop_price,
        current_price=current_price,
        highest_price=high_price,
        trailing_activation_price=trailing_activation_price,
        trailing_offset_pct=(profile.trailing_offset_pct if profile.style == "trailing" else None),
        trailing_active=trailing_active,
        trailing_activated_at=None,
        step_trigger_pct=step_trigger_pct,
        step_increment_pct=step_increment_pct,
        step_level=0,
        next_step_trigger_price=next_step_trigger_price,
        protected_quantity=quantity,
        broker_stop_order_id=None,
        last_fill_at=_ensure_utc(fill.fill_timestamp),
        last_evaluated_at=evaluated_at,
        last_updated_at=None,
        update_count=0,
        last_error=None,
        payload={
            "sync_mode": "virtual",
            "price_reference": _json_safe(asdict(price_reference)),
        },
    )


def _evaluate_stop_state(
    *,
    state: StopState,
    profile: StopProfile,
    price_reference: PriceReference,
) -> StopDecision:
    current_price = price_reference.current_price
    high_price = max(state.highest_price or state.entry_price, price_reference.high_price, current_price)
    desired_stop_price = state.current_stop_price
    trailing_active = bool(state.trailing_active)
    activation_changed = False
    step_level = state.step_level
    step_level_changed = False
    next_step_trigger_price = state.next_step_trigger_price

    if state.stop_style == "trailing":
        activation_price = state.trailing_activation_price or _quantize_price(
            state.entry_price * (Decimal("1") + profile.trailing_activation_pct)
        )
        if not trailing_active and high_price >= activation_price:
            trailing_active = True
            activation_changed = True
        if trailing_active:
            desired_stop_price = max(
                desired_stop_price,
                _quantize_price(high_price * (Decimal("1") - profile.trailing_offset_pct)),
            )

    elif state.stop_style == "step":
        trigger_distance = state.entry_price * profile.step_trigger_pct
        if trigger_distance > 0:
            step_level = max(0, floor((high_price - state.entry_price) / trigger_distance))
        step_level_changed = step_level != state.step_level
        if step_level_changed and state.step_level == 0:
            activation_changed = True
        desired_stop_price = max(
            desired_stop_price,
            _quantize_price(state.initial_stop_price + (state.entry_price * profile.step_increment_pct * step_level)),
        )
        next_step_trigger_price = _quantize_price(
            state.entry_price * (Decimal("1") + (profile.step_trigger_pct * Decimal(step_level + 1)))
        )

    return StopDecision(
        stop_style=state.stop_style,
        current_price=current_price,
        high_price=high_price,
        desired_stop_price=_quantize_price(desired_stop_price),
        trailing_active=trailing_active,
        activation_changed=activation_changed,
        step_level=step_level,
        step_level_changed=step_level_changed,
        next_step_trigger_price=next_step_trigger_price,
    )


def _create_stop_update_history(
    db: Session,
    *,
    state: StopState,
    event_timestamp: datetime,
    event_type: str,
    status: str,
    previous_stop_price: Decimal | None,
    new_stop_price: Decimal | None,
    reference_price: Decimal | None,
    high_watermark: Decimal | None,
    step_level: int | None,
    broker_stop_order_id: str | None,
    message: str | None,
    payload: dict[str, Any] | None,
) -> None:
    db.add(
        StopUpdateHistory(
            stop_state_id=state.id,
            asset_class=state.asset_class,
            venue=state.venue,
            mode=state.mode,
            symbol=state.symbol,
            timeframe=state.timeframe,
            event_timestamp=event_timestamp,
            event_type=event_type,
            status=status,
            previous_stop_price=previous_stop_price,
            new_stop_price=new_stop_price,
            reference_price=reference_price,
            high_watermark=high_watermark,
            step_level=step_level,
            broker_stop_order_id=broker_stop_order_id,
            message=message,
            payload=payload,
        )
    )


def _load_stop_profile(db: Session, *, asset_class: str, settings: Settings) -> StopProfile:
    default_style = settings.stop_stock_style if asset_class == "stock" else settings.stop_crypto_style
    style = _resolve_str_setting(db, f"stops.{asset_class}.style", default=default_style).lower()
    if style not in SUPPORTED_STOP_STYLES:
        style = "fixed"

    if asset_class == "stock":
        fallback_stop_pct = _resolve_decimal_setting(db, f"stops.{asset_class}.fallback_stop_pct", default=settings.stop_stock_fallback_pct)
        trailing_activation_pct = _resolve_decimal_setting(
            db,
            f"stops.{asset_class}.trailing_activation_pct",
            default=settings.stock_trailing_activation_pct,
        )
        trailing_offset_pct = _resolve_decimal_setting(
            db,
            f"stops.{asset_class}.trailing_offset_pct",
            default=settings.stock_trailing_offset_pct,
        )
        step_trigger_pct = _resolve_decimal_setting(
            db,
            f"stops.{asset_class}.step_trigger_pct",
            default=settings.stock_step_trigger_pct,
        )
        step_increment_pct = _resolve_decimal_setting(
            db,
            f"stops.{asset_class}.step_increment_pct",
            default=settings.stock_step_increment_pct,
        )
    else:
        fallback_stop_pct = _resolve_decimal_setting(db, f"stops.{asset_class}.fallback_stop_pct", default=settings.stop_crypto_fallback_pct)
        trailing_activation_pct = _resolve_decimal_setting(
            db,
            f"stops.{asset_class}.trailing_activation_pct",
            default=settings.crypto_trailing_activation_pct,
        )
        trailing_offset_pct = _resolve_decimal_setting(
            db,
            f"stops.{asset_class}.trailing_offset_pct",
            default=settings.crypto_trailing_offset_pct,
        )
        step_trigger_pct = _resolve_decimal_setting(
            db,
            f"stops.{asset_class}.step_trigger_pct",
            default=settings.crypto_step_trigger_pct,
        )
        step_increment_pct = _resolve_decimal_setting(
            db,
            f"stops.{asset_class}.step_increment_pct",
            default=settings.crypto_step_increment_pct,
        )

    return StopProfile(
        asset_class=asset_class,
        style=style,
        fallback_stop_pct=fallback_stop_pct,
        trailing_activation_pct=trailing_activation_pct,
        trailing_offset_pct=trailing_offset_pct,
        step_trigger_pct=step_trigger_pct,
        step_increment_pct=step_increment_pct,
    )


def _load_price_reference(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
    fill: ExecutionFill,
) -> PriceReference:
    candle = (
        db.query(Candle)
        .filter(
            Candle.asset_class == asset_class,
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
        )
        .order_by(Candle.timestamp.desc(), Candle.id.desc())
        .first()
    )
    if candle is not None:
        return PriceReference(
            symbol=symbol,
            timeframe=timeframe,
            reference_timestamp=_ensure_utc(candle.timestamp) or datetime.now(UTC),
            current_price=parse_optional_decimal(candle.close) or Decimal("0"),
            high_price=parse_optional_decimal(candle.high) or parse_optional_decimal(candle.close) or Decimal("0"),
            source="candle",
            candle_id=candle.id,
        )

    fallback_price = parse_optional_decimal(fill.fill_price) or Decimal("0")
    fallback_timestamp = _ensure_utc(fill.fill_timestamp) or datetime.now(UTC)
    return PriceReference(
        symbol=symbol,
        timeframe=timeframe,
        reference_timestamp=fallback_timestamp,
        current_price=fallback_price,
        high_price=fallback_price,
        source="fill",
        candle_id=None,
    )


def _resolve_stop_route(order: ExecutionOrder) -> StopRouteTarget:
    if order.asset_class == "stock" and order.mode == "live":
        return StopRouteTarget(asset_class="stock", mode="live", venue="public", route_key="public_live")
    if order.asset_class == "stock":
        return StopRouteTarget(asset_class="stock", mode="paper", venue="alpaca", route_key="alpaca_stock_paper")
    if order.asset_class == "crypto" and order.mode == "live":
        return StopRouteTarget(asset_class="crypto", mode="live", venue="kraken", route_key="kraken_live")
    return StopRouteTarget(asset_class="crypto", mode="paper", venue="alpaca", route_key="alpaca_crypto_paper")


def _upsert_stop_sync_state(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    mode: str,
    timeframe: str,
    last_evaluated_at: datetime,
    last_fill_at: datetime | None,
    filled_count: int,
    created_count: int,
    activated_count: int,
    updated_count: int,
    unchanged_count: int,
    failed_count: int,
    last_status: str,
    last_error: str | None,
) -> StopSyncState:
    record = get_stop_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        record = StopSyncState(asset_class=asset_class, venue=venue, mode=mode, timeframe=timeframe)
        db.add(record)

    record.venue = venue
    record.mode = mode
    record.last_evaluated_at = _ensure_utc(last_evaluated_at)
    record.last_fill_at = _ensure_utc(last_fill_at)
    record.filled_count = filled_count
    record.created_count = created_count
    record.activated_count = activated_count
    record.updated_count = updated_count
    record.unchanged_count = unchanged_count
    record.failed_count = failed_count
    record.last_status = last_status
    record.last_error = last_error
    return record


def _resolve_default_mode(*, asset_class: str, settings: Settings) -> str:
    if settings.default_mode in {"paper", "live"}:
        return settings.default_mode
    return settings.stock_execution_mode if asset_class == "stock" else settings.crypto_execution_mode


def _resolve_str_setting(db: Session, key: str, *, default: str) -> str:
    record = get_setting(db, key=key)
    if record is None or record.value in {None, ""}:
        return default
    return str(record.value)


def _resolve_decimal_setting(db: Session, key: str, *, default: float) -> Decimal:
    record = get_setting(db, key=key)
    if record is None or record.value in {None, ""}:
        return Decimal(str(default))
    return parse_optional_decimal(record.value) or Decimal(str(default))


def _resolved_state_status(state: StopState) -> str:
    if state.stop_style == "trailing" and state.trailing_active:
        return "trailing_active"
    if state.stop_style == "step" and state.step_level > 0:
        return "step_active"
    return "protected"


def _quantize_price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return (_ensure_utc(value) or value).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
