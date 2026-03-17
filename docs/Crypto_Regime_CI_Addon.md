Yep. Here is the **exact contract v1** I would use for the **CI Crypto Regime Add-on**, built so it does **not** mutate the README-defined core bot behavior, does **not** touch candle-writing ownership, and stays advisory unless you explicitly promote it later. That matches the project’s single-writer candle rule, dependency-safe worker flow, crypto-on-Kraken market-data path, feature/regime separation, and the fact that more complex order-book work is outside the initial core scope.    

## 1. Contract name

**CI Crypto Regime Advisory v1**

Purpose:

* produce an **advisory crypto regime** for CI / research / comparison
* use **Kraken-native** crypto data first
* optionally enrich with **DeFiLlama**
* optionally include **Hurst exponent**
* optionally run **StandardScaler + GaussianMixture**
* never block the core bot if it fails
* never silently replace the official crypto regime

Official output states remain:

* `bull`
* `neutral`
* `risk_off`
* plus one add-on-only state: `unavailable`

The core bot still expects crypto regime behavior to end in `bull / neutral / risk_off` before strategies run, so the CI layer should mirror that vocabulary for comparison instead of inventing ten mood rings.  

## 2. Hard boundaries

These are the non-negotiables.

**2.1 Core bot remains source of execution truth**

* The existing crypto regime remains the official runtime regime used by strategies and risk unless a later feature flag promotes the CI regime.

**2.2 CI add-on is read-only against candles**

* It may consume OHLCV from existing tables.
* It may not fetch or write OHLCV bars.
* Only the candle worker keeps that crown.  

**2.3 CI add-on is advisory by default**

* It may log disagreements with core regime.
* It may expose scores in API/UI.
* It may not block orders by itself in v1.

**2.4 Fail-open for the core system**

* If Kraken order-book fetch fails, DeFiLlama fails, scaler/model artifact missing, or inference errors, the core bot continues.
* CI output becomes `unavailable` or `degraded`, and the failure is logged.

**2.5 Audit everything**

* Every run, model choice, settings change, and failure writes an event/log entry, because the project requires important worker actions and blocked reasons to be visible.   

## 3. Inputs contract

### 3.1 Required internal inputs

These must come from the existing bot database/runtime:

* `crypto universe` from the hard-coded Kraken universe
* `OHLCV` already written by the candle worker
* existing crypto feature snapshots if available
* current core crypto regime
* candle freshness metadata
* system mode / kill switch / circuit breaker state for display context only

This follows the existing worker order of candle → feature → regime, and keeps the add-on downstream.  

### 3.2 Optional external inputs

These are allowed but not required:

* **Kraken order-book depth** for BTC/USD and ETH/USD first
* optional Kraken depth for other top-universe names later
* **DeFiLlama** enrichment such as funding/open-interest style context if you choose to wire it

### 3.3 Required minimum history

No inference unless all of this is true:

* bias timeframe `4h` has enough history
* setup timeframe `1h` has enough history
* optional trigger timeframe `15m` is fresh if included
* all required internal features for the chosen model version are present

Suggested first thresholds:

* `4h`: minimum 120 bars
* `1h`: minimum 240 bars
* `15m`: minimum 288 bars if used
* order-book feature warmup: minimum 20 snapshots
* Hurst only computed when the full lookback window is available

## 4. Feature contract

The add-on should version its feature set explicitly.

### 4.1 Feature set version

`ci_crypto_regime_feature_set_v1`

### 4.2 Mandatory features

These are the base layer and should not depend on DeFiLlama:

* `btc_trend_4h`
* `btc_trend_1h`
* `eth_trend_4h`
* `eth_trend_1h`
* `crypto_breadth_pct_above_ma`
* `crypto_realized_vol_1h`
* `crypto_realized_vol_4h`
* `btc_return_z_1h`
* `eth_return_z_1h`

These align with the README’s crypto regime inputs: BTC trend, ETH trend, breadth, realized volatility, and risk-on/risk-off behavior. 

### 4.3 Kraken order-book features

These are optional in config, but first-class in the contract:

* `btc_spread_bps`
* `btc_top10_imbalance`
* `btc_top25_depth_usd`
* `btc_sweep_cost_buy_5k_bps`
* `btc_sweep_cost_sell_5k_bps`
* `eth_spread_bps`
* `eth_top10_imbalance`
* `eth_top25_depth_usd`
* `eth_sweep_cost_buy_5k_bps`
* `eth_sweep_cost_sell_5k_bps`
* `microstructure_support_score`

### 4.4 Hurst features

Optional but supported:

* `btc_hurst_4h`
* `btc_hurst_1h`
* `eth_hurst_4h`
* `eth_hurst_1h`

Rule:

* Hurst is computed as a feature only
* it is never persisted as a regime on its own
* if insufficient history, store `null` and mark feature as unavailable

### 4.5 DeFiLlama features

Optional and non-blocking:

* `market_funding_bias`
* `market_open_interest_z`
* `market_oi_change_24h`
* `market_defi_tvl_change_24h`

