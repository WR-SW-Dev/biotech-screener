# Spec 075 — inst_delta_z Restoration Checkpoint (2026-05-06)

**Status:** Checkpoint / audit gate. No code changes.
**Scope:** Determines if/when `inst_delta_z` is eligible for restoration to the selector.
**Guardrails:** No automatic restoration. No production weight changes. No retrain.
            Insufficient evidence → EXTEND_SHADOW.

---

## 1. Current state

| Dimension | Value | Source |
|---|---|---|
| **Selector weight** | **0.00** (was 0.35) | `run_screen.py` lines 150–151, commit `26dd60744` |
| **Selector zeroing date** | 2026-05-04 | Governance log `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` |
| **Ranker (production)** | **Absent** — 2-feature model uses `coinvest_score_z` + `financial_score` only | `production_data/ranker_v2_model.json` |
| **Ranker (5-feat rollback)** | weight = **+0.00221** (effectively zero) | `production_data/ranker_v2_model_5feat_rollback.json` |
| **Computed in output?** | Yes — computed as diagnostic field in `rankings.csv` | `run_screen.py` lines 5038–5069 |
| **Coverage guardrail** | Zeroed to 0.0 if < 10% of tickers have non-zero delta | `run_screen.py` lines 5077–5097 |
| **Active ruleset** | v1.14.0, id `622edb77` | `production_data/decision_rulesets/v1.14.0_coinvest_only_selector.json` |
| **Forward shadow running?** | Yes — T0=2026-04-28, daily 19:30 ET | `inst_delta_forward_shadow_T0_2026_04_28.md` |

**What "zeroed" means precisely:** `inst_delta_z` is still computed from institutional data and written to `rankings.csv` as a diagnostic column. It receives weight=0.00 in the selector signal composition (`A4_SELECTOR_CONFIG`), so it has no effect on `selector_score`, `actionable_rank`, or top-30 membership. It does not appear in the production 2-feature ranker at all.

**What production paths would consume `inst_delta_z` if restored:**

1. **Selector** (`run_screen.py` lines 132–152): Edit `SignalSpec("inst_delta_z", 0.00)` → prior weight 0.35. Requires updating `coinvest_score_z` from 1.00 back to 0.65. Ruleset ID advances.
2. **Shadow tracker**: Re-enable B6 bundle IC probe in `shadow_review_gate.py`.
3. **Rank-change monitor**: Top-30 diffs would widen; calibration threshold may need re-checking.
4. **Ranker** (if desired, separately): Add `inst_delta_z` back to ranker feature set — requires full retrain + Checklist v2. This is NOT part of the restoration path for the selector alone.

---

## 2. Root cause for zeroing

**Primary — negative IC ALERT (2026-05-04):**

| Metric | Value | Source |
|---|---|---|
| Rolling Spearman IC (36 dates, 2026-02-19→2026-04-02) | **−0.097** | `ic_health_monitor` |
| IC hit-rate | **11.1%** (only 4/36 dates positive) | `ic_health_monitor` |
| Calibration event-IC (75 postmortems) | **−0.244** | `calibration_evidence` |
| IC inflection point | ~2026-02-28 | Governance review |
| Comparator (coinvest_score_z, same window) | mean_ic = **+0.097**, hit-rate = **89.7%** | Comparator probe |
| Cross-correlation ρ(inst_delta, coinvest) | **−0.33** (anti-correlated) | Governance review |

The degradation is isolated to `inst_delta_z`. Coinvest is healthy over the same window.

**Secondary — cohort contamination (2026-04-25):**

Four managers were added to the registry on 2026-04-25. This caused `inst_delta_z` to show byte-identical values across the 2026-04-25/27/28 snapshots (the delta computation required two 13F-cycle snapshots; the new managers had no prior delta to compare). The SIGNAL_ALERT was validly persistent through ~2026-05-15. This is a structural data artifact, not a permanent signal failure, but it compounded the negative-IC finding.

**13F context:**

