
## `PHASE_CHECKLIST.md`

```md
# Phase Checklist

This checklist is the implementation roadmap for the small-account multi-asset trading bot.

Use it to keep development aligned with the project guide and prevent drift.

---

## Phase 1 - Project Bootstrap

### Goal
Create the initial full-stack skeleton and local development environment.

### Deliverables
- backend project scaffold
- frontend project scaffold
- Docker Compose
- PostgreSQL container
- environment loading
- base FastAPI app
- base React app
- health endpoints

### Exit Criteria
- backend starts on configured non-blocked port
- frontend starts on configured non-blocked port
- PostgreSQL starts successfully
- `/health` returns OK
- `.env` loads correctly

### Status
- [ ] complete

---

## Phase 2 - Database and Core Settings

### Goal
Create persistent configuration and workflow tracking tables.

### Deliverables
- Alembic setup
- settings table
- workflow run table
- workflow stage status table
- account snapshot table
- system event table

### Exit Criteria
- migrations run cleanly
- settings can be created and updated
- workflow stages can be recorded
- backend reads settings from DB and environment safely

### Status
- [ ] complete

---

## Phase 3 - Broker and Market Data Adapters

### Goal
Implement broker and data integrations as clean adapters.

### Deliverables
- Kraken crypto trading adapter
- Kraken crypto market data adapter
- Public stock trading adapter
- Alpaca stock paper adapter
- Alpaca crypto paper adapter
- Alpaca stock OHLCV adapter

### Exit Criteria
- account state can be retrieved from all relevant brokers
- stock OHLCV fetch works from Alpaca
- crypto OHLCV fetch works from Kraken
- errors are logged clearly
- adapters are separated by asset and venue

### Status
- [ ] complete

---

## Phase 4 - Single Candle Worker

### Goal
Implement the only component allowed to write candle data.

### Deliverables
- candle worker
- stock backfill logic
- stock incremental logic
- crypto backfill logic
- crypto incremental logic
- watermark persistence
- candle freshness tracking

### Rules
- no other worker may fetch or write candles
- all downstream workers consume candle data read-only

### Exit Criteria
- stock candles can backfill
- stock candles can incrementally sync
- crypto candles can backfill within supported limits
- crypto candles can incrementally sync
- freshness timestamps persist correctly

### Status
- [ ] complete

---

## Phase 5 - Universe Engine

### Goal
Build the stock and crypto universes used by the strategy engine.

### Deliverables
- AI stock universe worker
- Alpaca fallback stock universe worker
- hard-coded Kraken top-15 crypto universe
- ETF filtering logic
- stock universe persistence

### Rules
- AI universe runs first
- if AI fails, fallback universe is used
- downstream workers wait for universe resolution

### Exit Criteria
- daily stock universe can be created from AI
- fallback universe works if AI fails
- stock universe max size is enforced
- ETFs are excluded except SPY and QQQ
- crypto universe is available every cycle

### Status
- [ ] complete

---

## Phase 6 - Feature Engine

### Goal
Compute indicators and reusable feature inputs for strategies and regime.

### Deliverables
- indicator pipeline
- volume/liquidity features
- trend features
- volatility features
- persistence layer for computed features

### Exit Criteria
- features are generated for stocks
- features are generated for crypto
- computations are repeatable
- feature data is timestamped and queryable

### Status
- [ ] complete

---

## Phase 7 - Regime Engine

### Goal
Classify stock and crypto market conditions before strategies run.

### Deliverables
- stock regime classifier
- crypto regime classifier
- regime persistence
- regime API exposure

### Exit Criteria
- stock regime returns bull / neutral / risk_off
- crypto regime returns bull / neutral / risk_off
- strategies can query current regime state
- regime blocks or reduces entries appropriately

### Status
- [ ] complete

---

## Phase 8 - Strategy Engine

### Goal
Generate candidates from enabled stock and crypto strategies.

### Deliverables
- stock strategy modules
- crypto strategy modules
- candidate generation pipeline
- blocked reason persistence
- score/readiness output

### Suggested Initial Strategy Set

#### Stocks
- HTF Context + 5m Reclaim Long (`htf_reclaim_long`) for the active paper workflow
- optional expansion later only after the paper contract is proven

#### Crypto
- 4H/1H Trend Continuation Long
- VWAP Reclaim Long
- Breakout Long
- BBRSI Mean Reversion Long

### Exit Criteria
- strategy candidates are produced for stocks
- strategy candidates are produced for crypto
- blocked reasons are recorded clearly
- regime restrictions are respected
- strategy enable/disable settings work

### Status
- [ ] complete

---

## Phase 9 - Risk and Sizing Engine

### Goal
Apply account-safe trade gating for a moderate-risk small account.

### Deliverables
- max risk-per-trade enforcement
- default risk profile support
- max deployment enforcement
- stock cash-based sizing
- fee-aware acceptance logic
- slippage-aware acceptance logic
- circuit breaker logic
- long-only-until-$2500 rule

### Critical Rules
- no trade may risk more than 2%
- default risk should support a moderate profile, typically 1.0% to 1.25%
- total deployment may not exceed 90%
- stocks must size from available cash
- no shorts before account equity exceeds $2500

### Exit Criteria
- risk cap enforcement works
- default moderate-risk sizing works
- deployment cap enforcement works
- stock available-cash sizing works
- long-only restriction works
- circuit breakers block new entries correctly

### Status
- [ ] complete

---

## Phase 10 - Execution Engine

### Goal
Route accepted orders to the correct venue in paper/live/mixed mode.

### Deliverables
- order router
- live crypto routing to Kraken
- live stock routing to Public
- paper stock routing to Alpaca stock paper
- paper crypto routing to Alpaca crypto paper
- duplicate-order protection
- order/fill persistence

### Exit Criteria
- correct venue is selected by mode and asset class
- live and paper paths remain separated
- order errors are handled and logged
- fills persist correctly

### Status
- [ ] complete

---

## Phase 11 - Stop Manager

### Goal
Protect positions with required stop logic.

### Deliverables
- fixed stop manager
- trailing stop manager
- step trailing manager
- broker-specific stop update behavior
- stop persistence

### Exit Criteria
- every filled position receives initial protection
- trailing behavior works when activated
- step trailing works
- stop state is visible through API/UI

### Status
- [ ] complete

---

## Phase 12 - Position Sync, Reconciliation, and PnL

### Goal
Maintain accurate account state and performance reporting.

### Deliverables
- position sync
- open-order sync
- account snapshot logic
- realized PnL
- unrealized PnL
- stock/crypto/total PnL separation

### Exit Criteria
- positions reconcile with broker state
- realized/unrealized PnL computes correctly
- total, stock, and crypto PnL are visible
- live/paper mode is labeled correctly

### Status
- [ ] complete

---

## Phase 13 - Frontend Controls and Monitoring

### Goal
Expose all major state and control surfaces in the UI.

### Deliverables
- dashboard page
- universe page
- strategies page
- positions page
- data page
- settings page
- logs/events page

### Required Buttons
- refresh universe
- refresh strategies
- backfill candles
- sync incremental candles
- recompute regime
- flatten stocks
- flatten crypto
- flatten all
- toggle kill switch

### Exit Criteria
- all required pages render
- all required control actions are wired
- key system state is visible
- blocked reasons and risk states are visible

### Status
- [ ] complete

---

## Phase 14 - Settings Panel

### Goal
Make core operating behavior configurable without code edits.

### Deliverables
- app mode settings
- universe settings
- risk settings
- stop settings
- strategy settings
- circuit breaker settings
- broker mode toggles

### Exit Criteria
- settings persist in DB
- settings reload safely
- strategy toggles work
- kill switch works from UI
- circuit breaker settings affect runtime behavior

### Status
- [ ] complete

---

## Phase 15 - PowerShell Supervisor Scripts

### Goal
Provide one-command startup and one-command graceful shutdown.

### Deliverables
- `Start-Bot.ps1`
- `Stop-Bot.ps1`
- optional `Wait-ForHealth.ps1`
- PID/state file handling
- health checks

### Exit Criteria
- one command starts the full stack
- one command stops the full stack safely
- worker order is respected during startup
- no abrupt shutdown of active components

### Status
- [ ] complete

---

## Phase 16 - Testing and Validation

### Goal
Build confidence before live deployment.

### Deliverables
- unit tests
- integration tests
- workflow dependency tests
- risk engine tests
- strategy engine tests
- UI smoke tests
- paper trading validation checklist

### Exit Criteria
- core unit tests pass
- integration tests pass
- worker dependency ordering is verified
- risk rules are verified
- paper mode runs stably for an extended period

### Status
- [ ] complete

---

## Phase 17 - Live Guarded Rollout

### Goal
Move from paper to small-size live deployment safely.

### Deliverables
- live rollout checklist
- kill switch validation
- circuit breaker validation
- trade audit logging
- post-trade review workflow

### Exit Criteria
- live routing works for both asset classes
- position sizes remain disciplined but practical for a moderate-risk profile
- kill switch is tested
- circuit breakers are tested
- live logs are sufficient for troubleshooting

### Status
- [ ] complete

---

## Ongoing Rules Checklist

Keep these checked throughout the life of the project.

### Architecture Rules
- [ ] stock and crypto domains remain cleanly separated
- [ ] shared logic only lives in `common`
- [ ] only one candle worker writes OHLCV data
- [ ] workers respect dependency order
- [ ] paper/live execution paths remain separate

### Risk Rules
- [ ] no trade exceeds 2% risk
- [ ] default risk remains in the moderate range unless intentionally changed
- [ ] total deployed capital stays at or below 90%
- [ ] stocks size from available cash
- [ ] long-only remains enforced until account equity exceeds $2500
- [ ] fees and slippage are included in order acceptance

### Operational Rules
- [ ] kill switch blocks new trades immediately
- [ ] stock and crypto circuit breakers operate independently
- [ ] blocked reasons are persisted and visible
- [ ] major worker actions are logged
- [ ] frontend state matches backend truth

---

## Definition of Project Success

The project is on track when:

- the bot starts cleanly
- the universe builds correctly
- the candle worker keeps data fresh
- regime classification works
- strategies produce transparent candidates
- risk gating protects the account while still allowing moderate participation
- execution routes correctly
- stops manage exits properly
- PnL is accurate
- the operator can control the full system from the UI

---

## Source of Truth Reminder

Use this checklist together with `README.md`.

- `README.md` defines what the bot is and how it should behave.
- `PHASE_CHECKLIST.md` defines how to build it in the correct order.