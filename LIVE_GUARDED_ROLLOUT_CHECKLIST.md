# Live Guarded Rollout Checklist

Use this checklist before enabling meaningful live routing for either asset class.

The goal is not speed. The goal is a clean first live day with visible controls, reversible actions, and an honest audit trail.

---

## 1. Preflight state

Confirm these first:

- backend health endpoint is green
- frontend is reachable
- latest backup was created with `scripts\backup_project.ps1`
- latest `pytest -q` passed
- kill switch behavior is understood by the operator
- stock and crypto live/paper modes are intentional
- trading-enabled toggles are intentional
- no unresolved critical system events are present

---

## 2. Route mode review

Before live rollout, confirm:

- `execution.default_mode` is intentional
- `execution.stock.mode` is intentional
- `execution.crypto.mode` is intentional
- paper remains the default unless explicitly changing a route
- only the asset class being promoted is moved live
- the other asset class stays unchanged unless explicitly requested

---

## 3. Kill switch validation

Required before first live use.

Recommended sequence:

1. enable kill switch
2. run the kill switch validation endpoint
3. confirm validation result is recorded in trade audit events
4. confirm no new entries route while the kill switch is engaged
5. disable kill switch only after validation is complete

Notes:

- flatten remains honest and manual-follow-up oriented when broker liquidation is not truly implemented
- do not treat a toggle alone as proof; capture the validation result and audit event

---

## 4. Circuit breaker validation

Required before increasing live confidence.

For each asset class being considered for live routing:

1. inspect risk sync state
2. confirm breaker settings are present and intentional
3. run the circuit breaker validation endpoint
4. verify the validation result is written to trade audit events
5. verify tripped breaker states are visible and interpretable

Notes:

- if a breaker has not been observed in runtime yet, mark validation as incomplete rather than pretending it passed
- breaker recovery should remain deliberate and operator-reviewed

---

## 5. Trade audit logging review

Before live rollout, confirm the audit trail can show:

- kill switch toggle events
- kill switch validation events
- circuit breaker validation events
- order routed events
- order route failure events
- fill persisted events
- manual flatten requests

Questions to answer:

- can you tell what was attempted?
- can you tell what actually routed?
- can you tell which mode and venue were used?
- can you tell whether the action was paper or live?

---

## 6. Post-trade review workflow

After any paper or live fill, review:

- order status
- fill status
- stop protection status
- position reconciliation status
- related audit events
- any mismatch or warning notes

Minimum expectation:

- every reviewed trade should be explainable without digging through unrelated code

---

## 7. Rollout shape

Recommended guarded sequence:

### Step A
- keep both asset classes paper
- verify checklist, validation endpoints, and audit feed

### Step B
- move one asset class live with the smallest practical size
- leave the other asset class unchanged
- watch audit feed and post-trade review after every fill

### Step C
- only after stable operation, consider enabling the second asset class live

---

## 8. Abort conditions

Stop and re-evaluate if any of these occur:

- kill switch cannot be validated cleanly
- circuit breaker state is unclear
- route mode is ambiguous
- live/paper labeling is confusing
- audit feed does not clearly show actions and outcomes
- reconciliation mismatches remain unresolved
- operator cannot explain what happened after a routed order

---

## 9. Success criteria for guarded rollout

The rollout is behaving correctly when:

- live routing works for the intended asset class
- position size remains disciplined
- kill switch validation is captured
- circuit breaker validation is captured
- audit events are readable and useful
- post-trade review gives a coherent trade story
- the operator can stop new entries quickly if needed
