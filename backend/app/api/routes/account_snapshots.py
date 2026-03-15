from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.core.config import Settings, get_settings
from backend.app.models.core import AccountSnapshot
from backend.app.schemas.core import AccountSnapshotCreate, AccountSnapshotRead
from backend.app.services.adapter_registry import AdapterRegistry
from backend.app.services.settings_service import get_setting

router = APIRouter(prefix="/account-snapshots", tags=["account-snapshots"])
ZERO = Decimal("0")


@router.post("", response_model=AccountSnapshotRead, status_code=201)
def create_account_snapshot(
    payload: AccountSnapshotCreate,
    db: Session = Depends(get_db),
) -> AccountSnapshotRead:
    record = AccountSnapshot(**payload.model_dump(exclude_none=True))
    db.add(record)
    db.commit()
    db.refresh(record)
    return AccountSnapshotRead.model_validate(record)


@router.get("/latest/{account_scope}", response_model=AccountSnapshotRead | None)
def get_latest_account_snapshot(account_scope: str, db: Session = Depends(get_db)) -> AccountSnapshotRead | None:
    if account_scope not in {"total", "stock", "crypto"}:
        raise HTTPException(status_code=404, detail="Account scope not supported")

    record = _latest_snapshot(db, account_scope=account_scope)
    if record is not None:
        return AccountSnapshotRead.model_validate(record)

    fallback = _resolve_live_account_snapshot(db, account_scope=account_scope)
    if fallback is not None:
        return fallback

    return None


def _latest_snapshot(db: Session, *, account_scope: str) -> AccountSnapshot | None:
    return (
        db.query(AccountSnapshot)
        .filter(AccountSnapshot.account_scope == account_scope)
        .order_by(AccountSnapshot.as_of.desc(), AccountSnapshot.id.desc())
        .first()
    )


def _resolve_live_account_snapshot(db: Session, *, account_scope: str) -> AccountSnapshotRead | None:
    settings = get_settings()
    if account_scope == "total":
        stock_snapshot = _resolve_live_asset_snapshot(db, asset_class="stock", settings=settings)
        crypto_snapshot = _resolve_live_asset_snapshot(db, asset_class="crypto", settings=settings)
        rows = [row for row in (stock_snapshot, crypto_snapshot) if row is not None]
        if not rows:
            return None
        as_of = max((row.as_of for row in rows), default=datetime.now(UTC))
        mode = rows[0].mode if len({row.mode for row in rows}) == 1 else "mixed"
        return AccountSnapshotRead(
            id=0,
            account_scope="total",
            venue="aggregate",
            mode=mode,
            equity=sum((row.equity for row in rows), ZERO),
            cash=sum((row.cash for row in rows), ZERO),
            buying_power=sum((row.buying_power for row in rows if row.buying_power is not None), ZERO),
            realized_pnl=sum((row.realized_pnl for row in rows), ZERO),
            unrealized_pnl=sum((row.unrealized_pnl for row in rows), ZERO),
            as_of=as_of,
        )

    return _resolve_live_asset_snapshot(db, asset_class=account_scope, settings=settings)


def _resolve_live_asset_snapshot(db: Session, *, asset_class: str, settings: Settings) -> AccountSnapshotRead | None:
    mode = _resolve_execution_mode(db, asset_class=asset_class, settings=settings)
    adapter_key = _adapter_key_for(asset_class=asset_class, mode=mode)
    registry = AdapterRegistry(settings)
    adapter_factory = getattr(registry, adapter_key, None)
    if adapter_factory is None:
        return None

    latest_asset_snapshot = _latest_snapshot(db, account_scope=asset_class)
    try:
        adapter = adapter_factory()
        account_state = adapter.get_account_state()
    except Exception:
        return None
    finally:
        close_method = getattr(locals().get("adapter"), "close", None)
        if callable(close_method):
            close_method()

    return AccountSnapshotRead(
        id=latest_asset_snapshot.id if latest_asset_snapshot is not None else 0,
        account_scope=asset_class,
        venue=account_state.venue,
        mode=account_state.mode,
        equity=account_state.equity,
        cash=account_state.cash,
        buying_power=account_state.buying_power,
        realized_pnl=latest_asset_snapshot.realized_pnl if latest_asset_snapshot is not None else ZERO,
        unrealized_pnl=latest_asset_snapshot.unrealized_pnl if latest_asset_snapshot is not None else ZERO,
        as_of=datetime.now(UTC),
    )


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


def _adapter_key_for(*, asset_class: str, mode: str) -> str:
    if asset_class == "stock" and mode == "live":
        return "public_trading"
    if asset_class == "stock":
        return "alpaca_stock_paper"
    if asset_class == "crypto" and mode == "live":
        return "kraken_trading"
    return "alpaca_crypto_paper"
