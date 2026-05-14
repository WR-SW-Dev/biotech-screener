# Spec 072: vNext Ranker D1–D6 Diagnostic Template

**Status:** TEMPLATE (do not run until D7/D8/D9 all pass on 2026-05-22)

**Purpose:** Once D7/D8/D9 verification gates pass, use this template for full diagnostic (D1–D6) comparison of frozen candidate set vs current production ranker.

---

## D1: Composition Jaccard (Universe Overlap)

**Definition:** How much does vNext candidate-ranked Top-30 overlap with current production Top-30?

**Method:**
```
J = |vNext ∩ Production| / |vNext ∪ Production|
```

**Threshold:**
- `J >= 0.70`: Composition mostly stable; candidate is incremental (expected for ranking refinement)
- `0.50 <= J < 0.70`: Moderate churn; candidate ranks differently enough to matter
- `J < 0.50`: Major composition change; high risk; needs further investigation

**Expected:** J ≈ 0.60–0.75 for reasonable ranker refinement (some new names, some exits, not wholesale swap)

**Red flags:**
- J < 0.40 → candidate may be optimizing in-sample; requires generalization audit
- J > 0.90 → candidate adds no marginal value; correlated with coinvest; reconsider D7/D8/D9 results

---

## D2: Block Delta Confirmation

**Definition:** Are selector output (eligible universe) and gating logic unchanged?

**Method:** Run selector on same date range; confirm gate counts (clinical pass, liquidity pass, coinvest threshold pass).

**Gate counts:**
```
2026-05-15 snapshot:
- Pre-gate universe: 299 tickers
- Post-clinical gate: ~280 (typical)
- Post-liquidity gate: ~270 (typical)
- Post-coinvest gate: ~60 (target)
```

**Threshold:**
- Gate counts within ±5 of baseline → selector unchanged ✓
- Gate counts drift > ±10 → investigate; may indicate universe/data change

**Do NOT:**
- Change selector formula to match vNext results
- Add/remove gates to optimize vNext composition
- Adjust coinvest threshold based on this test

---

## D3: Forward-Return Comparison (T+5 / T+20)

**Definition:** Does vNext-ranked Top-30 outperform current production Top-30 on forward SEC filing returns?

**Method:** Measure equal-weight portfolio returns (T+5 and T+20 business days) on each ranking.

**Expected comparison:**
```
vNext T+5 return - Production T+5 return = margin (expected: -2pp to +3pp; 0 is OK)
vNext T+20 return - Production T+20 return = margin (expected: -1pp to +2pp; 0 is OK)
```

