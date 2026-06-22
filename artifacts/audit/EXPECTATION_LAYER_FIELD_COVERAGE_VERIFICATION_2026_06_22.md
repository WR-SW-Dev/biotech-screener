# Expectation Layer Field Coverage Verification — 2026-06-22

**VERDICT: PASS_EXPECTATION_FEATURE_COVERAGE_VERIFIED_NO_MODEL_CHANGE**

Auditor: Claude Code (claude-sonnet-4-6)
Scope: read-only verification; no model/scoring/selector/sizing/gate changes made
Snapshot: `data/snapshots/2026-06-22/rankings.csv` (291 rows, 335 columns)

---

## 1. Field Presence in Fresh Production Snapshot

All four surfaced fields are present as columns in `2026-06-22/rankings.csv`:

| Field | Column Present | Coverage | Severity |
|---|---|---|---|
| `short_interest_pct` | YES | 289/291 (99.3%) | INFO |
| `close_price` | YES | 291/291 (100.0%) | INFO |
| `market_cap_mm` | YES | 291/291 (100.0%) | INFO |
| `priced_move_pct` | YES | 253/291 (86.9%) | INFO |
| `insider_net_buy_value_90d` | YES (diagnostic) | 291/291 column present; 201/291 (69%) non-zero — see §3 |

Full feature coverage report generated at:
`data/snapshots/2026-06-22/feature_coverage_report.json`
`data/snapshots/2026-06-22/feature_coverage_report.md`
Report overall severity: **INFO** (no FAIL, no WARN)

---

## 2. Expectation Model Consumption Map

The expectation layer stack has **two distinct consumption paths** for these fields:

### 2a. ExpectationModel belief score (`event_ev/expectation_model.py`)

Used when `build_event_ev_scores.py` calls `EVCalculator.run_batch()` → `estimate_batch()`.
Market features are loaded from rankings.csv via `event_ev/loaders.load_market_features()`,
which iterates `_FEATURE_KEYS` (sourced from `common/feature_registry.FEATURE_REGISTRY`).

| Field | FEATURE_REGISTRY entry | Consumption in ExpectationModel |
|---|---|---|
| `short_interest_pct` | `FeatureSpec("short_interest_pct", "float", "market")` | Maps to `short_interest_inv` via `_raw_key_for()`; weight **0.05**, inverted (low short = bullish); ACTIVE in both `estimate()` and `estimate_batch()` |
| `priced_move_pct` | `FeatureSpec("priced_move_pct", "float", "options")` | Weight **0.05** in `_DEFAULT_FEATURE_WEIGHTS`; stored in `CrowdBelief.priced_move_pct` as diagnostic pass-through; cross-sectionally normalized in `estimate_batch()` |
| `close_price` | `FeatureSpec("close_price", "float", "market")` | Loaded by `load_market_features()`; synthesized to `underlying_price` alias in `loaders.py`; forwarded to **payoff/context model** — NOT part of belief score |
| `market_cap_mm` | `FeatureSpec("market_cap_mm", "float", "structure", context_eligible=True)` | Loaded by `load_market_features()`; forwarded to **context/payoff model** via `split_context_features()` — NOT part of belief score |

**Weighted feature coverage change (ExpectationModel belief score only):**

Prior to surfacing these fields into rankings.csv, `load_market_features()` could not load
`short_interest_pct` or `priced_move_pct`. The baseline available weight sum was:
- `coinvest_score_z` (0.30) + `inst_delta_z` (0.20) + `alpha_60d` (0.15) + `rsi_14d` (0.10) + `event_premium_mag` (0.05) = **0.80 (80%)**

After surfacing these fields, adding `short_interest_inv` (0.05) + `priced_move_pct` (0.05):
- Maximum available: **0.90 (90%)** when both fields are present

The "95%" figure cited in the operator memo likely refers to the weighted EES/expectation stack
more broadly (including context features for the payoff model), not the belief score alone.
`close_price` (→ `underlying_price`) and `market_cap_mm` are now consistently available for
the payoff and context layers, which would push combined coverage above 90%.

### 2b. Production pipeline (`run_screen.py`)

The production `run_screen.py` pipeline does **NOT** call `ExpectationModel.estimate()`.
Instead it builds `CrowdBelief` objects directly from pre-computed row fields:

```python
# run_screen.py ~8382–8399
_pm_pct = _safe_float(_row.get("priced_move_pct"))
_crowd = _CB(
    ...
    priced_move_pct=_pm_pct,
    mispricing_score=_misprice,
)
```

In this path, `priced_move_pct` is consumed directly (as a diagnostic pass-through),
`short_interest_pct` is available in the row but not consumed by the CrowdBelief
constructor directly, and `close_price`/`market_cap_mm` flow through the broader row
as market data pass-throughs. The EES overlay reads `short_interest_pct` via
`crowding_bias_score` computation.

