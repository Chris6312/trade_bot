# Small Account Multi-Asset Trading Bot

A disciplined, automation-first trading bot designed for **small accounts under $500**, with a focus on **balanced growth, controlled drawdown, deterministic worker flow, and clean operator controls**.

This project supports:

- **Crypto live trading:** Kraken Pro
- **Stock live trading:** Public.com
- **Stock paper trading:** Alpaca Paper Stocks
- **Crypto paper trading:** Alpaca Paper Crypto
- **Stock market data:** Alpaca
- **Crypto market data:** Kraken
- **Backend:** Python + FastAPI + PostgreSQL + Docker
- **Frontend:** React
- **Supervisor:** PowerShell 7

---

## 1. Core Goal

The bot is designed to trade a small account with a **moderate-risk profile**, balancing opportunity and protection by prioritizing:

- controlled drawdown
- long-only trading until account equity exceeds **$2,500**
- strict but practical risk controls
- fee-aware execution
- limited position count
- deterministic worker sequencing
- clear paper/live separation

This is not a high-frequency system and not a reckless momentum cannon. It is a structured execution engine meant to grow cautiously while still participating in stronger market conditions.

---

## 2. Primary Behavior Rules

These rules define expected bot behavior and should not be violated unless explicitly redesigned.

### Trading rules
- Account focus is **sub-$500** operation.
- **Long-only** for both stocks and crypto until account equity is **greater than $2,500**.
- Maximum risk per trade is **2% of account equity**.
- Default risk per trade should be **1.0% to 1.25%**, unless overridden.
- Total capital deployed across all open trades must not exceed **90% of account equity**.
- For **stocks**, position sizing must be based on **available cash**, not just total equity.
- Broker fees and expected slippage must be included in trade acceptance logic.
- Bot must support:
  - fixed stops
  - trailing stops
  - step trailing stops
- Bot must be **regime-aware** and reduce or block entries in poor conditions.

### Worker rules
- Only **one worker** is allowed to fetch candles for both:
  - backfill
  - incremental sync
- Other workers must wait for required upstream workers to finish before beginning their cycle.
- Stock universe generation order:
  1. AI stock universe worker runs first
  2. if AI fails, fallback stock universe loader uses Alpaca top 50 / most-active logic
  3. candle worker updates data
  4. downstream workers resume

### Control rules
- A **master kill switch** must block new entries immediately.
- Separate **asset-class circuit breakers** must exist for:
  - stocks
  - crypto
- Frontend must provide manual buttons for:
  - refresh universe
  - refresh strategies
  - backfill candles
  - incremental sync
  - recompute regime
  - flatten positions
  - toggle kill switch

---

## 3. Brokers and Data Sources

### Live execution
- **Crypto:** Kraken Pro
- **Stocks:** Public.com

### Paper execution
- **Stocks:** Alpaca Paper Stocks
- **Crypto:** Alpaca Paper Crypto

### Market data
- **Stocks OHLCV:** Alpaca
- **Crypto OHLCV:** Kraken

### Universe sources
- **Stocks:** AI-generated universe or Alpaca fallback top-50 universe
- **Crypto:** hard-coded top 15 Kraken universe

---

## 4. Strategy Scope

Initial release should stay disciplined but allow enough flexibility to support a moderate-risk profile.

### Stocks
Recommended starting set:
- HTF Context + 5m Reclaim Long

### Crypto
Recommended starting set:
- 4H/1H Trend Continuation Long
- VWAP Reclaim Long
- Breakout Long
- BBRSI Mean Reversion Long

### Timeframe guidance

#### Stocks
- bias: `1h`
- setup: `15m`
- entry trigger: `5m`
- optional daily filter: `1d`

#### Crypto
- bias: `4h`
- setup: `1h`
- entry trigger: `15m`
- optional daily filter: `1d`

---

## 5. Risk Framework

### Per-trade
- hard max risk: **2.0%**
- recommended default risk: **1.0% to 1.25%**
- trade must pass fee-adjusted and slippage-adjusted acceptance tests

### Deployment
- total deployed capital cap: **90%**
- reserve capital must remain available
- stock sizing must respect available cash
- position count must remain limited for small account stability

