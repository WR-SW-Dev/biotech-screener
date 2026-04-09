# Spec 061a: Stage 1 Tiebreaker — Promotion Decision Rule

**Date:** 2026-04-09
**Status:** DEFINED (pre-evidence)
**Candidate ruleset:** `research_ev_stage1_tiebreaker.json` (b19d2bfa)

---

## What Stage 1 does

Sets `event_ev_stage: "tiebreaker"` in the decision ruleset. The decision engine
inserts `-ev_score` before the alphabetic ticker tiebreak in the sort key. This
only reorders names with **identical** final_score + missing_count. In practice:
names tied at the Top-30 cutoff boundary.

Stage 1 does NOT change scores, weights, sizing, or eligibility. It is the
minimum possible integration of EV into production.

---

## Promotion gate: ENABLE Stage 1 canary when ALL of:

1. **Readiness: ≥5 daily EV artifacts** with avg ≥50 tickers/day
   - Source: `ev_promotion_readiness.json` → `tiebreaker.ready == true`

2. **Validation: ≥3 real resolved outcomes** (not future-dated pre-populated)
   - Source: `ev_validation_ledger.jsonl` entries where `realized_1d_return` is not null
   - Rationale: need at least some evidence the model isn't systematically wrong

3. **No regression in shadow**: Stage 1 candidate vs production on the same
   snapshot dates shows ≤2 Top-30 boundary changes, and none of the displaced
   names outperformed the replacements by >2pp over the observation window
   - Source: daily shadow comparison (not yet built — see monitoring below)

4. **Brier score < 0.50** on resolved matches
   - Source: `ev_validation_summary.json` → `brier_score`
   - 0.50 is random-coin calibration; we need to beat it

5. **Human sign-off** — governance review of the above evidence
   - This spec defines the criteria; it does not auto-promote

---

## Keep shadow only (do NOT enable) if ANY of:

- Readiness gate not met (<5 days or coverage <50 tickers)
- Zero real resolved outcomes with prices
- Brier score ≥ 0.50 (worse than random)
- Shadow comparison shows Stage 1 displaces a name that subsequently
  outperforms the replacement (even n=1 is a yellow flag at this stage)
- Outcome model still using pooled base rate for all clinical phases
  (partially fixed — Phase 3 CRT-calibrated, Phase 1/2 excluded)

---

## What to monitor daily

1. `ev_promotion_readiness.json` — does tiebreaker gate say ready?
2. `ev_validation_summary.json` — Brier score, n_matched, n_with_prices
3. Top-30 boundary: which tickers sit at ranks 29-31 in production, and
   would Stage 1 swap any of them?
4. First real resolution: TVTX PDUFA ~Apr 13 is the first test

---

## After Stage 1 is enabled

- Run as canary alongside production for ≥10 trading days
- Track: did the tiebreaker change any Top-30 names?
- Track: did those changes help or hurt (excess return of swapped names)?
- Do NOT proceed to Stage 2 (rank overlay) until:
  - ≥15 days of Stage 1 canary data
  - ≥10 real resolved outcomes
  - Brier < 0.35 (better than trivial calibration)
  - Human governance review

---

## Timeline expectation

- Readiness gate: ~Apr 14 (5 daily artifacts)
- First real resolution: ~Apr 13 (TVTX PDUFA)
- Earliest possible Stage 1 canary: ~Apr 15-16
- Stage 2 consideration: not before May
