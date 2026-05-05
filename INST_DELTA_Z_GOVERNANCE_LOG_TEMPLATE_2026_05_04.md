# inst_delta_z Signal Health — Governance Log TEMPLATE
**Date:** 2026-05-04
**Ruleset:** 2a3e79eb (v1.13.0)
**Status:** TEMPLATE — disposition not yet filed

Cross-reference: INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md

---

## Disposition

Select one:

- [ ] **Option A** — Shadow inst_delta_z selector weight to zero; promote if shadow validates
- [ ] **Option B** — Reduce inst_delta_z selector weight to ~15-20%; shadow accumulation 30-60 days
- [ ] **Option C** — Watch only; re-assess after Tuesday 2026-05-05 ic_health_monitor run
- [ ] **Option D** — Bundle IC probe first; defer A/B/C decision pending result

## Rationale

_(operator fills in — 1-3 sentences)_

## Conditions for re-opening

_(e.g. "re-open if mean_ic remains below -0.05 after 2026-05-12 refresh")_

## Follow-up tickets

- [ ] _(if A) Draft v1.14.0_b6_coinvest_only_selector.json + promotion memo_
- [ ] _(if B) Create new shadow arm in coinvest_shadow_tracker_
- [ ] _(if D) Run bundle IC probe script — read-only, no production touch_

## Sign-off

Operator: _______________
Date filed: _______________

---

_Convert this file to INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md (drop TEMPLATE) once disposition is chosen._
