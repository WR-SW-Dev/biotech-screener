# Spec 091 — `score_rank_pct` Degradation Governance Memo (2026-05-07)

**Status:** SPEC / MEMO ONLY. No code changes. No weight changes. No selector / ranker / sizing changes. No signal suppression. No retrain. Defines the evidence bundle and decision tree that any future weight-affecting action on `score_rank_pct` (or its inputs) must produce. This memo is the controlling governance record while the WARN streak is open.

**Origin:** `score_rank_pct` IC health WARN streak observed in `artifacts/ic_dashboard/history.jsonl`; Day-3 escalation recorded in `SCORE_RANK_PCT_STREAK_MONITOR_2026_05_07.md`; Day-4 confirmed by 2026-05-07 dashboard. `artifacts/audit/held_spec_ledger_2026_05_07.md` §1 lists `score_rank_pct SPEC_REQUIRED` as an actionable blocker.

**Priority:** Governance. No production runtime impact while in OBSERVE state. Not a P0 fix, not an alpha-research promotion. Spec writeup is the next gate before *any* downstream action.

**Classification:** Signal-health monitoring spec. The signal is INFORMATIONAL inside `ic_health_monitor` (`agents/ic_health_monitor/SOUL.md:46`) — it is not a selector or ranker feature. Degradation here does not directly degrade the live model, but it is a leading indicator that the composite score's rank-percentile is decoupling from forward returns.

---

## Hard constraints

- Do NOT change ranker weights, selector weights, or sizing logic.
- Do NOT change `composite_score` construction in `module_5_composite_v3.py` or upstream module weights.
- Do NOT modify `common/score_to_er.py::attach_rank_and_z` (the canonical writer of `score_rank_pct`).
- Do NOT suppress, demote, or rename the signal in `ic_health_monitor`.
- Do NOT escalate the WARN to ALERT classification by hand — the threshold change is itself a Checklist v2-class governance event.
- Do NOT use this WARN as evidence to revisit any prior closed lane (clinical, EES, expression overlay, etc.). The WARN is about the composite score's rank-return coupling, not about any upstream feature.
- Do NOT retrain ranker v2 on the basis of this WARN.
- Do NOT bundle any code change with this memo. The memo's purpose is to define what evidence is required, not to act on it.

---

## 1. Problem statement

`score_rank_pct` is the continuity-corrected percentile of `composite_score` (best rank → highest percentile, see `common/score_to_er.py:163-270`). It is monitored by `ic_health_monitor` as an informational health signal: rolling 60-date / 20-day-horizon Spearman IC against forward returns, with hit-rate.

**WARN threshold (per `SCORE_RANK_PCT_STREAK_MONITOR_2026_05_07.md`):**

```
mean_ic ≤ 0.0  AND  hit_rate < 50%
```

Streak progression observed in `artifacts/ic_dashboard/history.jsonl`:

| Day | Date | mean_ic (60d) | hit_rate | latest_ic | Health |
|-----|------|---------------|----------|-----------|--------|
| ... | 2026-04-27 | +0.0191 | — | — | WEAK (transition) |
| ... | 2026-04-28 | +0.0098 | — | — | WEAK |
| ... | 2026-04-29 | +0.0124 | — | — | WEAK |
| ... | 2026-04-30 | +0.0073 | — | — | WEAK |
| ... | 2026-05-01 | +0.0011 | 39% | -0.0316 | WEAK |
| 1 | 2026-05-04 | -0.0041 | <50% | — | WARN |
| 2 | 2026-05-05 | -0.0098 | 34.2% | — | WARN |
| 3 | 2026-05-06 | -0.0119 | 28.95% | — | WARN — escalation |
| 4 | 2026-05-07 | **-0.0157** | **27%** | -0.0124 | WARN |

The trajectory is monotone: HEALTHY (Mar–Apr 24) → WEAK (Apr 27–May 1) → WARN (May 4 onward). The 2026-05-07 dashboard window covers 2026-02-24 → 2026-05-06 (37 dates). Mid-February through early-March IC bars in the dashboard show consistent negatives (`SCORE_RANK_PCT_STREAK_MONITOR_2026_05_07.md`: "structural degradation pattern, not a recent perturbation").

**The question this memo gates:** what evidence must be produced before any action — weight change, signal demotion, alert-threshold change, or composite redefinition — is permitted?

---

## 2. What this memo does and does not assert

