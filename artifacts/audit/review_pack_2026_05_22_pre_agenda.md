# 2026-05-22 Ranker Research Review Pack — Pre-Agenda

**Date prepared:** 2026-05-14  
**Review date:** 2026-05-22 (or earliest post-cohort-window day with sufficient clean data)  
**Status:** PREP (no action until review date; all scaffolding pre-positioned)

---

## Pre-Review Gates (Must Pass Before Starting Review)

### Gate 1: 13F Q1 2026 Refresh Completion

**Check on 2026-05-22 morning:**
```bash
python3 -c "
import json
inst = json.load(open('production_data/institutional_summary.json'))
print(f'as_of_date: {inst[\"as_of_date\"]}')
print(f'mtime: {inst.get(\"created_at\", \"N/A\")}')
assert inst['as_of_date'] >= '2026-04-30', 'Q1 2026 refresh not complete'
assert inst['elite_managers_total'] >= 37, 'Manager count unexpected'
"
```

**Pass criterion:** as_of_date >= 2026-04-30 (Q1 2026 cutoff)

**Fail action:** Defer entire review to 2026-05-23 or later.

---

### Gate 2: Cohort Distortion Clearance

**Check on 2026-05-22 morning (latest snapshot, typically 2026-05-21):**
```bash
python3 -c "
import csv
from pathlib import Path

snap_date = '2026-05-21'  # or latest available
snap_path = Path(f'data/snapshots/{snap_date}/rankings.csv')
rows = list(csv.DictReader(open(snap_path)))

inst_z = [float(r['inst_delta_z']) for r in rows if r.get('inst_delta_z')]
mean_abs = sum(abs(x) for x in inst_z) / len(inst_z)
max_abs = max(abs(x) for x in inst_z)

print(f'Snapshot: {snap_date}')
print(f'Mean |inst_delta_z|: {mean_abs:.3f} (locked: 0.743)')
print(f'Max |inst_delta_z|: {max_abs:.3f} (locked: 4.42)')

# Pass if distortion cleared
assert mean_abs < 0.70, f'Distortion NOT cleared: mean={mean_abs:.3f} vs threshold 0.70'
assert max_abs < 4.0, f'Max still high: {max_abs:.3f} vs threshold 4.0'
print('✓ PASS: Cohort distortion cleared')
"
```

**Pass criterion:** Mean |inst_delta_z| < 0.70 AND Max |inst_delta_z| < 4.0

**Fail action:** Defer entire review to 2026-05-23 or later; wait for additional 13F processing.

---

### Gate 3: Sufficient Forward-Return Window

**Check:** Latest snapshot date >= 2026-05-21 (at least 1 week post-13F refresh; T+5 returns computable)

**Pass criterion:** Can compute T+5 returns on at least 5 snapshots post-cohort-clear

**Fail action:** Defer entire review to 2026-05-29 or later; accumulate more post-clear data.

---

## Review Agenda (If All Pre-Gates Pass)

### Section A: Spec 072 — vNext Ranker Review (90 minutes)

**Timeline:** 09:00–10:30 ET

#### A1: D7/D8/D9 Pre-Run Validation (15 min)

Check that previous day's D7/D8/D9 diagnostic run is available:

```bash
ls -lh artifacts/research/spec_072/
# Expected files:
#   d7_orthogonality.csv
#   d8_within_quintile_ic.csv
#   d9_residualized_ic.csv
#   summary.md
```

**If files missing:** Run diagnostics now:
```bash
python3 scripts/research/run_spec072_vnext_verification.py \
  --start-date 2026-05-15 \
  --end-date 2026-05-21 \
  --candidate-set frozen \
  --output-dir artifacts/research/spec_072/
```

#### A2: D7 Orthogonality Verdict (15 min)

**Read:** `artifacts/research/spec_072/d7_orthogonality.csv`

**Threshold:**
```
Correlation with coinvest_score_z: |r| < 0.40
Residualized IC: >= +0.04 (t > 1.5, p < 0.05)
```