Rule:

* if unavailable, the model either uses a no-DeFiLlama feature set or marks those features missing and downgrades confidence

## 5. Model contract

### 5.1 Supported mode values

* `rules_only`
* `gmm_only`
* `hybrid_rules_plus_gmm`

Recommended default for v1:

* `hybrid_rules_plus_gmm`

### 5.2 StandardScaler contract

If ML mode is enabled:

* scaler is fit **offline**, never in the live worker
* scaler parameters are versioned
* live inference only calls `transform`
* no partial refit in runtime
* feature order must exactly match the registered feature set

### 5.3 GaussianMixture contract

If GMM mode is enabled:

* model is fit offline
* default components: `3`
* output probabilities are persisted
* cluster-to-label mapping is fixed in the model registry
* live worker only calls `predict_proba` and `predict`

### 5.4 Label mapping contract

Each trained cluster must map to exactly one label:

* cluster `0` → `bull|neutral|risk_off`
* cluster `1` → `bull|neutral|risk_off`
* cluster `2` → `bull|neutral|risk_off`

That mapping is stored in DB and may not be inferred on the fly per run. No label roulette wheel.

## 6. Persistence contract

Keep CI add-on data isolated from core regime tables.

### 6.1 Table: `ci_crypto_regime_model_registry`

One row per model artifact bundle.

Fields:

```text
id
model_version                unique
feature_set_version
scaler_version               nullable
model_type                   rules_only|gmm_only|hybrid_rules_plus_gmm
label_map_json
training_window_start_at
training_window_end_at
training_notes
is_active
created_at
created_by
```

### 6.2 Table: `ci_crypto_regime_runs`

One row per inference attempt.

Fields:

```text
id
run_started_at
run_completed_at
status                       success|partial|failed|skipped
skip_reason                  nullable
model_version
feature_set_version
used_orderbook               bool
used_defillama               bool
used_hurst                   bool
data_window_end_at
error_message                nullable
degraded                     bool
```

### 6.3 Table: `ci_crypto_regime_feature_snapshots`

Long-form feature storage for audit/debug.

Fields:

```text
id
run_id
symbol_scope                 market|BTC/USD|ETH/USD|universe
timeframe                    15m|1h|4h|1d|null
feature_name
feature_value                nullable
feature_status               ok|missing|stale|error
source                       internal|kraken|defillama|derived
as_of_at
```

### 6.4 Table: `ci_crypto_regime_states`

One row per run, containing the final advisory state.

Fields:

```text
id
run_id
as_of_at
state                        bull|neutral|risk_off|unavailable
confidence                   decimal(6,5)
cluster_id                   nullable
cluster_prob_bull            nullable
cluster_prob_neutral         nullable
cluster_prob_risk_off        nullable
agreement_with_core          agree|disagree|core_unavailable
advisory_action              allow|tighten|block|ignore
core_regime_state
degraded                     bool
reason_codes_json
summary_json
```

### 6.5 No overwrite rule

* core regime tables stay untouched
* CI tables never overwrite core state
* joins happen in API/service layer only

## 7. Runtime worker contract

### 7.1 Worker name

`ci_crypto_regime_worker`

### 7.2 Position in flow

This worker runs **after** the core regime worker finishes, not before. That preserves the existing dependency-safe flow. 

### 7.3 Schedule

Suggested default:

* every 15 minutes at `:00:30`, `:15:30`, `:30:30`, `:45:30`

Reason:

* it consumes already-synced candle data
* it is not latency-sensitive
* it should trail the normal candle/feature/regime chain, not race it

### 7.4 Worker output rules

Per run, it must do exactly one of:

* write a `success` run + state
* write a `partial` run + degraded state
* write a `failed` run with no state
* write a `skipped` run with reason

### 7.5 Skip reasons

Allowed skip reasons:

* `disabled`
* `advisory_only_disabled`
* `missing_history`
* `stale_internal_data`
* `core_regime_not_ready`
* `model_not_registered`
* `feature_contract_mismatch`

## 8. Settings contract

These should live in Settings, but under a clearly isolated CI / Admin area so they do not masquerade as core trading behavior. The frontend spec already requires searchable, staged settings with audit logging and confirmation for risky changes. 

Required settings:

```text
CI_CRYPTO_REGIME_ENABLED                    bool default false
CI_CRYPTO_REGIME_ADVISORY_ONLY              bool default true
CI_CRYPTO_REGIME_MODEL_VERSION              string
CI_CRYPTO_REGIME_MODE                       rules_only|gmm_only|hybrid_rules_plus_gmm
CI_CRYPTO_REGIME_USE_ORDERBOOK             bool default true
CI_CRYPTO_REGIME_USE_DEFILLAMA             bool default false
CI_CRYPTO_REGIME_USE_HURST                 bool default true
CI_CRYPTO_REGIME_RUN_INTERVAL_MINUTES      int default 15
CI_CRYPTO_REGIME_STALE_AFTER_SECONDS       int default 1200
CI_CRYPTO_REGIME_MIN_BARS_4H               int default 120
CI_CRYPTO_REGIME_MIN_BARS_1H               int default 240
CI_CRYPTO_REGIME_MIN_BOOK_SNAPSHOTS        int default 20
CI_CRYPTO_REGIME_PROMOTE_TO_RUNTIME        bool default false
```

