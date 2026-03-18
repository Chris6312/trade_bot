
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.orm import Session

from backend.app.common.adapters.models import OrderRequest, OrderResult
from backend.app.common.adapters.utils import parse_datetime, parse_optional_decimal
from backend.app.core.config import Settings, get_settings
from backend.app.models.core import ExecutionFill, ExecutionOrder, ExecutionSyncState, RiskSnapshot
from backend.app.services.adapter_registry import AdapterRegistry
from backend.app.services.operator_service import create_audit_event
from backend.app.services.risk_service import VALID_ASSET_CLASSES, list_current_risk_snapshots
from backend.app.services.settings_service import get_setting, resolve_bool_setting, resolve_str_setting

SINGLE_EXECUTION_WRITER = "execution_worker"
EXECUTION_SOURCE = "execution_engine"
FILLED_STATUSES = {"filled", "partially_filled"}
TERMINAL_FAILURE_STATUS = "route_failed"


class TradingAdapter(Protocol):
    def place_order(self, request: OrderRequest) -> OrderResult:
        ...


@dataclass(slots=True, frozen=True)
class RouteTarget:
    asset_class: str
    mode: str
    venue: str
    adapter_key: str


@dataclass(slots=True, frozen=True)
class ExecutionPersistenceSummary:
    asset_class: str
    timeframe: str
    candidate_count: int
    routed_count: int
    duplicate_count: int
    blocked_count: int
    failed_count: int
    fill_count: int
    last_candidate_at: datetime | None
    last_routed_at: datetime | None
    venue: str | None
    mode: str | None
    last_status: str
    last_error: str | None
    skipped_reason: str | None = None


class AdapterResolver(Protocol):
    def __call__(self, route: RouteTarget) -> TradingAdapter:
        ...


class RegistryAdapterResolver:
    def __init__(self, registry: AdapterRegistry | None = None) -> None:
        self.registry = registry or AdapterRegistry()

    def __call__(self, route: RouteTarget) -> TradingAdapter:
        return getattr(self.registry, route.adapter_key)()


def ensure_single_execution_writer(writer_name: str) -> None:
    if writer_name != SINGLE_EXECUTION_WRITER:
        raise PermissionError(
            f"{writer_name!r} is not allowed to write execution rows. "
            f"Only {SINGLE_EXECUTION_WRITER!r} may persist execution decisions.",
        )


