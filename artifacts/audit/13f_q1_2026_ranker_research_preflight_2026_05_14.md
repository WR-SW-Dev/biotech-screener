# 13F Q1 2026 Cohort Refresh: Why Ranker Research Interpretation Depends on Cohort State

**Date:** 2026-05-14  
**Status:** PREFLIGHT (read-only; no action)  
**Purpose:** Document how cohort distortion contaminates ranker research conclusions; structure clean-cohort-state requirement for 2026-05-22 verdict

---

## The Problem: Cohort Distortion Window (2026-04-25 through ~2026-05-15)

### What Happened

**2026-04-25, Saturday 12:57 ET:** Four new institutional managers added to elite_core via force-rebuild:
- Fairmount Funds Management (CIK 0001802528)
- Vestal Point Capital (CIK 0001974915)
- Kynam Capital Management (CIK 0001907884)
- Soleus Capital Management (CIK 0001802630)

**Root cause:** Manual `--force-overwrite --allow-weekend` rebuild closed institutional_summary gate for 4 new managers.

**Result:** Cohort expansion changed the baseline for all selection and ranking signals that depend on institutional data or relative positioning within the manager elite.

---

## How Cohort Distortion Affects Ranker Research

### Contaminated Signals

**inst_delta_z (directly affected):**
- Definition: change in elite manager holdings vs sector baseline
- Problem: baseline includes the 4 new managers (as of 2026-04-25 only)
- Symptom: inst_delta_z values locked at mean=0.743, max=4.42 across 19 consecutive snapshots (no new 13F data to recalibrate)
- Impact on selector: selector uses `0.35 × inst_delta_z` → biased eligibility decisions during distortion window

**coinvest_score_z (indirectly affected):**
- Definition: manager consensus signal aggregated from elite_core
- Problem: elite_core now includes 4 new managers → consensus weighted toward their holdings
- Symptom: subtle shift in which tickers appear in top-coinvest quintile; not locked, but slowly contaminating
- Impact on selector & ranker: selector uses `0.65 × coinvest_score_z`; ranker uses coinvest as 1 of 2 features

**score_rank_pct (indirectly affected via ranking changes):**
- Problem: if ranking reflects distorted cohort state, IC measurements are confounded
- Symptom: score_rank_pct WARN streak coincides with cohort expansion (2026-04-25)
- Impact on Spec 091: cannot determine whether WARN is true degradation or cohort artifact without post-refresh evidence

### Why This Matters for Spec 072 (vNext Ranker)

**Spec 072 frozen candidate set:**
- PRIMARY: `clinical_score_v2_z`
- BACKUP: `endpoint_strength_score`

**Interpretation problem:**
- If candidate shows good D8/D9 results during 2026-04-25 through 2026-05-13 window, are we measuring:
  - Real signal strength? OR
  - Candidate's fit to distorted cohort state?

**Example:** If clinical_score_v2_z ranks highly on specific tickers during distortion window, but those tickers only appear in Top-30 because coinvest_score_z is now biased (4 new managers), then D8 IC (within high-coinvest quintile) is measuring artifact, not signal.

---

## Why D7/D8/D9 Must Re-Run Post-13F-Refresh

### D7: Orthogonality

**Window issue:**
- `clinical_score_v2_z` correlation with coinvest_score_z is measured against **contaminated coinvest_score_z** during distortion
- Apparent correlation may be inflated (candidate appears orthogonal only because coinvest is miscalibrated)

**Solution:**
- Re-measure correlation post-13F-refresh on clean coinvest_score_z
- If correlation increases post-refresh (was artificially suppressed by distortion): candidate is NOT orthogonal
- If correlation stays the same: confidence in D7 pass is higher

---

### D8: Within-Quintile IC

**Window issue:**
- "Top coinvest quintile" is defined against **distorted coinvest_score_z** → quintile membership is wrong
- IC measured on wrong set of tickers → not valid measurement of marginal value

**Example drift:**
```
Pre-distortion (2026-04-23): Top quintile = [A, B, C, D, E, ...] (60 tickers)
Distortion (2026-04-25): Top quintile = [A, B, C', D', E', ...] (60 tickers; different members due to 4 new managers)
Post-refresh (2026-05-15): Top quintile = [A, B, C, D, E, ...] (reverts closer to pre-distortion)
```

**Solution:**
- Re-measure D8 on post-13F-refresh clean coinvest quintiles
- If D8 IC changes substantially → preliminary (distortion-window) results were confounded
- If D8 IC stays similar → preliminary results more trustworthy

---

### D9: Bin-Residualized IC

**Window issue:**
- Bin boundaries (stratified by coinvest_score_z) are wrong during distortion
- Within-bin IC measured on misaligned bins → noise

**Solution:**
- Re-run D9 on post-13F-refresh with correct bin boundaries
- If IC changes → distortion was major confounder
- If IC stable → candidate signal persists despite distortion

---

## Verification Sequence: 2026-05-22

### Pre-Verification Gate (must pass before proceeding to D7/D8/D9 re-run)

