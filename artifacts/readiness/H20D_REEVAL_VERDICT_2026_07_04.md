# h20d Re-evaluation Gate — Verdict & Recommendation — 2026-07-04

**Gate due:** 2026-07-01 (now 3 days overdue as of 2026-07-04)
**Verdict:** NOT CLEARED — deferred quarantine check never executed against a post-Q1-promotion snapshot
**Recommendation:** HOLD (maintain Q1 observation-only per PR #462) + run the deferred script locally before the next trading gate
**Authority:** Recommendation only — requires local operator execution + sign-off
**Companion:** PR #462 (Q1 2026 holdings ratification / observation-only tag)

---

## Recommendation

**HOLD.** Do not formally clear the h20d gate. Maintain the 55-manager cohort quarantine posture and keep the Q1 2026 snapshot at **observation/attribution only** (the state written by PR #462). This is a steady hold, **not** an escalation/re-freeze — no failure trigger has been breached. The gate can only be cleared by the authoritative quarantine script run against a post-promotion snapshot, which has not happened.

**Basis:** verified facts below.
**Safe next step:** local operator runs `tools/check_13f_cohort_quarantine.py` (command in Part 4).
**Do not do yet:** clear the gate, lift the quarantine, or authorize alpha/ranker/selector consumption of Q1 on the strength of documentation or Q4-cohort metrics.

---

## Part 1: Verified Facts

1. **The re-evaluation was deferred, not completed.** The only gate artifact is the PRELIMINARY `artifacts/readiness/H20D_REEVAL_GATE_2026_06_24.md`, which states: *"Quarantine Script: DEFERRED (pending Q1 13F promotion + snapshot)."* The quarantine script run on 2026-06-23 **FAILED at G2** — `REFRESH_NOT_LANDED — wait for next snapshot` (`prior_date did not advance: pre=2026-05-15 post=2026-05-15`) — because Q1 data was still cached at Q4 (May 15).

2. **No final verdict was ever produced.** No `H20D_JACCARD_FINAL_*.md` and no `13f_validation_verdict_55manager_weekly_*.md` output files exist in the repo (code search: 0 results). The weekly Jaccard monitoring the 2026-05-26 override was contingent on was never recorded.

3. **The last actual 55-manager cohort test FAILS the gate.** 55-manager cohort Jaccard = **0.463** (target >= 0.70; floor 0.40) and mean |inst_delta_z| = **1.0285** (target < 0.50). Every `held_spec_ledger` from 2026-05-28 through 2026-06-25 carries "last known Jaccard 0.463" unchanged — no improved measurement was ever taken.

4. **The "favorable" metrics in the 2026-06-24 memo are the WRONG cohort.** The Jaccard 0.875 / 100% coverage cited there were computed on **Q4 2025 data with the reduced 49-manager active set** — not the 55-manager Q1 cohort. Treating those as gate-clearing would repeat the same "wrong-cohort metrics as proof" pattern this governance package exists to correct. They must not be used to clear the gate.

5. **The precondition to run the deferred script is now met.** Q1 2026 13F was promoted to production via PR #429 (merged 2026-06-28); daily snapshots have run since (monitoring commits through 2026-07-03). So the deferred `check_13f_cohort_quarantine.py` (pre = last snapshot before promotion, post = first after) is now runnable.

6. **The monitoring layer has flagged the gate as overdue.** Pre-market snapshot commits state: 2026-07-02 — *"Governance gates h20d + IC checkpoint overdue — require local operator execution"*; 2026-07-03 — *"h20d quarantine and IC checkpoint 2 days overdue — must run before July 7 open."*

---

## Part 2: Why HOLD (not lift, not escalate)

- **Cannot lift:** the authoritative like-for-like 55-manager Jaccard/inst_delta test has not been run or recorded; the last real value fails the 0.70 gate. Clearing on documentation alone is not permitted under the fail-closed posture.
- **No escalation / re-freeze:** no failure trigger breached — Jaccard 0.463 is above the 0.40 floor, and no inst_delta > 1.50 has been recorded. The model/ranker freeze status (lifted by the 2026-05-26 override) is unchanged; only Q1 signal consumption stays gated.
- **Interim posture:** Q1 remains observation-only (PR #462 `cohort_state.json`); `coinvest_score_z` stays usable (within-snapshot renormalization).

---

## Part 3: Structural caveat on the clearing test

`inst_delta_z` becomes decision-grade only when the current and prior quarters are built with the **same** 55-manager cohort. The Q1 2026 snapshot's prior is Q4 2025 (built with a smaller cohort), so the **first** post-promotion run is not yet fully like-for-like — a genuinely like-for-like comparison arrives with the **Q2 2026 snapshot** (Q2 13F due ~2026-08-14). A first-pass Jaccard on Q1-vs-Q4 should therefore be read as directional, not definitive, and the gate may legitimately remain in observation-only until Q2 data lands.

---

## Part 4: Required Action (local operator, before the next trading gate)

```bash
python3 tools/check_13f_cohort_quarantine.py \
    --pre-date  <last snapshot before Q1 promotion> \
    --post-date <first snapshot after Q1 promotion> \
    --output    artifacts/readiness/H20D_JACCARD_FINAL_2026_07_07.md
```

- **If PASS** (Jaccard >= 0.70, no coverage drop >= 10pp): formally clear h20d; supersede the PR #462 observation-only tag with a decision-grade `cohort_state.json`.
- **If FAIL but no trigger breached** (Jaccard in [0.40, 0.70)): keep observation-only; re-evaluate on the Q2 2026 snapshot.
- **If trigger breached** (Jaccard < 0.40 or inst_delta > 1.50): escalate — consider partial re-freeze per the 2026-05-26 override contingencies.

---

**Status:** gate OPEN (uncleared); interim HOLD / observation-only
**Prepared:** 2026-07-04 (observe-only; no production mutation outside the reviewable PR)
**Related:** `artifacts/readiness/H20D_REEVAL_GATE_2026_06_24.md`, `artifacts/audit/h20d_decision_memo_55manager_override_2026_05_26.md`, `artifacts/audit/q1_2026_holdings_ratification_2026_07_04.md`, PR #429 (`962c221`), PR #462
