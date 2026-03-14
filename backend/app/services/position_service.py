from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.orm import Session

from backend.app.common.adapters.models import AccountPosition, AccountState, OpenOrder
from backend.app.core.config import Settings, get_settings
from backend.app.models.core import (
    AccountSnapshot,
    Candle,
    ExecutionFill,
    ExecutionOrder,
    PositionState,
    PositionSyncState,
    OpenOrderState,
    ReconciliationMismatch,
)
from backend.app.services.adapter_registry import AdapterRegistry
from backend.app.services.settings_service import get_setting
from backend.app.services.strategy_service import VALID_ASSET_CLASSES

SINGLE_POSITION_WRITER = "position_worker"
POSITION_SOURCE = "position_sync"
OPEN_ORDER_SOURCE = "position_sync"
AGGREGATE_VENUE = "aggregate"
ZERO = Decimal("0")
DECIMAL_TOLERANCE = Decimal("0.00000001")
OPEN_ORDER_STATUSES = {
    "new",
    "accepted",
    "submitted",
    "pending",
    "open",
    "pending_new",
    "partially_filled",
    "held",
    "routing",
}


@dataclass(slots=True, frozen=True)
class SyncRouteTarget:
    asset_class: str
    mode: str
    venue: str
    adapter_key: str


@dataclass(slots=True)
class InternalPositionSnapshot:
    symbol: str
    quantity: Decimal = ZERO
    average_entry_price: Decimal | None = None
    cost_basis: Decimal | None = None
    realized_pnl: Decimal = ZERO
    last_fill_at: datetime | None = None
    side: str = "long"


@dataclass(slots=True, frozen=True)
class PositionSyncSummary:
    asset_class: str
    timeframe: str
    position_count: int
    open_order_count: int
    mismatch_count: int
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    last_fill_at: datetime | None
    last_synced_at: datetime
    venue: str | None
    mode: str | None
    last_status: str
    last_error: str | None
    skipped_reason: str | None = None


class PositionSyncAdapter(Protocol):
    def get_account_state(self) -> AccountState:
        ...

    def list_open_orders(self) -> tuple[OpenOrder, ...]:
        ...


class AdapterResolver(Protocol):
    def __call__(self, route: SyncRouteTarget) -> PositionSyncAdapter:
        ...


class RegistryAdapterResolver:
    def __init__(self, registry: AdapterRegistry | None = None) -> None:
        self.registry = registry or AdapterRegistry()

    def __call__(self, route: SyncRouteTarget) -> PositionSyncAdapter:
        return getattr(self.registry, route.adapter_key)()


def ensure_single_position_writer(writer_name: str) -> None:
    if writer_name != SINGLE_POSITION_WRITER:
        raise PermissionError(
            f"{writer_name!r} is not allowed to write position rows. "
            f"Only {SINGLE_POSITION_WRITER!r} may persist reconciliation state.",
        )