```bash
# 1. Check 13F refresh completed
python3 -c "
import json
inst = json.load(open('production_data/institutional_summary.json'))
print(f'as_of_date: {inst[\"as_of_date\"]}')
print(f'Required: >= 2026-04-30')
assert inst['as_of_date'] >= '2026-04-30', 'Q1 2026 refresh not yet complete'
"

# 2. Check inst_delta_z distortion cleared
python3 -c "
import csv
from pathlib import Path
snap = Path('data/snapshots/2026-05-21/rankings.csv')
rows = list(csv.DictReader(open(snap)))
inst_z = [float(r['inst_delta_z']) for r in rows if r.get('inst_delta_z')]
mean_abs = sum(abs(x) for x in inst_z) / len(inst_z)
print(f'Mean |inst_delta_z|: {mean_abs:.3f}')
print(f'Locked value: 0.743')
assert mean_abs < 0.70, 'inst_delta_z distortion still active; defer review'
"
```

**If either gate fails:** Defer D7/D8/D9 re-run until post-13F-refresh window fully clear (~2026-05-20).

### D7/D8/D9 Re-Run (only after gates pass)

```bash
python3 scripts/research/run_spec072_vnext_verification.py \
  --start-date 2026-05-15 \
  --end-date 2026-05-21 \
  --candidate-set frozen \
  --output-dir artifacts/research/spec_072/
```

**Comparison:** Check if D7/D8/D9 thresholds differ from preliminary window (2026-04-25 through 2026-05-13).

**Expected:**
- If preliminary D8/D9 passed on distortion-window data, post-refresh re-run may show different IC
- If results are similar: confidence in candidate is higher
- If results change materially: preliminary results were confounded; re-evaluate

---

## Cohort State Timeline

| Date Range | Cohort State | Data Quality | Research Use |
|---|---|---|---|
| 2026-04-01–04-24 | Clean (pre-expansion) | Good | Baseline reference |
| 2026-04-25–05-13 | Distorted (4 mgrs added) | Contaminated | ⚠ Preliminary only; do not base final verdict |
| 2026-05-14 | Distorted (no 13F update) | Stale | Not useful for research |
| 2026-05-15+ (post-refresh) | Clean (Q1 2026 filings ingested) | Fresh | ✓ Use for final verification |

---

## Which Specs Are Affected

### Directly Affected (Cannot Verify Until Cohort Clear)

**Spec 072 (vNext Ranker):**
- D7/D8/D9 gates must re-run on clean cohort data
- Cannot approve frozen candidate until post-refresh verification
- Preliminary results are indicative only

**Spec 091 (score_rank_pct Warning):**
- CRT test must determine if WARN is cohort-driven or true degradation
- Cannot assess Multi-Horizon IC until post-13F-refresh data available
- Cannot make governance decision without evidence bundle

### Indirectly Affected (May Be Reinterpreted)

**Spec 096 (Doctrine):**
- Doctrine is frozen; no change needed
- But interpretation of which signals are "marginal" depends on clean cohort state

**13F Refresh Preflight (General):**
- Same cohort validation applies to all research that depends on institutional data

---

## Decision Point: 2026-05-22

**Only proceed to final Spec 072 verdict if:**
1. ✓ 13F Q1 2026 refresh completed (as_of_date >= 2026-04-30)
2. ✓ inst_delta_z distortion cleared (mean |x| < 0.70, no longer locked at 0.743)
3. ✓ D7/D8/D9 re-run on clean post-refresh data (2026-05-15 through 2026-05-21)
4. ✓ Results match or exceed preliminary thresholds

**If any gate fails:** Defer Spec 072 verdict to 2026-05-29 or beyond.

---

## Contamination Risk Summary

| Risk | Severity | Mitigated By |
|---|---|---|
| inst_delta_z locked at 0.743 (no fresh 13F) | HIGH | Wait for 13F refresh; verify normalization |
| coinvest_score_z shifted (4 new mgrs) | MEDIUM | Re-run D7 orthogonality test post-refresh |
| Top-coinvest quintile membership wrong | MEDIUM | Re-compute D8 bin boundaries post-refresh |
| Bin-residualized IC on wrong strata | MEDIUM | Re-run D9 stratification post-refresh |
| score_rank_pct IC confounded | HIGH | Run CRT test to separate distortion from signal |

---

## Guardrails

❌ Do NOT base final D7/D8/D9 verdict on distortion-window (2026-04-25 through 2026-05-13) data  
❌ Do NOT interpret preliminary D8/D9 results as promotion-ready without post-refresh re-verification  
❌ Do NOT change selector/ranker during distortion window based on research findings  
❌ Do NOT mix distortion-window data with post-refresh data in same IC calculation  
✓ DO re-run D7/D8/D9 on clean post-refresh window (2026-05-15+) before 2026-05-22 decision  
✓ DO require 13F refresh completion AND distortion clearance before final verdict  

---

## References

- **Cohort distortion regime:** `memory/regime_post_cohort_change_distortion_2026_04_28.md`
- **13F Q1 2026 general preflight:** `artifacts/audit/13f_q1_2026_refresh_preflight_2026_05_14.md`
- **Spec 072 D7/D8/D9 prep:** `artifacts/audit/spec_072_vnext_ranker_review_prep_2026_05_14.md`
- **Spec 091 evidence bundle:** `artifacts/audit/score_rank_pct_evidence_bundle_template_2026_05_14.md`
- **Spec 096 doctrine:** Gate/ranker separation; marginal value requirement
