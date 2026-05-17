# 13F Q1 2026 Cohort Refresh Runbook

**Purpose:** Deterministic validation workflow for May 2026 13F refresh. Enables fast clearance decision when holdings exceed 70% filing threshold (~2026-05-23).

**Scope:** Refresh monitoring, validation gates, quarantine lift criteria, forbidden changes during freeze.

**Timeline:**
- **Now (2026-05-17):** Runbook ready, monitoring active
- **~2026-05-23:** Expected ≥34 managers filed (trigger validation rerun)
- **~2026-05-26:** h20d checkpoint, architecture freeze lift decision
- **~2026-06-20:** Final quarantine lift or extension decision

---

## Monitoring Status

**Current state (2026-05-15):**
- Filed: 6/48 managers (12.5%) — Renaissance, RTW, Soleus, Avidity, Avoro, Krensavage
- Holdings file: `holdings_2026-03-31.json` created (210 tickers, 345 positions)
- Cohort Jaccard: 0.536 (< 0.70 threshold; quarantine ACTIVE)
- inst_delta_z distortion: Locked at mean |0.743| since 2026-04-25 (stale 4-manager addition)
- Monitoring cron: Weekday 6:22 PM ET via job 7b627c0e (active through 2026-06-20)

**Expected timeline:**
| Date | Target | Event |
|------|--------|-------|
| 2026-05-20 | 50% (24+ mgrs) | Monitoring continues |
| 2026-05-22 | 70% (34+ mgrs) | **VALIDATION RERUN TRIGGER** |
| 2026-06-01 | 95% (45+ mgrs) | Near-final cohort |
| 2026-06-15 | 100% filing deadline | All 48 should be in |
| 2026-06-20 | Clearance decision | Gates pass/fail verdict |

---

## Validation Gates (6 Required)

When ≥34 managers filed, run ALL 6 gates before lift decision. **All must pass** for quarantine clearance.

### Gate 1: File Freshness

**Command:**
```bash
python -c "
import json
from datetime import datetime
summary = json.load(open('production_data/institutional_summary.json'))
print(f'cache_as_of_date: {summary.get(\"cache_as_of_date\")}')
import os
mtime = os.path.getmtime('production_data/institutional_summary.json')
print(f'mtime: {datetime.fromtimestamp(mtime)}')
"
```

**Pass condition:**
- `cache_as_of_date` ≥ 2026-04-30 (Q1 2026 cutoff)
- `mtime` > 2026-05-22 12:00 ET (fresher than pre-refresh state of 2026-04-25)

**Fail action:** Defer validation; file not yet refreshed.

---

### Gate 2: inst_delta_z Normalization

**Command:**
```bash
python -m tools.data_explorer compare \
  --date-a 2026-04-24 \
  --date-b 2026-05-22 \
  --field inst_delta_z \
  --output artifacts/13f_validation/inst_delta_z_ks_test_2026_05_22.json
```

**Pass condition:**
- KS-statistic ≥ 0.30 vs pre-refresh (2026-04-24) baseline
- Mean |inst_delta_z| distribution differs from locked 0.743
- (This IS expected — the refresh causes this change.)

**Fail action:** Distortion persists; new filings not ingested. Check file freshness (Gate 1).

---

### Gate 3: SIGNAL_ALERT Clearance

**Command:**
```bash
grep -c "SIGNAL_ALERT" artifacts/rank_change_monitor_2026_05_22.log
```

**Pass condition:**
- SIGNAL_ALERT entry for inst_delta_z exists
- Next entry shows `status: cleared` or timestamp > 2026-05-23 06:00 ET

**Fail action:** SIGNAL_ALERT still active; defer lift. Monitoring continues.

**Note:** This clears automatically at next ic_health heartbeat post-ingest (usually within 24 hours of Gate 1 passing).

---

### Gate 4: Top-30 Composition Audit

**Command:**
```bash
python -m tools.check_13f_cohort_quarantine \
  --pre-date 2026-04-24 \
  --post-date 2026-05-22 \
  --output artifacts/13f_validation/jaccard_and_attribution_2026_05_22.md
```

