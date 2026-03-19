from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.models.core import AccountSnapshot, FeatureSnapshot, RiskSnapshot, RiskSyncState, StrategySnapshot
from backend.app.services.operator_service import create_audit_event
from backend.app.services.settings_service import get_setting
from backend.app.services.strategy_service import VALID_ASSET_CLASSES, list_current_strategy_snapshots

SINGLE_RISK_WRITER = "risk_worker"
RISK_SOURCE = "risk_engine"


@dataclass(slots=True, frozen=True)
class ComputedRiskRow:
    asset_class: str
    venue: str
    source: str
    symbol: str
    strategy_name: str
    direction: str
    timeframe: str
    candidate_timestamp: datetime
    computed_at: datetime
    status: str
    risk_profile: str
    decision_reason: str | None
    blocked_reasons: tuple[str, ...]
    account_equity: float | None
    account_cash: float | None
    entry_price: float | None
    stop_price: float | None
    take_profit_price: float | None
    stop_distance: float | None
    stop_distance_pct: float | None
    quantity: float | None
    notional_value: float | None
    deployment_pct: float | None
    cumulative_deployment_pct: float | None
    requested_risk_pct: float | None
    effective_risk_pct: float | None
    max_risk_pct: float | None
    risk_budget_amount: float | None
    projected_loss_amount: float | None
    projected_loss_pct: float | None
    fee_pct: float | None
    slippage_pct: float | None
    estimated_fees: float | None
    estimated_slippage: float | None
    strategy_readiness_score: float | None
    strategy_composite_score: float | None
    strategy_threshold_score: float | None
    payload: dict[str, Any]


@dataclass(slots=True, frozen=True)
class RiskPersistenceSummary:
    asset_class: str
    timeframe: str
    candidate_count: int
    accepted_count: int
    blocked_count: int
    last_candidate_at: datetime | None
    last_computed_at: datetime | None
    deployment_pct: float
    breaker_status: str | None
    skipped_reason: str | None = None


@dataclass(slots=True, frozen=True)
class RiskConfig:
    profile_name: str
    max_deployment_pct: float
    max_risk_pct: float
    default_risk_pct: float
    long_only_until_equity: float
    fee_pct: float
    slippage_pct: float
    soft_stop_pct: float
    hard_stop_pct: float
    total_hard_stop_pct: float


@dataclass(slots=True, frozen=True)
class AccountContext:
    total_equity: float | None
    asset_cash: float | None
    total_cash: float | None
    asset_pnl_pct: float | None
    total_pnl_pct: float | None
    asset_scope: str
    soft_breaker_active: bool
    hard_breaker_reason: str | None
    total_breaker_reason: str | None


def ensure_single_risk_writer(writer_name: str) -> None:
    if writer_name != SINGLE_RISK_WRITER:
        raise PermissionError(
            f"{writer_name!r} is not allowed to write risk rows. "
            f"Only {SINGLE_RISK_WRITER!r} may persist risk decisions.",
        )


