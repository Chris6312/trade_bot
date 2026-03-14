from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.services.adapter_registry import AdapterRegistry
from backend.app.services.ai_universe_service import AIUniverseService
from backend.app.services.universe_service import (
    UniverseSymbolRecord,
    crypto_universe_records,
    default_snapshot_path,
    ensure_utc,
    get_universe_run,
    list_universe_symbols,
    normalize_stock_candidates,
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
        registry: AdapterRegistry | None = None,
        settings: Settings | None = None,
        ai_service: AIUniverseService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.registry = registry or AdapterRegistry(self.settings)
        self.ai_service = ai_service or AIUniverseService(self.settings)
        self._ny_tz = ZoneInfo("America/New_York")

    def resolve_stock_universe(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> UniverseResolutionSummary:
        resolved_at = ensure_utc(now) or datetime.now(UTC)
        trade_date = trading_date_for_now(resolved_at)
        current_run = get_universe_run(self.db, asset_class="stock", trade_date=trade_date)

        if self.settings.ai_run_once_daily and not force:
            cached = self._load_cached_stock_universe(run=current_run, trade_date=trade_date)
            if cached is not None:
                return cached

        fallback_candidates, asset_metadata = self._fetch_fallback_candidates()
        if not fallback_candidates:
            persist_universe_run(
                self.db,
                asset_class="stock",
                venue="alpaca",
                trade_date=trade_date,
                source="fallback",
                status="failed",
                symbols=[],
                resolved_at=resolved_at,
                last_error="fallback_source_returned_no_candidates",
                payload={"candidate_count": 0},
            )
            raise RuntimeError("fallback_source_returned_no_candidates")

        ai_error: str | None = None
        ai_source_requested = self.settings.stock_universe_source.lower() == "ai"
        if ai_source_requested and self.settings.ai_enabled:
            try:
                ranked = self.ai_service.rank_candidates(fallback_candidates)
                ranked_candidates = self._merge_ai_rankings(fallback_candidates, ranked)
                selected = normalize_stock_candidates(
                    candidates=ranked_candidates,
                    asset_metadata=asset_metadata,
                    max_size=self.settings.stock_universe_max_size,
                    source="ai",
                    venue="alpaca",
                )
                if selected:
                    snapshot_path = self._persist_and_snapshot(
                        asset_class="stock",
                        venue="alpaca",
                        source="ai",
                        trade_date=trade_date,
                        symbols=selected,
                        resolved_at=resolved_at,
                        payload={"candidate_count": len(fallback_candidates), "resolution": "ai"},
                    )
                    logger.info(
                        "stock_universe_resolved_ai",
                        extra={"trade_date": trade_date.isoformat(), "symbol_count": len(selected)},
                    )
                    return UniverseResolutionSummary(
                        asset_class="stock",
                        trade_date=trade_date.isoformat(),
                        source="ai",
                        symbols=tuple(item.symbol for item in selected),
                        snapshot_path=snapshot_path,
                    )
                ai_error = "ai_returned_no_eligible_symbols"
            except Exception as exc:
                ai_error = f"{type(exc).__name__}: {exc}"
                logger.warning("stock_universe_ai_failed", extra={"trade_date": trade_date.isoformat(), "error": ai_error})

        fallback_symbols = normalize_stock_candidates(
            candidates=fallback_candidates,
            asset_metadata=asset_metadata,
            max_size=self.settings.stock_universe_max_size,
            source="fallback",
            venue="alpaca",
        )
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
                last_error=ai_error or "fallback_filtering_removed_all_symbols",
                payload={"candidate_count": len(fallback_candidates), "resolution": "fallback"},
            )
            raise RuntimeError(ai_error or "fallback_filtering_removed_all_symbols")

        snapshot_path = self._persist_and_snapshot(
            asset_class="stock",
            venue="alpaca",
            source="fallback",
            trade_date=trade_date,
            symbols=fallback_symbols,
            resolved_at=resolved_at,
            last_error=ai_error,
            payload={"candidate_count": len(fallback_candidates), "resolution": "fallback"},
        )
        logger.info(
            "stock_universe_resolved_fallback",
            extra={"trade_date": trade_date.isoformat(), "symbol_count": len(fallback_symbols), "ai_error": ai_error},
        )
        return UniverseResolutionSummary(
            asset_class="stock",
            trade_date=trade_date.isoformat(),
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

    def _fetch_fallback_candidates(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        adapter = self.registry.alpaca_stock_screener()
        rows = adapter.fetch_most_active(top=max(self.settings.stock_universe_max_size * 2, 50), by="volume")
        metadata: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            try:
                metadata[symbol] = adapter.fetch_asset(symbol=symbol)
            except Exception as exc:
                logger.info("alpaca_asset_lookup_skipped", extra={"symbol": symbol, "error": str(exc)})
                metadata[symbol] = {}
        return rows, metadata

    @staticmethod
    def _merge_ai_rankings(
        base_candidates: list[dict[str, Any]],
        rankings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ranking_map = {str(item.get("symbol") or "").upper(): item for item in rankings}
        merged: list[dict[str, Any]] = []
        for candidate in base_candidates:
            symbol = str(candidate.get("symbol") or "").upper()
            merged_row = dict(candidate)
            if symbol in ranking_map:
                merged_row.update(ranking_map[symbol])
            merged.append(merged_row)
        return merged

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
