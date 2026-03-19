# Trade_Bot Strategy, Readiness, and Regime Guide

This document explains the **current implementation** in the uploaded project backup, with wording tuned for operators and future handoffs.

It covers:
- what each strategy is trying to do
- how the readiness score is built
- how regime logic affects strategy eligibility
- the most common reasons a strategy is blocked

---

## 1. Big picture

The bot currently supports these initial strategies:

### Stocks
- `htf_reclaim_long`

The morning AI stock shortlist is now intended to act as a strict setup scout for this paper contract, returning at most five symbols across READY NOW and WATCHLIST, with explicit NONE behavior when nothing qualifies.

### Crypto
- `trend_continuation_long`
- `vwap_reclaim_long`
- `breakout_long`
- `bbrsi_mean_reversion_long`

All strategies are currently **long-only**.

---

## 2. How the readiness score works

Think of readiness as the strategy's cockpit score. It is not just “did the signal trigger?” It is a weighted blend of:

- **trend score**
- **participation score**
- **liquidity score**
- **stability score**
- **signal score**

### Current weighted formula

```text
composite_score =
    0.28 * trend_score
  + 0.18 * participation_score
  + 0.18 * liquidity_score
  + 0.16 * stability_score
  + 0.20 * signal_score
```

All component scores are clamped to the range **0.00 to 1.00**.

### How status is decided

A strategy row becomes:

- **Ready** when there are **no blocked reasons** and the composite score is at or above the threshold
- **Blocked** when there is at least one blocked reason

The system also appends `composite_below_threshold` as a blocked reason when the composite score is below the threshold.

### Readiness vs composite score

- If a strategy is **Ready**, `readiness_score = composite_score`
- If a strategy is **Blocked**, `readiness_score = min(composite_score, threshold_score)`

That means blocked rows can still have a decent-looking readiness number, but they are capped at the threshold and remain blocked until the blockers clear.

---

## 3. Shared component scores

These are the reusable building blocks used by all current strategies.

### 3.1 Trend score

Trend score blends four ideas:

- close above `sma_20`
- close above `ema_20`
- `momentum_20` relative to a target
- `trend_slope_20` relative to a target

#### Current construction

```text
trend_score = average(
  close > sma_20,
  close > ema_20,
  momentum_20 / 0.05,
  trend_slope_20 / 0.02
)
```

Booleans score as `1.0` for true and `0.0` for false.

### 3.2 Participation score

Participation asks whether the move has some fuel in the tank.

```text
participation_score = average(
  relative_volume_20 / 1.2,
  momentum_20 / 0.03
)
```

### 3.3 Liquidity score

Liquidity targets are different for stocks and crypto.

#### Stocks

```text
liquidity_score = average(
  dollar_volume / 500,000,
  dollar_volume_sma_20 / 400,000
)
```

#### Crypto

```text
liquidity_score = average(
  dollar_volume / 2,500,000,
  dollar_volume_sma_20 / 2,000,000
)
```

### 3.4 Stability score

Stability rewards lower realized volatility and a calmer ATR profile.

#### Stocks

- realized volatility target: `0.035`
- ATR/close target: `0.04`

#### Crypto

- realized volatility target: `0.08`
- ATR/close target: `0.07`

The score uses inverse-ratio logic, so **less turbulence = better score**.

---

## 4. Regime logic

The regime engine is a shared weather map for each asset class. It does **not** currently create per-strategy regime states.

### 4.1 Regime states

- `bull`
- `neutral`
- `risk_off`

### 4.2 Regime entry policy mapping

```text
bull      -> full
neutral   -> reduced
risk_off  -> blocked
```

### 4.3 What the regime engine measures

For each asset class it computes:

- **breadth_ratio**
- **benchmark_support_ratio**
- **participation_ratio**
- **volatility_support_ratio**

Then it creates a weighted `bull_score`:

```text
bull_score =
    0.45 * breadth_ratio
  + 0.25 * benchmark_support_ratio
  + 0.20 * participation_ratio
  + 0.10 * volatility_support_ratio
```

### 4.4 Regime classification rules

#### Bull

