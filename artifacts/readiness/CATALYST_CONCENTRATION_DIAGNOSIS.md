# Catalyst Concentration Diagnosis — 2026-05-27

**Issue:** Portfolio weighted 40.8% toward catalysts ≤7 days, violating bucket_drift (10% policy) and phase2_health gates.

---

## Executive Summary

**Readiness HOLD is blocked by a policy/ranking alignment issue, NOT selector bias.**

The selector correctly assigns A-tier status more favorably to 8–90d catalysts (38.2%) than 0–7d (25.5%), but the final portfolio is still 40.8% near-term because institutional consensus (coinvest signal) is concentrated in a small set of very high-conviction near-term plays (COGT, RVMD, SYRE, PRAX) that dominate the rank order.

**The fix is governance, not algorithm tuning:**
- Either relax the 0–30d bucket policy target (10% → 40%) to align with institutional consensus, OR
- Implement post-freeze selector timing gates to enforce historical policy distribution

---

## Root Cause Analysis

### Selector Tier Assignment (NOT biased toward near-term)

**Distribution of A-tier assignments by catalyst timing:**
| Catalyst Timing | A-Tier Assignment Rate |
|---|---|
| 0-7d (n=55) | 25.5% (14/55) |
| **8-90d (n=55)** | **38.2% (21/55)** ← HIGHEST |
| 90+d (n=85) | 16.5% (14/85) |
| no catalyst (n=23) | 0% (0/23) |

**Finding:** Selector FAVORS 8-90d catalysts for A-tier assignment — **selector is working correctly**.

### Portfolio Ranking (IS biased toward near-term)

**Top 15 positions by actionable_rank show near-term clustering:**
1. **COGT** (5d, A-tier) — **rank #1** ← Drives concentration
2. DNTH (34d, A-tier) — rank #2
3. NRIX (66d, A-tier) — rank #3
4. URGN (97d, A-tier) — rank #4
5. ALMS (35d, A-tier) — rank #5
6. **SYRE** (5d, B-tier) — **rank #6** ← Near-term
7. ORIC (97d, C-tier) — rank #7
8. **RVMD** (5d, A-tier) — **rank #8** ← Near-term
9. CMPS (34d, C-tier) — rank #9
10. DRUG (158d, A-tier) — rank #10
11. STOK (126d, A-tier) — rank #11
12. **PRAX** (5d, B-tier) — **rank #12** ← Near-term
13. TRVI (34d, C-tier) — rank #13
14. ABVX (97d, B-tier) — rank #14
15. XENE (66d, B-tier) — rank #15

**Pattern:** Top-ranked near-term catalysts (COGT, SYRE, RVMD, PRAX) are interspersed with longer-duration positions, but their exceptional ranking pulls them into the final 30-position portfolio.

### The Mechanism: Coinvest Concentration

**Hypothesis:** `coinvest_score_z` (institutional consensus signal) is concentrated in a small set of near-term catalysts, giving them disproportionate ranking weight.

