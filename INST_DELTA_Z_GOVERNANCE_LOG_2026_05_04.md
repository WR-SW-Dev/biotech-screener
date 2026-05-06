# inst_delta_z Signal Health — Governance Log
**Date filed:** 2026-05-04
**Ruleset:** 2a3e79eb (v1.13.0) → 622edb77 (v1.14.0)
**Status:** FILED

Cross-reference: INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md

---

## Disposition

- [X] **Option A** — inst_delta_z selector weight zeroed; coinvest_score_z weight set to 1.00
- [ ] Option B — Shadow reduce
- [ ] Option C — Watch only
- [ ] Option D — Bundle IC probe first

## Rationale

Two-frame ALERT confirmed (ic_health_monitor + calibration_evidence). Comparator probe
showed coinvest_score_z healthy over same window (mean_ic=+0.097, hit_rate=0.897,
rho=-0.33 vs inst_delta_z). Degradation isolated to inst_delta_z. Option A applied.

## Changes applied (2026-05-04)

| File | Change |
|------|--------|
| `run_screen.py` lines 132-152 | `coinvest_score_z` 0.65→1.00, `inst_delta_z` 0.35→0.00 |
| `run_phase2_snapshot_delta.py` line 31 | `PHASE2_PINNED_RULESET_ID` 2a3e79eb→622edb77 |
| `CLAUDE.md` Active Ruleset | v1.13.0 → v1.14.0, id 2a3e79eb → 622edb77 |
| `production_data/decision_rulesets/v1.14.0_coinvest_only_selector.json` | New ruleset file (copy of v1.13.0; id derived from file hash = 622edb77) |

## Conditions for re-opening

Re-open if: (a) inst_delta_z mean_ic recovers above +0.02 sustained for 10+ dates in
ic_health_monitor, AND (b) calibration_evidence event-IC turns positive. Not before both.

## Follow-up tickets

- [ ] Monitor inst_delta_z IC in weekly ic_health_monitor runs; document in sentinel notes
- [ ] Forward shadow: track coinvest-only selector performance vs prior B6 bundle in shadow tracker
- [ ] If inst_delta_z recovers in Q3 2026 13F cycle, re-evaluate reinstatement via Spec process

## Sign-off

Operator: Darren Schulz
Date filed: 2026-05-04

---

## Correction note (appended 2026-05-06 — phantom hash)

The `622edb77` hash referenced above (lines 3, 28, 29, 30) was the **initial computed hash** of `production_data/decision_rulesets/v1.14.0_coinvest_only_selector.json`. After 2026-05-05 edits added `selector_config` fields to the ruleset file, the recomputed hash became `8887576e`. Commit `bd91b523d` ("fix(ruleset): correct v1.14.0 hash to 8887576e (was phantom 622edb77)") records the correction.

**Canonical active ruleset id is `8887576e` v1.14.0.** The `622edb77` references in this log are preserved as audit-trail evidence of the phantom-hash episode and must NOT be edited or deleted. See:

- `RULESET_CHANGELOG.md` v1.14.0 entry (controlling changelog record).
- `artifacts/promotions/promotion_2026-05-04_8887576e.{json,md}` (synthetic-backfilled receipt — Spec 086 Option (a)).
- `artifacts/audit/spec_086_v1_14_0_freeze_compliance_audit_2026_05_06.md` (controlling audit memo: v1.14.0 is a demotion-class hygiene patch, NOT a Checklist v2 promotion).
- `policy_demotion_path_2026_05_06.md` (auto-memory: 5-element governed demotion path).