def list_current_execution_orders(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[ExecutionOrder]:
    rows = (
        db.query(ExecutionOrder)
        .filter(
            ExecutionOrder.asset_class == asset_class,
            ExecutionOrder.timeframe == timeframe,
        )
        .order_by(
            ExecutionOrder.candidate_timestamp.desc(),
            ExecutionOrder.routed_at.desc(),
            ExecutionOrder.id.desc(),
        )
        .all()
    )
    current: dict[tuple[str, str], ExecutionOrder] = {}
    for row in rows:
        key = (row.symbol, row.strategy_name)
        if key not in current:
            current[key] = row
    return sorted(current.values(), key=lambda row: (row.symbol, row.strategy_name))


def list_recent_execution_fills(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[ExecutionFill]:
    return (
        db.query(ExecutionFill)
        .filter(
            ExecutionFill.asset_class == asset_class,
            ExecutionFill.timeframe == timeframe,
        )
        .order_by(ExecutionFill.fill_timestamp.desc(), ExecutionFill.id.desc())
        .all()
    )


def get_execution_sync_state(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> ExecutionSyncState | None:
    return (
        db.query(ExecutionSyncState)
        .filter(
            ExecutionSyncState.asset_class == asset_class,
            ExecutionSyncState.timeframe == timeframe,
        )
        .one_or_none()
    )


def rebuild_execution_for_asset_class(
    db: Session,
    *,
    writer_name: str,
    asset_class: str,
    timeframe: str,
    routed_at: datetime | None = None,
    settings: Settings | None = None,
    adapter_resolver: AdapterResolver | None = None,
) -> ExecutionPersistenceSummary:
    ensure_single_execution_writer(writer_name)
    if asset_class not in VALID_ASSET_CLASSES:
        raise ValueError(f"Unsupported asset class: {asset_class}")

    runtime_settings = settings or get_settings()
    target_time = _ensure_utc(routed_at) or datetime.now(UTC)
    accepted_rows = [
        row for row in list_current_risk_snapshots(db, asset_class=asset_class, timeframe=timeframe) if row.status == "accepted"
    ]
    if not accepted_rows:
        _upsert_execution_sync_state(
            db,
            asset_class=asset_class,
            venue="unrouted",
            mode=_resolve_execution_mode(db, asset_class=asset_class, settings=runtime_settings),
            timeframe=timeframe,
            last_routed_at=target_time,
            last_candidate_at=None,
            candidate_count=0,
            routed_count=0,
            duplicate_count=0,
            blocked_count=0,
            failed_count=0,
            fill_count=0,
            last_status="risk_unavailable",
            last_error=None,
        )
        db.commit()
        return ExecutionPersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            candidate_count=0,
            routed_count=0,
            duplicate_count=0,
            blocked_count=0,
            failed_count=0,
            fill_count=0,
            last_candidate_at=None,
            last_routed_at=target_time,
            venue=None,
            mode=_resolve_execution_mode(db, asset_class=asset_class, settings=runtime_settings),
            last_status="risk_unavailable",
            last_error=None,
            skipped_reason="risk_unavailable",
        )

    resolved_mode = _resolve_execution_mode(db, asset_class=asset_class, settings=runtime_settings)
    route_target = _resolve_route_target(asset_class=asset_class, mode=resolved_mode)
    last_candidate_at = max((_ensure_utc(row.candidate_timestamp) for row in accepted_rows if row.candidate_timestamp), default=None)
    routed_count = 0
    duplicate_count = 0
    blocked_count = 0
    failed_count = 0
    fill_count = 0
    last_error: str | None = None
    last_status = "completed"
    resolver = adapter_resolver or RegistryAdapterResolver(AdapterRegistry(runtime_settings))

    if not _asset_trading_enabled(db, asset_class=asset_class):
        blocked_count = len(accepted_rows)
        last_status = f"{asset_class}_trading_disabled"
        previous_state = get_execution_sync_state(db, asset_class=asset_class, timeframe=timeframe)
        if previous_state is None or previous_state.last_status != last_status:
            create_audit_event(
                db,
                event_type="audit.execution_blocked",
                severity="warning",
                message=f"{asset_class.title()} execution is blocked because trading is disabled.",
                payload={"asset_class": asset_class, "mode": route_target.mode, "venue": route_target.venue, "reason": last_status},
            )
        _upsert_execution_sync_state(
            db,
            asset_class=asset_class,
            venue=route_target.venue,
            mode=route_target.mode,
            timeframe=timeframe,
            last_routed_at=target_time,
            last_candidate_at=last_candidate_at,
            candidate_count=len(accepted_rows),
            routed_count=0,
            duplicate_count=0,
            blocked_count=blocked_count,
            failed_count=0,
            fill_count=0,
            last_status=last_status,
            last_error=None,
        )
        db.commit()
        return ExecutionPersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            candidate_count=len(accepted_rows),
            routed_count=0,
            duplicate_count=0,
            blocked_count=blocked_count,
            failed_count=0,
            fill_count=0,
            last_candidate_at=last_candidate_at,
            last_routed_at=target_time,
            venue=route_target.venue,
            mode=route_target.mode,
            last_status=last_status,
            last_error=None,
        )

    if _kill_switch_enabled(db, settings=runtime_settings):
        blocked_count = len(accepted_rows)
        last_status = "kill_switch_blocked"
        previous_state = get_execution_sync_state(db, asset_class=asset_class, timeframe=timeframe)
        if previous_state is None or previous_state.last_status != last_status:
            create_audit_event(
                db,
                event_type="audit.execution_blocked",
                severity="warning",
                message=f"{asset_class.title()} execution is blocked by the master kill switch.",
                payload={"asset_class": asset_class, "mode": route_target.mode, "venue": route_target.venue, "reason": last_status},
            )
        _upsert_execution_sync_state(
            db,
            asset_class=asset_class,
            venue=route_target.venue,
            mode=route_target.mode,
            timeframe=timeframe,
            last_routed_at=target_time,
            last_candidate_at=last_candidate_at,
            candidate_count=len(accepted_rows),
            routed_count=0,
            duplicate_count=0,
            blocked_count=blocked_count,
            failed_count=0,
            fill_count=0,
            last_status=last_status,
            last_error=None,
        )
        db.commit()
        return ExecutionPersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            candidate_count=len(accepted_rows),
            routed_count=0,
            duplicate_count=0,
            blocked_count=blocked_count,
            failed_count=0,
            fill_count=0,
            last_candidate_at=last_candidate_at,
            last_routed_at=target_time,
            venue=route_target.venue,
            mode=route_target.mode,
            last_status=last_status,
            last_error=None,
        )

    adapter = resolver(route_target)
    try:
        for risk_row in sorted(accepted_rows, key=lambda row: (row.candidate_timestamp, row.id)):
            existing = db.query(ExecutionOrder).filter(ExecutionOrder.risk_snapshot_id == risk_row.id).one_or_none()
            if existing is not None:
                duplicate_count += 1
                continue

            client_order_id = _build_client_order_id(risk_row)
            request = _build_order_request(risk_row, runtime_settings=runtime_settings, client_order_id=client_order_id)
            order_record = ExecutionOrder(
                risk_snapshot_id=risk_row.id,
                asset_class=risk_row.asset_class,
                venue=route_target.venue,
                mode=route_target.mode,
                source=EXECUTION_SOURCE,
                symbol=risk_row.symbol,
                strategy_name=risk_row.strategy_name,
                direction=risk_row.direction,
                timeframe=risk_row.timeframe,
                candidate_timestamp=_ensure_utc(risk_row.candidate_timestamp) or target_time,
                routed_at=target_time,
                client_order_id=client_order_id,
                broker_order_id=None,
                status="routing",
                order_type=request.order_type,
                side=request.side,
                quantity=request.quantity,
                notional_value=request.notional,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                fill_count=0,
                decision_reason="execution_pending",
                error_message=None,
                payload={
                    "route": asdict(route_target),
                    "risk_snapshot_id": risk_row.id,
                    "risk_decision_reason": risk_row.decision_reason,
                    **(
                        {"take_profit_price": str(request.take_profit_price)}
                        if request.take_profit_price is not None
                        else {}
                    ),
                },
            )
            db.add(order_record)
            db.flush()
            try:
                result = adapter.place_order(request)
            except Exception as exc:  # pragma: no cover - covered in tests with fake adapter
                order_record.status = TERMINAL_FAILURE_STATUS
                order_record.decision_reason = TERMINAL_FAILURE_STATUS
                order_record.error_message = str(exc)
                order_record.payload = {**(order_record.payload or {}), "error": str(exc)}
                create_audit_event(
                    db,
                    event_type="audit.order_route_failed",
                    severity="error",
                    message=f"Order routing failed for {risk_row.symbol} on {route_target.venue}.",
                    payload={
                        "asset_class": risk_row.asset_class,
                        "symbol": risk_row.symbol,
                        "mode": route_target.mode,
                        "venue": route_target.venue,
                        "client_order_id": client_order_id,
                        "risk_snapshot_id": risk_row.id,
                        "error": str(exc),
                    },
                )
                failed_count += 1
                last_error = str(exc)
                last_status = TERMINAL_FAILURE_STATUS
                continue

            order_record.venue = result.venue or route_target.venue
            order_record.broker_order_id = result.order_id
            order_record.status = str(result.status or "submitted")
            order_record.decision_reason = "execution_routed"
            order_record.payload = {**(order_record.payload or {}), "broker_response": result.raw}
            create_audit_event(
                db,
                event_type="audit.order_routed",
                severity="info",
                message=f"Order routed for {risk_row.symbol} via {order_record.venue} in {order_record.mode} mode.",
                payload={
                    "asset_class": order_record.asset_class,
                    "symbol": order_record.symbol,
                    "mode": order_record.mode,
                    "venue": order_record.venue,
                    "status": order_record.status,
                    "client_order_id": order_record.client_order_id,
                    "broker_order_id": order_record.broker_order_id,
                    "risk_snapshot_id": risk_row.id,
                },
            )
            routed_count += 1

            fill = _build_fill_record(order_record=order_record, risk_row=risk_row, result=result, routed_at=target_time)
            if fill is not None:
                db.add(fill)
                order_record.fill_count = 1
                create_audit_event(
                    db,
                    event_type="audit.order_filled",
                    severity="info",
                    message=f"Fill persisted for {order_record.symbol} with status {fill.status}.",
                    payload={
                        "asset_class": order_record.asset_class,
                        "symbol": order_record.symbol,
                        "mode": order_record.mode,
                        "venue": order_record.venue,
                        "status": fill.status,
                        "client_order_id": order_record.client_order_id,
                        "broker_order_id": order_record.broker_order_id,
                        "venue_fill_id": fill.venue_fill_id,
                    },
                )
                fill_count += 1
    finally:
        close_method = getattr(adapter, "close", None)
        if callable(close_method):
            close_method()

    if failed_count and routed_count == 0:
        last_status = TERMINAL_FAILURE_STATUS
    elif duplicate_count and routed_count == 0 and failed_count == 0:
        last_status = "duplicate_skipped"

    _upsert_execution_sync_state(
        db,
        asset_class=asset_class,
        venue=route_target.venue,
        mode=route_target.mode,
        timeframe=timeframe,
        last_routed_at=target_time,
        last_candidate_at=last_candidate_at,
        candidate_count=len(accepted_rows),
        routed_count=routed_count,
        duplicate_count=duplicate_count,
        blocked_count=blocked_count,
        failed_count=failed_count,
        fill_count=fill_count,
        last_status=last_status,
        last_error=last_error,
    )
    db.commit()
    return ExecutionPersistenceSummary(
        asset_class=asset_class,
        timeframe=timeframe,
        candidate_count=len(accepted_rows),
        routed_count=routed_count,
        duplicate_count=duplicate_count,
        blocked_count=blocked_count,
        failed_count=failed_count,
        fill_count=fill_count,
        last_candidate_at=last_candidate_at,
        last_routed_at=target_time,
        venue=route_target.venue,
        mode=route_target.mode,
        last_status=last_status,
        last_error=last_error,
    )


