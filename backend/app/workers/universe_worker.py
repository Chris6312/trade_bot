from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.settings_service import resolve_bool_setting, resolve_int_setting, resolve_str_setting
from backend.app.common.adapters.utils import dt_to_et_str
from backend.app.workers.ai_research_worker import list_ai_research_picks
from backend.app.services.universe_service import (
    FALLBACK_UNIVERSE_ALLOWLIST,
    FALLBACK_UNIVERSE_MAX_SIZE,
    UniverseSymbolRecord,
    crypto_universe_records,
    default_snapshot_path,
    ensure_utc,
    get_universe_run,
    list_universe_symbols,
    persist_universe_run,
    read_snapshot,
    stock_universe_ready,
    trading_date_for_now,
    write_snapshot,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class UniverseResolutionSummary:
    asset_class: str
    trade_date: str
    source: str
    symbols: tuple[str, ...]
    snapshot_path: str | None
    from_cache: bool = False
    skipped_reason: str | None = None


class UniverseWorker:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self._ny_tz = ZoneInfo("America/New_York")

    def resolve_stock_universe(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> UniverseResolutionSummary:
        """Build the stock watchlist for today.

        Priority order:
          1. Cache  – already resolved today and ``force=False``.
          2. AI research picks – from the premarket scan (``ai_research_picks``
             table, written by AiResearchWorker).
          3. Fallback – hard-coded 25-symbol allowlist built directly from
             FALLBACK_UNIVERSE_ALLOWLIST.  No screener API call is made.
        """
        resolved_at = ensure_utc(now) or datetime.now(UTC)
        trade_date = trading_date_for_now(resolved_at)
        trade_date_str = trade_date.isoformat()
        current_run = get_universe_run(self.db, asset_class="stock", trade_date=trade_date)

        # --- 1. Cache hit ---
        if self._ai_run_once_daily() and not force:
            cached = self._load_cached_stock_universe(run=current_run, trade_date=trade_date)
            if cached is not None:
                return cached

        # --- 2. AI research picks ---
        ai_error: str | None = None
        if self._ai_enabled() and self._stock_universe_source() == "ai":
            try:
                research_picks = list_ai_research_picks(self.db, trade_date_str=trade_date_str)
                if research_picks:
                    venue = research_picks[0].venue or "alpaca"
                    selected: list[UniverseSymbolRecord] = []
                    for rank, pick in enumerate(research_picks, start=1):
                        selected.append(
                            UniverseSymbolRecord(
                                symbol=pick.symbol,
                                rank=rank,
                                source="ai_research",
                                venue=venue,
                                asset_class="stock",
                                selection_reason=pick.catalyst[:120] if pick.catalyst else None,
                                payload={
                                    "ai_entry_zone_low":      str(pick.entry_zone_low)      if pick.entry_zone_low      else None,
                                    "ai_entry_zone_high":     str(pick.entry_zone_high)     if pick.entry_zone_high     else None,
                                    "ai_stop_loss":           str(pick.stop_loss)           if pick.stop_loss           else None,
                                    "ai_take_profit_primary": str(pick.take_profit_primary) if pick.take_profit_primary else None,
                                    "ai_take_profit_stretch": str(pick.take_profit_stretch) if pick.take_profit_stretch else None,
                                    "ai_use_trail_stop":      pick.use_trail_stop,
                                    "ai_is_bonus_pick":       pick.is_bonus_pick,
                                    "ai_risk_reward_note":    pick.risk_reward_note,
                                    "ai_scanned_at":          dt_to_et_str(pick.scanned_at),
                                },
                            )
                        )

                    # Cap at exactly the AI picks returned — never pad to max_size.
                    ai_cap = min(self._stock_universe_max_size(), len(selected))
                    selected = selected[:ai_cap]

                    # Clear any stale run for today (e.g. a fallback seeded by
                    # _ensure_universe_ready) so AI picks fully overwrite it.
                    stale_run = get_universe_run(self.db, asset_class="stock", trade_date=trade_date)
                    if stale_run is not None:
                        stale_run.constituents.clear()
                        self.db.flush()

                    snapshot_path = self._persist_and_snapshot(
                        asset_class="stock",
                        venue=venue,
                        source="ai_research",
                        trade_date=trade_date,
                        symbols=selected,
                        resolved_at=resolved_at,
                        payload={
                            "resolution": "ai_research",
                            "pick_count": len(selected),
                            "trade_date": trade_date_str,
                        },
                    )
                    logger.info(
                        "stock_universe_resolved_ai_research",
                        extra={"trade_date": trade_date_str, "symbol_count": len(selected), "venue": venue},
                    )
                    return UniverseResolutionSummary(
                        asset_class="stock",
                        trade_date=trade_date_str,
                        source="ai_research",
                        symbols=tuple(item.symbol for item in selected),
                        snapshot_path=snapshot_path,
                    )
                ai_error = "ai_research_no_picks_for_trade_date"
                logger.warning("stock_universe_ai_research_empty", extra={"trade_date": trade_date_str})
            except Exception as exc:
                ai_error = f"{type(exc).__name__}: {exc}"
                logger.warning("stock_universe_ai_research_failed", extra={"trade_date": trade_date_str, "error": ai_error})

        # --- 3. Fallback: hard-coded allowlist (no screener API call) ---
        fallback_symbols = self._build_fallback_universe()
        if not fallback_symbols:
            persist_universe_run(
                self.db,
                asset_class="stock",
                venue="alpaca",
                trade_date=trade_date,
                source="fallback",
                status="failed",
                symbols=[],
                resolved_at=resolved_at,
                last_error=ai_error or "fallback_allowlist_empty",
                payload={"resolution": "fallback"},
            )
            raise RuntimeError(ai_error or "fallback_allowlist_empty")

        snapshot_path = self._persist_and_snapshot(
            asset_class="stock",
            venue="alpaca",
            source="fallback",
            trade_date=trade_date,
            symbols=fallback_symbols,
            resolved_at=resolved_at,
            last_error=ai_error,
            payload={"resolution": "fallback", "symbol_count": len(fallback_symbols)},
        )
        logger.info(
            "stock_universe_resolved_fallback",
            extra={
                "trade_date": trade_date_str,
                "symbol_count": len(fallback_symbols),
                "ai_error": ai_error,
            },
        )
        return UniverseResolutionSummary(
            asset_class="stock",
            trade_date=trade_date_str,
            source="fallback",
            symbols=tuple(item.symbol for item in fallback_symbols),
            snapshot_path=snapshot_path,
        )

    def resolve_crypto_universe(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> UniverseResolutionSummary:
        resolved_at = ensure_utc(now) or datetime.now(UTC)
        trade_date = trading_date_for_now(resolved_at)
        current_run = get_universe_run(self.db, asset_class="crypto", trade_date=trade_date)
        if current_run is not None and current_run.status == "resolved" and not force:
            symbols = tuple(item.symbol for item in current_run.constituents)
            return UniverseResolutionSummary(
                asset_class="crypto",
                trade_date=trade_date.isoformat(),
                source=current_run.source,
                symbols=symbols,
                snapshot_path=current_run.snapshot_path,
                from_cache=True,
            )

        symbols = crypto_universe_records()
        snapshot_path = self._persist_and_snapshot(
            asset_class="crypto",
            venue="kraken",
            source="static",
            trade_date=trade_date,
            symbols=symbols,
            resolved_at=resolved_at,
            payload={"resolution": "static_top_15"},
        )
        return UniverseResolutionSummary(
            asset_class="crypto",
            trade_date=trade_date.isoformat(),
            source="static",
            symbols=tuple(item.symbol for item in symbols),
            snapshot_path=snapshot_path,
        )

    def require_stock_universe_ready(self, *, now: datetime | None = None) -> tuple[str, ...]:
        trade_date = trading_date_for_now(now)
        if not stock_universe_ready(self.db, trade_date=trade_date):
            raise RuntimeError("stock_universe_unresolved")
        return tuple(item.symbol for item in list_universe_symbols(self.db, asset_class="stock", trade_date=trade_date))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_fallback_universe(self) -> list[UniverseSymbolRecord]:
        """Build the static fallback watchlist from FALLBACK_UNIVERSE_ALLOWLIST.

        Symbols are sorted alphabetically for deterministic ordering and
        capped at FALLBACK_UNIVERSE_MAX_SIZE.  No broker API call is made.
        """
        max_size = min(self._stock_universe_max_size(), FALLBACK_UNIVERSE_MAX_SIZE)
        sorted_symbols = sorted(FALLBACK_UNIVERSE_ALLOWLIST)[:max_size]
        return [
            UniverseSymbolRecord(
                symbol=symbol,
                rank=rank,
                source="fallback",
                venue="alpaca",
                asset_class="stock",
                selection_reason="hard_coded_fallback_allowlist",
                payload={},
            )
            for rank, symbol in enumerate(sorted_symbols, start=1)
        ]

    def _stock_universe_source(self) -> str:
        value = resolve_str_setting(self.db, "stock_universe_source", default=self.settings.stock_universe_source).lower()
        return value if value in {"ai", "fallback"} else self.settings.stock_universe_source.lower()

    def _stock_universe_max_size(self) -> int:
        return max(1, resolve_int_setting(self.db, "stock_universe_max_size", default=self.settings.stock_universe_max_size))

    def _ai_enabled(self) -> bool:
        return resolve_bool_setting(self.db, "ai_enabled", default=self.settings.ai_enabled)

    def _ai_run_once_daily(self) -> bool:
        return resolve_bool_setting(self.db, "ai_run_once_daily", default=self.settings.ai_run_once_daily)

    def _load_cached_stock_universe(
        self,
        *,
        run: Any,
        trade_date: Any,
    ) -> UniverseResolutionSummary | None:
        if run is None or run.status != "resolved":
            return None

        if run.snapshot_path:
            snapshot_symbols = read_snapshot(path=run.snapshot_path)
            if snapshot_symbols:
                return UniverseResolutionSummary(
                    asset_class="stock",
                    trade_date=trade_date.isoformat(),
                    source=run.source,
                    symbols=tuple(item.symbol for item in snapshot_symbols),
                    snapshot_path=run.snapshot_path,
                    from_cache=True,
                    skipped_reason="already_resolved_today",
                )

        if run.constituents:
            snapshot_path = self._persist_snapshot_only(
                asset_class="stock",
                trade_date=trade_date,
                symbols=[
                    UniverseSymbolRecord(
                        symbol=item.symbol,
                        rank=item.rank,
                        source=item.source,
                        venue=item.venue,
                        asset_class=item.asset_class,
                        selection_reason=item.selection_reason,
                        payload=item.payload or {},
                    )
                    for item in run.constituents
                ],
                resolved_at=run.resolved_at or datetime.now(UTC),
            )
            run.snapshot_path = snapshot_path
            self.db.commit()
            return UniverseResolutionSummary(
                asset_class="stock",
                trade_date=trade_date.isoformat(),
                source=run.source,
                symbols=tuple(item.symbol for item in run.constituents),
                snapshot_path=snapshot_path,
                from_cache=True,
                skipped_reason="already_resolved_today",
            )
        return None

    def _persist_and_snapshot(
        self,
        *,
        asset_class: str,
        venue: str,
        source: str,
        trade_date: Any,
        symbols: list[UniverseSymbolRecord],
        resolved_at: datetime,
        payload: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> str:
        snapshot_path = self._persist_snapshot_only(
            asset_class=asset_class,
            trade_date=trade_date,
            symbols=symbols,
            resolved_at=resolved_at,
        )
        persist_universe_run(
            self.db,
            asset_class=asset_class,
            venue=venue,
            trade_date=trade_date,
            source=source,
            status="resolved",
            symbols=symbols,
            snapshot_path=snapshot_path,
            resolved_at=resolved_at,
            last_error=last_error,
            payload=payload,
        )
        return snapshot_path

    def _persist_snapshot_only(
        self,
        *,
        asset_class: str,
        trade_date: Any,
        symbols: list[UniverseSymbolRecord],
        resolved_at: datetime,
    ) -> str:
        path = default_snapshot_path(asset_class=asset_class, trade_date=trade_date)
        return write_snapshot(path=path, symbols=symbols, trade_date=trade_date, resolved_at=resolved_at)