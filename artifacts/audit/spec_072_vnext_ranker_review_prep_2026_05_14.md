# Spec 072: vNext Ranker Review Prep — 2026-05-22 Verification Package

**Date:** 2026-05-14  
**Status:** PREP (no model changes; read-only scaffolding)  
**Review window:** 2026-05-22 (on or after cohort-window close + 13F Q1 2026 refresh validated)

---

## Spec 072 Frozen Candidate Set

**PRIMARY:** `clinical_score_v2_z`  
**BACKUP:** `endpoint_strength_score`

No additions, removals, substitutions, or tuning. These are the only candidates subject to 2026-05-22 verification.

### Why Frozen

Preliminary D8/D9 results strong (conditional IC ≈ +0.20 within L3 coinvest; effective ~+3 NW-corrected) but:
- Sample short (5–10 tickers)
- Partially overlaps cohort-quarantine window (2026-04-25 onward; distortion active)
- Does not meet promotion-grade threshold yet

Verification gates (D7/D8/D9) must pass **again** on post-cohort-window, post-13F-refresh clean data before advancing to full diagnostic (D1–D6).

---

## Diagnostic Sequence & Thresholds

### D7: Orthogonality

**Definition:** Candidate is orthogonal to coinvest_score_z (selector input already carries manager insight).

**Method:** Pearson correlation + residualized IC (remove coinvest effect, remeasure candidate IC).

**Pass threshold:**
```
Correlation with coinvest_score_z: |r| < 0.40
Residualized IC after coinvest removal: still significant (p < 0.05, t > 1.96)
```

**Fail:** Correlation > 0.40 or residualized IC loses significance → candidate is redundant with selector; do not advance.

---

### D8: Within-Quintile IC (Marginal Ordering Value)

**Definition:** Candidate ranks names **within** high-coinvest quintile (not across universe; constrained to where selector already passed).

**Method:** Partition top-quintile eligible names; compute T+5/T+20 forward-return correlation within partition.

**Pass threshold:**
```
T+5 IC within top quintile: >= +0.06 (t > 1.5)
T+20 IC within top quintile: >= +0.04 (t > 1.2)
Sample size within quintile: >= 30 tickers across lookback window
```

**Fail:** IC < threshold or sample < 30 → no marginal ordering value in ranker context; do not advance.

---

### D9: Bin-Residualized IC (True Ranking Signal)

**Definition:** After removing coinvest_score_z effect via bin-residualization (stratified residuals), does candidate retain IC?

**Method:**
1. Stratify universe into 5 bins by coinvest_score_z
2. Within each bin, residualize candidate (subtract bin mean, scale by bin std)
3. Remeasure T+5/T+20 IC on residualized candidate
4. Confirm IC sign/magnitude unchanged

**Pass threshold:**
```
Residualized T+5 IC: >= +0.04 (p < 0.05)
Residualized T+20 IC: >= +0.03 (p < 0.10)
Sign consistency: same direction as pre-residualization
```

**Fail:** Residualized IC < threshold or sign flips → candidate's predictive power is confounded with coinvest; do not advance.

---

## D7/D8/D9 Data Requirements

**Lookback window:** 2026-04-25 through 2026-05-13 (pre-13F-refresh; contaminated by cohort distortion; use with caution)

**Re-run window (post-13F-refresh, on 2026-05-22):** 2026-05-15 through 2026-05-21 (post-refresh; clean cohort state; preferred for final verdict)

**Forward returns:** SEC filings only; no intraday pricing; T+5 = +5 business days; T+20 = +20 business days.

---

## If D7/D8/D9 Pass: Proceed to D1–D6

Do **not** run D1–D6 unless D7/D8/D9 all pass. See `spec_072_vnext_d1_d6_template_2026_05_14.md` for full D1–D6 structure.

---

## Prohibited Actions

