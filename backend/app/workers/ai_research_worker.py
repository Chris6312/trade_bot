"""ai_research_worker.py

Orchestrates the premarket AI research scan.

Schedule:
  - Runs once per NYSE trading day between ``ai_premarket_time_et`` (default
    08:40) and 09:00 ET, on the first eligible call in that window.
  - Also fires at startup if the current time falls inside the window, so a
    late-start bot does not miss the scan.
  - NYSE holidays (full-day closures) are skipped automatically via
    ``pandas_market_calendars``.

Pipeline position:
  AI research → universe → candle → feature → regime → strategy → risk →
  execution → stop → position

Cash source:
  Reads the latest ``AccountSnapshot`` from the DB.  Falls back to ``None``
  (prompt still runs, cash field just says "unknown").

Broker venue:
  - paper / alpaca  → venue = "alpaca"
  - live (stock)    → venue = "public"  (Public.com)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time as clock_time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.models.core import AccountSnapshot, AiResearchPick
from backend.app.common.adapters.utils import dt_to_et_str
from backend.app.services.ai_research_service import AiResearchPickResult, AiResearchService
from backend.app.services.settings_service import resolve_bool_setting, resolve_str_setting
from backend.app.services.universe_service import trading_date_for_now

logger = logging.getLogger(__name__)

_NY_TZ = ZoneInfo("America/New_York")

# How far before 09:00 ET we start accepting the scan (minutes).
_SCAN_WINDOW_END_ET = clock_time(9, 0)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AiResearchRunSummary:
    status: str  # "executed" | "skipped" | "failed"
    trade_date: str
    pick_count: int = 0
    skipped_reason: str | None = None
    error: str | None = None
    venue: str = "alpaca"


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class AiResearchWorker:
    """Thin orchestrator: guards schedule/holidays, fetches cash, calls service,
    persists picks."""

    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        ai_service: AiResearchService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.ai_service = ai_service or AiResearchService(self.settings)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_if_due(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> AiResearchRunSummary:
        """Run the premarket scan if the schedule and guards allow.

        ``force=True`` bypasses the time-window and already-ran checks
        (used by the UI / manual trigger endpoint).
        """
        utc_now = (now or datetime.now(UTC)).astimezone(UTC)
        et_now = utc_now.astimezone(_NY_TZ)
        trade_date = trading_date_for_now(utc_now)
        trade_date_str = trade_date.isoformat()
        venue = self._resolve_venue()

        if not force:
            skip = self._should_skip(et_now=et_now, trade_date=trade_date, trade_date_str=trade_date_str)
            if skip:
                return AiResearchRunSummary(
                    status="skipped",
                    trade_date=trade_date_str,
                    skipped_reason=skip,
                    venue=venue,
                )

        cash = self._fetch_available_cash(venue=venue)

        try:
            picks = self.ai_service.run_premarket_scan(cash_available=cash, now=et_now)
        except Exception as exc:
            logger.exception("ai_research_scan_failed")
            return AiResearchRunSummary(
                status="failed",
                trade_date=trade_date_str,
                error=f"{type(exc).__name__}: {exc}",
                venue=venue,
            )

        if not picks:
            return AiResearchRunSummary(
                status="failed",
                trade_date=trade_date_str,
                error="ai_returned_no_picks",
                venue=venue,
            )

        count = self._persist_picks(
            picks=picks,
            trade_date_str=trade_date_str,
            scanned_at=utc_now,
            cash=cash,
            venue=venue,
        )

        logger.info(
            "ai_research_picks_persisted",
            extra={"trade_date": trade_date_str, "pick_count": count, "venue": venue, "scanned_at_et": dt_to_et_str(utc_now)},
        )
        return AiResearchRunSummary(
            status="executed",
            trade_date=trade_date_str,
            pick_count=count,
            venue=venue,
        )

    # ------------------------------------------------------------------
    # Schedule guards
    # ------------------------------------------------------------------

    def _should_skip(
        self,
        *,
        et_now: datetime,
        trade_date: date,
        trade_date_str: str,
    ) -> str | None:
        """Return a skip-reason string, or None if the scan should proceed."""
        # Weekend
        if et_now.weekday() >= 5:
            return "weekend"

        # NYSE full-day holiday
        if not _is_nyse_trading_day(trade_date):
            return "nyse_holiday"

        # Not yet inside the scan window
        trigger = self._parse_trigger_time()
        current_t = et_now.time().replace(tzinfo=None)
        if current_t < trigger:
            return f"before_scan_window_{trigger.strftime('%H:%M')}_ET"

        # Past 09:00 — too late for a premarket scan
        if current_t >= _SCAN_WINDOW_END_ET:
            return "after_scan_window_09:00_ET"

        # Already ran today
        if self._already_ran_today(trade_date_str):
            return "already_ran_today"

        return None

    def _parse_trigger_time(self) -> clock_time:
        raw = str(self.settings.ai_premarket_time_et or "08:40")
        try:
            h, m = raw.split(":", 1)
            return clock_time(int(h), int(m))
        except Exception:
            return clock_time(8, 40)

    def _already_ran_today(self, trade_date_str: str) -> bool:
        row = (
            self.db.execute(
                select(AiResearchPick.id)
                .where(AiResearchPick.trade_date == trade_date_str)
                .limit(1)
            ).first()
        )
        return row is not None

    # ------------------------------------------------------------------
    # Cash resolution
    # ------------------------------------------------------------------

    def _fetch_available_cash(self, *, venue: str) -> Decimal | None:
        """Pull cash from the latest AccountSnapshot for this venue/mode."""
        # Determine mode from venue
        mode = "live" if venue == "public" else "paper"
        asset_class = "stock"

        # account_scope pattern used in position_worker: "{asset_class}_{mode}"
        account_scope = f"{asset_class}_{mode}"

        row = self.db.execute(
            select(AccountSnapshot.cash)
            .where(AccountSnapshot.account_scope == account_scope)
            .order_by(desc(AccountSnapshot.as_of))
            .limit(1)
        ).first()

        if row is None:
            logger.warning(
                "ai_research_cash_not_found",
                extra={"account_scope": account_scope},
            )
            return None

        try:
            return Decimal(str(row.cash))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Venue resolution
    # ------------------------------------------------------------------

    def _resolve_venue(self) -> str:
        """Return 'public' when stock execution is live, else 'alpaca'."""
        mode = resolve_str_setting(
            self.db,
            "stock_execution_mode",
            default=self.settings.stock_execution_mode,
        ).lower()
        return "public" if mode == "live" else "alpaca"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_picks(
        self,
        *,
        picks: list[AiResearchPickResult],
        trade_date_str: str,
        scanned_at: datetime,
        cash: Decimal | None,
        venue: str,
    ) -> int:
        """Upsert picks; on symbol conflict for the same trade_date, overwrite."""
        count = 0
        for pick in picks:
            if not pick.symbol:
                continue

            values: dict[str, Any] = {
                "trade_date": trade_date_str,
                "scanned_at": scanned_at,
                "symbol": pick.symbol,
                "catalyst": pick.catalyst,
                "approximate_price": pick.approximate_price,
                "entry_zone_low": pick.entry_zone_low,
                "entry_zone_high": pick.entry_zone_high,
                "stop_loss": pick.stop_loss,
                "take_profit_primary": pick.take_profit_primary,
                "take_profit_stretch": pick.take_profit_stretch,
                "use_trail_stop": pick.use_trail_stop,
                "position_size_dollars": pick.position_size_dollars,
                "risk_reward_note": pick.risk_reward_note,
                "is_bonus_pick": pick.is_bonus_pick,
                "account_cash_at_scan": cash,
                "venue": venue,
                "raw_payload": pick.raw,
            }

            # Use INSERT … ON CONFLICT UPDATE for Postgres; fall back to
            # a delete+insert for SQLite (used in tests).
            bind = self.db.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                stmt = (
                    pg_insert(AiResearchPick)
                    .values(**values)
                    .on_conflict_do_update(
                        constraint="uq_ai_research_picks_date_symbol",
                        set_={k: v for k, v in values.items() if k not in ("trade_date", "symbol")},
                    )
                )
                self.db.execute(stmt)
            else:
                # SQLite path (tests)
                existing = self.db.execute(
                    select(AiResearchPick).where(
                        AiResearchPick.trade_date == trade_date_str,
                        AiResearchPick.symbol == pick.symbol,
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    for k, v in values.items():
                        setattr(existing, k, v)
                else:
                    self.db.add(AiResearchPick(**values))

            count += 1

        self.db.commit()
        return count


# ------------------------------------------------------------------
# NYSE holiday helper
# ------------------------------------------------------------------

def _is_nyse_trading_day(d: date) -> bool:
    """Return True if *d* is a NYSE session day (not a holiday or weekend).

    ``pandas_market_calendars`` is imported lazily so that the module loads
    without the package installed (tests, CI).  When the library is absent
    the function assumes every weekday is a trading day.
    """
    try:
        import pandas_market_calendars as mcal  # type: ignore[import]
        cal = mcal.get_calendar("NYSE")
        schedule = cal.schedule(
            start_date=d.isoformat(),
            end_date=d.isoformat(),
        )
        return not schedule.empty
    except ImportError:
        # Library not installed — treat every weekday as a trading day.
        logger.warning(
            "pandas_market_calendars_not_installed",
            extra={"date": str(d), "note": "holiday check skipped"},
        )
        return True
    except Exception:
        logger.warning("nyse_calendar_check_failed", extra={"date": str(d)})
        return True


# ------------------------------------------------------------------
# Public helper: list today's picks (used by universe_worker)
# ------------------------------------------------------------------

def list_ai_research_picks(db: Session, *, trade_date_str: str) -> list[AiResearchPick]:
    """Return all persisted picks for *trade_date_str*, ordered by
    is_bonus_pick asc (core picks first) then id asc."""
    rows = db.execute(
        select(AiResearchPick)
        .where(AiResearchPick.trade_date == trade_date_str)
        .order_by(AiResearchPick.is_bonus_pick.asc(), AiResearchPick.id.asc())
    ).scalars().all()
    return list(rows)
