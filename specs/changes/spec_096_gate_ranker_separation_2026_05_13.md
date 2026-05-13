# Spec 096 — Gate/Ranker Separation Doctrine

**Status**: SPEC ONLY (classification + documentation)  
**Date**: 2026-05-13  
**Priority**: 4 (architecture clarity, no implementation)  
**Investment**: ~3–4 hours (signal audit + classification)

---

## Problem Statement

Current production ranking mixes **eligibility gates** (hard risk controls), **alpha ranker features** (ordering signals), and **risk overlays** (drawdown, beta constraints) without clear separation. This creates ambiguity about:

1. What is a gate vs. an alpha feature?
2. Should risk controls appear in the ranker score or as separate overlays?
3. Which signals belong in the production ranker vs. shadow-only?

Spec 096 documents the separation framework and classifies all current signals.

---

## Investment Logic

- Architectural clarity improves future ranker design and evaluation
- Prevents false alpha claims (e.g., liquidity screening is a gate, not a ranking signal)
- Spec 072 (Screener vNext) depends on clear gate/ranker separation
- No production change; pure documentation

---

## Exact Evidence Needed

### 1. Gate / Risk Control / Alpha Candidate Classification

For each signal below, classify as:
- **GATE**: hard eligibility filter (fail = name excluded)
- **RISK_OVERLAY**: soft risk control (applied post-ranking)
- **ALPHA_CANDIDATE**: ordering signal within eligible set
- **SHADOW_ONLY**: no production role yet

| Signal | Current Status | Classification | Rationale |
|--------|---|---|---|
| False catalyst (BPIQ/IR validation) | Production | GATE | Hard exclusion |
| Stale thesis (days since update > threshold) | Production | GATE | Hard exclusion |
| Liquidity (ADV min, OI min, bid-ask spread max) | Production | GATE | Hard exclusion |
| Runway (months until cash burn) | Production | GATE | Hard exclusion |
| Dilution (warrants, preferred, options overhang) | ? | GATE or RISK_OVERLAY | TBD |
| Execution stress (price slippage, volume impact est.) | ? | RISK_OVERLAY | TBD |
| Trap flags (delisted risk, bankruptcy risk) | Production | GATE | Hard exclusion |
| Coinvest_score_z | Production (ranker) | ALPHA_CANDIDATE | Selector output; marginal ranker value TBD (Spec 094) |
| Financial_score_z | Production (ranker) | ALPHA_CANDIDATE | Ranker feature; sign/intention TBD (Spec 093) |
| Catalyst timing / catalyst_decay_w | Shadow | ALPHA_CANDIDATE | Descriptive monitoring (Spec 098) |
| Catalyst quality / binary_quality | Shadow | ALPHA_CANDIDATE | Descriptive monitoring (Spec 098) |
| Clinical design quality | Shadow | ALPHA_CANDIDATE | Orthogonality TBD (Spec 099); no selector/ranker role |
| Event_ev_p_hit | Shadow | ALPHA_CANDIDATE | Prospective binder only; calibration TBD (Spec 097) |
| Options implied vol premium | Shadow | RISK_OVERLAY | Spec 062; no promotion yet |

### 2. Current Gate Enforcement

- **Hard gates**: confirm they are applied before ranker (example: A4 selector logic)
- **Soft gates**: confirm they are applied post-ranking or as overlays
- **Missing gates**: are there risk signals that should be gates but are not?

### 3. Alpha Candidate Evaluation Order

Document the priority order for promoting new alpha candidates:
1. Prove marginal ordering value in correct universe (Spec 095 scope)
2. Show orthogonality to existing features (correlations, principal component analysis)
3. Accumulate post-PIT/post-cohort prospective evidence
4. Only then promote via Checklist v2 (FM + bootstrap + FDR + LOSO + year stab)

---

## Data Constraints

- Pure documentation; no data analysis needed
- Use existing signal definitions from scoring modules and production config

---

## Out-of-Scope

- ❌ Change production gates or ranker
- ❌ Evaluate alpha candidates (done in Specs 097–100)
- ❌ Promote any signal to production
- ❌ Remove any signal

---

## Tests / Analysis Commands

```bash
# Audit production selection/ranking logic
grep -r "gate\|filter\|exclude\|hard\|soft" common/selection_logic.py common/ranker.py --include="*.py" | head -20

# List all scoring modules
ls common/scoring_modules/

# Check signal correlations (post-implementation)
python3 << 'EOF'
import pandas as pd
import numpy as np

# Load snapshot with all signals
snap = pd.read_csv('data/snapshots/2026-05-13/rankings.csv')
ranking_cols = [c for c in snap.columns if c.endswith('_z') or c.endswith('_score')]
print("Ranking columns:", ranking_cols)

# Correlation matrix
corr = snap[ranking_cols].corr()
print("Correlations:\n", corr)
EOF
```

---

## Pass/Fail Criteria

**PASS:**
- ✅ All signals classified (GATE / RISK_OVERLAY / ALPHA_CANDIDATE / SHADOW_ONLY)
- ✅ Rationale documented for each classification
- ✅ Current gate enforcement confirmed (are gates applied before ranker?)
- ✅ Missing gates identified (if any)
- ✅ Alpha candidate promotion order documented

**FAIL:**
- ❌ Classification incomplete or ambiguous
- ❌ Gate enforcement unclear

---

## Expected Outcome

1. **Spec 072 conformance**: Clear separation enables Screener vNext design (coinvest as gate, clinical/catalyst as ranker)
2. **Reduced ambiguity**: Future ranker proposals explicitly state GATE vs ALPHA_CANDIDATE vs SHADOW_ONLY
3. **Promotion path clarity**: Alpha candidates know the order (marginal value → orthogonality → prospective evidence → Checklist v2)

---

## Rollback / No-Op Statement

Documentation only. No production changes. If classification reveals issues (e.g., a gate is embedded in the ranker instead of applied before), flag for Spec 098 (ranker architecture audit).

---

## Related Specs

- **Informs:** Specs 097–100 (alpha candidate classification guides evaluation priority)
- **Enables:** Spec 072 (Screener vNext architecture depends on clear gate/ranker separation)