The prior_date in `institutional_summary_delta.json` is still at 2025-12-31 (Q4 2025). The Q1 2026 13F refresh (~2026-05-15) will advance prior_date to 2026-03-31, which changes the delta baseline for all tickers. This is a significant regime shift for `inst_delta_z` — the post-refresh signal may behave differently from the pre-refresh period.

---

## 3. Review checkpoint

**Primary review date: 2026-06-02** (first Monday after 2026-05-26 h20d verdict)

This date is chosen to clear three gates in sequence:
1. **13F refresh lands** (~2026-05-15) — prior_date advances; quarantine window closes
2. **Quarantine clears** (~2026-05-15 + 5–10 trading days = ~2026-05-27) — Top-30 Jaccard stabilizes post-refresh
3. **Forward shadow h20d verdict** (2026-05-26) — `inst_delta_forward_shadow_T0_2026_04_28.md`

**Final verdict date: 2026-07-21** (per `inst_delta_forward_shadow_T0_2026_04_28.md`)

Do not treat the 2026-06-02 checkpoint as a promotion decision. It is an evidence review. The final verdict at 2026-07-21 determines whether Checklist v2 is warranted.

---

## 4. Commands to run at review (2026-06-02)

```bash
# Step 1: Verify 13F refresh landed and quarantine cleared
python -m tools.check_13f_cohort_quarantine \
    --pre-date 2026-05-14 \
    --post-date 2026-05-19 \
    --output artifacts/13f_diff_2026_05_19.md

# Step 2: Read ic_health_monitor for inst_delta_z (rolling, post-refresh dates only)
python tools/run_ic_health_monitor.py --signal inst_delta_z --from-date 2026-05-16

# Step 3: Read calibration_evidence for current event-IC
python tools/run_crt.py --dry-run 2>&1 | grep event_ic
# OR: check artifacts/calibration_evidence/calibration_summary.json → event_ic field

# Step 4: Read forward shadow artifacts
cat data/snapshots/*/shadow_summary.json | grep -A5 inst_delta

# Step 5: Top-30 Jaccard stability check (post-refresh)
python tools/rank_change_monitor.py --as-of-date 2026-06-01 | grep jaccard

# Step 6: Cross-signal forward shadow
# (auto-filed daily by cron at 19:40 ET; read latest artifact)
ls artifacts/cross_signal_shadow/ | tail -5
```

---

## 5. Required metrics and pass/fail thresholds

All thresholds apply to **post-13F-refresh dates only** (i.e., snapshots on or after the date when `institutional_summary_delta.json` shows `prior_date = 2026-03-31`).

### IC recovery (required — both must pass)

| Metric | RESTORE_CANDIDATE threshold | Source |
|---|---|---|
| `inst_delta_z` rolling mean Spearman IC | **≥ +0.02** sustained across **≥ 10 dates** | `ic_health_monitor` |
| `calibration_evidence` event-IC | **> 0.0** (any positive) | `calibration_summary.json` → `event_ic` |

If either metric fails: **KEEP_ZEROED** or **EXTEND_SHADOW** (see decision tree).

### Cohort quarantine clearance (required before any IC evidence counts)

| Metric | Threshold | Source |
|---|---|---|
| Top-30 Jaccard (pre vs post refresh) | **≥ 0.70** | `check_13f_cohort_quarantine.py` |
| Manager registry Δ | **≤ 5** new managers | `check_13f_cohort_quarantine.py` |
| Coverage drop | **< 10pp** | `check_13f_cohort_quarantine.py` |
| `inst_delta_z` sd in post-refresh snapshot | **> 0.10** | G1 guardrail in quarantine tool |
| `prior_date` in delta JSON | Advanced from 2025-12-31 to 2026-03-31 | G2 guardrail |

If any quarantine metric fails: abort review. No IC evidence is valid while quarantine is active.

### Forward shadow (informational — does not gate alone, but informs decision)

