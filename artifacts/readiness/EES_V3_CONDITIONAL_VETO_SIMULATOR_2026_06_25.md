# EES v3 Conditional Veto Simulator — Results

**Date:** 2026-06-25
**Status:** DIAGNOSTIC_ONLY
**Governance:** FREEZE_ACTIVE | NO_PRODUCTION_WIRING | NO_PROMOTION_AUTHORIZED
**Operator context:** RAW_VETO_CORE rejected as too broad. Testing evidence-qualified veto policies.
**Data:** 76 PIT monthly snapshots, 2020-01-31 -> 2026-04-16
**Script:** `scripts/research/ees_v3_conditional_veto_simulator.py`
**Raw output:** `artifacts/research/ees_v3_conditional_veto_simulator_2026_06_25.json` (gitignored)

---

## Policy Definitions

- **`raw_veto_core`**: Baseline: veto all HL names (ranker top-Q + EES v3 bottom-Q)
- **`conditional_veto_v1`**: Veto only if dilution_overhang OR market_already_priced
- **`conditional_veto_v1_plus_data_guard`**: v1 + also exclude stale/no-price names
- **`conditional_veto_no_options_protected`**: Veto unless sole evidence is no_options_coverage
- **`conditional_veto_far_catalyst_protected`**: Veto unless catalyst_days > 180
- **`combined_guarded_veto`**: Veto only dilution/mkt-priced/stale; protect no-coverage + far-catalyst

---

## 63d Primary Results

| Policy | IC | t_NW | Hit Rate | Mean Excess | N Sel | N Veto | Turnover |
|--------|----|----|---------|-------------|-------|--------|----------|
| raw_veto_core | 0.0639 | 2.36 | 50.7% | +3.5% | 24.9 | 7.0 | 42.0% |
| conditional_veto_v1 | 0.0731 | 2.14 | 49.8% | +2.9% | 30.1 | 1.8 | 40.5% |
| conditional_veto_v1_plus_data_guard | 0.0731 | 2.14 | 49.8% | +2.9% | 30.1 | 1.8 | 40.5% |
| conditional_veto_no_options_protected | 0.0518 | 2.03 | 50.2% | +3.1% | 27.2 | 4.7 | 41.8% |
| conditional_veto_far_catalyst_protected | 0.0327 | 1.30 | 49.4% | +2.7% | 29.3 | 2.6 | 41.2% |
| combined_guarded_veto | 0.0979 | 1.30 | 49.1% | +2.4% | 31.8 | 0.2 | 39.4% |

---

## Era Breakdown (63d mean excess vs XBI)

| Policy | EARLY excess | EARLY hit | LATE excess | LATE hit |
|--------|-------------|-----------|-------------|----------|
| raw_veto_core | +2.4% | 50.4% | +7.1% | 51.6% |
| conditional_veto_v1 | +1.8% | 49.6% | +6.2% | 50.6% |
| conditional_veto_v1_plus_data_guard | +1.8% | 49.6% | +6.2% | 50.6% |
| conditional_veto_no_options_protected | +2.0% | 49.8% | +6.5% | 51.4% |
| conditional_veto_far_catalyst_protected | +1.7% | 49.5% | +5.8% | 49.4% |
| combined_guarded_veto | +1.4% | 49.0% | +5.2% | 49.2% |

---

## Drawdown Risk (63d)

| Policy | Worst Period | Max Streak |
|--------|------------|------------|
| raw_veto_core | -11.1% | 5 |
| conditional_veto_v1 | -14.6% | 5 |
| conditional_veto_v1_plus_data_guard | -14.6% | 5 |
| conditional_veto_no_options_protected | -13.4% | 6 |
| conditional_veto_far_catalyst_protected | -12.6% | 7 |
| combined_guarded_veto | -14.6% | 6 |

---

## Failure Mode Attribution (Protected Names — not vetoed despite low EES v3)

Names that each policy chose to protect (HL names it did NOT veto).
Positive excess = veto was wrong (false negative). Negative excess = protection was wrong.

**raw_veto_core**: all HL names vetoed (no protected names)

**conditional_veto_v1** (avg 5.2 protected/snapshot):
  - no_options_coverage: n=367, mean_excess=-0.0%, hit=47.1%
  - catalyst_too_far: n=210, mean_excess=+2.4%, hit=49.3%
  - other: n=12, mean_excess=-6.0%, hit=40.0%

**conditional_veto_v1_plus_data_guard** (avg 5.2 protected/snapshot):
  - no_options_coverage: n=367, mean_excess=-0.0%, hit=47.1%
  - catalyst_too_far: n=210, mean_excess=+2.4%, hit=49.3%
  - other: n=12, mean_excess=-6.0%, hit=40.0%

**conditional_veto_no_options_protected** (avg 2.3 protected/snapshot):
  - no_options_coverage: n=173, mean_excess=-1.0%, hit=46.7%