def list_current_position_states(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[PositionState]:
    return (
        db.query(PositionState)
        .filter(
            PositionState.asset_class == asset_class,
            PositionState.timeframe == timeframe,
        )
        .order_by(PositionState.symbol.asc(), PositionState.id.asc())
        .all()
    )


def list_current_open_orders(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[OpenOrderState]:
    return (
        db.query(OpenOrderState)
        .filter(
            OpenOrderState.asset_class == asset_class,
            OpenOrderState.timeframe == timeframe,
        )
        .order_by(OpenOrderState.symbol.asc(), OpenOrderState.submitted_at.desc(), OpenOrderState.id.desc())
        .all()
    )


def list_active_reconciliation_mismatches(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[ReconciliationMismatch]:
    return (
        db.query(ReconciliationMismatch)
        .filter(
            ReconciliationMismatch.asset_class == asset_class,
            ReconciliationMismatch.timeframe == timeframe,
            ReconciliationMismatch.status == "active",
        )
        .order_by(ReconciliationMismatch.detected_at.desc(), ReconciliationMismatch.id.desc())
        .all()
    )


def get_position_sync_state(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> PositionSyncState | None:
    return (
        db.query(PositionSyncState)
        .filter(
            PositionSyncState.asset_class == asset_class,
            PositionSyncState.timeframe == timeframe,
        )
        .one_or_none()
    )


def rebuild_position_sync_for_asset_class(
    db: Session,
    *,
    writer_name: str,
    asset_class: str,
    timeframe: str,
    synced_at: datetime | None = None,
    settings: Settings | None = None,
    adapter_resolver: AdapterResolver | None = None,
) -> PositionSyncSummary:
    ensure_single_position_writer(writer_name)
    if asset_class not in VALID_ASSET_CLASSES:
        raise ValueError(f"Unsupported asset class: {asset_class}")

    runtime_settings = settings or get_settings()
    target_time = _ensure_utc(synced_at) or datetime.now(UTC)
    resolved_mode = _resolve_execution_mode(db, asset_class=asset_class, settings=runtime_settings)
    route_target = _resolve_route_target(asset_class=asset_class, mode=resolved_mode)
    resolver = adapter_resolver or RegistryAdapterResolver(AdapterRegistry(runtime_settings))
    adapter = resolver(route_target)

    last_error: str | None = None
    last_status = "completed"
    try:
        broker_account = adapter.get_account_state()
        broker_open_orders = adapter.list_open_orders()
    except Exception as exc:
        last_error = str(exc)
        last_status = "sync_failed"
        _upsert_position_sync_state(
            db,
            asset_class=asset_class,
            venue=route_target.venue,
            mode=route_target.mode,
            timeframe=timeframe,
            last_synced_at=target_time,
            last_fill_at=None,
            position_count=0,
            open_order_count=0,
            mismatch_count=0,
            realized_pnl=ZERO,
            unrealized_pnl=ZERO,
            last_status=last_status,
            last_error=last_error,
        )
        db.commit()
        return PositionSyncSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            position_count=0,
            open_order_count=0,
            mismatch_count=0,
            realized_pnl=ZERO,
            unrealized_pnl=ZERO,
            last_fill_at=None,
            last_synced_at=target_time,
            venue=route_target.venue,
            mode=route_target.mode,
            last_status=last_status,
            last_error=last_error,
        )
    finally:
        close_method = getattr(adapter, "close", None)
        if callable(close_method):
            close_method()

    internal_positions = _build_internal_positions(
        db,
        asset_class=asset_class,
        timeframe=timeframe,
        venue=route_target.venue,
        mode=route_target.mode,
    )
    latest_prices = _get_latest_prices(
        db,
        asset_class=asset_class,
        timeframe=timeframe,
        symbols={*internal_positions.keys(), *(position.symbol for position in broker_account.positions)},
    )

    db.query(PositionState).filter(
        PositionState.asset_class == asset_class,
        PositionState.timeframe == timeframe,
        PositionState.mode == route_target.mode,
    ).delete(synchronize_session=False)
    db.query(OpenOrderState).filter(
        OpenOrderState.asset_class == asset_class,
        OpenOrderState.timeframe == timeframe,
        OpenOrderState.mode == route_target.mode,
    ).delete(synchronize_session=False)
    db.query(ReconciliationMismatch).filter(
        ReconciliationMismatch.asset_class == asset_class,
        ReconciliationMismatch.timeframe == timeframe,
        ReconciliationMismatch.mode == route_target.mode,
        ReconciliationMismatch.status == "active",
    ).delete(synchronize_session=False)

    mismatches: list[ReconciliationMismatch] = []
    symbols = sorted({*internal_positions.keys(), *(position.symbol for position in broker_account.positions)})
    realized_total = ZERO
    unrealized_total = ZERO
    last_fill_at = max((item.last_fill_at for item in internal_positions.values() if item.last_fill_at is not None), default=None)

    broker_positions_by_symbol = {position.symbol: position for position in broker_account.positions}

    for symbol in symbols:
        broker_position = broker_positions_by_symbol.get(symbol)
        internal_position = internal_positions.get(symbol)
        broker_qty = _decimal_or_none(getattr(broker_position, "quantity", None))
        internal_qty = _decimal_or_none(internal_position.quantity if internal_position is not None else None)
        quantity = broker_qty if broker_qty is not None else (internal_qty or ZERO)
        quantity_delta = None
        if broker_qty is not None or internal_qty is not None:
            quantity_delta = (broker_qty or ZERO) - (internal_qty or ZERO)

        status = _resolve_position_status(broker_qty=broker_qty, internal_qty=internal_qty)
        mismatch_reason = None
        if status == "broker_only":
            mismatch_reason = "position_missing_in_db"
        elif status == "internal_only":
            mismatch_reason = "position_missing_at_broker"
        elif status == "mismatch":
            mismatch_reason = "position_quantity_delta"

        if mismatch_reason is not None:
            mismatches.append(
                ReconciliationMismatch(
                    asset_class=asset_class,
                    venue=route_target.venue,
                    mode=route_target.mode,
                    timeframe=timeframe,
                    mismatch_type=mismatch_reason,
                    symbol=symbol,
                    severity="warning",
                    status="active",
                    internal_value=str(internal_qty) if internal_qty is not None else None,
                    broker_value=str(broker_qty) if broker_qty is not None else None,
                    message=_build_position_mismatch_message(symbol=symbol, mismatch_type=mismatch_reason),
                    detected_at=target_time,
                    payload={
                        "broker_quantity": str(broker_qty) if broker_qty is not None else None,
                        "internal_quantity": str(internal_qty) if internal_qty is not None else None,
                    },
                )
            )

        internal_avg = internal_position.average_entry_price if internal_position is not None else None
        broker_avg = getattr(broker_position, "average_entry_price", None) if broker_position is not None else None
        average_entry_price = broker_avg or internal_avg
        current_price = latest_prices.get(symbol)
        if current_price is None and broker_position is not None:
            broker_market_value = _decimal_or_none(getattr(broker_position, "market_value", None))
            if broker_market_value is not None and broker_qty not in (None, ZERO):
                current_price = broker_market_value / broker_qty
        if current_price is None:
            current_price = average_entry_price

        cost_basis = None
        if internal_position is not None:
            cost_basis = internal_position.cost_basis
        elif broker_position is not None:
            cost_basis = _decimal_or_none(getattr(broker_position, "cost_basis", None))

        market_value = None
        if current_price is not None:
            market_value = current_price * quantity
        elif broker_position is not None:
            market_value = _decimal_or_none(getattr(broker_position, "market_value", None))

        realized_pnl = internal_position.realized_pnl if internal_position is not None else ZERO
        unrealized_pnl = ZERO
        if quantity > ZERO and current_price is not None and average_entry_price is not None:
            unrealized_pnl = (current_price - average_entry_price) * quantity

        realized_total += realized_pnl
        unrealized_total += unrealized_pnl

        db.add(
            PositionState(
                asset_class=asset_class,
                venue=route_target.venue,
                mode=route_target.mode,
                source=POSITION_SOURCE,
                symbol=symbol,
                timeframe=timeframe,
                side=(broker_position.side if broker_position is not None else (internal_position.side if internal_position is not None else "long")),
                status=_position_row_status(quantity=quantity, reconciliation_status=status),
                reconciliation_status=status,
                quantity=quantity,
                broker_quantity=broker_qty,
                internal_quantity=internal_qty,
                quantity_delta=quantity_delta,
                average_entry_price=average_entry_price,
                broker_average_entry_price=broker_avg,
                internal_average_entry_price=internal_avg,
                cost_basis=cost_basis,
                market_value=market_value,
                current_price=current_price,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                last_fill_at=internal_position.last_fill_at if internal_position is not None else None,
                synced_at=target_time,
                mismatch_reason=mismatch_reason,
                payload={
                    "broker_position": broker_position.raw if broker_position is not None else None,
                    "internal_position": {
                        "quantity": str(internal_qty) if internal_qty is not None else None,
                        "average_entry_price": str(internal_avg) if internal_avg is not None else None,
                        "cost_basis": str(internal_position.cost_basis) if internal_position is not None and internal_position.cost_basis is not None else None,
                        "realized_pnl": str(realized_pnl),
                    } if internal_position is not None else None,
                },
            )
        )

    open_order_mismatches = _persist_open_orders(
        db,
        asset_class=asset_class,
        timeframe=timeframe,
        synced_at=target_time,
        venue=route_target.venue,
        mode=route_target.mode,
        broker_orders=broker_open_orders,
    )
    mismatches.extend(open_order_mismatches)

    for mismatch in mismatches:
        db.add(mismatch)

    _persist_account_snapshot(
        db,
        account_scope=asset_class,
        venue=broker_account.venue,
        mode=broker_account.mode,
        equity=broker_account.equity,
        cash=broker_account.cash,
        buying_power=broker_account.buying_power,
        realized_pnl=realized_total,
        unrealized_pnl=unrealized_total,
        as_of=target_time,
    )
    db.flush()
    _rebuild_total_account_snapshot(db, as_of=target_time)

    last_status = "completed" if not mismatches else "reconciled_with_mismatches"
    _upsert_position_sync_state(
        db,
        asset_class=asset_class,
        venue=route_target.venue,
        mode=route_target.mode,
        timeframe=timeframe,
        last_synced_at=target_time,
        last_fill_at=last_fill_at,
        position_count=len(symbols),
        open_order_count=len(broker_open_orders),
        mismatch_count=len(mismatches),
        realized_pnl=realized_total,
        unrealized_pnl=unrealized_total,
        last_status=last_status,
        last_error=None,
    )
    db.commit()

    return PositionSyncSummary(
        asset_class=asset_class,
        timeframe=timeframe,
        position_count=len(symbols),
        open_order_count=len(broker_open_orders),
        mismatch_count=len(mismatches),
        realized_pnl=realized_total,
        unrealized_pnl=unrealized_total,
        last_fill_at=last_fill_at,
        last_synced_at=target_time,
        venue=route_target.venue,
        mode=route_target.mode,
        last_status=last_status,
        last_error=None,
    )


def _persist_open_orders(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
    synced_at: datetime,
    venue: str,
    mode: str,
    broker_orders: tuple[OpenOrder, ...],
) -> list[ReconciliationMismatch]:
    broker_by_key = {_build_broker_open_order_key(order): order for order in broker_orders}
    internal_orders = _list_internal_open_orders(
        db,
        asset_class=asset_class,
        timeframe=timeframe,
        venue=venue,
        mode=mode,
    )
    internal_by_key = {_build_internal_open_order_key(order): order for order in internal_orders}
    mismatches: list[ReconciliationMismatch] = []

    for key in sorted(set(broker_by_key) | set(internal_by_key)):
        broker_order = broker_by_key.get(key)
        internal_order = internal_by_key.get(key)
        reconciliation_status = "matched"
        mismatch_reason = None
        source = OPEN_ORDER_SOURCE

        if broker_order is None:
            reconciliation_status = "internal_only"
            mismatch_reason = "open_order_missing_at_broker"
            source = "execution"
        elif internal_order is None:
            reconciliation_status = "broker_only"
            mismatch_reason = "open_order_missing_in_db"
            source = "broker"
        else:
            source = "broker"

        symbol = broker_order.symbol if broker_order is not None else internal_order.symbol
        submitted_at = broker_order.submitted_at if broker_order is not None else _ensure_utc(internal_order.routed_at)
        db.add(
            OpenOrderState(
                execution_order_id=internal_order.id if internal_order is not None else None,
                asset_class=asset_class,
                venue=venue,
                mode=mode,
                source=source,
                symbol=symbol,
                timeframe=timeframe,
                unique_order_key=key,
                client_order_id=(broker_order.client_order_id if broker_order is not None else internal_order.client_order_id),
                broker_order_id=(broker_order.order_id if broker_order is not None else internal_order.broker_order_id),
                status=(broker_order.status if broker_order is not None else internal_order.status),
                order_type=(broker_order.order_type if broker_order is not None else internal_order.order_type),
                side=(broker_order.side if broker_order is not None else internal_order.side),
                quantity=(broker_order.quantity if broker_order is not None else internal_order.quantity),
                notional_value=(broker_order.notional if broker_order is not None else internal_order.notional_value),
                limit_price=(broker_order.limit_price if broker_order is not None else internal_order.limit_price),
                stop_price=(broker_order.stop_price if broker_order is not None else internal_order.stop_price),
                submitted_at=submitted_at,
                synced_at=synced_at,
                reconciliation_status=reconciliation_status,
                mismatch_reason=mismatch_reason,
                payload={
                    "broker_order": broker_order.raw if broker_order is not None else None,
                    "internal_order": internal_order.payload if internal_order is not None else None,
                },
            )
        )
        if mismatch_reason is not None:
            mismatches.append(
                ReconciliationMismatch(
                    asset_class=asset_class,
                    venue=venue,
                    mode=mode,
                    timeframe=timeframe,
                    mismatch_type=mismatch_reason,
                    symbol=symbol,
                    severity="warning",
                    status="active",
                    internal_value=internal_order.client_order_id if internal_order is not None else None,
                    broker_value=broker_order.order_id if broker_order is not None else None,
                    message=_build_order_mismatch_message(symbol=symbol, mismatch_type=mismatch_reason),
                    detected_at=synced_at,
                    payload={
                        "order_key": key,
                        "internal_order_id": internal_order.id if internal_order is not None else None,
                        "broker_order_id": broker_order.order_id if broker_order is not None else None,
                    },
                )
            )
    return mismatches


def _list_internal_open_orders(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
    venue: str,
    mode: str,
) -> list[ExecutionOrder]:
    return (
        db.query(ExecutionOrder)
        .filter(
            ExecutionOrder.asset_class == asset_class,
            ExecutionOrder.timeframe == timeframe,
            ExecutionOrder.venue == venue,
            ExecutionOrder.mode == mode,
            ExecutionOrder.status.in_(tuple(OPEN_ORDER_STATUSES)),
        )
        .order_by(ExecutionOrder.routed_at.desc(), ExecutionOrder.id.desc())
        .all()
    )


def _build_internal_positions(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
    venue: str,
    mode: str,
) -> dict[str, InternalPositionSnapshot]:
    fills = (
        db.query(ExecutionFill, ExecutionOrder)
        .join(ExecutionOrder, ExecutionOrder.id == ExecutionFill.execution_order_id)
        .filter(
            ExecutionFill.asset_class == asset_class,
            ExecutionFill.timeframe == timeframe,
            ExecutionFill.mode == mode,
            ExecutionOrder.venue == venue,
        )
        .order_by(ExecutionFill.fill_timestamp.asc(), ExecutionFill.id.asc())
        .all()
    )
    state: dict[str, InternalPositionSnapshot] = {}
    for fill_row, order_row in fills:
        symbol_state = state.setdefault(fill_row.symbol, InternalPositionSnapshot(symbol=fill_row.symbol))
        fee = _decimal_or_zero(fill_row.fee_amount)
        fill_qty = _decimal_or_zero(fill_row.quantity)
        fill_price = _decimal_or_zero(fill_row.fill_price)
        side = (order_row.side or "buy").lower()
        symbol_state.last_fill_at = _max_dt(symbol_state.last_fill_at, _ensure_utc(fill_row.fill_timestamp))
        symbol_state.side = "short" if side == "sell" and symbol_state.quantity < ZERO else "long"

        if side == "buy":
            existing_cost = _decimal_or_zero(symbol_state.cost_basis)
            new_cost = existing_cost + (fill_qty * fill_price) + fee
            new_qty = symbol_state.quantity + fill_qty
            symbol_state.quantity = new_qty
            symbol_state.cost_basis = new_cost if new_qty > ZERO else ZERO
            symbol_state.average_entry_price = (new_cost / new_qty) if new_qty > ZERO else None
            continue

        sell_qty = fill_qty
        available_qty = symbol_state.quantity if symbol_state.quantity > ZERO else ZERO
        matched_qty = sell_qty if sell_qty <= available_qty else available_qty
        avg_cost = _decimal_or_zero(symbol_state.average_entry_price)
        if matched_qty > ZERO:
            symbol_state.realized_pnl += ((fill_price - avg_cost) * matched_qty) - fee
            remaining_qty = available_qty - matched_qty
            symbol_state.quantity = remaining_qty
            symbol_state.cost_basis = (avg_cost * remaining_qty) if remaining_qty > ZERO else ZERO
            symbol_state.average_entry_price = avg_cost if remaining_qty > ZERO else None
        else:
            symbol_state.realized_pnl -= fee
            symbol_state.quantity = ZERO
            symbol_state.cost_basis = ZERO
            symbol_state.average_entry_price = None

    return {
        symbol: snapshot
        for symbol, snapshot in state.items()
        if snapshot.quantity != ZERO or snapshot.realized_pnl != ZERO
    }


def _get_latest_prices(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
    symbols: set[str],
) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    for symbol in sorted(symbols):
        row = (
            db.query(Candle)
            .filter(
                Candle.asset_class == asset_class,
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
            )
            .order_by(Candle.timestamp.desc(), Candle.id.desc())
            .first()
        )
        if row is not None and row.close is not None:
            prices[symbol] = _decimal_or_zero(row.close)
    return prices


def _persist_account_snapshot(
    db: Session,
    *,
    account_scope: str,
    venue: str,
    mode: str,
    equity: Decimal,
    cash: Decimal,
    buying_power: Decimal | None,
    realized_pnl: Decimal,
    unrealized_pnl: Decimal,
    as_of: datetime,
) -> AccountSnapshot:
    record = AccountSnapshot(
        account_scope=account_scope,
        venue=venue,
        mode=mode,
        equity=equity,
        cash=cash,
        buying_power=buying_power,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        as_of=as_of,
    )
    db.add(record)
    return record


def _rebuild_total_account_snapshot(db: Session, *, as_of: datetime) -> AccountSnapshot | None:
    latest_snapshots: list[AccountSnapshot] = []
    for scope in ("stock", "crypto"):
        snapshot = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.account_scope == scope)
            .order_by(AccountSnapshot.as_of.desc(), AccountSnapshot.id.desc())
            .first()
        )
        if snapshot is not None:
            latest_snapshots.append(snapshot)

    if not latest_snapshots:
        return None

    mode = latest_snapshots[0].mode if len({item.mode for item in latest_snapshots}) == 1 else "mixed"
    total = AccountSnapshot(
        account_scope="total",
        venue=AGGREGATE_VENUE,
        mode=mode,
        equity=sum((item.equity for item in latest_snapshots), ZERO),
        cash=sum((item.cash for item in latest_snapshots), ZERO),
        buying_power=sum((item.buying_power for item in latest_snapshots if item.buying_power is not None), ZERO),
        realized_pnl=sum((item.realized_pnl for item in latest_snapshots), ZERO),
        unrealized_pnl=sum((item.unrealized_pnl for item in latest_snapshots), ZERO),
        as_of=as_of,
    )
    db.add(total)
    return total


def _upsert_position_sync_state(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    mode: str,
    timeframe: str,
    last_synced_at: datetime,
    last_fill_at: datetime | None,
    position_count: int,
    open_order_count: int,
    mismatch_count: int,
    realized_pnl: Decimal,
    unrealized_pnl: Decimal,
    last_status: str,
    last_error: str | None,
) -> PositionSyncState:
    record = get_position_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        record = PositionSyncState(asset_class=asset_class, venue=venue, mode=mode, timeframe=timeframe)
        db.add(record)

    record.venue = venue
    record.mode = mode
    record.last_synced_at = _ensure_utc(last_synced_at)
    record.last_fill_at = _ensure_utc(last_fill_at)
    record.position_count = position_count
    record.open_order_count = open_order_count
    record.mismatch_count = mismatch_count
    record.realized_pnl = realized_pnl
    record.unrealized_pnl = unrealized_pnl
    record.last_status = last_status
    record.last_error = last_error
    return record


def _build_broker_open_order_key(order: OpenOrder) -> str:
    if order.order_id:
        return f"broker:{order.order_id}"
    if order.client_order_id:
        return f"client:{order.client_order_id}"
    return f"broker:{order.symbol}:{order.status}"


def _build_internal_open_order_key(order: ExecutionOrder) -> str:
    if order.broker_order_id:
        return f"broker:{order.broker_order_id}"
    if order.client_order_id:
        return f"client:{order.client_order_id}"
    return f"internal:{order.id}"


def _resolve_route_target(*, asset_class: str, mode: str) -> SyncRouteTarget:
    if asset_class == "stock" and mode == "live":
        return SyncRouteTarget(asset_class="stock", mode="live", venue="public", adapter_key="public_trading")
    if asset_class == "stock":
        return SyncRouteTarget(asset_class="stock", mode="paper", venue="alpaca", adapter_key="alpaca_stock_paper")
    if asset_class == "crypto" and mode == "live":
        return SyncRouteTarget(asset_class="crypto", mode="live", venue="kraken", adapter_key="kraken_trading")
    return SyncRouteTarget(asset_class="crypto", mode="paper", venue="alpaca", adapter_key="alpaca_crypto_paper")


def _resolve_execution_mode(db: Session, *, asset_class: str, settings: Settings) -> str:
    default_mode = _resolve_str_setting(db, "execution.default_mode", default=settings.default_mode).lower()
    if default_mode in {"paper", "live"}:
        return default_mode
    if default_mode == "mixed":
        per_asset_default = settings.stock_execution_mode if asset_class == "stock" else settings.crypto_execution_mode
        asset_mode = _resolve_str_setting(db, f"execution.{asset_class}.mode", default=per_asset_default).lower()
        return asset_mode if asset_mode in {"paper", "live"} else "paper"
    return "paper"


def _resolve_str_setting(db: Session, key: str, *, default: str) -> str:
    record = get_setting(db, key=key)
    if record is None or record.value is None or record.value == "":
        return default
    return str(record.value)


def _resolve_position_status(*, broker_qty: Decimal | None, internal_qty: Decimal | None) -> str:
    if broker_qty is None and internal_qty is None:
        return "matched"
    if broker_qty is None and (internal_qty or ZERO) != ZERO:
        return "internal_only"
    if internal_qty is None and (broker_qty or ZERO) != ZERO:
        return "broker_only"
    if broker_qty is None or internal_qty is None:
        return "matched"
    if abs(broker_qty - internal_qty) <= DECIMAL_TOLERANCE:
        return "matched"
    return "mismatch"


def _position_row_status(*, quantity: Decimal, reconciliation_status: str) -> str:
    if quantity <= ZERO and reconciliation_status == "matched":
        return "closed"
    if quantity <= ZERO:
        return "flat_mismatch"
    if reconciliation_status == "matched":
        return "open"
    return "open_mismatch"


def _build_position_mismatch_message(*, symbol: str, mismatch_type: str) -> str:
    mapping = {
        "position_missing_in_db": f"Broker reports an open {symbol} position that is missing from persisted fills.",
        "position_missing_at_broker": f"Persisted fills imply an open {symbol} position that the broker does not report.",
        "position_quantity_delta": f"Broker and persisted fills disagree on the open quantity for {symbol}.",
    }
    return mapping[mismatch_type]


def _build_order_mismatch_message(*, symbol: str, mismatch_type: str) -> str:
    mapping = {
        "open_order_missing_at_broker": f"Persisted execution shows an open {symbol} order that the broker does not report.",
        "open_order_missing_in_db": f"Broker reports an open {symbol} order that is missing from persisted execution rows.",
    }
    return mapping[mismatch_type]


def _decimal_or_zero(value: Decimal | None) -> Decimal:
    return value if value is not None else ZERO


def _decimal_or_none(value: Decimal | None) -> Decimal | None:
    return value if value is not None else None


def _max_dt(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if left >= right else right


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
