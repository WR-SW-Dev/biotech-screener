# 2026-05-22 Ranker Review — Blockers Brief

**Date Prepared**: 2026-05-14  
**Review Date**: 2026-05-22  
**Type**: Governance checkpoint + evidence status brief  
**Authorization**: No production ranker change authorized

---

## Review Framing

```
2026-05-22 Ranker Review = governance + evidence checkpoint only.
No production ranker change authorized.
```

The review is an interim briefing on post-13F-refresh validation status and Spec 072 re-verification results. All hard blockers remain in place. The decision gates for actual ranker promotion evidence open post-h20d IC checkpoint (2026-05-26) contingent on:
1. Spec 100 forward-return wiring implementation
2. 13F cohort distortion clearance validation
3. Spec 072 D7/D8/D9 re-verification completion

---

## Hard Blockers (All Enforced Until Post-h20d)

| # | Blocker | Type | Status | Action |
|---|---------|------|--------|--------|
| 1 | **Spec 096 doctrine** | Hard policy | ✅ Locked | Enforced for all ranker decisions |
| 2 | **Spec 100 true ranker IC tooling** | Code impl | ❌ Pending | Should complete before promotion evidence accepted (target: pre-h20d) |
| 3 | **Spec 094 marginal-value proof** | Evidence gate | ⏳ Design locked | Evidence collection post-13F-refresh; review 2026-05-22 onward |
| 4 | **Spec 095 IC-scope proof** | Audit gate | ⏳ Memo locked | Deferred until Spec 100 tool fix complete |
| 5 | **Checklist v2** | Gating battery | ❌ Not started | Gates locked until Specs 094/095 evidence pass |
| 6 | **13F Q1 2026 refresh** | Data gate | ⏳ Expected 2026-05-15 | Validation required before evidence gates open |
| 7 | **Spec 072 D7/D8/D9 re-verification** | Candidate validation | ⏳ Pending re-run post-refresh | Results due 2026-05-22 |

---

## Current Operating Stack (2026-05-14)

### Closed/Shipped
✅ **Spec 105** — Expectation Layer Coverage (commit `c6bcb91c`, 2026-05-14)
- All 4 expectation fields above thresholds: short_interest_pct 98.3%, close_price 100%, market_cap_mm 100%, priced_move_pct 83.6%
- Insider confirmed diagnostic-only (not consumed by ranker)

✅ **Spec 087 B2** — Dashboard Envelope (2026-05-14)

✅ **Spec 088 Phase B** — Catalyst Delta Filtered (2026-05-14)

### Pending (Not Blocking Ranker Review)
⏳ **Spec 104 Phase B** — Insider Stabilization (pending 2026-05-15 snapshot; 4/5 days measured)

⏳ **Spec 089 Phase 1.5A** — Ranker Governance KG Pilot (schema locked commit `8bee00e4`; implementation deferred post-closures)

### Implementation Gaps
❌ **Spec 100** — Scaffold only; forward-return wiring + IC computation remain stubbed; NOT usable for promotion evidence

---

## Dependencies & Validation Gates

### Pre-Review Validation (2026-05-15 through 2026-05-22)

**Gate: 13F Q1 2026 Refresh** (Expected ~2026-05-15)
```
✓ File freshness: institutional_summary.json mtime > 2026-05-14; as_of_date >= 2026-04-30
✓ inst_delta_z normalization: mean |x| ≠ locked 0.743 value
✓ SIGNAL_ALERT clearance: ic_health_monitor clears inst_delta_z alert at next heartbeat
✓ Top-ticker attribution: ALMS/ANAB rank deltas stabilize post-refresh
✓ No model changes: selector/ranker/sizing weights unchanged; organic snapshot only
```
**Owner**: Operator (2026-05-16 validation)  
**Pass Threshold**: All 5 checks must pass before evidence gates can open

**Gate: CRT Test** (Scheduled 2026-05-20)
```
✓ Cohort Regime Test: partition pre/post cohort IC; confirm score_rank_pct WARN coincides with cohort expansion
✓ Expected finding: WARN was cohort-driven; clears post-refresh without model change
✓ If WARN persists: escalation path (Multi-Horizon IC → PIT audit → Checklist v2)
```
**Owner**: Operator (via ic_health_monitor + manual analysis)  
**Pass Threshold**: WARN streak explanation confirmed