**Pass condition:**
- Top-30 Jaccard ≥ 0.70
- Changed tickers (entries/exits): < 15 (vs pre-refresh top-30)
- Largest attribution deltas attributable to manager composition (ALMS entry, ANAB dropout)

**Fail action:**
- If Jaccard < 0.70: quarantine continues until next batch
- If delta > threshold: document as regime shift, defer model decisions

---

### Gate 5: Governance Segregation (No Model Changes)

**Verification checklist:**
```
□ Selector weights unchanged (0.65 coinvest + 0.35 inst_delta)
□ Ranker v2 features unchanged (2-feature pairwise)
□ Ranking methodology unchanged (A4 + 2-feat ranker + EW Top-30)
□ Scoring module weights unchanged (Module 5 rank-norm for financial_score)
□ Production runs 2026-04-25 through 2026-05-22 organic (data-only, no logic changes)
□ No selector/ranker/sizing decisions made during quarantine window
```

**Pass condition:** All checkboxes verified via commit log audit.

**Fail action:** If any model change detected, halt lift decision; escalate.

---

### Gate 6: Producer Data Quality (G1/G2/G3 Guardrails)

**Command:**
```bash
python -m tools.check_13f_cohort_quarantine \
  --pre-date 2026-04-24 \
  --post-date 2026-05-22 \
  --guardrail-check \
  --output artifacts/13f_validation/producer_qa_2026_05_22.txt
```

**G1 - Snapshot Completeness:**
- rankings.csv exists for 2026-05-22
- institutional_summary_delta.json generated
- inst_delta_z standard deviation > 0.1

**G2 - Producer Freshness:**
- `institutional_summary.json:cache_as_of_date` advanced from 2026-04-13
- `prior_date` in delta JSON advanced (reflects new manager set)

**G3 - Cause Attribution:**
- Manager-level changes (4 added 2026-04-25, new filings ~2026-05-22)
- Snapshot-window changes (manual roll vs automatic)
- Distinguish data event (holdings refresh) from signal event (alpha change)

**Pass condition:** All G1/G2/G3 guardrails clear.

**Fail action:** Producer audit required; defer lift.

---

## Hard NO-GO Conditions (Forbidden Even If All Gates Pass)

| Condition | Action | Reason |
|-----------|--------|--------|
| Architecture freeze NOT lifted (~2026-05-26) | BLOCK ranker/selector/sizing changes | Policy until h20d checkpoint |
| Cohort Jaccard < 0.70 | BLOCK any model decision | Top-30 still unstable |
| Coverage drop ≥10pp (tickers_common) | BLOCK; producer audit required | Likely producer error, not regime |
| Manager Δ (new + removed) > 5 | Extended quarantine (~3 weeks) | Cohort-contaminated, attribution ambiguous |
| coinvest_score_z KS ≥ 0.20 vs pre-refresh | Manual review required | Possible registry corruption |
| SIGNAL_ALERT still active | BLOCK lift; monitoring continues | Pending ic_health heartbeat |

---

## Decision Matrix: Clearance Verdict

```
If ALL 6 gates PASS + NO hard NO-GO conditions:
  → Quarantine LIFTED (conditional on freeze lift ~2026-05-26)
  → Ranker/selector/sizing changes UNBLOCKED (post-freeze only)
  → Proceed to Checklist v2 / IC validation (Spec 100 final_score baseline)
  
If ANY gate FAILS or hard NO-GO triggered:
  → Quarantine EXTENDED 10 trading days
  → Re-validate after next batch
  → No model changes authorized
  
If Jaccard 0.70–0.85 (borderline):
  → Standard cohort window (no special handling)
  → Proceed with standard governance (Checklist v2)
  → Monitor for additional drift
```

---

## Commands Quick Reference

### Pre-May-23 (Monitoring Phase)
```bash
# Check filing progress
cat production_data/13f_filing_status.json | jq '.filing_count'

# Expected output: will increment as new filings arrive
```