**Pass threshold:**
- `vNext T+5 >= Production T+5 - 1pp` (candidate doesn't underperform)
- `vNext T+20 >= Production T+20 - 0.5pp` (candidate holds up on longer horizon)
- Sample size: >= 20 snapshots in test window (2026-05-15 through earliest possible close date)

**Fail:**
- `vNext T+5 < Production T+5 - 1pp` → candidate systematically underperforms; reconsider
- `vNext T+20 < Production T+20 - 0.5pp` → long-horizon regression; investigate

**Interpretation note:** This is **not** an IC measurement (which requires universe-wide signal power). It is a **portfolio comparison** (ranking quality within gated universe). Pass threshold is "no worse than current" not "demonstrable improvement."

---

## D4: Stability (Rank Churn & Volatility)

**Definition:** How much does vNext ranking change day-to-day?

**Method:**
```
1. Compute daily Spearman rank correlation between vNext rankings on consecutive days
2. Measure std(rank change) for each ticker across 5-day rolling window
```

**Threshold:**
- Daily rank correlation: >= 0.85 (stable rankings)
- Std(rank change): <= 3 positions (ticker not jumping wildly)
- Volatility comparable to or lower than production ranker

**Red flags:**
- Daily correlation < 0.75 → candidate is noisy; may be overfitting
- Std > 5 positions → candidate is twitchy; risk of whipsaw in rebalance

---

## D5: Trap Pass-Through Audit

**Definition:** Does vNext ranking respect trap filter logic (liquidity, dilution, stale-thesis)?

**Method:** Identify known trap-flagged names (as of 2026-05-14); confirm none appear in vNext Top-30 unless trap status has genuinely resolved.

**Expected:** vNext ranking does not promote trap-flagged names without independent evidence of trap resolution.

**Mechanism check:**
- Trap logic happens BEFORE ranker (gates exclude trap names first)
- vNext candidate should rank only within post-trap-gate universe
- If vNext Top-30 includes trap names: check if trap flags cleared or if vNext bypassed gate logic

---

## D6: Self-Dominance Check (Tautology Test)

**Definition:** Is vNext candidate just a reweighting of existing selection signals, or does it add independent information?

**Method:**
1. Run linear regression: `vNext_ranking = β₀ + β₁ × coinvest_score_z + β₂ × financial_score_z + ε`
2. Compute R² (how much of vNext variance is explained by existing signals)

**Threshold:**
- `R² < 0.75` → vNext is reasonably independent; adds new information ✓
- `R² >= 0.75` → vNext is mostly a linear combo of existing signals; low marginal value ⚠
- `R² > 0.90` → vNext is essentially redundant; do not promote

**Interpretation:** If D8 (within-quintile IC) passed but D6 fails, candidate may have IC only within selector output, not as independent signal. Reconsider whether candidate is truly suitable for ranker role (vs selector enhancement).

---

## D1–D6 Summary Verdict

**All pass (Composition J, Block delta, Returns, Stability, Trap logic, Self-dominance):**
→ Candidate is ready for **Checklist v2 battery** (FM, bootstrap, FDR, LOSO, year stab, domain audit)

**Any fail:**
→ Candidate is not promotion-ready; document blocker:
  - If Composition J < 0.5: in-sample overfitting risk
  - If Returns margin < -1pp: underperformance risk
  - If Stability poor: implementation risk (whipsaw)
  - If Trap logic violated: gating logic needs review
  - If Self-dominance > 0.75: low marginal value (maybe improve selector instead)

---

## Required Data & Outputs

**Input:**
- vNext ranking (from D7/D8/D9 approved candidate)
- Production ranking (baseline)
- Daily snapshots 2026-05-15 through [end of test window]
- Forward return data (SEC filing windows)

**Outputs:**
1. D1_composition_jaccard.csv (ticker comparison, union/intersection counts)
2. D2_block_delta.csv (gate counts, consistency check)
3. D3_forward_return_comparison.csv (T+5/T+20 portfolio returns both rankings)
4. D4_stability_metrics.csv (daily rank correlation, std rank change)
5. D5_trap_audit.csv (trap names in vNext Top-30, flag status)
6. D6_self_dominance.csv (linear regression R², coefficient interpretation)
7. d1_d6_summary.md (verdict + narrative)

---

## Constraints & Guardrails

❌ Do NOT modify selector formula to match vNext composition  
❌ Do NOT add/remove gates to optimize vNext results  
❌ Do NOT interpret positive returns as signal validation (requires universe-wide IC + Checklist v2)  
❌ Do NOT shadow-ship vNext ranking until D1–D6 all pass + Checklist v2 ready  
❌ Do NOT change any production weights based on this comparison  

---

## Only Run If D7/D8/D9 All Pass

**Gate:** All three diagnostic gates (orthogonality, within-quintile IC, residualized IC) must pass thresholds on post-13F-refresh clean data before D1–D6 is worth running.

**Expected timeline:** 2026-05-22 (D7/D8/D9) → 2026-05-24/25 (D1–D6 if D7/D8/D9 pass)

---

## References

- **Spec 072:** `specs/changes/spec_072_screener_vnext_2026_05_01.md`
- **D7/D8/D9 prep:** `artifacts/audit/spec_072_vnext_ranker_review_prep_2026_05_14.md`
- **Spec 096 doctrine:** Gate/ranker separation; marginal value requirement