**Decision point:**
- **PASS:** Clinical_score_v2_z is orthogonal; proceed to A3
- **FAIL (|r| >= 0.40):** Candidate is redundant with selector; close PRIMARY; evaluate BACKUP
- **FAIL (residualized IC < 0.04):** Candidate has no independent signal; close PRIMARY; evaluate BACKUP

#### A3: D8 Within-Quintile IC Verdict (15 min)

**Read:** `artifacts/research/spec_072/d8_within_quintile_ic.csv`

**Threshold:**
```
T+5 IC within top-coinvest quintile: >= +0.06 (t > 1.5)
T+20 IC within top-coinvest quintile: >= +0.04 (t > 1.2)
Sample size: >= 30 tickers
```

**Decision point:**
- **PASS:** Candidate shows marginal ordering value within selector output; proceed to A4
- **FAIL:** No within-quintile IC; close candidate; evaluate BACKUP

#### A4: D9 Residualized IC Verdict (15 min)

**Read:** `artifacts/research/spec_072/d9_residualized_ic.csv`

**Threshold:**
```
Residualized T+5 IC: >= +0.04 (p < 0.05)
Residualized T+20 IC: >= +0.03 (p < 0.10)
Sign consistent with pre-residualization
```

**Decision point:**
- **PASS:** Candidate IC persists after coinvest removal; proceed to A5
- **FAIL:** IC was confounded with coinvest; close candidate

#### A5: Decision — Proceed to D1–D6 or Close (15 min)

**If D7/D8/D9 all PASS:**
- Proceed to D1–D6 diagnostics (see `spec_072_vnext_d1_d6_template_2026_05_14.md`)
- Timeline: 2026-05-24/25
- Expected completion: 2026-05-26 or 2026-05-27

**If ANY D7/D8/D9 FAIL:**
- Close PRIMARY candidate (clinical_score_v2_z)
- Evaluate BACKUP (endpoint_strength_score) with same D7/D8/D9 gates
  - If BACKUP passes: proceed to D1–D6 on BACKUP
  - If BACKUP fails: close Spec 072 research; document blocker; escalate

**Verdict memo:** Commit to `artifacts/audit/spec_072_d7_d8_d9_verdict_2026_05_22.md`

---

### Section B: Spec 091 — score_rank_pct WARN Governance (60 minutes)

**Timeline:** 10:30–11:30 ET

#### B1: WARN Status Check (10 min)

**Check:** Latest ic_health_monitor heartbeat (typically daily 19:00 ET)

```bash
# Check latest ic_health alert status
ls -lht data/snapshots/*/ic_health_monitor.json | head -3
# or check rank_change_alerts for SIGNAL_ALERT mention
```

**Question:** Did WARN clear post-13F-refresh?

#### B2: CRT — Cohort Regime Test (20 min)

**Purpose:** Separate cohort distortion artifact from true degradation

**Method:**
```bash
python3 -c "
import json
from pathlib import Path

# Pre-cohort IC (baseline, 2026-04-01 through 2026-04-24)
# Post-cohort IC (contaminated, 2026-04-25 through 2026-05-13)
# Post-refresh IC (clean, 2026-05-15 through 2026-05-21)

# Load ic_health snapshots from each period
# Compute score_rank_pct IC by period

# Hypothesis: if WARN enters at cohort expansion (2026-04-25) and clears post-refresh,
# then cohort distortion was cause
"
```

**Decision point:**
- **COHORT-DRIVEN:** WARN coincides with cohort expansion; clears post-refresh → close Spec 091 with no model change; document that cohort distortion was confounding variable
- **TRUE DEGRADATION:** WARN predates cohort expansion OR persists post-refresh → proceed to B3

#### B3: Multi-Horizon IC (if CRT shows true degradation) (20 min)

**Purpose:** Does score_rank_pct have real predictive power across horizons?