def _build_order_request(
    risk_row: RiskSnapshot,
    *,
    runtime_settings: Settings,
    client_order_id: str,
) -> OrderRequest:
    side = "buy" if (risk_row.direction or "long").lower() != "short" else "sell"

    # Prefer the dedicated column added by the AI research pipeline; fall back
    # to the payload key written by risk_service when it copies the AI pick.
    take_profit_price = parse_optional_decimal(risk_row.take_profit_price)
    if take_profit_price is None:
        payload = risk_row.payload or {}
        take_profit_price = parse_optional_decimal(payload.get("ai_take_profit_primary"))

    return OrderRequest(
        symbol=risk_row.symbol,
        side=side,
        order_type=runtime_settings.execution_order_type,
        quantity=parse_optional_decimal(risk_row.quantity),
        notional=None,
        limit_price=None,
        stop_price=parse_optional_decimal(risk_row.stop_price),
        take_profit_price=take_profit_price,
        time_in_force=runtime_settings.execution_time_in_force,
        client_order_id=client_order_id,
    )


def _build_fill_record(
    *,
    order_record: ExecutionOrder,
    risk_row: RiskSnapshot,
    result: OrderResult,
    routed_at: datetime,
) -> ExecutionFill | None:
    status = str(result.status or "submitted").lower()
    if status not in FILLED_STATUSES:
        return None

    raw = result.raw if isinstance(result.raw, dict) else {}
    quantity = (
        parse_optional_decimal(raw.get("filled_qty"))
        or parse_optional_decimal(raw.get("filled_quantity"))
        or parse_optional_decimal(raw.get("qty"))
        or parse_optional_decimal(risk_row.quantity)
    )
    fill_price = (
        parse_optional_decimal(raw.get("filled_avg_price"))
        or parse_optional_decimal(raw.get("average_price"))
        or parse_optional_decimal(raw.get("price"))
        or parse_optional_decimal(risk_row.entry_price)
    )
    if quantity is None or fill_price is None:
        return None

    fee_amount = (
        parse_optional_decimal(raw.get("filled_fee"))
        or parse_optional_decimal(raw.get("fee"))
        or parse_optional_decimal(risk_row.estimated_fees)
    )
    notional_value = quantity * fill_price
    fill_timestamp = _parse_fill_timestamp(raw.get("filled_at") or raw.get("timestamp") or routed_at)
    return ExecutionFill(
        execution_order_id=order_record.id,
        asset_class=order_record.asset_class,
        venue=order_record.venue,
        mode=order_record.mode,
        symbol=order_record.symbol,
        timeframe=order_record.timeframe,
        fill_timestamp=fill_timestamp,
        status=status,
        quantity=quantity,
        fill_price=fill_price,
        notional_value=notional_value,
        fee_amount=fee_amount,
        venue_fill_id=str(raw.get("fill_id") or raw.get("trade_id") or result.order_id),
        payload=raw,
    )