The asset class is `bull` when:

- `bull_score >= 0.67`
- `breadth_ratio >= 0.55`
- `benchmark_support_ratio >= 0.50`

#### Neutral

The asset class is `neutral` when:

- `bull_score >= 0.40`
- `breadth_ratio >= 0.25`

#### Risk off

Everything else becomes `risk_off`.

### 4.5 How regime affects strategy thresholds

Each strategy has a base threshold. Regime can tighten it:

- `full` keeps the base threshold unchanged
- `reduced` adds `+0.075` to the threshold
- `blocked` forces the threshold to `1.00`

### 4.6 How regime blocks entries

If the entry policy is `blocked`, the strategy receives the blocked reason:

- `regime_blocked`

If regime is missing entirely, the strategy receives:

- `regime_unavailable`

So the regime layer is a shared gate above the individual strategy conditions.

---

## 5. Stock strategies

## 5.1 `trend_pullback_long`

### Intent

This strategy wants a stock that is already in an uptrend, but has drifted back toward the 20 EMA without breaking trend structure. It is basically looking for a tidy pullback instead of chasing a rocket plume.

### Base threshold

- `0.60`

### What must look good

- close above `ema_20`
- close above `sma_20`
- `momentum_20 > 0.01`
- `trend_slope_20 > 0.004`
- distance from close to `ema_20` must be **not too stretched**

### Pullback distance rule

The strategy calculates:

```text
pullback_distance = abs(close - ema_20) / ema_20
```

It blocks the setup if:

- `pullback_distance > 0.025`

### Signal score

```text
signal_score = (0.03 - min(pullback_distance, 0.03)) / 0.03
```

This means the closer price is to the pullback sweet spot, the better the signal score.

### Common blocked reasons

- `close_below_ema20`
- `close_below_sma20`
- `momentum_too_weak`
- `trend_slope_too_weak`
- `pullback_too_extended`
- `composite_below_threshold`
- `regime_blocked`
- `strategy_disabled`

---

## 5.2 `vwap_reclaim_long` (stocks)

### Intent

This strategy wants a stock that has reclaimed VWAP after previously trading below it, while still keeping broader trend support. It is looking for a fresh reclaim, not a move that already happened three candles ago and is now wearing sunglasses indoors.

### Base threshold

- `0.59`

### What must look good

- current close above `ema_20`
- current close above current candle `vwap`
- previous candle should **not** already have closed above previous VWAP
- relative volume should show at least decent participation

### Participation requirement

- `relative_volume_20 >= 0.9`

### Signal score

```text
reclaim_distance = (close - vwap) / vwap
signal_score = reclaim_distance / 0.012
```

Clamped into `0.00` to `1.00`.

### Common blocked reasons

- `vwap_missing`
- `close_below_ema20`
- `close_below_vwap`
- `insufficient_candles`
- `already_above_vwap`
- `participation_too_low`
- `composite_below_threshold`
- `regime_blocked`
- `strategy_disabled`

---

## 5.3 `opening_range_breakout_long`

### Intent

This strategy looks for a stock breaking above a recent short-term high with participation and momentum. In the current implementation it uses a 5-candle lookback for the breakout reference.

### Base threshold

- `0.64`

### What must look good

- current close above the highest high of the previous 5 candles
- `relative_volume_20 >= 1.1`
- `momentum_20 > 0.015`

### Breakout reference

```text
recent_high = highest high of previous 5 candles, excluding latest
```

### Signal score

```text
breakout_pct = (close - recent_high) / recent_high
signal_score = breakout_pct / 0.015
```

Clamped into `0.00` to `1.00`.

### Common blocked reasons

- `insufficient_candles`
- `no_recent_breakout`
- `participation_too_low`
- `momentum_too_weak`
- `composite_below_threshold`
- `regime_blocked`
- `strategy_disabled`

---

## 6. Crypto strategies

## 6.1 `trend_continuation_long`

### Intent

This is the crypto trend-rider. It wants a coin already above its moving averages, still carrying momentum, but not so extended that the entry is buying the fireworks after the finale.

### Base threshold

- `0.61`

### What must look good