**Does assert:**
- The WARN streak is real and structural, not a 1–2 day perturbation.
- The signal is currently informational, not a selector / ranker feature, so the WARN does not auto-imply a runtime fix.
- The `inst_delta_z` ALERT (concurrent, mean_ic = -0.1022 on 2026-05-07) is governed under separate memory (`regime_post_cohort_change_distortion_2026_04_28.md`); cohort-window distortion through ~2026-05-15 may partially explain composite-score-IC drift but cannot be the only factor (the score_rank_pct decline began before the inst_delta inflation window).
- A signal-degradation finding alone is not authority to change scoring weights. Per `policy_demotion_path_2026_05_06.md`, demotion of an active signal requires a 5-element governed path. Per `policy_alpha_freeze_2026_04_04.md`, promotion / weight-increase requires Checklist v2.

**Does NOT assert:**
- That `composite_score` is broken.
- That any upstream module (Module 1-5) is the cause.
- That the inst_delta cohort-change distortion is or is not the dominant driver.
- That the WARN will resolve automatically post-13F refresh (~2026-05-15).
- That `score_rank_pct` should be removed from the IC dashboard.

These are the questions the future evidence bundle (§4) must answer.

---

## 3. Why this matters to the investment thesis

`score_rank_pct` is the rank-percentile of the composite score. If its IC is structurally negative, that means: at the top of the composite-score distribution, forward returns are lower than at the middle / bottom of the distribution, on a 20-day horizon, over the rolling window. That is the inverse of what the composite is designed to predict.

Two interpretations are possible and not mutually exclusive:

1. **Cohort-window distortion (transient):** The post-13F manager-cohort change (2026-04-25 added 4 managers; see `regime_post_cohort_change_distortion_2026_04_28.md`) inflated `inst_delta_z` byte-identically across 04-25 / 27 / 28 and continues to inflate it. `inst_delta_z` is a selector pruner. If composite ranking depends on a feature that is artificially inflated for ~3 weeks, the rank-percentile's coupling to true forward returns will weaken.

2. **Structural drift (persistent):** The composite weights, last governed in v1.13.0 (2a3e79eb) and operational under v1.14.0 (8887576e — coinvest-only selector with `inst_delta_z` zeroed), may not be the optimal coupling for the current return regime. Note: `inst_delta_z` was demoted out of the selector at v1.14.0 per `policy_demotion_path_2026_05_06.md`, so its inflation should NOT be propagating through the selector — but the composite score (Module 5) still uses it as an input, and `score_rank_pct` is computed against `composite_score`, not selector output.

Resolving (1) vs (2) is the central evidence question. Acting before the question is resolved risks (a) over-reacting to a transient cohort-window distortion or (b) under-reacting to a real degradation that compounds.

---

## 4. Evidence bundle required for any future action

Any future change touching `composite_score`, `score_rank_pct`, or any of Module 5's inputs **on the basis of this WARN streak** must produce the following bundle. Each item is an independent gate.

### 4a. CRT — Cohort Regime Test (cohort-window distortion isolation)

**Question:** Is the IC degradation explained by the post-13F cohort-window inflation of `inst_delta_z`?

**Required:**
- Recompute `score_rank_pct` IC on the rolling window with `inst_delta_z` held at its pre-cohort-add value (2026-04-24 snapshot value) for all dates ≥ 2026-04-25.
- Recompute `score_rank_pct` IC after excluding all top-30 names whose `inst_delta_z` is in the cohort-add inflation set.
- Recompute on dates strictly after the post-13F refresh closes (~2026-05-15) and on a ≥ 20-trading-day forward window post-close.
- Document mean IC, hit rate, and the gap between adjusted and unadjusted readings.

**Pass/fail:** If the adjusted IC is ≥ 0 and the unadjusted IC is < 0 by ≥ 0.01, the WARN is classified COHORT-WINDOW-DRIVEN (transient) and no weight action is taken. If the adjusted IC is also < 0, the WARN is classified STRUCTURAL and the IC / PIT / Checklist v2 gates below must run.

**Hard requirement:** Cannot run with confidence until the post-13F refresh window closes (~2026-05-15) and a ≥ 20-trading-day forward window has accumulated. **Earliest CRT date: ~2026-06-15.**

### 4b. IC — Independent IC validation (post-PIT, multi-horizon)

**Question:** Is the IC degradation present across horizons and across PIT-strict cohort definitions?