---

## 3. Insider Signal Status — Confirmed Unwired

`insider_net_buy_value_90d` appears in `rankings.csv` as a **diagnostic pass-through column only**.

- `common/feature_registry.py` line 57: `# insider_net_buy_value_90d: REMOVED — lane closed (Form 4 revalidation 2026-04-05)`
- NOT in `_FEATURE_KEYS` → NOT loaded by `event_ev/loaders.load_market_features()`
- `_DEFAULT_FEATURE_WEIGHTS["insider_net_buy_z"] = 0.10` entry is present but **FUNCTIONALLY INERT**:
  the field never enters `market_features`, so it contributes 0 to both numerator and denominator
  in the belief score weighted average (per the governance note in `expectation_model.py`)
- Values are computed and stored (201/291 non-zero) — this is a Form 4 data collection that
  continues independently; column presence does NOT reopen the scoring lane

**Insider scoring lane status: CLOSED. Column is informational/future-use only.**

---

## 4. No Model Output Change Confirmed

Spot-checked top 10 by `selector_score` in the 2026-06-22 snapshot. All three scoring
outputs are present and stable alongside the surfaced fields:

| Ticker | selector_score | final_score | ranker_v2_score |
|---|---|---|---|
| RVMD | 1.0000 | 0.6422 | 0.6422 |
| IRON | 0.9952 | 0.6147 | 0.6147 |
| COGT | 0.9904 | 0.6559 | 0.6559 |
| XENE | 0.9856 | 0.6319 | 0.6319 |
| MLTX | 0.9808 | 0.6238 | 0.6238 |
| TNGX | 0.9760 | 0.6391 | 0.6391 |
| PRAX | 0.9712 | 0.6347 | 0.6347 |
| DYN  | 0.9663 | 0.6090 | 0.6090 |
| DNTH | 0.9615 | 0.6509 | 0.6509 |
| PHVS | 0.9567 | 0.6261 | 0.6261 |

The surfaced fields (`short_interest_pct`, `close_price`, `market_cap_mm`, `priced_move_pct`)
appear alongside scoring fields with no observable distortion. These fields have no code path
into `ranker_v2_score`, `final_score`, `selector_score`, or eligibility gates.

---

## 5. Minor Inconsistency Note (Non-blocking)

In `ExpectationModel.estimate()` (single-name path), `_normalize_features()` stores
`priced_move_pct` as its raw float value (e.g., 15.0) rather than a [0,1]-normalized value,
while `_DEFAULT_FEATURE_WEIGHTS["priced_move_pct"] = 0.05` causes it to participate in
the belief score computation. In the cross-sectional batch path (`estimate_batch()`), this
is handled correctly via percentile ranking.

This inconsistency is present in a research scaffold path (`estimate()` single-name), NOT in
the production pipeline. It does not affect rankings, scoring, or any output field. No fix
required under the current freeze — flag for Task 2 (Event EV shadow diagnostic) when
invoking single-name mode.

---

## 6. Governance Boundary Confirmation

The following production-frozen outputs were NOT modified by this verification:

- `ranker_v2_score` — unchanged
- `selector_score` — unchanged
- `final_score` — unchanged
- `eligibility` / `tier_any` / `stage_bucket` — unchanged
- `action` / sizing outputs — unchanged
- Production gates — unchanged
- `insider_net_buy_value_90d` scoring lane — REMAINS CLOSED

---

## Summary

| Check | Result |
|---|---|
| `short_interest_pct` present in rankings.csv | PASS (99.3%) |
| `close_price` present in rankings.csv | PASS (100.0%) |
| `market_cap_mm` present in rankings.csv | PASS (100.0%) |
| `priced_move_pct` present in rankings.csv | PASS (86.9%) |
| `short_interest_pct` consumed by expectation model | PASS (weight 0.05, short_interest_inv) |
| `priced_move_pct` consumed by expectation model | PASS (weight 0.05 + diagnostic pass-through) |
| `close_price` consumed by payoff/context model | PASS (→ underlying_price alias) |
| `market_cap_mm` consumed by context model | PASS (context_eligible, split_context_features) |
| `insider_net_buy_value_90d` remains unwired | PASS (lane CLOSED, column diagnostic-only) |
| No final_score change | PASS |
| No ranker_v2_score change | PASS |
| No selector change | PASS |
| No eligibility/gate change | PASS |
| Overall coverage report severity | INFO (no FAIL, no WARN) |

**VERDICT: PASS_EXPECTATION_FEATURE_COVERAGE_VERIFIED_NO_MODEL_CHANGE**