### Post-May-23 (Validation Phase)
```bash
# Run all gates in sequence
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Gate 1: File freshness
python -c "import json; print(json.load(open('production_data/institutional_summary.json')).get('cache_as_of_date'))"

# Gate 2: inst_delta_z normalization
python -m tools.data_explorer compare --date-a 2026-04-24 --date-b 2026-05-22 --field inst_delta_z

# Gate 3: SIGNAL_ALERT status
grep SIGNAL_ALERT artifacts/rank_change_monitor_2026_05_22.log | tail -3

# Gate 4: Jaccard + attribution
python -m tools.check_13f_cohort_quarantine --pre-date 2026-04-24 --post-date 2026-05-22 | tee artifacts/13f_validation/verdict_2026_05_22.md

# Gate 5: Model change audit
git log --oneline 2026-04-25..2026-05-22 -- "common/ranker_active_contract.py" "scoring_model_*.py" "module_*.py" | wc -l
# Should be 0 (no logic changes)

# Gate 6: Producer QA
python -m tools.check_13f_cohort_quarantine --pre-date 2026-04-24 --post-date 2026-05-22 --guardrail-check
```

### Decision Memo Template
```markdown
# 13F Q1 2026 Cohort Refresh Clearance Decision
**Date:** [YYYY-MM-DD]
**Filing count:** [N/48 managers]
**Cohort Jaccard:** [X.XX]

## Gate Results
- Gate 1 (File freshness): [PASS/FAIL]
- Gate 2 (inst_delta normalization): [PASS/FAIL]
- Gate 3 (SIGNAL_ALERT): [PASS/FAIL]
- Gate 4 (Jaccard audit): [PASS/FAIL]
- Gate 5 (No model changes): [PASS/FAIL]
- Gate 6 (Producer QA): [PASS/FAIL]

## Hard NO-GO Check
- Architecture freeze lifted: [YES/NO] → [PROCEED/HOLD]
- Jaccard ≥ 0.70: [YES/NO] → [PROCEED/EXTEND]
- Coverage drop < 10pp: [YES/NO] → [PROCEED/AUDIT]
- Manager Δ ≤ 5: [YES/NO] → [PROCEED/EXTEND]
- coinvest KS < 0.20: [YES/NO] → [PROCEED/REVIEW]
- SIGNAL_ALERT cleared: [YES/NO] → [PROCEED/HOLD]

## Verdict
[LIFT QUARANTINE / EXTEND 10 DAYS / ESCALATE]

If LIFT: Ranker IC validation (Spec 100 final_score) proceeds post-freeze-lift (~2026-05-26).
If EXTEND: Next validation window ~2026-06-02 (assuming continuous filing).
If ESCALATE: [Root cause + remediation plan]

**Sign-off:** [User approval]
**Committed:** [Commit hash of decision memo]
```

---

## Key Constraints

**During 13F quarantine (through 2026-05-22 or until cleared):**
- ✗ Do NOT use fresh holdings for alpha/ranker/selector decisions
- ✗ Do NOT claim top-30 changes are signal (cohort artifact risk)
- ✗ Do NOT promote institutions/signals based on early filer subset
- ✗ Do NOT modify institutional_summary.json (producer-only)
- ✓ Attribution analysis + observation lane OK
- ✓ Non-model-dependent specs (KG, Hermes infrastructure) OK

**Even after quarantine lifts (~2026-05-26):**
- ✗ Do NOT change ranker/selector/sizing until architecture freeze lifts (~2026-05-26)
- ✗ Do NOT use old IC claims (composite_score); use Spec 100 final_score only
- ✓ Full Checklist v2 battery + forward validation required for any promotion

---

## Related Documentation

- **Cohort quarantine prep:** `13f_cohort_quarantine_prep_2026_05_01.md` (memory)
- **13F monitoring status:** `13f_q1_2026_monitoring_live_2026_05_15.md` (memory)
- **Preflight validation gates:** `13f_q1_2026_preflight_2026_05_14.md` (memory)
- **Distortion regime:** `regime_post_cohort_change_distortion_2026_04_28.md` (memory)
- **Architecture freeze:** `policy_freeze_architecture_2026_04_19.md` (memory)

---

## Revision History

- **2026-05-17:** Initial runbook; gates documented; decision matrix defined
- Expected next update: 2026-05-23 (post-validation)