**Required:**
- Re-run IC on `score_rank_pct` over horizons: 5d, 10d, 20d, 60d.
- Re-run with PIT-strict cohort: `tier_any` ≥ Tier 2 only, then expand to full universe.
- Bootstrap 95% CI (≥ 1000 draws, block bootstrap with block-length matched to forward horizon).
- NW-corrected t-statistic (≥ 5 lags for 20d horizon).
- Year-stability check across 2025 vs 2026 segments (where data permits).

**Pass/fail:** WARN is structurally confirmed if mean_ic < 0 with NW-t < -1.65 on at least 2 of 4 horizons AND CI excludes 0 on at least 1 horizon.

**Hard requirement:** Post-PIT only (snapshot dates ≥ 2026-04-13). No pre-PIT-correction backtest evidence. Earliest sufficient sample: post-2026-05-15 if cohort window required, otherwise immediately runnable on post-PIT data.

### 4c. PIT — PIT integrity audit on composite inputs

**Question:** Is the IC degradation a side-effect of a known PIT contamination, schema drift, or input-data anomaly?

**Required:**
- Walk Module 5 inputs (Modules 1–4 outputs feeding `module_5_composite_v3.py`) and confirm each is on its current PIT contract (no pre-PIT data leaking through any of the 5 module outputs).
- Check `production_data/` for any field-rename / schema-version mismatch in the rolling window (Feb 24 → present).
- Cross-reference with `incomplete_production_run_fallback_2026_05_01.md` — confirm no missing-input fallbacks (e.g., `inst_delta_z = 0` due to missing `institutional_summary_delta.json`) within the window.
- Check `production_data/decision_rulesets/` for any active-ruleset rotation inside the window. If `8887576e` (v1.14.0) was promoted 2026-05-04, attribute the IC slope before vs after that date and verify the slope was already negative pre-promotion.

**Pass/fail:** If any PIT or input integrity issue is found, the WARN is classified DATA-CONTAMINATED and remediation is data-pipeline scope, not scoring scope. CRT / IC / Checklist v2 are paused pending data fix. If clean, proceed to Checklist v2.

### 4d. Checklist v2 — Full alpha-freeze battery

**Question:** Does any proposed remedy (weight change, input change, composite redefinition) clear the same evidence bar that any new alpha promotion would have to clear?

**Required (per `policy_alpha_freeze_2026_04_04.md`):**
- G1: Signal card. Selector Δ NW-t ≥ 2.0 AND ranker IC NW-t ≥ 2.0.
- G2: Fama-MacBeth incremental NW-t ≥ 1.96.
- G3: Block bootstrap 95% CI excludes 0.
- G4: BH FDR q-value < 0.10 (family-wise correction across any candidate variants).
- G5: LOSO worst-slice IC > 0 across all 6 dimensions.
- Year-stability: IC sign-stable across both available calendar-year segments.

**Pass/fail:** Pass on all 5 gates → eligible for promotion of the proposed remedy. Fail on any gate → remedy is rejected; WARN remains open under continued monitoring. Marginal pass (G1 = 1.65–1.96) → PROVISIONAL only, requires re-test in the next monitoring cycle.

**Hard requirement:** ≥ 30 resolved post-PIT outcomes required for FM and LOSO stability. Today: ~7. **Earliest Checklist v2 readiness: ~2026-06-15.**

---

## 5. Decision tree (no action permitted outside this tree)

| Branch | Trigger | Permitted action |
|--------|---------|------------------|
| **A. Streak breaks** | Two consecutive HEALTHY readings (mean_ic > 0 AND hit_rate ≥ 50%) | Close this spec. Document in `SCORE_RANK_PCT_STREAK_MONITOR_2026_05_07.md` recovery section. No weight action. No retrain. |
| **B. Streak persists, CRT classifies COHORT-WINDOW-DRIVEN** | CRT (§4a) shows adjusted IC ≥ 0 | Continue monitoring through post-13F window close + 20-trading-day forward. No weight action. Re-evaluate in next monitoring cycle. |
| **C. Streak persists, CRT classifies STRUCTURAL** | CRT (§4a) shows adjusted IC < 0 | Run IC (§4b) + PIT (§4c). Document findings. Do NOT proceed to remedy without §5 D or E. |
| **D. PIT classifies DATA-CONTAMINATED** | PIT (§4c) finds an integrity issue | Open a data-pipeline ticket. WARN remains open under monitoring. No scoring change. |
| **E. STRUCTURAL + clean PIT, candidate remedy proposed** | C path completes cleanly | Run Checklist v2 (§4d) on the proposed remedy. Only a pass authorizes change, and only under separate operator approval and a written promotion / demotion receipt. |
| **F. ALERT escalation needed** | mean_ic ≤ -0.05 AND hit_rate < 25% on any reading | Reclassify health from WARN to ALERT in `ic_health_monitor`. This reclassification is itself a Checklist v2-class change to the threshold table and requires a separate spec, not a code edit. |