**Method:**
```bash
# Measure score_rank_pct IC on post-refresh clean data
# T+5, T+20, T+60 forward returns
# Threshold: at least 2 horizons with IC >= +0.04 (t > 1.5)
```

**Decision point:**
- **PASSES:** Real signal; proceed to B4 (PIT Audit)
- **FAILS:** No IC across horizons; retire signal; close Spec 091

#### B4: PIT Integrity Audit (if Multi-Horizon passes) (10 min)

**Purpose:** Are inputs clean?

**Checks:**
```bash
# 1. Missing values in inputs < 5%
# 2. Rank computation deterministic
# 3. No stale data
# 4. No double-counted signals
```

**Decision point:**
- **CLEAN:** Data is good; proceed to Checklist v2 (out of scope for 2026-05-22)
- **ISSUES:** Fix data/formula; re-run Multi-Horizon IC post-fix

**Verdict memo:** Commit to `artifacts/audit/spec_091_evidence_bundle_2026_05_22.md`

---

### Section C: Spec 096 — Doctrine Enforcement (30 minutes)

**Timeline:** 11:30–12:00 ET

#### C1: Gate/Ranker Separation Confirmation

**Checklist:**
- [ ] Selector excludes names (no continuous scoring in gate)
- [ ] Ranker ranks survivors only (ordinal; no confidence weights)
- [ ] Risk control is post-ranking overlay (not integrated into ranking)
- [ ] No composite construction during pending phase

#### C2: Marginal Value Gate Application

**Question:** Do Spec 072 and Spec 091 candidates require marginal value proof?

**Answer:** YES. Spec 096 requires:
- Spec 072: D8 (within-quintile IC) proves marginal ordering value ✓
- Spec 091: Multi-Horizon IC required before consideration ✓

#### C3: Blockers Review (Specs 094, 095, old-100)

**Status check:**
- [ ] Spec 094 (marginal value proof): Spec 072 D8 test satisfies this
- [ ] Spec 095 (IC scope correction): Old Spec 100 tooling not yet built; Spec 072 uses post-hoc D8 test (not true ranker IC)
- [ ] Old Spec 100 (ranker IC tooling): Not built; blocks any ranker promotion

**Implication:** Even if Spec 072 D7/D8/D9 all pass AND D1–D6 passes, ranker promotion cannot proceed until Spec 100 IC tooling is implemented.

**Decision:** Spec 072 verdict is "promote to shadow phase" not "promote to production."

---

### Section D: Forward-Return Test — Post-Cohort-Window Accumulation (30 minutes)

**Timeline:** 12:00–12:30 ET

#### D1: Coinvest vs Production Top-30 Comparison

**Purpose:** Sanity check that forward returns are comparable post-cohort-clear

**Method:**
```bash
# Measure T+5/T+20 returns on:
# - Current production Top-30 (2026-05-15 through 2026-05-21)
# - Coinvest-only ranking (0.65 × coinvest, no inst_delta)

# Compare margins (expected: within ±1pp)
```

**Decision point:**
- **COMPARABLE:** Ranker is not broken; proceed to final review section
- **DIVERGENT (> ±2pp):** Investigate whether inst_delta contamination is still active despite cohort-clear metrics

#### D2: Forward-Return Window Sufficiency

**Question:** Do we have enough data for statistical power?

**Requirement:** >= 20 snapshots with T+5/T+20 returns (roughly 4 weeks post-cohort-clear)

**Timeline:** If 2026-05-15 is post-refresh, then 2026-05-22 gives ~5 trading days of post-clear returns; need to defer full comparison to 2026-05-29 for T+5 sufficiency

**Decision:** May need to defer full forward-return comparison or use conservative (wider) confidence intervals on 2026-05-22

---

## Summary Verdict Template

**Verdict memo structure (commit after review):**

