# Spec 075 — inst_delta_z Restoration Checkpoint (2026-05-05)

**Status:** Governance ticket. No code changes. Defines the decision gate and binary output for restoring or extending the inst_delta_z zero-weight.

**Hold-off scope:** This ticket does NOT restore inst_delta_z automatically. It defines when and how a human reviews the evidence and makes a binary decision. No weight changes, no selector changes until that decision is made.

---

## 1. Current state

`inst_delta_z` weight was zeroed in the selector on 2026-05-04 (v1.14.0):

```python
# run_screen.py lines ~150-151
SignalSpec("coinvest_score_z", 1.00),   # redistributed from 0.65
SignalSpec("inst_delta_z", 0.00),        # was 0.35; zeroed 2026-05-04
```

**Why it was zeroed:** The 2026-04-25 13F cohort rebuild added 4 new managers, contaminating `inst_delta_z`. Per the attribution audit (`artifacts/audit/inst_delta_attribution_2026-04-28.md`), 43% of the top-30 was plausibly artifact-driven. Six names were identified as high-confidence artifacts: NRIX, COGT, ZYME, MIRM, ORKA, ABVX. The signal is expected to self-heal after the Q1 2026 13F refresh (~2026-05-15).

**Forward shadow already running:** `tools/inst_delta_forward_compare.py` runs daily at ~19:30 ET. It compares current (coinvest-only) vs. counterfactual (coinvest + inst_delta) portfolios using T0 prices frozen in `artifacts/audit/inst_delta_forward_shadow/T0_*_lock.json`. Checkpoints written to `artifacts/audit/inst_delta_forward_shadow/checkpoint_{TODAY}.json`. Scheduled verdict milestones: **h20d = 2026-05-26**, final = 2026-07-21.

**Coverage guard:** A 50% floor exists at `run_screen.py:5085-5097` — if fewer than 50% of dev cohort have non-zero `inst_delta_z`, all values are zeroed automatically (fail-closed). This guard remains active regardless of this ticket.

---

## 2. Checkpoint gate — 2026-05-22

**Trigger date:** 2026-05-22 (post-13F refresh, post-cohort-window close, aligned with Phase A verdict review).

**Purpose:** Binary decision — restore `inst_delta_z` to 0.35 selector weight, or extend zero-weight through h20d verdict (2026-05-26) and then re-evaluate.

---

## 3. Inputs required at checkpoint

All three inputs must be available before the decision can be made. If any is unavailable, the default is **extend zero-weight** (fail-closed).

### Input A — 13F quarantine cleared

Run `tools/check_13f_cohort_quarantine.py` and confirm:

1. Q1 2026 13F refresh has landed (expected ~2026-05-15).
2. Top-30 Jaccard similarity pre/post refresh ≥ 0.70 (quarantine trigger threshold per `13f_cohort_quarantine_prep_2026_05_01.md`).
3. The six high-confidence artifact names (NRIX, COGT, ZYME, MIRM, ORKA, ABVX) show materially changed `inst_delta_z` values post-refresh (confirms contamination was cohort-driven, not structural).

If Jaccard < 0.70 or the artifact names are unchanged: **quarantine NOT cleared → extend zero-weight**.

### Input B — Forward shadow h20d verdict (available 2026-05-26, use latest checkpoint if 2026-05-22 review)

Read the most recent checkpoint from `artifacts/audit/inst_delta_forward_shadow/`. At minimum, 15d of post-T0 data should be available by 2026-05-22.

Evaluate:
- **Counterfactual (coinvest + inst_delta) median return** vs. **current (coinvest-only) median return** over 10d and 15d horizons.
- Sign consistency: does the counterfactual lead at both horizons, or does it alternate?
- Per `interp_framework_forward_shadows_2026_04_28.md`: HL Jaccard > 0.70 = coherent; < 0.40 = weak. Rolling 3d/5d medians take precedence over point-in-time.

Neutral or negative counterfactual differential: **shadow inconclusive or negative → extend zero-weight**.

### Input C — Inst_delta_z data coverage check

At the time of checkpoint review, run:
```python
# Quick coverage check
import pandas as pd
snap = pd.read_csv("data/snapshots/2026-05-22/rankings.csv")
coverage = (snap["inst_delta_z"] != 0).mean()
print(f"inst_delta_z coverage: {coverage:.1%}")
```

Coverage must be ≥ 0.70 (above the production 0.50 guard and providing margin) before restoration is considered.

---

## 4. Decision matrix

| Input A (quarantine) | Input B (shadow) | Input C (coverage) | Decision |
|---|---|---|---|
| Cleared | Positive | ≥ 0.70 | **RESTORE** to 0.35 |
| Cleared | Neutral/negative | ≥ 0.70 | **EXTEND** to h20d verdict |
| Not cleared | Any | Any | **EXTEND** to h20d verdict |
| Any | Any | < 0.70 | **EXTEND** (coverage guard fires anyway) |

**RESTORE** means: revert `run_screen.py` to `SignalSpec("coinvest_score_z", 0.65)` and `SignalSpec("inst_delta_z", 0.35)`. This is a one-line change with no other selector modifications.

**EXTEND** means: leave weights unchanged and schedule the next review at the h20d verdict date (2026-05-26).

---

## 5. Restoration procedure (if RESTORE decision)

1. Confirm all three inputs pass (document in the checkpoint review note).
2. Edit `run_screen.py` — restore the two SignalSpec weights:
   ```python
   SignalSpec("coinvest_score_z", 0.65),
   SignalSpec("inst_delta_z", 0.35),
   ```
3. Run `python -m pytest tests/ -q` — no regressions expected (weights are runtime values, not logic).
4. Run one manual screen and confirm `inst_delta_z` values are non-zero for ≥ 70% of tickers in the output.
5. Log the restoration in the forward shadow checkpoint directory with a `RESTORED_{date}.json` marker file.

Do NOT change any other selector block weights, ranker weights, or coverage guard thresholds as part of this restoration.

---

## 6. What this ticket does NOT cover

- Ranker promotion of `inst_delta_z` — that requires Checklist v2 (FM + bootstrap + FDR + LOSO + year stability), per `policy_alpha_freeze_2026_04_04.md`.
- Any weight above 0.35 — restoration is to the pre-contamination state only.
- Modifying the coverage guard threshold — it stays at 0.50.
- Action on the six artifact names (NRIX, COGT, ZYME, MIRM, ORKA, ABVX) — those resolve naturally as 13F data refreshes.

---

## 7. Artifacts to read at checkpoint

```
artifacts/audit/inst_delta_forward_shadow/checkpoint_{latest}.json
artifacts/audit/inst_delta_attribution_2026-04-28.md
artifacts/audit/inst_delta_robustness_battery_2026-04-28.json
logs/inst_delta_forward_shadow.log  (confirm daily run coverage since T0)
```

If the daily shadow log shows missed runs (WSL downtime), do not treat the checkpoint as authoritative — the differential will be biased by sampling gaps per `feedback_observation_bias_cron_monitoring.md`.