**No path in this tree authorizes:**
- Suppression of `score_rank_pct` from `ic_health_monitor`.
- Renaming, removal, or redefinition of `score_rank_pct` without a new spec.
- Action on the basis of a single day's reading.
- Weight changes to selector / ranker / Module 5 / composite_score derived from this WARN alone.

---

## 6. Cadence and timing

| Event | Date |
|-------|------|
| Recurring streak monitor (`4a96ad05405c`) | 22:00 ET Mon–Fri, until streak breaks |
| Post-13F cohort window close | ~2026-05-15 |
| First defensible CRT run | ~2026-06-15 (post-window + 20 trading days) |
| First defensible Checklist v2 (if needed) | ~2026-06-20+ |
| Memo review | After streak breaks OR after 4d batch completes, whichever first |

If the streak breaks before 2026-05-15, branch A applies and this memo closes without any §4 work. If the streak persists past 2026-05-15, the §4 evidence bundle becomes the next operator action — but only after the post-13F window has actually closed and a forward-return window has accumulated.

---

## 7. Out of scope

- Any code change. This memo creates no diffs.
- Suppression or renaming of `score_rank_pct` or any IC dashboard signal.
- Reweighting Module 5 inputs.
- Changing `inst_delta_z` weights, demotion, re-promotion, or recovery monitor logic. (Governed under separate memory and `policy_demotion_path_2026_05_06.md`.)
- Reactivating any closed alpha lane (clinical features, EES, expression as alpha, options as alpha).
- Modifying the WARN / WEAK / HEALTHY threshold table without a separate spec.
- Promoting any candidate remedy without a passing Checklist v2 bundle.
- Any retroactive change to the IC dashboard window or recomputation that would alter the historical record. The streak history is evidence and must remain immutable.

---

## 8. Acceptance for closure

This memo closes when **one** of the following is true and documented:

1. **Streak breaks (branch A).** Two consecutive HEALTHY readings observed and recorded in `history.jsonl` and `SCORE_RANK_PCT_STREAK_MONITOR_2026_05_07.md`. No further evidence required.
2. **CRT (§4a) classifies COHORT-WINDOW-DRIVEN, then streak breaks within one monitoring cycle of post-13F window close.** Branch B → A.
3. **§4 bundle completes (CRT + IC + PIT + Checklist v2)** with a written verdict memo at `artifacts/audit/score_rank_pct_evidence_bundle_<YYYY-MM-DD>.md`, AND any resulting remedy is either rejected (verdict documented) or accepted under separate operator approval with a promotion / demotion receipt.

The memo does NOT close on:
- Time alone.
- A single HEALTHY reading.
- Operator preference without §4 evidence.
- An assertion that "the cohort window must be the cause" without the §4a CRT actually being run.

---

## 9. Dependencies

| Dependency | Status |
|---|---|
| `regime_post_cohort_change_distortion_2026_04_28.md` (cohort window memory) | Active; window expected to close ~2026-05-15 |
| `policy_demotion_path_2026_05_06.md` | Controls any signal demotion path |
| `policy_alpha_freeze_2026_04_04.md` | Controls Checklist v2 bar |
| `incomplete_production_run_fallback_2026_05_01.md` | Required cross-check in §4c |
| `13f_cohort_quarantine_prep_2026_05_01.md` | Pre/post diff harness for §4a CRT |
| Post-13F refresh (Q1 2026) | ~2026-05-15 |
| n(resolved post-PIT outcomes) ≥ 30 | ~2026-06-15 |
| Recurring streak monitor `4a96ad05405c` | Live, 22:00 ET Mon–Fri |
| Streak-monitor evidence file `SCORE_RANK_PCT_STREAK_MONITOR_2026_05_07.md` | Live; updated as streak progresses |

---

_Spec only. No implementation. Evidence-collection-and-decision-tree governance memo. Authored 2026-05-07 in response to the Day-4 WARN streak (mean_ic = -0.0157, hit_rate = 27%, latest_ic = -0.0124 on 2026-04-08)._