def list_current_risk_snapshots(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[RiskSnapshot]:
    rows = (
        db.query(RiskSnapshot)
        .filter(
            RiskSnapshot.asset_class == asset_class,
            RiskSnapshot.timeframe == timeframe,
        )
        .order_by(
            RiskSnapshot.candidate_timestamp.desc(),
            RiskSnapshot.computed_at.desc(),
            RiskSnapshot.id.desc(),
        )
        .all()
    )
    current: dict[tuple[str, str], RiskSnapshot] = {}
    for row in rows:
        key = (row.symbol, row.strategy_name)
        if key not in current:
            current[key] = row
    return sorted(current.values(), key=lambda row: (row.symbol, row.strategy_name))


def get_risk_sync_state(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> RiskSyncState | None:
    return (
        db.query(RiskSyncState)
        .filter(
            RiskSyncState.asset_class == asset_class,
            RiskSyncState.timeframe == timeframe,
        )
        .one_or_none()
    )


def rebuild_risk_snapshots_for_asset_class(
    db: Session,
    *,
    writer_name: str,
    asset_class: str,
    venue: str,
    source: str,
    timeframe: str,
    computed_at: datetime | None = None,
    settings: Settings | None = None,
) -> RiskPersistenceSummary:
    ensure_single_risk_writer(writer_name)
    if asset_class not in VALID_ASSET_CLASSES:
        raise ValueError(f"Unsupported asset class: {asset_class}")

    runtime_settings = settings or get_settings()
    config = _load_risk_config(db, asset_class=asset_class, settings=runtime_settings)
    computed_time = _ensure_utc(computed_at) or datetime.now(UTC)
    previous_sync_state = get_risk_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    previous_breaker_status = previous_sync_state.breaker_status if previous_sync_state is not None else None
    strategy_rows = list_current_strategy_snapshots(db, asset_class=asset_class, timeframe=timeframe)
    if not strategy_rows:
        _upsert_risk_sync_state(
            db,
            asset_class=asset_class,
            venue=venue,
            timeframe=timeframe,
            last_computed_at=computed_time,
            last_candidate_at=None,
            candidate_count=0,
            accepted_count=0,
            blocked_count=0,
            deployment_pct=0.0,
            breaker_status=None,
            last_status="strategy_unavailable",
            last_error=None,
        )
        db.commit()
        return RiskPersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            candidate_count=0,
            accepted_count=0,
            blocked_count=0,
            last_candidate_at=None,
            last_computed_at=computed_time,
            deployment_pct=0.0,
            breaker_status=None,
            skipped_reason="strategy_unavailable",
        )

    account_context = _build_account_context(db, asset_class=asset_class, config=config)
    other_asset_deployment = _existing_other_asset_deployment(db, asset_class=asset_class, candidate_time=computed_time)
    total_equity = account_context.total_equity
    max_deployment_value = (total_equity or 0.0) * config.max_deployment_pct
    deployment_used = min(max(other_asset_deployment, 0.0), max_deployment_value)

    rows: list[ComputedRiskRow] = []
    accepted_count = 0
    blocked_count = 0
    last_candidate_at: datetime | None = None

    sorted_strategy_rows = sorted(
        strategy_rows,
        key=lambda row: (0 if row.status == "ready" else 1, -float(row.readiness_score), row.symbol, row.strategy_name),
    )

    for strategy_row in sorted_strategy_rows:
        candidate = _evaluate_strategy_row(
            db,
            strategy_row=strategy_row,
            account_context=account_context,
            config=config,
            computed_at=computed_time,
            deployment_used=deployment_used,
            source=source,
        )
        rows.append(candidate)
        if candidate.status == "accepted":
            accepted_count += 1
            deployment_used += candidate.notional_value or 0.0
        else:
            blocked_count += 1
        candidate_time = _ensure_utc(strategy_row.candidate_timestamp)
        if last_candidate_at is None or (candidate_time is not None and candidate_time > last_candidate_at):
            last_candidate_at = candidate_time

    final_deployment_pct = 0.0
    if total_equity and total_equity > 0:
        final_deployment_pct = min(deployment_used / total_equity, 1.0)

    for row in rows:
        existing = (
            db.query(RiskSnapshot)
            .filter(
                RiskSnapshot.asset_class == row.asset_class,
                RiskSnapshot.symbol == row.symbol,
                RiskSnapshot.strategy_name == row.strategy_name,
                RiskSnapshot.timeframe == row.timeframe,
                RiskSnapshot.candidate_timestamp == row.candidate_timestamp,
            )
            .one_or_none()
        )
        if existing is None:
            existing = RiskSnapshot(
                asset_class=row.asset_class,
                venue=row.venue,
                source=row.source,
                symbol=row.symbol,
                strategy_name=row.strategy_name,
                direction=row.direction,
                timeframe=row.timeframe,
                candidate_timestamp=row.candidate_timestamp,
            )
            db.add(existing)

        existing.venue = row.venue
        existing.source = row.source
        existing.direction = row.direction
        existing.computed_at = row.computed_at
        existing.status = row.status
        existing.risk_profile = row.risk_profile
        existing.decision_reason = row.decision_reason
        existing.blocked_reasons = list(row.blocked_reasons)
        existing.account_equity = row.account_equity
        existing.account_cash = row.account_cash
        existing.entry_price = row.entry_price
        existing.stop_price = row.stop_price
        existing.take_profit_price = row.take_profit_price
        existing.stop_distance = row.stop_distance
        existing.stop_distance_pct = row.stop_distance_pct
        existing.quantity = row.quantity
        existing.notional_value = row.notional_value
        existing.deployment_pct = row.deployment_pct
        existing.cumulative_deployment_pct = row.cumulative_deployment_pct
        existing.requested_risk_pct = row.requested_risk_pct
        existing.effective_risk_pct = row.effective_risk_pct
        existing.max_risk_pct = row.max_risk_pct
        existing.risk_budget_amount = row.risk_budget_amount
        existing.projected_loss_amount = row.projected_loss_amount
        existing.projected_loss_pct = row.projected_loss_pct
        existing.fee_pct = row.fee_pct
        existing.slippage_pct = row.slippage_pct
        existing.estimated_fees = row.estimated_fees
        existing.estimated_slippage = row.estimated_slippage
        existing.strategy_readiness_score = row.strategy_readiness_score
        existing.strategy_composite_score = row.strategy_composite_score
        existing.strategy_threshold_score = row.strategy_threshold_score
        existing.payload = row.payload

    breaker_status = account_context.total_breaker_reason or account_context.hard_breaker_reason
    if breaker_status is None and account_context.soft_breaker_active:
        breaker_status = f"{asset_class}_soft"

    last_status = "synced"
    skipped_reason: str | None = None
    if total_equity is None or total_equity <= 0:
        last_status = "account_unavailable"
        skipped_reason = "account_unavailable"
    elif breaker_status is not None and accepted_count == 0:
        last_status = "circuit_breaker_blocked"
        skipped_reason = breaker_status

    _upsert_risk_sync_state(
        db,
        asset_class=asset_class,
        venue=venue,
        timeframe=timeframe,
        last_computed_at=computed_time,
        last_candidate_at=last_candidate_at,
        candidate_count=len(rows),
        accepted_count=accepted_count,
        blocked_count=blocked_count,
        deployment_pct=final_deployment_pct,
        breaker_status=breaker_status,
        last_status=last_status,
        last_error=None,
    )
    if breaker_status is not None and breaker_status != previous_breaker_status:
        create_audit_event(
            db,
            event_type="audit.circuit_breaker_observed",
            severity="error" if "hard" in breaker_status or "total" in breaker_status else "warning",
            message=f"{asset_class.title()} circuit breaker observed as {breaker_status}.",
            payload={"asset_class": asset_class, "timeframe": timeframe, "breaker_status": breaker_status, "last_status": last_status},
        )
    elif previous_breaker_status is not None and breaker_status is None:
        create_audit_event(
            db,
            event_type="audit.circuit_breaker_cleared",
            severity="info",
            message=f"{asset_class.title()} circuit breaker has cleared.",
            payload={"asset_class": asset_class, "timeframe": timeframe, "previous_breaker_status": previous_breaker_status, "last_status": last_status},
        )
    db.commit()
    return RiskPersistenceSummary(
        asset_class=asset_class,
        timeframe=timeframe,
        candidate_count=len(rows),
        accepted_count=accepted_count,
        blocked_count=blocked_count,
        last_candidate_at=last_candidate_at,
        last_computed_at=computed_time,
        deployment_pct=final_deployment_pct,
        breaker_status=breaker_status,
        skipped_reason=skipped_reason,
    )


def _evaluate_strategy_row(
    db: Session,
    *,
    strategy_row: StrategySnapshot,
    account_context: AccountContext,
    config: RiskConfig,
    computed_at: datetime,
    deployment_used: float,
    source: str,
) -> ComputedRiskRow:
    feature = _latest_feature_snapshot(
        db,
        asset_class=strategy_row.asset_class,
        symbol=strategy_row.symbol,
        timeframe=strategy_row.timeframe,
    )
    entry_price = _float_or_none(feature.close if feature is not None else None)
    atr = _float_or_none(feature.atr_14 if feature is not None else None)

    blocked_reasons: list[str] = list(strategy_row.blocked_reasons or [])
    payload: dict[str, Any] = {
        "strategy_status": strategy_row.status,
        "strategy_decision_reason": strategy_row.decision_reason,
        "asset_pnl_pct": account_context.asset_pnl_pct,
        "total_pnl_pct": account_context.total_pnl_pct,
        "soft_breaker_active": account_context.soft_breaker_active,
    }

    if strategy_row.status != "ready":
        payload["upstream_blocked"] = True
        return _build_blocked_row(
            strategy_row=strategy_row,
            computed_at=computed_at,
            config=config,
            account_context=account_context,
            blocked_reasons=blocked_reasons or ["strategy_blocked_upstream"],
            payload=payload,
            source=source,
            entry_price=entry_price,
        )

    if account_context.total_breaker_reason is not None:
        blocked_reasons.append(account_context.total_breaker_reason)
    if account_context.hard_breaker_reason is not None:
        blocked_reasons.append(account_context.hard_breaker_reason)
    if strategy_row.direction != "long" and (account_context.total_equity or 0.0) <= config.long_only_until_equity:
        blocked_reasons.append("long_only_until_2500")
    if account_context.total_equity is None or account_context.total_equity <= 0:
        blocked_reasons.append("account_snapshot_unavailable")
    if entry_price is None or entry_price <= 0:
        blocked_reasons.append("entry_price_unavailable")

    use_contract_fixed_exits = strategy_row.asset_class == "stock" and strategy_row.strategy_name == "htf_reclaim_long"
    stop_distance = _derive_stop_distance(asset_class=strategy_row.asset_class, strategy_name=strategy_row.strategy_name, entry_price=entry_price, atr=atr)
    stop_price = (entry_price - stop_distance) if entry_price is not None and stop_distance is not None else None
    stop_distance_pct = (stop_distance / entry_price) if entry_price and stop_distance is not None and entry_price > 0 else None
    if stop_distance is None or stop_distance <= 0:
        blocked_reasons.append("stop_distance_unavailable")

    # --- AI research hint injection ---
    # When the universe was seeded by the premarket AI scan, each symbol
    # carries SL/TP levels in the strategy_row payload (propagated from
    # UniverseSymbolRecord.payload via feature/regime/strategy pipelines).
    # Override ATR-derived stop with the AI-suggested level when valid;
    # always capture take_profit_price so execution can submit bracket orders.
    _strat_payload: dict[str, Any] = strategy_row.payload or {}
    take_profit_price: float | None = None
    if use_contract_fixed_exits:
        payload["paper_contract_fixed_exit"] = True
        payload["paper_contract_rr_ratio"] = 1.5
        if stop_distance is not None and entry_price is not None:
            take_profit_price = round(entry_price + (1.5 * stop_distance), 8)
    else:
        _ai_sl = _float_or_none(_strat_payload.get("ai_stop_loss"))
        _ai_tp = _float_or_none(_strat_payload.get("ai_take_profit_primary"))
        if _ai_sl is not None and entry_price is not None and 0 < _ai_sl < entry_price:
            # Replace ATR stop only when AI level is tighter or equal (safer).
            _ai_stop_dist = entry_price - _ai_sl
            _ai_stop_pct  = _ai_stop_dist / entry_price
            if _ai_stop_pct <= 0.06:  # cap at 6 % — sanity guard
                stop_price       = _ai_sl
                stop_distance    = _ai_stop_dist
                stop_distance_pct = _ai_stop_pct
                payload["ai_stop_override"] = True
        if _ai_tp is not None and entry_price is not None and _ai_tp > entry_price:
            take_profit_price = _ai_tp
            payload["ai_take_profit_primary"] = str(_ai_tp)
        _ai_tp_stretch = _float_or_none(_strat_payload.get("ai_take_profit_stretch"))
        if _ai_tp_stretch is not None:
            payload["ai_take_profit_stretch"] = str(_ai_tp_stretch)
        if _strat_payload.get("ai_use_trail_stop"):
            payload["ai_use_trail_stop"] = True

        # --- Fallback TP: ATR-derived 2:1 reward when no AI pick exists ---
        # When the universe came from the screener fallback, there is no AI
        # take-profit level.  Synthesise one at 2× the stop distance so the
        # execution layer can still submit a bracket order and the stop_worker
        # has a clear exit target.  Only applied when:
        #   - take_profit_price is still None (AI didn't provide one)
        #   - stop_distance is valid (ATR-derived stop succeeded)
        #   - entry_price is known
        _FALLBACK_RR = 2.0  # reward-to-risk ratio for fallback universe
        if take_profit_price is None and stop_distance and entry_price:
            take_profit_price = round(entry_price + _FALLBACK_RR * stop_distance, 8)
            payload["fallback_take_profit"] = str(take_profit_price)
            payload["fallback_rr_ratio"] = _FALLBACK_RR

    requested_risk_pct = min(max(config.default_risk_pct, 0.0), config.max_risk_pct)
    effective_risk_pct = requested_risk_pct
    if account_context.soft_breaker_active:
        effective_risk_pct *= 0.5
    if stop_distance_pct is not None and stop_distance_pct >= 0.05:
        effective_risk_pct *= 0.75
    if getattr(strategy_row, "entry_policy", None) == "reduced":
        effective_risk_pct *= 0.75
    effective_risk_pct = min(max(effective_risk_pct, 0.0), config.max_risk_pct)

    fee_pct = config.fee_pct
    slippage_pct = config.slippage_pct
    roundtrip_fee_pct = fee_pct * 2.0
    roundtrip_slippage_pct = slippage_pct * 2.0

    if stop_distance_pct is not None:
        fee_threshold_pct = max(0.0030, stop_distance_pct * 0.35)
        slippage_threshold_pct = max(0.0025, stop_distance_pct * 0.30)
        if roundtrip_fee_pct > fee_threshold_pct:
            blocked_reasons.append("fees_too_high")
        if roundtrip_slippage_pct > slippage_threshold_pct:
            blocked_reasons.append("slippage_too_high")

    risk_budget_amount = (account_context.total_equity or 0.0) * effective_risk_pct
    max_budget_amount = (account_context.total_equity or 0.0) * config.max_risk_pct
    risk_budget_amount = min(risk_budget_amount, max_budget_amount)

    quantity: float | None = None
    notional_value: float | None = None
    deployment_pct: float | None = None
    cumulative_deployment_pct: float | None = None
    estimated_fees: float | None = None
    estimated_slippage: float | None = None
    projected_loss_amount: float | None = None
    projected_loss_pct: float | None = None

    if not blocked_reasons and entry_price and stop_distance and account_context.total_equity:
        per_unit_risk = stop_distance + (entry_price * (roundtrip_fee_pct + roundtrip_slippage_pct))
        if per_unit_risk <= 0:
            blocked_reasons.append("per_unit_risk_unavailable")
        else:
            remaining_deployment_value = max((account_context.total_equity * config.max_deployment_pct) - deployment_used, 0.0)
            if remaining_deployment_value <= 0:
                blocked_reasons.append("deployment_cap_reached")
            else:
                quantity_by_risk = risk_budget_amount / per_unit_risk if risk_budget_amount > 0 else 0.0
                quantity_by_deployment = remaining_deployment_value / entry_price
                if strategy_row.asset_class == "stock":
                    available_cash = account_context.asset_cash if account_context.asset_cash is not None else account_context.total_cash
                    if available_cash is None or available_cash <= 0:
                        blocked_reasons.append("stock_cash_unavailable")
                    else:
                        quantity_by_cash = available_cash / entry_price
                        quantity = float(floor(min(quantity_by_risk, quantity_by_deployment, quantity_by_cash)))
                        if quantity < 1:
                            blocked_reasons.append("insufficient_stock_cash")
                else:
                    quantity = _round_down(min(quantity_by_risk, quantity_by_deployment), 6)
                    if quantity <= 0:
                        blocked_reasons.append("insufficient_crypto_size")

                if quantity and quantity > 0 and not blocked_reasons:
                    notional_value = quantity * entry_price
                    estimated_fees = notional_value * roundtrip_fee_pct
                    estimated_slippage = notional_value * roundtrip_slippage_pct
                    projected_loss_amount = (quantity * stop_distance) + (estimated_fees or 0.0) + (estimated_slippage or 0.0)
                    projected_loss_pct = projected_loss_amount / account_context.total_equity
                    deployment_pct = notional_value / account_context.total_equity
                    cumulative_deployment_pct = min((deployment_used + notional_value) / account_context.total_equity, 1.0)

                    if projected_loss_pct > config.max_risk_pct + 1e-9:
                        blocked_reasons.append("max_risk_per_trade_exceeded")
                    if strategy_row.asset_class == "stock":
                        available_cash = account_context.asset_cash if account_context.asset_cash is not None else account_context.total_cash
                        if available_cash is not None and notional_value > available_cash + 1e-9:
                            blocked_reasons.append("stock_cash_limit_exceeded")
                    if notional_value > remaining_deployment_value + 1e-9:
                        blocked_reasons.append("deployment_cap_reached")

    payload.update(
        {
            "roundtrip_fee_pct": roundtrip_fee_pct,
            "roundtrip_slippage_pct": roundtrip_slippage_pct,
            "entry_policy": strategy_row.entry_policy,
        }
    )

    if blocked_reasons:
        return _build_blocked_row(
            strategy_row=strategy_row,
            computed_at=computed_at,
            config=config,
            account_context=account_context,
            blocked_reasons=blocked_reasons,
            payload=payload,
            source=source,
            entry_price=entry_price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            stop_distance=stop_distance,
            stop_distance_pct=stop_distance_pct,
            requested_risk_pct=requested_risk_pct,
            effective_risk_pct=effective_risk_pct,
            risk_budget_amount=risk_budget_amount,
            fee_pct=roundtrip_fee_pct,
            slippage_pct=roundtrip_slippage_pct,
            quantity=quantity,
            notional_value=notional_value,
            deployment_pct=deployment_pct,
            cumulative_deployment_pct=cumulative_deployment_pct,
            estimated_fees=estimated_fees,
            estimated_slippage=estimated_slippage,
            projected_loss_amount=projected_loss_amount,
            projected_loss_pct=projected_loss_pct,
        )

    payload["accepted"] = True
    return ComputedRiskRow(
        asset_class=strategy_row.asset_class,
        venue=strategy_row.venue,
        source=source,
        symbol=strategy_row.symbol,
        strategy_name=strategy_row.strategy_name,
        direction=strategy_row.direction,
        timeframe=strategy_row.timeframe,
        candidate_timestamp=_ensure_utc(strategy_row.candidate_timestamp) or computed_at,
        computed_at=computed_at,
        status="accepted",
        risk_profile=config.profile_name,
        decision_reason="risk_accepted",
        blocked_reasons=(),
        account_equity=account_context.total_equity,
        account_cash=account_context.asset_cash if strategy_row.asset_class == "stock" else account_context.total_cash,
        entry_price=entry_price,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
        stop_distance=stop_distance,
        stop_distance_pct=stop_distance_pct,
        quantity=quantity,
        notional_value=notional_value,
        deployment_pct=deployment_pct,
        cumulative_deployment_pct=cumulative_deployment_pct,
        requested_risk_pct=requested_risk_pct,
        effective_risk_pct=effective_risk_pct,
        max_risk_pct=config.max_risk_pct,
        risk_budget_amount=risk_budget_amount,
        projected_loss_amount=projected_loss_amount,
        projected_loss_pct=projected_loss_pct,
        fee_pct=roundtrip_fee_pct,
        slippage_pct=roundtrip_slippage_pct,
        estimated_fees=estimated_fees,
        estimated_slippage=estimated_slippage,
        strategy_readiness_score=_float_or_none(strategy_row.readiness_score),
        strategy_composite_score=_float_or_none(strategy_row.composite_score),
        strategy_threshold_score=_float_or_none(strategy_row.threshold_score),
        payload=payload,
    )


def _build_blocked_row(
    *,
    strategy_row: StrategySnapshot,
    computed_at: datetime,
    config: RiskConfig,
    account_context: AccountContext,
    blocked_reasons: list[str],
    payload: dict[str, Any],
    source: str = RISK_SOURCE,
    entry_price: float | None = None,
    stop_price: float | None = None,
    take_profit_price: float | None = None,
    stop_distance: float | None = None,
    stop_distance_pct: float | None = None,
    requested_risk_pct: float | None = None,
    effective_risk_pct: float | None = None,
    risk_budget_amount: float | None = None,
    fee_pct: float | None = None,
    slippage_pct: float | None = None,
    quantity: float | None = None,
    notional_value: float | None = None,
    deployment_pct: float | None = None,
    cumulative_deployment_pct: float | None = None,
    estimated_fees: float | None = None,
    estimated_slippage: float | None = None,
    projected_loss_amount: float | None = None,
    projected_loss_pct: float | None = None,
) -> ComputedRiskRow:
    reasons = tuple(dict.fromkeys(blocked_reasons))
    return ComputedRiskRow(
        asset_class=strategy_row.asset_class,
        venue=strategy_row.venue,
        source=source,
        symbol=strategy_row.symbol,
        strategy_name=strategy_row.strategy_name,
        direction=strategy_row.direction,
        timeframe=strategy_row.timeframe,
        candidate_timestamp=_ensure_utc(strategy_row.candidate_timestamp) or computed_at,
        computed_at=computed_at,
        status="blocked",
        risk_profile=config.profile_name,
        decision_reason=reasons[0] if reasons else strategy_row.decision_reason,
        blocked_reasons=reasons,
        account_equity=account_context.total_equity,
        account_cash=account_context.asset_cash if strategy_row.asset_class == "stock" else account_context.total_cash,
        entry_price=entry_price,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
        stop_distance=stop_distance,
        stop_distance_pct=stop_distance_pct,
        quantity=quantity,
        notional_value=notional_value,
        deployment_pct=deployment_pct,
        cumulative_deployment_pct=cumulative_deployment_pct,
        requested_risk_pct=requested_risk_pct,
        effective_risk_pct=effective_risk_pct,
        max_risk_pct=config.max_risk_pct,
        risk_budget_amount=risk_budget_amount,
        projected_loss_amount=projected_loss_amount,
        projected_loss_pct=projected_loss_pct,
        fee_pct=fee_pct,
        slippage_pct=slippage_pct,
        estimated_fees=estimated_fees,
        estimated_slippage=estimated_slippage,
        strategy_readiness_score=_float_or_none(strategy_row.readiness_score),
        strategy_composite_score=_float_or_none(strategy_row.composite_score),
        strategy_threshold_score=_float_or_none(strategy_row.threshold_score),
        payload=payload,
    )


def _build_account_context(db: Session, *, asset_class: str, config: RiskConfig) -> AccountContext:
    total = _latest_account_snapshot(db, account_scope="total")
    asset = _latest_account_snapshot(db, account_scope=asset_class)
    total_equity = _float_or_none((total.equity if total is not None else asset.equity if asset is not None else None))
    asset_cash = _float_or_none(asset.cash if asset is not None else None)
    total_cash = _float_or_none(total.cash if total is not None else None)
    asset_pnl_pct = _snapshot_pnl_pct(asset)
    total_pnl_pct = _snapshot_pnl_pct(total)

    hard_breaker_reason = None
    total_breaker_reason = None
    soft_breaker_active = False
    if total_pnl_pct is not None and total_pnl_pct <= config.total_hard_stop_pct:
        total_breaker_reason = "total_account_circuit_breaker_hard"
    if asset_pnl_pct is not None and asset_pnl_pct <= config.hard_stop_pct:
        hard_breaker_reason = f"{asset_class}_circuit_breaker_hard"
    elif asset_pnl_pct is not None and asset_pnl_pct <= config.soft_stop_pct:
        soft_breaker_active = True

    return AccountContext(
        total_equity=total_equity,
        asset_cash=asset_cash,
        total_cash=total_cash,
        asset_pnl_pct=asset_pnl_pct,
        total_pnl_pct=total_pnl_pct,
        asset_scope=asset_class,
        soft_breaker_active=soft_breaker_active,
        hard_breaker_reason=hard_breaker_reason,
        total_breaker_reason=total_breaker_reason,
    )


def _latest_account_snapshot(db: Session, *, account_scope: str) -> AccountSnapshot | None:
    return (
        db.query(AccountSnapshot)
        .filter(AccountSnapshot.account_scope == account_scope)
        .order_by(AccountSnapshot.as_of.desc(), AccountSnapshot.id.desc())
        .first()
    )


def _latest_feature_snapshot(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
) -> FeatureSnapshot | None:
    return (
        db.query(FeatureSnapshot)
        .filter(
            FeatureSnapshot.asset_class == asset_class,
            FeatureSnapshot.symbol == symbol,
            FeatureSnapshot.timeframe == timeframe,
        )
        .order_by(FeatureSnapshot.candle_timestamp.desc(), FeatureSnapshot.id.desc())
        .first()
    )


def _existing_other_asset_deployment(db: Session, *, asset_class: str, candidate_time: datetime) -> float:
    rows = (
        db.query(RiskSnapshot)
        .filter(
            RiskSnapshot.asset_class != asset_class,
            RiskSnapshot.status == "accepted",
        )
        .order_by(
            RiskSnapshot.candidate_timestamp.desc(),
            RiskSnapshot.computed_at.desc(),
            RiskSnapshot.id.desc(),
        )
        .all()
    )
    current: dict[tuple[str, str, str], RiskSnapshot] = {}
    for row in rows:
        key = (row.asset_class, row.symbol, row.strategy_name)
        if key not in current:
            current[key] = row
    return sum(float(row.notional_value or 0) for row in current.values() if _same_trade_day(row.candidate_timestamp, candidate_time))


def _same_trade_day(left: datetime | None, right: datetime | None) -> bool:
    left_utc = _ensure_utc(left)
    right_utc = _ensure_utc(right)
    if left_utc is None or right_utc is None:
        return False
    return left_utc.date() == right_utc.date()


def _derive_stop_distance(*, asset_class: str, strategy_name: str, entry_price: float | None, atr: float | None) -> float | None:
    if entry_price is None or entry_price <= 0:
        return None
    if asset_class == "stock" and strategy_name == "htf_reclaim_long":
        return round(atr, 8) if atr is not None and atr > 0 else None
    if asset_class == "stock":
        atr_multiple = 1.25
        min_pct = 0.008
    else:
        atr_multiple = 1.10
        min_pct = 0.012
    atr_component = (atr or 0.0) * atr_multiple
    pct_component = entry_price * min_pct
    distance = max(atr_component, pct_component)
    return round(distance, 8) if distance > 0 else None


def _load_risk_config(db: Session, *, asset_class: str, settings: Settings) -> RiskConfig:
    return RiskConfig(
        profile_name=_resolve_str_setting(db, "risk.default_profile", default="moderate"),
        max_deployment_pct=_resolve_float_setting(db, "risk.max_account_deployment_pct", default=settings.max_account_deployment_pct),
        max_risk_pct=_resolve_float_setting(db, "risk.max_per_trade_pct", default=settings.max_risk_per_trade_pct),
        default_risk_pct=_resolve_float_setting(db, "risk.default_per_trade_pct", default=settings.default_risk_per_trade_pct),
        long_only_until_equity=_resolve_float_setting(db, "risk.long_only_until_equity", default=settings.long_only_until_equity),
        fee_pct=_resolve_float_setting(db, f"risk.{asset_class}.fee_pct", default=settings.stock_fee_pct if asset_class == "stock" else settings.crypto_fee_pct),
        slippage_pct=_resolve_float_setting(db, f"risk.{asset_class}.slippage_pct", default=settings.stock_slippage_pct if asset_class == "stock" else settings.crypto_slippage_pct),
        soft_stop_pct=_resolve_float_setting(db, f"risk.{asset_class}.soft_stop_pct", default=settings.stock_soft_stop_pct if asset_class == "stock" else settings.crypto_soft_stop_pct),
        hard_stop_pct=_resolve_float_setting(db, f"risk.{asset_class}.hard_stop_pct", default=settings.stock_hard_stop_pct if asset_class == "stock" else settings.crypto_hard_stop_pct),
        total_hard_stop_pct=_resolve_float_setting(db, "risk.total_account.hard_stop_pct", default=settings.total_account_hard_stop_pct),
    )


def _resolve_float_setting(db: Session, key: str, *, default: float) -> float:
    record = get_setting(db, key=key)
    if record is None:
        return float(default)
    try:
        return float(record.value)
    except (TypeError, ValueError):
        return float(default)


def _resolve_str_setting(db: Session, key: str, *, default: str) -> str:
    record = get_setting(db, key=key)
    if record is None or not record.value:
        return default
    return str(record.value)


def _snapshot_pnl_pct(snapshot: AccountSnapshot | None) -> float | None:
    if snapshot is None or snapshot.equity is None or float(snapshot.equity) <= 0:
        return None
    pnl = float(snapshot.realized_pnl or 0) + float(snapshot.unrealized_pnl or 0)
    starting_equity = float(snapshot.equity) - pnl
    if starting_equity <= 0:
        return None
    return pnl / starting_equity


def _upsert_risk_sync_state(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    timeframe: str,
    last_computed_at: datetime,
    last_candidate_at: datetime | None,
    candidate_count: int,
    accepted_count: int,
    blocked_count: int,
    deployment_pct: float,
    breaker_status: str | None,
    last_status: str,
    last_error: str | None,
) -> RiskSyncState:
    record = get_risk_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        record = RiskSyncState(asset_class=asset_class, venue=venue, timeframe=timeframe)
        db.add(record)

    record.venue = venue
    record.last_computed_at = _ensure_utc(last_computed_at)
    record.last_candidate_at = _ensure_utc(last_candidate_at)
    record.candidate_count = candidate_count
    record.accepted_count = accepted_count
    record.blocked_count = blocked_count
    record.deployment_pct = deployment_pct
    record.breaker_status = breaker_status
    record.last_status = last_status
    record.last_error = last_error
    return record


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _round_down(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return floor(value * factor) / factor