def _parse_fill_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value) or datetime.now(UTC)
    try:
        return parse_datetime(value, field_name="fill_timestamp")
    except Exception:
        return _ensure_utc(datetime.now(UTC)) or datetime.now(UTC)


def _build_client_order_id(risk_row: RiskSnapshot) -> str:
    candidate_time = _ensure_utc(risk_row.candidate_timestamp) or datetime.now(UTC)
    return f"tb-{risk_row.asset_class[:2]}-{risk_row.id}-{candidate_time.strftime('%Y%m%d%H%M%S')}"


def _resolve_route_target(*, asset_class: str, mode: str) -> RouteTarget:
    if asset_class == "stock" and mode == "live":
        return RouteTarget(asset_class="stock", mode="live", venue="public", adapter_key="public_trading")
    if asset_class == "stock":
        return RouteTarget(asset_class="stock", mode="paper", venue="alpaca", adapter_key="alpaca_stock_paper")
    if asset_class == "crypto" and mode == "live":
        return RouteTarget(asset_class="crypto", mode="live", venue="kraken", adapter_key="kraken_trading")
    return RouteTarget(asset_class="crypto", mode="paper", venue="alpaca", adapter_key="alpaca_crypto_paper")


def _resolve_execution_mode(db: Session, *, asset_class: str, settings: Settings) -> str:
    default_mode = resolve_str_setting(db, "execution.default_mode", default=settings.default_mode).lower()
    if default_mode in {"paper", "live"}:
        return default_mode
    if default_mode == "mixed":
        per_asset_default = settings.stock_execution_mode if asset_class == "stock" else settings.crypto_execution_mode
        asset_mode = resolve_str_setting(db, f"execution.{asset_class}.mode", default=per_asset_default).lower()
        return asset_mode if asset_mode in {"paper", "live"} else "paper"
    return "paper"


