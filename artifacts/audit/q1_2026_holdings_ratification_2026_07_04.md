# Q1 2026 (2026-03-31) Holdings Ratification & Observation-Only Tag — 2026-07-04

**Decision:** RATIFIED (retain full-cohort Q1 2026 holdings on `main`), constrained to **observation-only**
**Authority:** Operator approval — D. Schulz (via merge of this PR)
**Effective date:** 2026-07-04
**Scope:** `production_data/holdings_2026-03-31.json` (+ `holdings_detailed.json`) — Q1 2026 13F snapshot
**Companion housekeeping (this PR):** Farallon Q1 filing-status re-sync; stale `cohort_pending.json` cleared

---

## Executive Summary

The Q1 2026 full-cohort 13F holdings file currently on `main` was **re-promoted by PR #429** ("Hermes skill sync + YTD/full-history validation + forward-validation pre-registration", merged 2026-06-28, squash `962c221`). This reintroduced the full-cohort dataset that had been **reverted on 2026-06-24** (`b502c17`, which restored `411cbe40` after a runaway-agent promotion `da349956`).

A read-only content diff (`411cbe40` vs `main`) confirms PR #429 was a **material data promotion, not a reserialization**. The promoted data itself is a **correct, clean full extract** — the issue is procedural: it re-entered inside an omnibus skill-sync PR rather than through a governed 13F promotion, merged over a warn-only-failing protected-paths check, and the **55-manager cohort quarantine has never been formally gate-lifted**.

**This memo ratifies retaining the data** (re-extracting it would be wasteful and it is verifiably correct) **while explicitly constraining it to observation/attribution use** via `data/snapshots/2026-03-31/cohort_state.json`. It does **not** lift the quarantine and does **not** authorize alpha/ranker/selector consumption of Q1.

---

## Part 1: Verified Facts

### 1.1 Content diff — `production_data/holdings_2026-03-31.json`

| Metric | Post-revert (`411cbe40`) | Current `main` (post-#429) |
|---|---|---|
| Managers | 6 | 54 |
| Tickers | 210 | 332 |
| Positions | 345 | 996 |
| File size | 172 KB | 742 KB |
| `_governance.run_id` | `2dafbbb00ebfd54a` | `49369a31e98e0231` |

Different `run_id` + 6→54 manager jump ⇒ fresh full extract (material promotion). `_schema.quarter_end` = `2026-03-31`, `prior_quarter_end` = `2025-12-31` in both. Embedded warnings on `main` flag only Krensavage and Broadfin/Kotler as non-filers for Q1 — Farallon is **present** in the 54.

### 1.2 PR #429

- State: closed / merged; head `5a016680`, squash `962c221` (2026-06-28).
- Scope: skill-sync, forward-validation protocol (RATIFIED `2cb905d`), tests, docs — plus reserialization/promotion of all four `production_data/holdings_*.json` files and addition of `data/13f_history_full/` (5-quarter PIT set 2025-03-31 → 2026-03-31).
- CI: one failing check — `protected model/ranker paths (warn-only)` — a single warn-only annotation; characterized in-thread as environmental/pre-existing on the base branch. PR merged with this check failing.
- Authorship rides on the `Warrenpoobear` owner account, which is shared by the operator and autonomous agents; account attribution alone does not distinguish operator vs. agent authorship.

### 1.3 Cohort quarantine status (unchanged by this memo)

- Last formal verdict: **QUARANTINE** — 55-manager cohort, Jaccard 0.463 (< 0.70), mean |inst_delta_z| 1.0285 (> 0.50). Ref: `artifacts/audit/h20d_decision_memo_55manager_override_2026_05_26.md`.
- The only lift on record is the 2026-05-26 **manual operator override** of the *registry freeze* (commit `e61b806`) — not a gate-based clearance of cohort signal validity.
- The h20d **re-evaluation gate was scheduled 2026-07-01** and is now **due/overdue** — no re-eval verdict artifact located as of 2026-07-04.

### 1.4 Farallon filing reconciliation (EDGAR primary source)

- `production_data/13f_filing_status.json` marked Farallon (CIK `0000909661`) **pending** for target quarter 2026-03-31, despite the Q1 extract already containing Farallon's holdings.
- EDGAR submissions API confirms Farallon **13F-HR** for period `2026-03-31`: accession `0000908834-26-000240`, filed `2026-05-15`. (Same-day `0000908834-26-000241` is a 13F-HR/A for the *prior* quarter — not applicable.)

---

## Part 2: What This Ratification Does / Does Not Do

**Does:**
- Retains the correct full-cohort Q1 2026 holdings on `main`.
- Writes `data/snapshots/2026-03-31/cohort_state.json` tagging Q1 **observation/attribution only** (`inst_delta_z_valid=false`, `rank_delta_valid=false`, `decision_grade=false`; `coinvest_score_z` remains a within-snapshot renormalization and stays usable).
- Re-syncs Farallon to `filed` and clears the stale `cohort_pending.json` (April cohort change was consumed by the 2026-04-27 snapshot).

**Does NOT:**
- Lift the 55-manager cohort quarantine.
- Authorize alpha / ranker / selector / sizing consumption of the Q1 snapshot.
- Change any model, ranker, scorer, or selector logic.

---

## Part 3: Open Items / Next Gates (not addressed here)

1. **h20d re-evaluation gate (due 2026-07-01)** — run the weekly cohort quarantine check and record a verdict; decide lift vs. hold on Jaccard/inst_delta trend.
2. **Formal quarantine-lift decision** — either a gate-based lift verdict or an explicit continued-hold, superseding this interim observation-only tag.
3. **Broadfin/Kotler (CIK `0001601692`)** — remains genuinely pending (irregular personal filer); leave as `pending` until a Q1 13F is confirmed.

---

## Part 4: Path Assumption Flagged for Review

`data/snapshots/<date>/cohort_state.json` is the documented convention (per `production_data/cohort_pending.json` instructions and `tools/onboard_manager.py`), but **no date-keyed snapshot directory currently exists on `main`** (only `data/snapshots/resolutions/`). This memo keys the tag by **quarter_end (`2026-03-31`)** for self-documentation. If the production pipeline keys snapshot-state by **run date** instead, relocate `cohort_state.json` accordingly before relying on the pipeline to honor it. The tag is fail-closed either way (it only restricts use).

---

**Ratified by:** D. Schulz (via merge of this PR)
**Prepared:** 2026-07-04 (observe-only investigation; no production mutation outside this reviewable PR)
**Related:** `artifacts/audit/h20d_decision_memo_55manager_override_2026_05_26.md`, PR #429 (`962c221`), revert `b502c17`, baseline `411cbe40`