**Gate: Spec 072 D7/D8/D9 Re-Verification** (Running 2026-05-16 through 2026-05-22)
```
✓ D7 (Orthogonality): clinical_score_v2_z correlation vs coinvest_score_z post-refresh
  — Current measurement contaminated by cohort-expanded coinvest baseline
✓ D8 (Within-Quintile IC): IC on correct "top coinvest quintile" post-refresh
  — Current quintile membership wrong due to distorted coinvest_score_z
✓ D9 (Non-Orthogonality Dock): evaluated against clinical_design_quality post-refresh
```
**Owner**: Spec 072 sponsor  
**Results Due**: 2026-05-22 (at review)  
**Pass Threshold**: 
- ✅ All 3 pass → candidate eligible for h20d evidence battery (post-h20d only)
- ⚠️ Any fail → candidate blocked until root cause resolved

---

## What Cannot Change (Until Post-h20d)

🚫 Selector weights (0.65 × coinvest, 0.35 × inst_delta)  
🚫 Ranker v2 weights (2-feature pairwise)  
🚫 Sizing logic  
🚫 Spec 072 promotion (clinical candidate to alpha)  
🚫 score_rank_pct weight (requires CRT + Multi-Horizon IC + PIT audit + Checklist v2)

---

## Next Concrete Operational Actions

### Immediate (Today, 2026-05-14)
- ✅ This brief prepared; shared with 2026-05-22 review stakeholders
- ⏳ Await 2026-05-15 13F filing availability (SEC EDGAR)

### Post-13F-Refresh (2026-05-16 onward)
1. **Trigger institutional data ingest** once SEC files available (2026-05-15 EOD or 2026-05-16 AM)
2. **Run 2026-05-15 snapshot** (triggers inst_delta_z recomputation against fresh institutional_summary.json)
3. **Run validation gates** (file freshness, as_of_date, inst_delta_z normalization, SIGNAL_ALERT, top-ticker attribution)
4. **Close Spec 104 Phase B** (run 5th day insider measurement; finalize stabilization report)
5. **Commit post-refresh audit** to `artifacts/audit/13f_q1_2026_refresh_postmortem_2026_05_XX.md`
6. **Brief CRT test sponsor** (cohort regime analysis due 2026-05-20)

### Pre-Review (2026-05-20 through 2026-05-22)
1. **Finalize CRT test results** (2026-05-20 EOD) — confirm cohort distortion hypothesis
2. **Collect Spec 072 D7/D8/D9 re-verification results** (running through 2026-05-22)
3. **Update blockers brief** with post-refresh status for all 7 hard blockers
4. **Prepare 2026-05-22 presentation**:
   - Cohort distortion clearance status (CLEARED / PARTIALLY CLEARED / STILL CONTAMINATED)
   - CRT test verdict (WARN was cohort-driven / WARN persists)
   - Spec 072 D7/D8/D9 re-verification results (all pass / conditional / fail)
   - Spec 100 status (timeline for forward-return wiring implementation)
   - Checklist v2 readiness (when can batteries start for passing candidates)

---

## Key Message for Review Attendees

```
All hard blockers remain in place. No selector weights, ranker weights, 
sizing logic, Spec 072 promotion, or score_rank_pct action authorized 
until post-refresh evidence gates clear (post-h20d checkpoint 2026-05-26).

The 2026-05-22 review is a governance briefing to:
1. Confirm cohort distortion cleared
2. Review Spec 072 candidate re-verification results
3. Update evidence collection roadmap
4. Set expectations for post-h20d decision gates (2026-05-26 onward)
```

---

## Timeline Summary

```
2026-05-15 PM   ← 13F Q1 2026 files available (expected)
2026-05-16 AM   ← Institutional data ingest triggered; snapshot generated
2026-05-16 PM   ← Validation gates pass; post-refresh audit committed
2026-05-20      ← CRT test complete; score_rank_pct WARN verdict ready
2026-05-22      ← Ranker review (governance checkpoint; interim evidence status)
2026-05-26      ← h20d IC checkpoint; decision gates open for post-review promotion evidence
```

---

## References

- **Spec 096 doctrine**: `policy_alpha_freeze_2026_04_04.md`
- **Spec 100 governance**: `specs/changes/spec_100_governance_follow_up_2026_05_13.md`
- **Spec 072 design**: `specs/changes/spec_072_screener_vnext_2026_05_01.md`
- **13F refresh preflight**: `artifacts/audit/13f_q1_2026_refresh_preflight_2026_05_14.md`
- **Cohort distortion regime**: `memory/regime_post_cohort_change_distortion_2026_04_28.md`
- **score_rank_pct evidence bundle**: `artifacts/audit/score_rank_pct_evidence_bundle_template_2026_05_14.md`
- **Review framing**: `memory/2026_05_22_ranker_review_framing.md`