### Circuit breakers
Recommended defaults for a moderate-risk profile:
- stock soft stop: `-3.5%`
- stock hard stop: `-5.5%`
- crypto soft stop: `-4.0%`
- crypto hard stop: `-6.5%`
- total account hard stop: `-7.5%`

These thresholds are intentionally looser than a conservative profile, allowing the bot to stay engaged through more normal volatility while still protecting the account from deeper damage.

---

## 6. Regime Model

The bot must classify market conditions before strategy execution.

### Stock regime inputs
- SPY trend
- QQQ trend
- stock breadth
- realized volatility
- momentum / participation context

### Crypto regime inputs
- BTC trend
- ETH trend
- crypto breadth across the hard-coded universe
- realized volatility
- risk-on / risk-off behavior

### Regime outputs
- bull
- neutral
- risk_off

### Regime behavior
- **bull:** full long playbook allowed
- **neutral:** moderate participation with tighter quality filters
- **risk_off:** block or heavily restrict new long entries

This moderate-risk design should still avoid forcing trades in poor conditions. Risk is increased through better participation in favorable regimes, not by becoming careless.

---

## 7. System Architecture

### Backend
- Python 3.12
- FastAPI
- SQLAlchemy / Alembic
- PostgreSQL
- Docker Compose

### Frontend
- React + Vite

### Supervisor
- PowerShell 7 scripts to:
  - start all services
  - wait for health
  - stop gracefully

### Suggested ports
Do not use `8000`, `5432`, `6399`, or `5173`.

Recommended host ports:
- backend: `8101`
- frontend: `4174`
- postgres: `55432`

---

## 8. Folder Layout

```text
project-root/
├─ backend/
│  ├─ app/
│  │  ├─ common/
│  │  │  ├─ config/
│  │  │  ├─ db/
│  │  │  ├─ enums/
│  │  │  ├─ logging/
│  │  │  ├─ models/
│  │  │  ├─ schemas/
│  │  │  ├─ services/
│  │  │  ├─ risk/
│  │  │  ├─ regime/
│  │  │  ├─ orchestration/
│  │  │  ├─ pnl/
│  │  │  ├─ utils/
│  │  │  └─ events/
│  │  ├─ stocks/
│  │  │  ├─ brokers/
│  │  │  ├─ data/
│  │  │  ├─ universe/
│  │  │  ├─ features/
│  │  │  ├─ strategies/
│  │  │  ├─ execution/
│  │  │  └─ sizing/
│  │  ├─ crypto/
│  │  │  ├─ brokers/
│  │  │  ├─ data/
│  │  │  ├─ universe/
│  │  │  ├─ features/
│  │  │  ├─ strategies/
│  │  │  ├─ execution/
│  │  │  └─ sizing/
│  │  ├─ workers/
│  │  ├─ api/
│  │  └─ main.py
│  ├─ migrations/
│  └─ tests/
├─ frontend/
│  ├─ src/
│  │  ├─ components/
│  │  ├─ pages/
│  │  ├─ features/
│  │  ├─ hooks/
│  │  ├─ stores/
│  │  ├─ api/
│  │  └─ types/
├─ scripts/
│  ├─ Start-Bot.ps1
│  ├─ Stop-Bot.ps1
│  ├─ Wait-ForHealth.ps1
│  └─ backup_project.ps1
├─ docker/
├─ docker-compose.yml
├─ .env
├─ README.md
└─ PHASE_CHECKLIST.md
```

---

## 9. Worker Flow

The bot must run in a dependency-safe order.

### Cycle order
1. AI stock universe worker
2. fallback universe loader if AI fails
3. candle worker
4. feature builder
5. regime worker
6. strategy worker
7. risk gate
8. execution worker
9. position manager / stop manager
10. reconciliation and PnL snapshot

### Critical rule
The **candle worker is the only component allowed to write OHLCV bars**.

All other workers consume candle data as read-only input.

---

## 10. Frontend Requirements

The frontend must include:

### Dashboard
- total equity
- stock equity / PnL
- crypto equity / PnL
- live/paper state
- deployment %
- open positions
- system health
- kill switch status

### Universe page
- AI stock universe results
- fallback universe results
- crypto hard-coded universe
- refresh controls

### Strategies page
- strategy readiness per symbol
- blocked reasons
- score breakdown
- regime state

### Positions page
- current positions
- stops
- realized / unrealized PnL
- flatten controls