```markdown
# 2026-05-22 Ranker Research Review Verdict

**Date:** 2026-05-22  
**Pre-gates:** PASS / FAIL [details]

## Spec 072 — vNext Ranker Verdict
- D7 (Orthogonality): PASS / FAIL [details]
- D8 (Within-Quintile IC): PASS / FAIL [details]
- D9 (Residualized IC): PASS / FAIL [details]
- **Decision:** Proceed to D1-D6 / Close PRIMARY / Evaluate BACKUP / Close research

## Spec 091 — score_rank_pct WARN Verdict
- CRT (Cohort-driven?): YES / NO [details]
- Multi-Horizon IC (if applicable): PASS / FAIL [details]
- **Decision:** Close with no change / Retire signal / Prepare evidence bundle

## Spec 096 — Doctrine Enforcement
- Gate/ranker separation: ✓ Confirmed
- Marginal value gate: ✓ Applied
- Blockers (Spec 094/095/100): Spec 100 IC tooling still required
- **Decision:** All pending research respects doctrine; no production changes authorized yet

## Forward-Return Test
- Coinvest vs production margin: [details]
- Data sufficiency: READY / PENDING [date]

## Overall Verdict
[Summary of go/no-go decisions and next steps]
```

---

## Timeline & Execution Notes

**2026-05-22 morning (before review):**
- Verify all pre-gates pass
- Confirm D7/D8/D9 diagnostic outputs available
- Prepare verdict memo shell

**2026-05-22 (review day):**
- Section A (Spec 072): 90 min
- Section B (Spec 091): 60 min
- Section C (Spec 096): 30 min
- Section D (Forward-return test): 30 min
- **Total:** ~3.5 hours

**2026-05-22 evening:**
- Commit verdict memo
- Identify next steps (D1–D6 if Spec 072 passes, etc.)

**2026-05-24/25 (if Spec 072 D7/D8/D9 pass):**
- Begin D1–D6 diagnostics
- Expected completion: 2026-05-26 or 2026-05-27

**2026-05-29:**
- Final review of all research outcomes
- Spec 096 enforcement confirmation
- Decision on shadow-phase advancement for Specs 098/099

---

## Prohibited Actions During Review

❌ Do NOT make production ranker changes based on review outcomes  
❌ Do NOT change selector weights (0.65/0.35)  
❌ Do NOT promote Spec 072 candidate to production without D1–D6 pass + Checklist v2  
❌ Do NOT promote Spec 091 action without full evidence bundle (CRT + Multi-Horizon + PIT + Checklist v2)  
❌ Do NOT interpret review outcomes as signal validation (requires Spec 100 IC tooling)  

---

## Success Criteria for Review

**Spec 072:**
- ✓ D7/D8/D9 gates clear AND D1–D6 plan documented

**Spec 091:**
- ✓ CRT verdict clear AND (WARN attributed or Multi-Horizon test planned)

**Spec 096:**
- ✓ Doctrine enforcement confirmed; no production changes authorized

**Forward-return test:**
- ✓ Baseline comparison shows ranker not broken; window sufficiency assessed

**Overall:**
- ✓ All verdicts documented
- ✓ Next phase (D1–D6, evidence bundle, shadow lanes) clearly scoped
- ✓ No production changes made
- ✓ Spec 096 blockers (Spec 100) remain outstanding

---

## References

- Spec 072 D7/D8/D9 prep: `artifacts/audit/spec_072_vnext_ranker_review_prep_2026_05_14.md`
- Spec 072 D1–D6 template: `artifacts/audit/spec_072_vnext_d1_d6_template_2026_05_14.md`
- Spec 091 evidence bundle: `artifacts/audit/score_rank_pct_evidence_bundle_template_2026_05_14.md`
- 13F cohort impact: `artifacts/audit/13f_q1_2026_ranker_research_preflight_2026_05_14.md`
- Current ranker identity: `artifacts/audit/current_ranker_identity_2026_05_14.md`
- Ranker research landscape: `memory/ranker_research_landscape_2026_05_14.md`