- close above `ema_20`
- close above `sma_20`
- `momentum_20 > 0.012`
- `trend_slope_20 > 0.006`
- extension from EMA should not be excessive

### Extension rule

```text
extension_from_ema = abs(close - ema_20) / ema_20
```

Blocked when:

- `extension_from_ema > 0.06`

### Signal score

```text
signal_score = (0.07 - min(extension_from_ema, 0.07)) / 0.07
```

### Common blocked reasons

- `close_below_ema20`
- `close_below_sma20`
- `momentum_too_weak`
- `trend_slope_too_weak`
- `trend_too_extended`
- `composite_below_threshold`
- `regime_blocked`
- `strategy_disabled`

---

## 6.2 `vwap_reclaim_long` (crypto)

### Intent

Same family as the stock version, but slightly more permissive on participation because crypto tends to be noisier and trades around the clock.

### Base threshold

- `0.58`

### What must look good

- close above `ema_20`
- close above VWAP
- previous candle should not already have closed above previous VWAP
- `relative_volume_20 >= 0.85`

### Signal score

```text
reclaim_distance = (close - vwap) / vwap
signal_score = reclaim_distance / 0.015
```

### Common blocked reasons

- `vwap_missing`
- `close_below_ema20`
- `close_below_vwap`
- `insufficient_candles`
- `already_above_vwap`
- `participation_too_low`
- `composite_below_threshold`
- `regime_blocked`
- `strategy_disabled`

---

## 6.3 `breakout_long`

### Intent

This is the crypto breakout hunter. It wants price to clear a recent swing high with enough momentum and participation to suggest the move is real.

### Base threshold

- `0.62`

### What must look good

- close above the highest high of the previous 10 candles
- `relative_volume_20 >= 1.0`
- `momentum_20 > 0.012`

### Breakout reference

```text
recent_high = highest high of previous 10 candles, excluding latest
```

### Signal score

```text
breakout_pct = (close - recent_high) / recent_high
signal_score = breakout_pct / 0.02
```

### Common blocked reasons

- `insufficient_candles`
- `no_recent_breakout`
- `participation_too_low`
- `momentum_too_weak`
- `composite_below_threshold`
- `regime_blocked`
- `strategy_disabled`

---

## 6.4 `bbrsi_mean_reversion_long`

### Intent

This is the only current mean-reversion strategy in the initial crypto pack. It looks for an oversold condition that is beginning to recover, using RSI plus Bollinger structure.

### Base threshold

- `0.57`

### What must look good

- enough candles to compute RSI and Bollinger bands
- `rsi_14 <= 45`
- close back above the lower Bollinger band
- current close above previous close for reversal confirmation

### Core reversal checks

It blocks when any of these fail:

- RSI is missing or too high
- close is still below the lower band
- current close is not above previous close

### Signal score

Two sub-scores are blended:

#### RSI score

```text
rsi_score = (50 - rsi) / 20
```

Lower RSI improves the score.

#### Band score

```text
band_score = (close - lower_band) / (middle_band - lower_band)
```

This rewards price climbing back off the lower band toward the mid-band.

#### Final signal score

```text
signal_score = 0.55 * rsi_score + 0.45 * band_score
```

### Common blocked reasons

- `insufficient_candles`
- `rsi_not_reset`
- `still_below_lower_band`
- `no_reversal_confirmation`
- `composite_below_threshold`
- `regime_blocked`
- `strategy_disabled`

---

## 7. Common blocked reasons across the strategy engine

Here is the practical dictionary for the most common blocked reasons.

