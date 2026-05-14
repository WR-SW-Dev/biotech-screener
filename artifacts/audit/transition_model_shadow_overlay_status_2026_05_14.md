# Markov Transition Model Shadow Overlay — Status Memo

**Date:** 2026-05-14  
**Commit:** `baf514b9` (also contains Spec 100 scaffold)  
**Status:** SHADOW-ONLY; production validation pending

---

## What Was Shipped in baf514b9

**Alongside Spec 100 scaffold** (not part of Spec 100), commit `baf514b9` also included:

- `event_ev/transition_model.py` — Observable Markov chain for runway financing risk
  - Five states: SAFE → WATCH → STRESSED → FINANCING_LIKELY → DISTRESS
  - State labeling from runway_buffer_months + ev_severity_score
  - Transition matrix estimation (pooled cross-sectional fallback)
  - Multi-step probabilities (30/60/90 day horizons)

- `tests/test_transition_model.py` — 16 tests for state labeling, matrix math, PIT safety

- `run_screen.py` integration — adds shadow columns only
  - `transition_runway_state`
  - `transition_p_runway_worse_60d`
  - `transition_p_financing_90d`
  - `transition_p_distress_90d`

- `transition_model_overlay.json` sidecar per snapshot

---

## Current Status: SHADOW-ONLY

**Shadow columns in production snapshots?**
- Yes: `transition_*` columns are written to rankings.csv
- But they do NOT affect ranking, selection, or truth-gate logic
- Diagnostic-only; no scoring authority

**Does it change ranking decisions?**
- No. Transition model is read-only overlay on final rankings.
- Does not affect `final_rank`, `actionable_rank`, selector eligibility, or action assignment

**Does it mutate historical snapshots?**
- No. Rankings.csv rows are not modified; overlay columns are appended only

**Does it require validation before production use?**
- Yes. Shadow status means: shipped for observation, not ready for production reliance

---

## Integration Points (run_screen.py)

The model is wired into the production snapshot enrichment pipeline:
- Loaded after ranking is final
- Columns added before CSV write
- No dependency on sorting, gating, or scoring

**Implication:** The overlay is live-shipped (data is in production snapshots), but should be treated as diagnostic only until validated.

---

## Validation Checklist (Before Production Use)

Before any production reliance on transition_model columns:

- [ ] Verify state labeling is correct (SAFE vs WATCH separation)
- [ ] Confirm transition matrix is stable (not overfitting to short window)
- [ ] Validate against historical runway outcomes (do transitions predict financing events?)
- [ ] Test PIT safety (no lookahead bias in state assignment or transitions)
- [ ] Assess model performance on held-out period (bootstrap or LOSO)
- [ ] Document limitations (e.g., sparse transitions in small cohort)

**Timeline:** Can defer until post-2026-05-15 (after 13F refresh) or post-2026-05-22 (after cohort-window closes), depending on priority.

---

## Why in Same Commit as Spec 100?

Likely accidental staging collision during the git workflow on 2026-05-14. The Markov model work was prepared in parallel with Spec 100 scaffold, and both ended up in the same commit.

**Recommendation:** Keep them together (reverting would be disruptive), but clearly document the separation via this memo.

---

## Not Part of Ranker Research Freeze

The Markov transition model is **not** subject to the ranker research freeze (Specs 072/091/096/100), because:
- It does not change ranker logic, weights, or features
- It does not contribute to ranking or selection
- It is a diagnostic overlay, not a ranker candidate

Shadow status is separate from ranker freeze.

---

## References

- Commit: `baf514b9`
- Model code: `event_ev/transition_model.py`
- Tests: `tests/test_transition_model.py`
- Integration: `run_screen.py` (added transition model enrichment)
- Status: Shadow-only diagnostic; validation pending