❌ Add features to frozen set  
❌ Remove or substitute candidates  
❌ Tune clinical_score_v2_z weights or definition  
❌ Build composite ranker (clinical + endpoint + other)  
❌ Shadow-ship candidate before 2026-05-22 verification  
❌ Use preliminary D8/D9 results as final promotion claim  
❌ Interpret D7/D8/D9 results during active cohort-distortion window as stable signal  
❌ Change selector (0.65 coinvest, 0.35 inst_delta) weights pending verification  

---

## 2026-05-22 Command Sequence

### Step 1: Verify 13F Q1 2026 refresh completed

```bash
# Check institutional_summary.json mtime + as_of_date
python3 -c "
import json
inst = json.load(open('production_data/institutional_summary.json'))
print(f'as_of_date: {inst[\"as_of_date\"]}')
print(f'Expected: >= 2026-04-30')
"
```

**Gate:** as_of_date >= 2026-04-30 (Q1 2026 cutoff). If not, defer review until refresh completes.

---

### Step 2: Verify cohort window cleared (SIGNAL_ALERT check)

```bash
# Check latest snapshot for inst_delta_z distortion symptoms
python3 -c "
import csv
from pathlib import Path
snap = Path('data/snapshots/2026-05-21/rankings.csv')  # or latest
with open(snap) as f:
    rows = list(csv.DictReader(f))
inst_deltas = [float(r['inst_delta_z']) for r in rows if r.get('inst_delta_z') and r['inst_delta_z'].strip()]
print(f'Mean |inst_delta_z|: {sum(abs(x) for x in inst_deltas)/len(inst_deltas):.3f}')
print(f'Max |inst_delta_z|: {max(abs(x) for x in inst_deltas):.3f}')
print(f'Expected: mean < 0.70 (vs locked 0.743), max < 4.0 (vs locked 4.42)')
"
```

**Gate:** If mean/max still match locked values (0.743 / 4.42), cohort window hasn't cleared; defer review.

---

### Step 3: Run D7/D8/D9 on frozen set (post-refresh clean data)

```bash
python3 scripts/research/run_spec072_vnext_verification.py \
  --start-date 2026-05-15 \
  --end-date 2026-05-21 \
  --candidate-set frozen \
  --output-dir artifacts/research/spec_072/

# Review outputs:
# - d7_orthogonality.csv (correlation, residualized IC)
# - d8_within_quintile_ic.csv (T+5/T+20 IC within coinvest top-quintile)
# - d9_residualized_ic.csv (bin-residualized IC)
# - summary.md (pass/fail verdict)
```

**Gate:** All three pass thresholds → proceed to Step 4. Any fail → close candidate; prepare backup.

---

### Step 4: Decision point

**If D7/D8/D9 all pass:**
- Proceed to D1–D6 diagnostics (see `spec_072_vnext_d1_d6_template_2026_05_14.md`)
- Expected 1–2 days of work; final review 2026-05-24 or later

**If any D7/D8/D9 fail:**
- Close PRIMARY candidate
- Run same D7/D8/D9 on BACKUP (endpoint_strength_score)
- If BACKUP fails: close Spec 072 candidate research; document blocker
- If BACKUP passes: proceed to D1–D6 on BACKUP

**If both fail:**
- Spec 072 vNext candidate research blocked; escalate to operator
- Document why frozen set failed verification gates
- Prepare alternative candidate evaluation plan (if any)

---

## Safety Constraints

- **Spec 096 doctrine:** No production ranker changes until all gates pass + Checklist v2 ready
- **Cohort regime:** Distortion window active until ~2026-05-15; interpretation of earlier results (pre-refresh) is preliminary
- **No model changes:** Zero selector/ranker/sizing edits during prep or review phase
- **Frozen set only:** D7/D8/D9 on PRIMARY/BACKUP only; no other candidates to be tested

---

## References

- **Spec 072:** `specs/changes/spec_072_screener_vnext_2026_05_01.md`
- **Spec 096:** Governance doctrine (gate/ranker separation; marginal value requirement; Checklist v2)
- **Cohort distortion:** `memory/regime_post_cohort_change_distortion_2026_04_28.md`
- **13F refresh preflight:** `artifacts/audit/13f_q1_2026_refresh_preflight_2026_05_14.md`