| Blocked reason | Meaning |
|---|---|
| `missing_feature_snapshot` | No feature row was available for the symbol and timeframe |
| `regime_unavailable` | Regime worker has not produced a usable regime snapshot yet |
| `regime_blocked` | Current regime entry policy is `blocked` |
| `strategy_disabled` | Strategy toggle is turned off in settings |
| `composite_below_threshold` | The weighted score did not clear the strategy threshold |
| `insufficient_candles` | Not enough candles exist for the calculation |
| `participation_too_low` | Relative volume or participation requirement did not pass |
| `momentum_too_weak` | Momentum input was below the strategy minimum |
| `trend_slope_too_weak` | Trend slope was too weak for the setup |
| `close_below_ema20` | Price is below EMA 20 |
| `close_below_sma20` | Price is below SMA 20 |
| `close_below_vwap` | Price has not reclaimed VWAP |
| `already_above_vwap` | The reclaim is no longer fresh |
| `no_recent_breakout` | Price has not exceeded the lookback high |
| `pullback_too_extended` | The pullback is no longer in the preferred distance zone |
| `trend_too_extended` | Trend continuation entry is too stretched from EMA |
| `rsi_not_reset` | RSI is not oversold enough for the mean reversion setup |
| `still_below_lower_band` | Price has not recovered above the lower Bollinger band |
| `no_reversal_confirmation` | No candle-to-candle reversal confirmation yet |

---

## 8. Current implementation notes

### 8.1 Default evaluation timeframe

The current workers default to the **first configured feature timeframe** for each asset class:

- stocks: first item of `stock_feature_timeframes` which is currently `1h`
- crypto: first item of `crypto_feature_timeframes` which is currently `4h`

That means the current engine is not yet doing a full multi-timeframe orchestration pass for every strategy. It is using the first configured timeframe as the default evaluation lane unless another timeframe is passed in explicitly.

### 8.2 Status model today

At the backend strategy-engine level, the persisted statuses are effectively:

- `ready`
- `blocked`

The richer UI labels such as **Near Ready**, **Regime Mismatch**, **Risk Blocked**, and **Cooldown** are presentation concepts around the core backend data model.

### 8.3 Shared regime, not per-strategy regime maps

A symbol can be blocked for one strategy and not another, but that is usually because the **strategy-specific setup rules differ**. The current regime layer is shared by asset class and timeframe, not strategy-specific.

---

## 9. Suggested UI wording for the strategy drawer

If you want the strategy drawer to feel crisp and operator-friendly, this language works well:

### Thresholds
- Base threshold
- Regime-adjusted threshold
- Composite score
- Readiness score

### Pillars passed / failed
- Trend
- Participation
- Liquidity
- Stability
- Signal

### Regime requirement
- Current regime
- Entry policy
- Regime impact on threshold

### Qualification summary
- Why it qualified
- Why it did not qualify
- Primary blocker
- All blockers

---

## 10. Quick reference table

| Strategy | Asset | Style | Base threshold | Primary idea |
|---|---|---:|---:|---|
| `htf_reclaim_long` | Stock | HTF context + 5m reclaim | 0.65 | 1h bias pass, 15m setup pass, then fresh 5m VWAP and EMA9 reclaim |
| `trend_continuation_long` | Crypto | Trend continuation | 0.61 | Strong trend, not overextended |
| `vwap_reclaim_long` | Crypto | VWAP reclaim | 0.58 | Fresh reclaim above VWAP |
| `breakout_long` | Crypto | Breakout | 0.62 | Break above recent 10-candle high |
| `bbrsi_mean_reversion_long` | Crypto | Mean reversion | 0.57 | Oversold recovery off lower Bollinger band |

---

## 11. Bottom line

The current strategy engine behaves like a five-pillar checkpoint:

1. Is the market weather acceptable?
2. Is the symbol trending well enough?
3. Is participation present?
4. Is liquidity sufficient?
5. Is the specific setup actually there right now?

If all five line up and the threshold clears, the row turns **ready**.
If not, the engine leaves breadcrumbs instead of smoke: **blocked reasons, component scores, threshold, and regime state**.


## 12. Stock paper contract review surface

The backend now exposes `/api/v1/operations/stock-paper-contract-review` as a joined audit view for the active stock paper contract. Each row is built from persisted AI research picks plus the latest strategy, risk, execution, and position records for the same symbol.

This review surface is meant to answer four operator questions quickly:
- did AI name the stock
- did the indicator approve it
- did risk accept it
- was a trade actually taken or skipped

It also surfaces the selected 1h and 15m MA pairs, the 1h/15m/5m contract pass flags, and the latest entry/stop/target recorded by the pipeline.
