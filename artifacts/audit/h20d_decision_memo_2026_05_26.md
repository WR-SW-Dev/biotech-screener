# h20d Decision Memo — May 26, 2026

**Decision Authority:** Darren Schulz  
**Decision Date:** 2026-05-26 EOD  
**Memo Status:** FINAL (finalized 2026-05-24 based on live 13F data)  
**Execution Path:** **Path B — DEFERRED**

---

## Executive Summary

Phase 2 Step 4 Knowledge Graph implementation is complete and validated (52/52 tests PASS). The 13F Q1 2026 refresh has materially restructured the institutional cohort: Jaccard similarity is **0.364** with 49/55 managers filed. This is well below the 0.70 clearance threshold and is unlikely to recover by June 1 given that 89% of managers have already filed. 

**Freeze-lift is deferred.** Phase 2 Step 5 enforcement and Spec 089 KG governance activation remain blocked. The re-decision gate is Jaccard ≥ 0.70 (condition-based, not calendar-based). The inst_delta forward shadow h20d interpretation is non-evaluable due to cohort contamination mid-observation window.

---

## Part 1: Gate Evaluation

### 13F Quarantine Status (as of 2026-05-24)

| Gate | Required | Actual | Status |
|---|---|---|---|
| Managers filed | ≥34 | 49/55 (84.9%) | ✅ |
| Jaccard similarity | ≥0.70 | **0.364** | ❌ |
| Top-30 stability | — | 14 entering / 14 leaving | ❌ |
| inst_delta_z distortion | Cleared | mean abs delta 1.09, 130 large changes | ❌ |

**Top-30 entering:** ALMS, APGE, ARWR, CMPS, DRUG, MLTX, MLYS, NRIX, RYTM, SNDX, SYRE, TRVI, TYRA, URGN  
**Top-30 leaving:** ANNX, ARGX, AXSM, BCRX, BLTE, CMPX, ERAS, INSM, KYMR, ORIC, SLDB, SLN, SRRK, TSHA

**Score signal distortion:**
- `coinvest_score_z`: mean abs delta 0.437, 27 large changes, top mover LBRX (+2.92)
- `inst_delta_z`: mean abs delta 1.090, 130 large changes, top mover RNA (−5.99)

**Registry:** 49/55 managers filed (84.9%). Two managers past the 45-day deadline (Broadfin, Farallon) may not file. With 89% of the registry settled, Jaccard 0.364 reflects a structural cohort shift, not a filing lag.

### Why Jaccard Will Not Recover to 0.70 by June 1

The original Path B re-decision assumed the filing gap (6/48 → 34+) would raise Jaccard. That assumption was valid in May. As of May 24, 49/55 managers have filed and Jaccard is 0.364. The remaining 6 filings (including 2 past-deadline) cannot close a 0.306-point gap. The cohort has structurally changed. The re-decision gate must be condition-based, not calendar-based.

### inst_delta Forward Shadow — Non-Evaluable at h20d

- T0: 2026-04-28
- h20d: 2026-05-26
- Cohort shift: 2026-05-15 (13F refresh)
- Observation window contaminated: yes (cohort changed at trading day ~13 of 20)

The `inst_delta_z` values from T0 to mid-May reflect the pre-refresh cohort. Values from mid-May reflect the post-refresh cohort. The 20-day window straddles the shift. No forward shadow interpretation is valid. The h20d shadow evidence cannot inform a promotion or demotion decision on `inst_delta_z`.

**Final verdict:** non-evaluable. Carry to final shadow review at T0+60d (2026-07-21) using the post-refresh cohort only.

---

## Part 2: Phase 2 Step 4 — Evidence Summary

**Status: COMPLETE ✅**  
All deliverables complete and validated prior to this decision gate. Preserved in staging branch.

| Component | Tests | Status |
|---|---|---|
| 4a: KG Loader | 17/17 | ✅ PASS |
| 4b: Query patterns | 10/10 | ✅ PASS |
| 4c: Contradiction detection | 12/12 | ✅ PASS |
| 4e: Integration contracts | 13/13 | ✅ PASS |
| Phase 1 PoC (Spec 110) | 22/22 | ✅ PASS |
| **Total** | **74/74** | **✅ PASS** |

Architecture validated: design-by-contract guard pattern, C0 structural coverage, C4 soft contradiction enforcement, loader-query-detector contracts.

Phase 2 Step 4 work is preserved. No work is wasted. Step 5 implementation design is locked and ready when the gate clears.

---

## Part 3: Decision

### Executed: Path B — Defer

**Actions taken / confirmed:**

1. ✅ Memo published with h20d verdict: **DEFERRED**
2. ✅ Phase 2 Step 4 branch preserved in staging (spec-110-pipeline-provenance-graph-2026-05-21)
3. ✅ Spec 089 KG remains advisory-only (no enforcement activation)
4. ✅ Phase 2 Step 5 implementation deferred — design locked, not started
5. ✅ Alpha freeze remains active — no ranker/selector/sizing changes authorized
6. ✅ inst_delta forward shadow: carried to T0+60d (2026-07-21), non-evaluable at h20d

**Actions deferred (blocked until gate clears):**

- Phase 2 Step 5 enforcement wiring (KG queries → preflight block/warning)
- Spec 089 KG governance activation (advisory → enforcement)
- Daily lineage monitoring on production snapshots
- Freeze-lift on ranker research

---

## Part 4: Re-Decision Gate

**Calendar date: ABANDONED.** The June 1 calendar gate from the draft memo is superseded.

**New gate (condition-based):**

```
Re-decision authorized when ALL of the following hold:
1. Jaccard similarity (pre-refresh vs post-refresh top-30) ≥ 0.70
2. inst_delta_z mean abs delta < 0.50 (post-refresh cohort, rolling 5-snapshot)
3. ≥10 post-refresh snapshots available for forward shadow validation
4. No active production incidents
```

**Monitoring:** 13F quarantine cron active weekdays 6:22 PM ET through 2026-06-20. Re-evaluate at gate conditions, not on a calendar schedule.

**Earliest plausible re-decision:** 2026-06-15 (if Jaccard stabilizes after post-refresh signal normalization). More likely: 2026-07-01+ given structural cohort shift magnitude.

---

## Part 5: Governance Continuity

| Policy | Status | Notes |
|---|---|---|
| Alpha freeze | **ACTIVE** | No promotions without Checklist v2 |
| Ranker freeze | **ACTIVE** | 2-feature pairwise locked |
| Selector freeze | **ACTIVE** | A4 selector locked |
| inst_delta quarantine | **ACTIVE** | Non-evaluable through 2026-07-21 |
| 13F quarantine | **ACTIVE** | Jaccard 0.364; gate: ≥0.70 |
| KG (Step 4) | **STAGING** | Complete, not enforcing |
| KG (Step 5) | **DEFERRED** | Blocked pending gate clearance |
| Spec 089 | **ADVISORY** | No enforcement until gate clears |

---

## Signature Block

**h20d Decision:** DEFERRED  
**13F Quarantine Verdict:** NOT CLEARED (Jaccard 0.364, gate requires ≥0.70)  
**Execution Path:** Path B  
**inst_delta h20d Shadow:** NON-EVALUABLE (cohort contamination; carry to 2026-07-21)  

**Approved by:** Darren Schulz  
**Finalized:** 2026-05-24 (decision date: 2026-05-26 EOD)  

**Implementation owner:** Claude  
**Next decision gate:** Condition-based (Jaccard ≥ 0.70 + distortion cleared + ≥10 post-refresh snapshots)
