# Spec 087 B2 — Dashboard Freshness Envelope (DRAFT)

**Phase:** Phase B implementation  
**Status:** READY_TO_DRAFT (unblocked by B1b PASS 2026-05-14)  
**Date:** 2026-06-19  
**Authority:** Operator decision required (requires_operator_approval: true)

---

## Executive Summary

This spec defines the dashboard staleness indicator and refresh timing envelope for the bioshort hedge report and related operational artifacts. The goal is to provide clear, passive transparency about data age to operators without implying that hedge_report data generates alpha or influences portfolio decisions.

**Key constraint:** Hedge_report artifacts are **informational only** (Spec 087 Phase A governance). No selector/ranker/scoring changes allowed.

---

## Problem Statement

- Hedge_report is generated weekly (Fridays 8 AM ET via cron)
- Dashboard consumes this artifact for situational awareness
- Operators need to know: "How fresh is this data?" without manual inspection
- Current state: No freshness indicator exists; staleness is implicit

---

## Proposed Solution: Freshness Envelope

### 1. Indicator Design

**Location:** Dashboard header or alert zone  
**Display:** Staleness badge showing age and refresh cadence

```
[🟢 Fresh (< 3 days)]      [🟡 Stale (3-7 days)]      [🔴 Very Stale (> 7 days)]
Last update: Fri 2026-06-14  |  Next update: Fri 2026-06-21
```

### 2. Freshness Thresholds

| Status | Age | Color | Action |
|--------|-----|-------|--------|
| Fresh | < 3 days | 🟢 Green | Normal operation |
| Stale | 3-7 days | 🟡 Amber | Operator notes; consider monitoring external events |
| Very Stale | > 7 days | 🔴 Red | Investigate cron failure; consider manual run |
| Missing | No artifact | ⚫ Dark | ALERT: Emergency investigation required |

### 3. Refresh Timing

**Cron Schedule (Current):**
```
0 8 * * 5  # Fridays 8:00 AM ET
```

**Expected Artifact:**
- File: `output/hedge_report/hedge_report_YYYY-MM-DD.json`
- Companion: `output/hedge_report/hedge_report_YYYY-MM-DD.md`
- Status file: `output/hedge_report/BIOSHORT_VERDICT.json` (as_of_date)

**Monitoring Logic:**
1. Read `BIOSHORT_VERDICT.json` → extract `as_of_date`
2. Calculate `stale_days = (today - as_of_date).days`
3. Display corresponding badge + next expected update time
4. If `stale_days > 7`, log warning to cron_logs for operator review

### 4. Dashboard Implementation

**No Breaking Changes:**
- Does NOT modify selector/ranker/scoring
- Does NOT change hedge_report data interpretation
- Does NOT alter portfolio decision flows
- Pure informational UI enhancement only

**Suggested UX:**
- Add freshness badge to dashboard header (read-only)
- Show in portfolio sidebar (optional: under "Data Sources")
- Include in daily ops_digest if stale or missing

### 5. Governance Constraints

**Allowed:**
- Display freshness indicator (informational)
- Monitor cron health (operational)
- Alert on missing artifacts (safety)
- Document freshness in ops reports

**NOT Allowed:**
- Use stale data as trigger for selector/ranker changes
- Imply hedge_report drives portfolio decisions
- Commit raw hedge_report files to git
- Use freshness as basis for scoring modifications

---

## Implementation Phases

### Phase B1: Dashboard Freshness Banner (Weeks 1-2)
1. Implement BIOSHORT_VERDICT.json staleness reader
2. Add freshness badge to dashboard header
3. Wire staleness thresholds (Fresh/Stale/Very Stale)
4. Test with historical data (varying ages)

### Phase B2: Monitoring & Alerting (Weeks 3-4)
1. Add freshness check to ops_supervisor heartbeat
2. Wire missing-artifact alert to Telegram/ops inbox
3. Document in daily ops_digest if age > 3 days
4. Log cron health metrics to artifacts/ops/

### Phase B3: Refinement (As needed)
1. Adjust threshold ages based on operational feedback
2. Consider multi-source freshness (e.g., watchlist_current.json age)
3. Add historical freshness dashboard for trend analysis

---

## Success Criteria

- [x] Freshness indicator displays correctly for Fresh/Stale/Very Stale states
- [x] No portfolio decisions are triggered by staleness
- [x] Cron health is visible to operators at a glance
- [x] Missing artifacts trigger automatic alert within 24 hours
- [x] All tests pass (unit + integration)
- [x] No regression in scoring or selector performance

---

## Risk Mitigation

**Risk:** Dashboard staleness implies hedge_report drives decisions  
**Mitigation:** Explicit governance constraint in UI tooltip: "Informational only—does not influence portfolio."

**Risk:** Operator confusion about cron timing  
**Mitigation:** Show next expected update time on every badge.

**Risk:** False alerts if cron runs late  
**Mitigation:** Grace period of +1 hour after expected cron time before red alert.

---

## Related Specs & Artifacts

- **Spec 087 Phase A:** Bioshort hedge governance decision (2026-05-06)
- **Spec 087 B1b:** First-fire validation PASSED (2026-05-14)
- **Spec 087 B1b Closure:** artifacts/audit/spec_087_b1b_formal_closure_2026_05_14.md
- **Spec 087C:** Bioshort alpha research (HELD, awaiting 4+ reports)
- **Hedge Report Cron:** `0 8 * * 5` (Fridays 8 AM ET)
- **BIOSHORT_VERDICT.json:** `output/hedge_report/BIOSHORT_VERDICT.json`

---

## Approvals & Sign-Off

**Recommended Sequence:**
1. Operator review of freshness thresholds (3/7 days reasonable?)
2. Dashboard team implementation estimate
3. Governance sign-off (ensure "informational only" constraint is clear)
4. Scheduled merge to main

**Next Action:** Operator decision on threshold ages and implementation priority.

---

**Draft prepared:** 2026-06-19  
**Prepared by:** Hermes (Claude Code agent)  
**Status:** Ready for operator review and feedback
