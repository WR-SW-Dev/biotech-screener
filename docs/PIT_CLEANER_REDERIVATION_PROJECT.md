# PIT-cleaner Re-derivation Project

Status: project start (2026-04-19)
Related: `docs/13F_BACKFILL_PLAN.md`, `docs/MODEL_DOCUMENTATION.md` § PIT
Prior work: Phases 3-5 (commits `df914cd4`, `cebb66f1`, `12e7ba0f`, `a7ec93f4`)

## Why this project exists

The 76-date Phase-5 full regen revealed that the current frozen A4 selector +
2-feature ranker had most of its apparent edge in pre-Phase-5 data, and the
edge came from institutional-state leakage rather than forward-looking alpha.

Partial results at 71/76 dates (2020-01 to 2025-10):

| Window | Pre-Phase-5 100% DEM | Phase 5 100% DEM |
|---|---|---|
| 57-mo pseudo-PIT | +107.4pp excess / t=1.80 / Sh 0.45 | +19.4pp / t=0.64 / Sh 0.03 |
| 12-mo live | +45.7pp / t=1.15 / Sh 1.24 | -1.1pp / t=0.10 / Sh 0.32 |

The model still produces a coherent biotech basket — it just happens to
track XBI once the institutional contamination is removed. The current
frozen selector/ranker was fit against data that contained the leak, so the
ranker's 2-feature *trained* weights (coinvest +0.061, financial -0.053)
were derived against a leak-amplified coinvest signal. The live deployed
artifact is already the capped Family C variant (coinvest +0.02, financial
-0.0533); the trained +0.061 is not the live weight.

Per existing memory (`feedback_coinvest_not_alpha.md`):
> "Coinvest is filter not alpha — not-held beats held on raw returns;
> quality filter only."

That note was written when the feature was still being used as alpha. Phase
5 just made it measurable.

## Critical framing — this is **PIT-cleaner**, not PIT-clean

Even with Phases 3-5 complete, historical research remains pseudo-PIT:
- Universe membership is current-state.
- Clinical state / trial records are partially retroactive.
- Manager registry is current-state (a 2024 addition is "elite" in 2020).
- Short interest is current-state historically.
- **The current decision-engine code and ruleset are applied retroactively.**
- Historical options are disabled (no PIT chain source exists yet).

A re-derivation done under these constraints is **less contaminated, not
uncontaminated**. No re-derived model can be promoted on historical
pseudo-PIT strength alone.

## Project goal

Produce at least three candidate selector/ranker families that are derived
under the cleanest currently available PIT constraints, and evaluate each
honestly against the current frozen model on both the pseudo-PIT window
and the live holdout.

## Non-negotiable evidence rules

1. Live forward monitoring remains the primary deployable evidence source.
2. No candidate is promoted on historical pseudo-PIT strength alone.
3. Live holdout is not re-used for tuning. Any candidate tuned on live is
   not a candidate, it's a recipe for regret.
4. Historical options overlay stays **OFF** for the duration of this
   project.
5. Every reported number is net-of-cost (50 bps one-way baseline).

## Feature allowlist / denylist

### Hard exclude from alpha derivation

These features either carry known contamination or were demonstrated to
have their power attributed to leakage in Phase 5:

- `coinvest_score_z` — institutional block, leak-amplified
- `inst_delta_z` — institutional delta, leak-amplified
- any derived `ranker_inst_block`, `selector_institutional_block` weights
- all historical options-derived fields (`opt_*`, `ranker_options_block`,
  options-dependent `ees_*` components) — no PIT source for historical IV
- `short_interest_pct` historically — current-state sidecar
- trial-record-derived fields sourced from current `trial_records.json`
  rather than per-date cache — case-by-case

### Allow / consider

Features that are closest to genuinely PIT-safe:

- EDGAR financial fields (`production_data/pit_financials/{TICKER}.json`) —
  filing-date gated, true PIT
- Price / return / volatility features derived from `price_history.csv`
- Dated catalyst / regulatory timing features from the event ledger where
  `disclosed_at` is present
- Survivorship-filtered universe (`ipo_dates.json` pre-IPO/delist gate) —
  already applied under `pit_mode=degrade`
- Archived snapshot inputs (`data/snapshots/{date}/inputs/`) where available
  (forward-only from 2026-04-17, so most of history is still the current
  file; flag explicitly)

### Special treatment for institutional signals

Do not conclude "institutional is useless" from one pass. Test it in
three roles per candidate family:

1. **Family A (off entirely)** — no institutional input to selector or ranker
2. **Family B (filter only)** — institutional signal used as a quality /
   risk gate with zero direct alpha weight
