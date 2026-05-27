# Catalyst Concentration Diagnosis — 2026-05-27

**Issue:** Portfolio weighted 40.8% toward catalysts ≤7 days, violating bucket_drift (10% policy) and phase2_health gates.

---

## Executive Summary

**Readiness remains in HOLD.** The blocker is not selector bias, but policy/ranking alignment.

The selector correctly assigns A-tier status more favorably to 8–90d catalysts (38.2%) than 0–7d (25.5%), but the final portfolio is still 40.8% near-term because institutional consensus (coinvest signal) is concentrated in a small set of very high-conviction near-term plays (COGT, RVMD, SYRE, PRAX) that dominate the rank order.

**Current constraint:** Portfolio violates catalyst-timing policy and Phase-2 health constraints.

**Core question:** Is the current signal/policy mismatch a temporary opportunity worth relaxing for, or a risk the portfolio construction layer must constrain?

**Governance decision required:** Choose one of three paths (relax policy, enforce gates post-freeze, or approve exception trade with monitoring).

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

## Governance Decision Paths

**The signal is real; the policy is misaligned with the current regime.** Governance must decide whether that mismatch represents a temporary opportunity worth relaxing for, or a risk the portfolio construction layer must constrain.

---

### Path C: Temporary Policy Override (FASTEST UNBLOCK)
- **Timeline:** Governance decision now
- **Action:** Explicitly override Phase-2 health / bucket-drift constraints for 2026-05-27 snapshot
- **Terms:** Relax 0–30d bucket target from 10% → 40% (current 43.3%) and 91–180d from 55% → 26.7% (current state)
- **Duration:** Temporary; reassess 2026-06-03 after IC monitoring window closes
- **Rationale:** Spec 072 ("coinvest as context layer") supports institutional consensus driving positioning; current 13F concentration on near-term catalysts is real and justified
- **Governance stance:** Accepts near-term event-risk concentration as intentional opportunity
- **Status:** NOT a clean readiness pass; this is a controlled policy exception
- **Risk:** Heightened drawdown exposure if near-term catalysts disappoint; must monitor daily

---

### Path A: Post-Freeze Portfolio Construction Gate (BEST DURABLE FIX)
- **Timeline:** After h20d freeze lift (2026-05-26), design and implement as spec item (2026-06-01+)
- **Action:** Add hard timing constraints to portfolio construction: enforce max 30% weight in 0–7d, min 40% in 90+d
- **Scope:** Selector/ranker architecture change; separates signal strength from portfolio distribution policy
- **Benefit:** Durable; preserves coinvest signal while enforcing policy diversification; no ongoing governance risk
- **Current status:** BLOCKED by architecture freeze (cannot implement until 2026-05-26 lift)
- **Interim:** Can proceed with **Path C (Policy Override)** while designing this fix

---

### Path B: Ranker / Coinvest Timing Adjustment (AVOID UNTIL SPEC REVIEW)
- **Timeline:** Spec 95/100 governance review required before implementation
- **Action:** Dampen coinvest concentration on near-term catalysts via ranker penalty, or reweight coinvest calculation
- **Risk:** Penalizing near-term coinvest could suppress institutional signal IC or distort the evidence base
- **Status:** Surgical in principle, but requires careful IC impact review
- **Recommendation:** Defer until Spec 95/100 review signals clear that IC dampening is acceptable

---

### Path D: Exception Trade (LAST RESORT ONLY)
- **Timeline:** Immediate
- **Action:** Approve single trade waiving Phase-2 health / bucket-drift HOLD verdict; establish daily monitoring gate
- **Scope:** Explicit readiness hold waiver; NOT a remediation, just a risk acknowledgment
- **Monitoring:** Daily portfolio hedge ratio, drawdown vs. XBI, near-term catalyst weight changes
- **Exit trigger:** If portfolio drawdown > 2pp relative to XBI by end-of-week, pause further positioning
- **Risk:** Highest; executes against readiness gates by design
- **Use case:** Only if governance needs trading while deliberating Paths C/A

---

## Governance Recommendation

**The signal is real. The policy is misaligned. Governance decides.**

- **If governance views the mismatch as an opportunity:** Choose **Path C** and temporarily relax policy. Explicit override; transparent accountability.

- **If governance views it as unmanaged concentration risk:** Choose **Path A** and enforce portfolio timing gates post-freeze. Best durable fix.

- **If governance is uncertain:** Maintain **HOLD**. Use **Path D** only as an explicit, accountable HOLD waiver with daily monitoring — not as a neutral bridge, but as an exception trade against Phase-2 health gates.

**Decision order (in sequence):**

1. **Immediate (2026-05-27):** Governance chooses stance on policy/signal mismatch
   - **Opportunity** → Path C (policy override with monitoring)
   - **Risk** → Maintain HOLD pending Path A design
   - **Accountable exception needed** → Path D (explicit HOLD waiver only)

2. **Post-freeze (2026-05-26+):** If HOLD maintained, design and implement **Path A (Portfolio Timing Gate)** as permanent fix

3. **Ongoing:** **Avoid Path B (Coinvest Adjustment)** until Spec 95/100 signals that IC impact is acceptable

---

## Canonical HOLD Framing

- **Selector:** Working as designed; no demonstrated near-term tiering bias.
- **Signal:** Real, observable, and materially concentrated in near-term catalysts.
- **Policy:** Misaligned with the current signal regime; requires governance decision.
- **Path D:** Exception trade only, not a neutral bridge. Requires explicit operator accountability.

---

## Final Statement

> Readiness HOLD is blocked by a real policy/ranking alignment issue. The selector is not biased; institutional consensus on near-term catalysts is concentrated and real. **Governance must decide:** Is this mismatch a temporary opportunity to relax policy for, or a concentration risk that requires portfolio construction gates? If uncertain, maintain HOLD; Path D is an exception trade, not a neutral bridge.

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

---

## GOVERNANCE DECISION — 2026-05-28

**Path C APPROVED: Temporary Policy Override**

Operator approved Path C effective 2026-05-28:
- Allow 0–30d exposure up to 40–45% (temporary)
- Monitor through 2026-06-03 forward eval IC window
- Revoke if mean_ic < 0.0200 at window close or drawdown breaches limits
- Path A (durable portfolio timing gates) mandated as post-freeze follow-on

**See:** `GOVERNANCE_DECISION_PATH_C_2026_05_28.md` for full decision memo, constraints, and Path A design target.
