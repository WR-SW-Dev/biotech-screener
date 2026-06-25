# Operator Decisions — 2026-06-25

**Recorded by:** Claude Code  
**Date:** 2026-06-25  
**Freeze status:** ACTIVE (unchanged)

---

## Decision 1: EES v3 PIT Sufficiency

**Decision: Require supplementary ≥50% `priced_move_pct` coverage backtest before Checklist v2 is considered satisfied.**

Reason: v3 may be structurally correct, but if the expectation/mispricing component depends on `priced_move_pct`, then a full-sample PIT can look better partly because low-coverage snapshots dilute or distort the actual signal. The 87.2% production coverage vs 8–33% historical coverage creates a data-regime gap that must be tested for robustness.

Pass conditions:
1. v3 remains positive across 42d/63d in the coverage-filtered sample
2. No catastrophic degradation vs full-sample v3 (IC drop < 50%)
3. Result is not driven only by sparse/missing priced_move_pct eras

Action taken: `scripts/research/pit_backtest_ees_v3_coverage_filtered.py` written and run (2026-06-25).

---

## Decision 2: Shadow Gate Sequencing

**Decision: 20d shadow gate does NOT block Checklist v2 diagnostic wiring. It DOES block freeze lift/promotion.**

Allowed in parallel:
- Diagnostic Checklist v2 wiring
- PIT validation and robustness backtests
- Artifact generation
- Non-production shadow reporting

Still blocked until 20d gate met:
- Freeze lift
- Production promotion
- selector/ranker/final_score integration
- Sizing or portfolio behavior changes

---

## Decision 3: Blocker 1 Closure Path

**Decision: Blocker 1 can be closed by v3 replacement, not v2 repair — conditional on supplementary coverage-filtered PIT passing.**

Governance classification:
```
BLOCKER_1_RESOLUTION_PATH = V3_REPLACEMENT_NOT_V2_REPAIR
STATUS = CONDITIONALLY_APPROVED_PENDING_PRICED_MOVE_COVERAGE_ROBUSTNESS
```

v2 will not be repaired. Component attribution confirms the negative contributors (`trap_overlay_score`, `base_rate_gap_score`) should be removed, not salvaged.

---

## Final Operator Decision

```
KEEP_FREEZE_ACTIVE

Proceed with:
1. Supplementary v3 PIT filtered to snapshots with priced_move_pct coverage >= 50%.
2. Checklist v2 diagnostic wiring in parallel.
3. 20d shadow gate accumulation in parallel.

Do not lift freeze.
Do not promote v3 into final_score.
Do not modify selector, sizing, trading, portfolio, or production gates.
```

---

*These decisions supersede and extend FREEZE_LIFT_READINESS_2026_06_25.md.*