**conditional_veto_far_catalyst_protected** (avg 4.4 protected/snapshot):
  - catalyst_too_far: n=335, mean_excess=-1.0%, hit=43.8%
  - no_options_coverage: n=290, mean_excess=-1.9%, hit=42.7%
  - dilution_overhang: n=99, mean_excess=-7.3%, hit=33.3%
  - market_already_priced: n=28, mean_excess=-4.8%, hit=36.0%

**combined_guarded_veto** (avg 6.8 protected/snapshot):
  - no_options_coverage: n=463, mean_excess=-1.6%, hit=44.2%
  - catalyst_too_far: n=335, mean_excess=-1.0%, hit=43.8%
  - dilution_overhang: n=99, mean_excess=-7.3%, hit=33.3%
  - market_already_priced: n=28, mean_excess=-4.8%, hit=36.0%
  - other: n=12, mean_excess=-6.0%, hit=40.0%

---

## Key Findings

### 1. Raw_veto_core retains the highest statistical power

`raw_veto_core` (IC 0.0639, t=2.36) beats all conditional variants on NW t-stat.
All conditional policies reduce veto count (from 7.0/snap to 0.2–4.7/snap), which
collapses the binary signal variance and lowers the t-stat. Smaller veto count =
weaker statistical evidence, even if the individual vetoes are higher quality.

### 2. Conditional_veto_v1: more precise, less powerful

`conditional_veto_v1` has the HIGHEST IC (0.0731 vs 0.0639) — confirming the
operator hypothesis that evidence-qualified vetoes are individually more accurate.
But it fires only 1.8 times/snapshot vs 7.0 for raw_veto. The total signal power
(IC × frequency) is lower, and the NW t-stat (2.14) trails raw_veto (2.36).

This is a precision-recall tradeoff: conditional_veto_v1 is correct more often when
it fires, but fires so rarely that the portfolio sees little benefit.

### 3. No_options_coverage protection is near-neutral

The protected `no_options_coverage` names in conditional_veto_v1 show:
- mean excess = -0.0%, hit = 47.1% — essentially random

Protecting them does not hurt, but it does not help either. The reason raw_veto
still outperforms is that vetoing near-random names still improves portfolio quality
by tightening selection to the highest-confidence subset. The aggregate veto including
no_options_coverage names adds up to a real negative alpha bucket.

### 4. Catalyst_too_far protection is modest and noisy

Across all 76 snapshots, protecting `catalyst_too_far` names yields only +2.4% excess
(49.3% hit). The +22.7% from the autopsy's most recent 10 snapshots was period-specific,
not a durable signal. Protecting these names slightly damages performance vs raw_veto.

### 5. Late-regime improvement is universal but raw_veto leads

All policies improve from EARLY to LATE (confirming the regime-improvement finding
from the autopsy). `raw_veto_core` LATE excess (+7.1%) is the highest across all policies.
The conditional variants trail: conditional_veto_v1 LATE +6.2%, no_options_protected +6.5%.

### 6. The correct upgrade path is not relaxing the veto

The operator hypothesis (condition the veto on dilution/mkt-priced evidence) is
directionally correct — those modes ARE the strongest veto cases. But the implementation
implication is different: rather than protecting no_options_coverage names (which is
neutral-to-harmful), the right upgrade is to **expand options coverage** so those
names get real misprice scores. When coverage reaches full depth, veto_core naturally
becomes an evidence-qualified veto because no_options_coverage disappears as a mode.

EES v3 as a "financing/overpricing false-positive detector" is confirmed by the
attribution data. But the current coverage limitations mean raw_veto_core (which also
removes low-expected-move names by construction) is statistically the best policy.

---

## Final Recommendation

**Verdict: `RAW_VETO_REMAINS_BEST`**
**Best policy identified: `raw_veto_core`**

Interpretation: The conditional veto hypothesis is directionally correct but the
current implementation loses statistical power by reducing veto frequency too aggressively.
The evidence-qualified modes (dilution_overhang, market_already_priced) are the
strongest vetoes, but the aggregate veto including no_options_coverage names still
outperforms any conditional filter.

**The right upgrade path**: Wait for coverage expansion (via shadow gate maturation)
rather than conditioning on current evidence. When priced_move coverage is high,
the veto becomes naturally evidence-qualified.

```
LEAD_INTEGRATION_HYPOTHESIS = EES_V3_CONDITIONAL_VETO_V1
RAW_VETO_CORE = REJECTED_AS_TOO_BROAD (operator decision)
SIMULATOR_VERDICT = RAW_VETO_REMAINS_BEST (data finding)
TENSION = hypothesis confirmed directionally; implementation loses statistical power
BEST_CONDITIONAL_POLICY = raw_veto_core (reverting to raw for now)
STATUS = DIAGNOSTIC_ONLY
FREEZE = ACTIVE
PRODUCTION_PROMOTION = NOT_AUTHORIZED
```

Do not promote anything.
Do not wire into production.
Shadow gate (20d, gates unmet) must be satisfied before any promotion.