### Data page
- candle freshness
- backfill status
- last sync timestamps

### Settings page
- mode controls
- strategy toggles
- risk settings
- stop settings
- circuit breaker settings
- universe settings

### Logs / Events page
- worker events
- broker events
- errors
- order events
- risk events

---

## 11. Required Environment Variables

Use these canonical names exactly:

```env
# Alpaca Paper Trading - STOCKS account
ALPACA_PAPER_KEY=your_alpaca_paper_key_here
ALPACA_PAPER_SECRET=your_alpaca_paper_secret_here

# Alpaca Paper Trading - CRYPTO account
ALPACA_PAPER_KEY_CRYPTO=your_alpaca_crypto_key_here
ALPACA_PAPER_SECRET_CRYPTO=your_alpaca_crypto_secret_here

# Kraken Live Trading (Crypto)
KRAKEN_API_KEY=your_kraken_api_key_here
KRAKEN_API_SECRET=your_kraken_api_secret_here

# Public.com Live Trading (Stocks)
PUBLIC_API_SECRET=your_public_api_secret_here

# AI Mode — Stock Universe Source
# Set to "ai" to enable AI-owned stock universe creation.
# When "ai", the AI premarket worker creates the daily stock universe,
# legacy stock rotation is disabled, and downstream workers wait for
# AI startup resolution before their first pass.
# Set to "legacy" (default) to use the classic Alpaca most-actives rotator.
STOCK_UNIVERSE_SOURCE=ai

# OpenAI / AI provider settings (required when STOCK_UNIVERSE_SOURCE=ai)
# OPENAI_API_KEY=your_openai_api_key_here
# AI_MODEL=gpt-5-mini
```

Recommended supporting values:

```env
APP_ENV=dev
APP_PORT=8101
FRONTEND_PORT=4174
POSTGRES_PORT=55432
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/tradingbot
UI_ORIGIN=http://localhost:4174

DEFAULT_MODE=mixed
MAX_ACCOUNT_DEPLOYMENT_PCT=0.90
MAX_RISK_PER_TRADE_PCT=0.02
DEFAULT_RISK_PER_TRADE_PCT=0.0125

LONG_ONLY_UNTIL_EQUITY=2500
```

---

## 12. Startup and Shutdown

### Start script responsibilities
`Start-Bot.ps1` should:
1. verify PowerShell 7
2. verify Docker is available
3. start PostgreSQL
4. wait for DB health
5. run migrations
6. start backend
7. start workers in safe order
8. start frontend
9. display health URLs and mode

### Stop script responsibilities
`Stop-Bot.ps1` should:
1. block new entries
2. let in-flight operations finish safely
3. stop worker loops gracefully
4. stop backend
5. stop frontend
6. stop Docker services
7. clean temporary state files

---

## 13. Development Rules

- Keep stock and crypto logic separated except for shared common services.
- Avoid hidden behavior. Persist important decisions and blocked reasons.
- Every trade candidate must show why it was accepted or rejected.
- Every worker must be observable through logs and DB/system events.
- Paper mode stability comes before live rollout.
- Do not widen strategy count too early for a small account.
- The candle pipeline must remain single-writer.

---

## 14. Initial Release Scope

### Include
- stock live via Public
- crypto live via Kraken
- paper stocks via Alpaca
- paper crypto via Alpaca
- AI stock universe with fallback
- hard-coded top-15 Kraken crypto universe
- regime engine
- strategy engine
- risk engine
- stop manager
- frontend controls
- PowerShell supervisor scripts

### Exclude for initial release
- short selling
- options
- leverage
- smart order routing
- multi-user support
- large-universe experimentation
- complex order-book alpha models

---

## 15. Success Criteria

The bot is “on track” when it can do all of the following:

- start and stop cleanly from PowerShell
- build daily stock universe from AI or fallback
- sync stock and crypto candles through one worker only
- classify market regime
- generate strategy candidates with explicit reasons
- size trades safely for a moderate-risk small account
- place paper/live trades to the correct venue
- manage stops correctly
- display real-time state and PnL in the frontend
- respect kill switch and circuit breakers at all times

---

## 16. Source of Truth Reminder

This file is the behavioral source of truth for the bot.

If implementation and this document disagree, either:
- update the implementation to match the guide, or
- formally revise the guide before continuing work