Promotion rule:

* `CI_CRYPTO_REGIME_PROMOTE_TO_RUNTIME` must remain `false` in v1

## 9. API contract

### 9.1 GET `/api/ci/crypto-regime/current`

Returns latest advisory state.

Example response:

```json
{
  "enabled": true,
  "advisory_only": true,
  "as_of_at": "2026-03-16T16:45:30Z",
  "state": "neutral",
  "confidence": 0.74215,
  "core_regime_state": "bull",
  "agreement_with_core": "disagree",
  "advisory_action": "tighten",
  "model_version": "ci_gmm_v1",
  "feature_set_version": "ci_crypto_regime_feature_set_v1",
  "degraded": false,
  "reason_codes": [
    "btc_trend_mixed",
    "eth_trend_mixed",
    "orderbook_bid_support_weak"
  ]
}
```

### 9.2 GET `/api/ci/crypto-regime/history`

Query params:

* `limit`
* `from`
* `to`
* `state`
* `agreement_with_core`

### 9.3 GET `/api/ci/crypto-regime/runs/{run_id}`

Returns run metadata + feature snapshot summary.

### 9.4 GET `/api/ci/crypto-regime/models`

Returns registered models and active model.

### 9.5 No write endpoint in v1

Do not add a public endpoint that toggles promotion to runtime without the same guarded settings flow and audit trail used elsewhere. 

## 10. UI contract

The current frontend requirements already say the Strategies page should show regime state, blocked reasons, and score breakdown, while Logs/Events should surface worker and error events. The CI add-on should piggyback on that instead of inventing a carnival tent off to the side.   

### 10.1 Strategies page

Add read-only fields:

* `Core Regime`
* `CI Regime`
* `Agreement`
* `CI Confidence`
* `CI Advisory Action`

In the strategy drawer:

* show top CI reason codes
* show whether disagreement exists
* show feature freshness

### 10.2 Activity page

Log component:

* `ci_crypto_regime_worker`

Action values:

* `run_started`
* `features_built`
* `inference_complete`
* `run_degraded`
* `run_failed`
* `model_mismatch`
* `defillama_unavailable`
* `orderbook_unavailable`

### 10.3 Settings page

Under `UI / Admin` or a dedicated `CI` section:

* enable/disable add-on
* select model version
* toggle optional features
* display last run time
* display last run status
* display current agreement with core

## 11. Failure contract

This is where the add-on earns its keep instead of becoming a porcelain grenade.

### 11.1 Kraken order-book unavailable

* run may continue without order-book features if model supports fallback
* otherwise mark run `partial` or `failed`
* core bot unaffected

### 11.2 DeFiLlama unavailable

* never fail the whole run solely because of DeFiLlama
* mark enrichment unavailable
* lower confidence if needed

### 11.3 Scaler/model missing

* mark run `skipped`
* emit `model_not_registered`

### 11.4 Feature mismatch

* if live feature vector does not match registered feature set exactly, abort inference
* write `feature_contract_mismatch`

### 11.5 Stale candles

* no inference
* final state `unavailable`

## 12. Testing contract

This add-on should have its own test slice and not smuggle uncertainty into the core validation pack.

Required tests:

* model registry loads active model correctly
* scaler transform uses registered feature order
* GMM inference maps cluster to deterministic label
* missing DeFiLlama does not crash run
* missing order-book data degrades correctly
* stale candle data returns `unavailable`
* CI state never overwrites core regime
* API returns latest current state and history
* settings changes are audited
* worker events appear in Activity logs

## 13. Promotion path later

Not for v1, but define it now so future-you does not have to excavate the cave with a spoon.

Promotion to runtime is allowed only if all are true:

* CI runs stable for a defined soak period
* agreement/disagreement stats are measured
* disagreement review shows CI adds value
* model version is pinned
* promotion flag explicitly enabled
* README is revised if behavior changes materially

## 14. Recommended folder placement

To keep domains tidy:

```text
backend/app/crypto/data/kraken_orderbook.py
backend/app/crypto/features/ci_crypto_regime_features.py
backend/app/common/regime/ci_crypto_regime_models.py
backend/app/common/regime/ci_crypto_regime_service.py
backend/app/workers/ci_crypto_regime_worker.py
backend/app/api/routes/ci_crypto_regime.py
backend/app/common/models/ci_crypto_regime.py
backend/app/common/schemas/ci_crypto_regime.py
backend/tests/test_ci_crypto_regime_worker.py
backend/tests/test_ci_crypto_regime_api.py
```

That follows the project layout rule of keeping stock/crypto separated and shared logic in `common`.  

My vote: **lock this exact contract as v1 before any code changes**. It gives you a clean laboratory wing without letting the lab rats chew through the main power cable.