def _kill_switch_enabled(db: Session, *, settings: Settings) -> bool:
    return resolve_bool_setting(db, "controls.kill_switch_enabled", default=settings.execution_kill_switch_enabled)


def _asset_trading_enabled(db: Session, *, asset_class: str) -> bool:
    return resolve_bool_setting(db, f"controls.{asset_class}.trading_enabled", default=True)


def _upsert_execution_sync_state(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    mode: str,
    timeframe: str,
    last_routed_at: datetime,
    last_candidate_at: datetime | None,
    candidate_count: int,
    routed_count: int,
    duplicate_count: int,
    blocked_count: int,
    failed_count: int,
    fill_count: int,
    last_status: str,
    last_error: str | None,
) -> ExecutionSyncState:
    record = get_execution_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        record = ExecutionSyncState(asset_class=asset_class, venue=venue, mode=mode, timeframe=timeframe)
        db.add(record)

    record.venue = venue
    record.mode = mode
    record.last_routed_at = _ensure_utc(last_routed_at)
    record.last_candidate_at = _ensure_utc(last_candidate_at)
    record.candidate_count = candidate_count
    record.routed_count = routed_count
    record.duplicate_count = duplicate_count
    record.blocked_count = blocked_count
    record.failed_count = failed_count
    record.fill_count = fill_count
    record.last_status = last_status
    record.last_error = last_error
    return record


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
