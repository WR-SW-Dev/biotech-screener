# Spec 096 — Event-EV p_hit Monitoring Gate (2026-05-08)

**Status:** Monitoring and governance spec. No code changes. No backfill.
**Priority:** 4
**Origin:** T8 Escalation 3 (revised) from ranking alternatives audit (2026-05-08).
**Context:** Spec 077 binder shipped (`_bind_event_ev_p_hit`, node_id exact + ticker/date ±7d fallback). 37 postmortems carry `event_ev_p_hit` in `resolution_source`; 0 non-null — EV artifact coverage not yet reached those events. Blocker is prospective accumulation, not join infrastructure.

**Hard constraints:**
- No backfill unless exact node_id evidence exists in an EV artifact dated before the event
- No Alt 6 promotion or formal IC test before Gate 3 threshold is reached
- No code changes to binder logic unless a binder defect is confirmed by monitoring
- Monitor monthly; do not re-run daily

---

## 1. Purpose

Define the monitoring cadence and sample-size gate for `event_ev_p_hit` accumulation, so that:

1. The binder health is verified monthly (is it populating records as EV artifacts are created?)
2. A clear threshold (Gate 3) exists for when Alt 6 (Event-EV) can run its first calibration / return-discrimination audit

---

## 2. Monthly Monitoring Check

On the first working day of each month, run the following check:

```
postmortem_root = artifacts/postmortem/
For each postmortem .json file:
  Read resolution_source.event_ev_p_hit
  Count: total records, field-present records, non-null records
  Report: date range of non-null records, match_type distribution
```

Report format (add to a running log at `artifacts/audit/event_ev_p_hit_monitoring.md`):

| Check date | Total postmortems | Field present | Non-null | Match types | Notes |
|------------|------------------|---------------|----------|-------------|-------|

**Binder health signal:** If new postmortems are being created (events resolving) but no new non-null `event_ev_p_hit` records appear over 3 consecutive months, investigate whether:
1. EV artifacts are being generated for those events (check `artifacts/event_ev/`)
2. The node_id or ticker/date matching is failing silently

---

## 3. Gate 3 Definition

**Gate 3** for Alt 6 formal IC testing is cleared when:

- **First calibration look:** n ≥ 15 bound post-PIT HIT/MISS records with non-null `event_ev_p_hit`
  - At this threshold: compute return-discrimination audit only (median EV-positive vs EV-negative returns among resolved events). Descriptive only; no IC statistic.
- **Formal IC test:** n ≥ 30 bound post-PIT HIT/MISS records with non-null `event_ev_p_hit`
  - At this threshold: run Spearman IC of `event_ev_p_hit` vs `excess_return_5d` (or event outcome) within the bound subset. Requires Gate 4 (n≥30 total HIT/MISS) and Gate 7 (IC scope spec confirmed) also cleared.

Post-PIT = snap_date or event_date ≥ 2026-04-17.

---

## 4. Backfill Policy

No backfill unless:
- An EV artifact exists with an exact `node_id` match to a historical postmortem record
- The EV artifact's `snapshot_date` (the as-of date of the EV computation) is provably before the event resolution date

If these conditions are not met, all historical records with null `event_ev_p_hit` remain null. Do not impute.

---

## 5. Expected Accumulation Rate

At the current postmortem resolution rate (~3-4 HIT/MISS per month), and assuming EV artifacts are generated for a subset of those events, Gate 3 (n=15 first calibration look) may be reached by 2026-Q4 at the earliest. Gate 3 (n=30 formal IC) is unlikely before 2027 unless EV artifact coverage accelerates significantly.

This timeline is informational only. The gate is a count threshold, not a date. Do not attempt the first calibration audit before n=15 is verified regardless of date.

---

## 6. Artifacts

- Binder implementation: `tools/catalyst_resolution_tracker.py`, function `_bind_event_ev_p_hit`
- Monitoring log: `artifacts/audit/event_ev_p_hit_monitoring.md` (create on first monthly check)
- Gate 3 tracker: add a row to the monthly monitoring log