| Metric | What to check | Threshold |
|---|---|---|
| h20d median return: inst_delta_z selected vs excluded | See `inst_delta_forward_shadow_T0_2026_04_28.md` | Positive differential |
| Top-30 Jaccard stability post-refresh | Rolling 5-day Jaccard ≥ 0.85 | Stable membership |
| Rank-delta distribution | `rank_change_monitor.py` output | No systematic coinvest-negating shuffle |
| Cap-bucket distribution: top-30 | Pre/post inst_delta restoration comparison | No meaningful shift |
| Catalyst family: top-30 | Phase 2/3 representation unchanged | < 10pp shift |
| Stage-bucket: top-30 | Pre-commercial representation unchanged | < 10pp shift |

---

## 6. Decision tree

```
START: Review on 2026-06-02
│
├─ [Quarantine NOT cleared] → ABORT — run again 2026-06-16
│
├─ Quarantine cleared?
│   │
│   ├─ mean_ic < +0.02 (< 10 dates post-refresh) → KEEP_ZEROED
│   │   (degradation persists after fresh 13F baseline)
│   │
│   ├─ mean_ic ≥ +0.02 AND event-IC ≤ 0 → EXTEND_SHADOW
│   │   (IC recovering but calibration_evidence not positive yet;
│   │    schedule 2026-07-01 follow-up)
│   │
│   └─ mean_ic ≥ +0.02 (10+ dates) AND event-IC > 0 → RESTORE_CANDIDATE
│       (both recovery conditions met per governance log)
│       → File disposition under INST_DELTA_Z_GOVERNANCE_LOG_TEMPLATE
│       → Requires explicit user approval before any weight edit
│       → Requires ruleset version bump (v1.15.0)
│       → Blast-radius diff required before commit
```

**Current decision (2026-05-06): EXTEND_SHADOW**

Rationale: The 13F refresh has not yet landed. IC evidence from pre-refresh dates is contaminated by cohort-change distortion. Forward shadow h20d verdict is still 20 days out. Insufficient evidence for any stronger verdict.

---

## 7. Files and functions involved in restoration

| File | Change required | Notes |
|---|---|---|
| `run_screen.py` lines 150–151 | `inst_delta_z` weight 0.00 → 0.35; `coinvest_score_z` 1.00 → 0.65 | Only edit after RESTORE_CANDIDATE + user approval |
| `production_data/decision_rulesets/` | New `v1.15.0_b6_selector.json` (copy of v1.14.0 + weight edits) | Ruleset ID derived from file hash |
| `run_phase2_snapshot_delta.py` line 31 | `PHASE2_PINNED_RULESET_ID` → new ruleset ID | |
| `CLAUDE.md` Active Ruleset | v1.14.0 → v1.15.0, id update | |
| `INST_DELTA_Z_GOVERNANCE_LOG_*` | File new disposition under template | Use `INST_DELTA_Z_GOVERNANCE_LOG_TEMPLATE_2026_05_04.md` |

**Do NOT touch:** `ranker_v2_model.json`, `module_5_scoring_v3.py`, `selector_engine.py`, `event_ev/`, CRT schema, or any postmortem files.

---

## 8. Rollback path (if restoration is later approved and then reverts)

```bash
# Revert selector weight to coinvest-only (v1.14.0 behavior)
# Edit run_screen.py:
#   SignalSpec("coinvest_score_z", 1.00)
#   SignalSpec("inst_delta_z", 0.00)
# Update ruleset ID back to 622edb77 in:
#   run_phase2_snapshot_delta.py
#   CLAUDE.md
#   production_data/decision_rulesets/ (copy v1.14.0 as current)

# Verify rollback:
python run_screen.py --as-of-date <today> --dry-run | grep selector_score
python tools/verify_snapshot_integrity.py --date <today>
```

Rollback is a one-snapshot operation. Rankings from prior snapshots are unaffected (immutable).

---

## 9. What this spec does NOT do

- Does not restore `inst_delta_z` to the selector
- Does not change any ranker weights
- Does not retrain the model
- Does not change the forward shadow parameters or cron schedule
- Does not modify the 13F manager registry
- Does not backfill any signal or snapshot

The gate defined here is a decision-point artifact only. Restoration requires a separate operator action after reviewing this checkpoint.