3. **Family C (small capped alpha)** — institutional allowed a bounded,
   monotone contribution with weight ≤ 0.02. Note: Family C is already the
   live deployed vector in `production_data/ranker_v2_model.json` (coinvest
   capped at +0.02); the 0.061 figure is the trained basis, not the live
   weight.

The working hypothesis is B. A tests the null. C tests whether a small
capped role survives.

## Walkforward design

No single pooled fit. Use rolling windows across the 76-date Phase-5 regen:

```
Train windows: expanding, start = 2020-01-31
Validation windows: rolling 12-month, lagged by 3 months
Live holdout: 2024-10-01 through latest snapshot — touched ONCE at the end
```

A candidate must be selected on the walkforward validation series, not
tuned on the live holdout. The live holdout is the final arbiter.

## Metrics (net-of-cost, 50 bps one-way)

### Per-window reporting (for each candidate and the frozen benchmark)

- Cumulative return, monthly excess vs XBI, annualized
- Hit rate (% months with excess > 0)
- Sharpe, Sortino, Information Ratio
- Max drawdown, Ulcer index, Calmar
- Turnover (monthly)
- Tail concentration (top-3 contributor share, bottom-3 drag)
- t-stat on monthly excess

### Stability diagnostics

- Feature importance stability across walkforward folds
- Performance when each block is removed in isolation (block-dropout)
- Performance conditional on regime (XBI up months vs down months)
- Does the candidate collapse to tracking XBI when the dominant block is
  removed? (this is the A4 selector's current failure mode)

## Comparison tests

1. **Current frozen model (A4 + 2-feat ranker) vs Family A / B / C**
   on the 76-date Phase-5 regen and the live holdout separately.
2. **Institutional role: off vs filter vs capped-alpha** within Family B/C.
3. **Options historical OFF** throughout — already default.
4. **30/70 DEM/XBI wrapper applied to each candidate** per standing
   allocation policy.
5. **Ex-tail and concentration**: drop top-N contributors per candidate,
   re-compute all metrics. The candidate that survives the tail-drop test
   is the one that generalizes.

## Decision rule

Rank candidates by this ordering (not the best pseudo-PIT CAGR):

1. Live holdout net excess vs XBI (primary)
2. Live holdout ex-tail robustness
3. Lower dependence on known-contaminated blocks
4. Simpler / more interpretable logic
5. Acceptable turnover (<0.25 monthly) and drawdown (> -35% in live)

If no candidate clears (1) convincingly, the right call is **demote the
current model, keep 30/70 DEM/XBI, and wait for more live evidence**.

## Deliverables

1. Executive summary of candidate comparison
2. Feature allowlist / denylist (this doc is the canonical source)
3. Candidate family definitions (frozen in separate ruleset JSONs)
4. Walkforward derivation artifact (code + configs)
5. Benchmark vs candidate tables (live holdout + walkforward)
6. Institutional-role comparison table
7. Recommendation, drawn from:
   - keep frozen model for now
   - replace selector only
   - replace ranker only
   - replace both
   - demote institutional to filter only
   - demote model, no replacement yet

## Honesty constraints

- This is PIT-**cleaner**, not PIT-clean.
- Historical results remain pseudo-PIT.
- Options historical block is off throughout.
- If no candidate shows real live improvement, the report says so clearly.
- If the best conclusion is "demote the current model and rebuild from a
  non-institutional core," the report says that directly.

## Working hypothesis

- Institutional contribution to selector should be **zero or filter-only**
  in the final candidate.
- The most promising candidate is a simpler non-institutional core, with
  institutional used only as a secondary filter if it demonstrably improves
  stability without inflating historical alpha.
- The live holdout may not have enough power (12-18 months) to reject or
  confirm at high confidence. The honest outcome may be "no confident
  promotion yet; keep 30/70 and add live months."

## What this session covers

The full project is multi-session. This session covers:
1. Plan (this document).
2. Freezing the current benchmark: final 76-date Phase-5 numbers vs live
   holdout vs pre-Phase-5 baseline.
3. Family A first-pass: re-rank the 76 snapshots with
   `--coinvest-eval-mode off` via `scripts/eval_forward_returns.py`, which
   zeros the coinvest contribution in the ranker without requiring a full
   regen rerun. Compare to the current-model results on the same 76 dates.
4. Report what Family A alone tells us, and what Families B/C require to
   build (ruleset JSON + selector gate logic).

Families B (filter-only) and C (capped-alpha) require new ruleset JSON
files and — for the selector side — code changes to support the new
gating logic. Those belong in a follow-up session.
