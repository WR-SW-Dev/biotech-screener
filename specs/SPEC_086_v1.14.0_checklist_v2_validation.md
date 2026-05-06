# Spec 086 — v1.14.0 Coinvest-Only Selector: Checklist v2 Validation Bundle

**Status:** OPEN — validation bundle not yet run
**Created:** 2026-05-06
**Triggered by:** 2026-05-06 data integrity audit finding R2
**Blocking:** v1.14.0 promotion_status upgrade from HOLD to CONFIRMED

---

## Background

v1.14.0 (8887576e) was promoted 2026-05-04 as a **governed mitigation** for the
inst_delta_z SIGNAL_ALERT (mean_ic=-0.097, two-frame confirmed). The selector was
reweighted from coinvest_score_z 65% / inst_delta_z 35% to coinvest_score_z 100%
/ inst_delta_z 0% — a weight change within the existing A4 selector+ranker
architecture. No new pipeline code. Ranker unchanged. EW Top-30 unchanged.

**What was validated (2026-04-04 Queue C):**

The B6 bundle (coinvest 65% + inst_delta 35%) cleared Queue C:
- Bootstrap: mean=0.0242, CI=[0.0125, 0.037], P(>0)=0.9999 — PASS
- LOSO: ROBUST across all 6 dimensions — PASS
- 67 monthly periods (Jun 2020 – Apr 2026)

**What was NOT validated:**

The coinvest-only (100%) variant was not separately run through Queue C. The
governing Checklist v2 requires FM + bootstrap + FDR + LOSO + year-stability
per `policy_alpha_freeze_2026_04_04.md`. Whether the 100% coinvest variant
meets all five bars is unconfirmed.

Freeze regime compliance note: the freeze protocol requires that any weight
change materially reducing a passing signal (inst_delta_z passed Queue A at
2/5, below bar but above zero) be validated under Checklist v2 before the
change is classified as confirmed rather than provisional.

**Current production status:**

```
v1.14.0:
  production_active: true
  selector_change: governed mitigation for inst_delta_z ALERT
  checklist_v2_complete: unconfirmed
  promotion_status: HOLD (provisional — pending this spec)
```

---

## What This Spec Requires

Run `scripts/research/checklist_v2_rerun.py --queue C` with the v1.14.0
selector weights (coinvest_score_z=1.0, inst_delta_z=0.0) on the same
research panel used for the 2026-04-04 rerun.

**Five gates:**

| Gate | Method | Bar |
|------|--------|-----|
| G1 | Signal card: selector Δ (t ≥ 2.0), ranker IC (t ≥ 2.0) | Both must pass |
| G2 | Fama-MacBeth incremental NW-t | ≥ 1.96 |
| G3 | Block bootstrap 95% CI | Excludes zero |
| G4 | BH FDR q-value | q < 0.10 |
| G5 | LOSO worst-slice | Positive in all 6 dimensions |

**Queue C specifically:** bootstrap + LOSO on the production selector with the
new weights. Replicate the exact Queue C setup from checklist_v2_rerun.py with
the B6 SelectorConfig updated to coinvest_score_z=1.0, inst_delta_z=0.0.

---

## Panel and Data Requirements

- Panel: `output/signals/research_panel.csv` (same as 2026-04-04 run)
- Selector config override: `SelectorConfig` with `coinvest_score_z=1.0`,
  `inst_delta_z=0.0` (mirrors run_screen.py A4_SELECTOR_CONFIG as of v1.14.0)
- Period: same 67-period window (Jun 2020 – Apr 2026) used in prior Queue C
- No look-ahead: all inputs must be PIT-gated

---

## Outputs Required

1. `output/checklist_v2_v1.14.0/queue_c_coinvest_only.json` — raw results
2. `output/checklist_v2_v1.14.0/operator_memo.md` — human-readable summary
3. Update this spec with the verdict

---

## Decision Tree

| Queue C Result | Action |
|----------------|--------|
| All 5 gates pass (ROBUST) | Upgrade promotion_status to CONFIRMED; close Spec 086 |
| Bootstrap passes, LOSO MODERATE | Upgrade to PROVISIONAL_CONFIRMED; document sensitivity |
| Bootstrap or LOSO fails | Escalate to ops; consider rollback to B6 (65/35) weights; do not expand cadence |

**Under no circumstance should the verdict be used to adjust scoring weights
or trigger a rollback without a separate governance review. This spec produces
evidence only.**

---

## Not In Scope

- Re-evaluating coinvest_score_z standalone (already 3/5 SHADOW — no new run needed)
- Running Queue A or Queue B again (unchanged)
- Modifying production code, rulesets, or rankings
- Changing cron schedules or agent configs

---

## Tracking

- Audit finding: `agents/grok_biotech_watch/CLASSIFIER_TUNING_FOLLOWUP.md` (cross-reference)
- Fleet receipt: FAIL on ic_health_monitor (score_rank_pct WARN) — unrelated but context
- Governance log: `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md`
- Sentinel re-anchor: commit 7ac2ceee (2026-05-05)
- Promotion receipt backfill: `artifacts/promotions/promotion_2026-05-04_8887576e.json`

---

*Spec 086 authored by Hermes Agent, 2026-05-06. Operators: review and assign
before scheduling the validation run. No automated execution — this is evidence
collection only.*