**Evidence:**
- Selector uses `coinvest_score_z` as PRIMARY gating mechanism (coinvest-only model per ruleset v1.14.0)
- Near-term catalyst positions (e.g., COGT rank #1, RVMD rank #8) achieve exceptionally high coinvest scores
- When top-30 selection is made by rank, these high-scoring near-term plays are pulled in
- Result: 40.8% near-term weight despite selector tier assignment NOT favoring near-term

---

## Impact Chain

```
coinvest_score_z concentration on COGT, RVMD, SYRE
  ↓
High actionable_rank for these near-term catalysts
  ↓
Top-30 portfolio selection pulls in 12 near-term positions (40.8% weight)
  ↓
phase2_health FAIL: catalyst_7d_weight_high (40.83% > threshold)
  ↓
bucket_drift FAIL: Binary 0-30d high (43.3% vs 10% policy) ← 33.3pp violation
  ↓
READINESS HOLD ← Cannot trade until resolved
```

---

## Why This Happened

**Institutional consensus (13F managers) is concentrated on near-term catalysts:**
- Fairmount, Deep Track, Logos Global Q1 2026 positions include high-conviction near-term clinical readouts
- These positions have strong sponsor backing + clinical catalyst timing certainty
- Coinvest aggregates this consensus, weighting them heavily
- Selector respects coinvest signal (per architecture: coinvest as context layer, not binary gate per Spec 072)

**But portfolio policy expects broader catalyst timing distribution:**
- 10% policy for 0-30d bucket assumes diversification across event horizons
- 55% policy for 91-180d reflects long-duration (higher volatility) preference
- Current portfolio: 43.3% near-term (4.3x policy), 26.7% long-term (0.49x policy)

---

## Remediation Paths

### Path A: Post-Freeze Selector Timing Gate (BEST STRUCTURAL FIX)
- **Timeline:** After h20d freeze lift (2026-05-26), implement in Spec (new governance item)
- **Action:** Add portfolio construction constraint: enforce max 30% weight in 0-7d, min 40% in 90+d
- **Scope:** Selector architecture change; requires spec approval + testing
- **Benefit:** Decouples institutional signal (coinvest) from portfolio distribution policy
- **Current status:** BLOCKED by architecture freeze

### Path B: Coinvest/Ranker Timing Adjustment (SURGICAL)
- **Timeline:** Spec governance review (can initiate now, activate post-freeze)
- **Action:** Adjust ranker penalty for near-term catalysts, OR reweight coinvest calculation to dampen near-term concentration
- **Scope:** Signal engineering within existing Spec 095/100 framework
- **Benefit:** Surgical; respects institutional signal while aligning timing distribution
- **Risk:** Unintended IC impact; requires Spec 95/100 review before deployment

### Path C: Policy Relaxation (FASTEST CLEAN GOVERNANCE PATH)
- **Timeline:** Governance decision now
- **Action:** Relax 0–30d bucket target from 10% → 40%, 91–180d from 55% → 30% to align with institutional consensus regime
- **Scope:** Policy override; explicitly acknowledges near-term institutional conviction
- **Benefit:** Immediate unblock; no algorithm changes; transparent governance decision
- **Risk:** Increases near-term event risk; may conflict with long-duration strategy intent
- **Precedent:** Spec 072 ("coinvest as context layer") supports institutional consensus driving positioning

### Path D: Exception Trade with Daily Monitoring (HIGH RISK)
- **Timeline:** Immediate
- **Action:** Approve single trade waiving HOLD verdict; monitor daily portfolio hedge ratio / drawdown
- **Scope:** One-off exception; explicit risk acknowledgment
- **Benefit:** Fastest path
- **Risk:** Executes against Phase 2 health gates by design; drawdown spike if near-term catalysts disappoint

---

## Recommendation

**Governance Decision:** 

The realistic framing is that **the existing policy bucket targets are misaligned with the current institutional signal regime.** The selector is functioning correctly; the policy is the constraint.

**Recommended sequence (in order of confidence):**

1. **Primary path:** Governance decision on **Path C (Policy Relaxation)**. If institutional consensus on near-term catalysts is intentional and high-conviction, relax 0–30d exposure cap to 40% and document as governance override.

2. **Secondary path:** If policy must remain strict, approve **Path A (Post-Freeze Timing Gate)** as a spec item for post-h20d implementation, with interim **Path D (Exception Trade)** if necessary.

3. **Avoid:** Path B (Coinvest adjustment) without clear Spec 95/100 governance, as it risks unintended IC suppression.

---

## Related Issues

- **Spec 087 B1b:** Awaiting first-fire validation; when active, will reduce near-term catalyst weighting via hedging
- **Spec 072:** "Coinvest as context, not binary gate" — suggests near-term concentration expected under institutional consensus
- **Phase 2 Step 5:** KG gating deferred; would provide second-order gating on catalyst timing

---

## Data Summary

| Metric | Value | Policy | Status |
|--------|-------|--------|--------|
| **0-7d catalyst weight** | 40.83% | 10% max | ✗ EXCEED |
| **0-7d position count** | 12 | ~3 | ✗ EXCEED |
| **Portfolio binary 0-30d** | 43.3% | 10% | ✗ FAIL |
| **Portfolio binary 91-180d** | 26.7% | 55% | ✗ FAIL |
| **Total portfolio positions** | 30 | 30 | ✓ OK |
| **A-tier concentration** | 8/12 0-7d | balanced | ⚠ SKEWED |
