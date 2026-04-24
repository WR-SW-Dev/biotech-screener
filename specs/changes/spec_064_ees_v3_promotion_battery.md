# Spec 064 — EES v3 Promotion Battery

**Status**: P0 sidecar emission wired into daily pipeline 2026-04-23. First artifact expected on next scheduled run. P1/P2 not started (gated on 5 consecutive clean coverage snapshots).
**Author**: Claude / arrenchulz
**Date**: 2026-04-23
**Ruleset impact**: NO (diagnostic overlay; no selector/ranker/portfolio change)
**Alpha stack impact**: NO until promotion gate clears
**Depends on**: `pit_backtest_ees_v2.py`, `ees_v3_checklist_battery.py`, current A4 + 2-feat ranker baseline, Spec 062 (sidecar precedent)

---

## Objective

Define the exact conditions under which EES v3 may be promoted from
**diagnostic-only overlay** to a role that gates selection. Current state
per memory audit (2026-04-14): Checklist v2 = 4/5, WS4 gate fails with
`t_adj = 1.53` vs `1.65` threshold, attributed to structural autocorrelation
from overlapping forward horizons. Historical-backtest claims are not
credible (2026-04-17 invalidation; ruleset drift from `69a0c7f8` → `2a3e79eb`).
This spec replaces generic "find more IC" work with a two-track verification:

1. **Data-plane trust** — coverage of `priced_move_pct`, `short_interest_pct`,
   and gap-computable rows must be sufficient and stable before any stats
   result is believable.
2. **WS4-targeted statistics** — autocorrelation-honest t-stats and
   bootstrap inference, with cross-snapshot aggregates stripped per the
   2026-04-19 architecture freeze ("per-snapshot tables, not cross-snapshot
   aggregates").

No promotion without **both** tracks green **and** ≥30 live trading days of
forward sidecar evidence.

## Context

- **Frozen baseline**: A4 selector + 2-feat pairwise ranker (coinvest +0.02,
  financial −0.0533). Any new component must prove incremental value over
  this, not correlate with it.
- **Known-null component**: `base_rate_gap_score` (IC = −0.090,
  anti-predictive). Kept in battery as negative control only.
- **Forward-only evidence policy (2026-04-17)**: no historical alpha claim
  is credible; live monitoring is the only valid evidence.
- **Architecture-freeze policy (2026-04-19)**: attribution only, not
  performance; per-snapshot tables, not cross-snapshot aggregates.

## P0 — Sidecar diff emission (blocking)

### Artifact path
`data/snapshots/{YYYY-MM-DD}/ees_sidecar_diff.json`

### Schema

```json
{
  "snapshot_date": "2026-04-23",
  "ees_version": "v3",
  "baseline": {
    "selector": "A4_2feat_ranker",
    "ruleset": "2a3e79eb",
    "selected_tickers": ["..."]
  },
  "ees_overlay": {
    "would_filter": [
      {"ticker": "XXX", "reason_code": "trap|timing|quality",
       "ees_score": -1.23, "driver_component": "conditional_misprice_score"}
    ],
    "would_add":    [{"ticker": "YYY", "ees_score": 2.05, "driver_component": "..."}],
    "would_retain": ["..."]
  },
  "coverage": {
    "total_eligible": 297,
    "pct_priced_move": 0.68,
    "pct_short_interest": 0.82,
    "pct_gap_computable": 0.55,
    "pct_full_ees_computable": 0.49,
    "hard_fail_flags": []
  },
  "forward_outcomes": {
    "horizon_days": 21,
    "status": "pending",
    "available_as_of": "2026-05-22"
  }
}
```

Separate appender (runs +21 trading days post-anchor):
`data/snapshots/{anchor}/ees_sidecar_outcomes.json` with realized 21d
returns keyed by `(ticker, anchor_date)` for both filtered and retained
names.

### Coverage hard-fail thresholds

Evaluated per-snapshot. Any metric breaching for **≥3 consecutive
snapshots** blocks P1/P2 progress until resolved.

| Metric | Min | Stability |
|---|---|---|
| `pct_priced_move` | 0.60 | MoM delta ≤ 10pp |
| `pct_short_interest` | 0.70 | MoM delta ≤ 10pp |
| `pct_gap_computable` | 0.50 | MoM delta ≤ 10pp |
| `pct_full_ees_computable` | 0.40 | MoM delta ≤ 10pp |

30-day sidecar countdown begins only after **5 consecutive snapshots**
with zero hard-fail flags.

### Wiring

Post-promotion hook in `tools/run_daily_production.py`, mirroring how
`ees_v3_overlay.json` is written. No changes to ranker, portfolio, or
decision artifacts.

## P1 — WS4 gate math (gated on P0 clean)

### Problem

Current NW t-stat fails at `t_adj = 1.53` (threshold 1.65). Root cause:
overlapping forward horizons (e.g. 21d returns with daily snapshots → 20d
overlap between adjacent observations) violate the independence assumption
under-corrected by default NW lag choices.

### Test A — Newey-West with horizon-matched lag

For horizon `h` days, set lag `L = h − 1` (Hansen-Hodrick convention with
Bartlett weights):

```
V_NW = γ(0) + 2·Σ_{k=1..L} (1 − k/(L+1)) · γ(k)
SE_adj = √(V_NW / N)
t_adj  = mean_IC / SE_adj
```

Report per horizon (21 / 42 / 63d):

- `t_raw`, `t_adj`
- `N_raw`, `N_eff = N / (1 + 2·Σρ_k)`
- `inflation_factor = SE_adj / SE_raw`
- Lag `L` used and justification

### Test B — Stationary block bootstrap (Politis-Romano)

- `B = 2000` replications
- Expected block length `L* = h` (matches overlap structure)
- 95% CI on mean IC
- Pass: lower bound > 0

### Test C — Overlapping-sample variance correction

Britten-Jones et al. (2011) correction as independent cross-check on Test A.

### WS4 pass criteria (all four)

1. `t_adj ≥ 1.65` under horizon-matched lag at primary horizon (21d)
2. `N_eff ≥ 30`
3. Block bootstrap 95% CI excludes zero
4. Sign agreement across Tests A and C (no method-dependent inference)

### Scope constraint (freeze-compliant)

Strip all cross-snapshot aggregates from `pit_backtest_ees_v2.py`: no
rolling-IC charts, no decile-spread-over-time tables. Keep only
per-snapshot tables + the four WS4 stats above.

## P2 — Incremental value over frozen baseline (gated on P1 pass)

### Fama-MacBeth incremental regression

Per snapshot:

```
r_{i,t+21} = α + β_1·coinvest_z_i + β_2·financial_z_i + β_3·ees_v3_score_i + ε_i
```

where the first two features match the frozen 2-feat ranker.

### Aggregation

- Collect `β_3` and `t(β_3)` per snapshot
- Mean across snapshots
- Apply WS4 NW correction to the mean (same lag convention as P1)

### Pass criteria

- `mean(β_3) > 0` with `t_adj ≥ 1.96`
- Adding EES improves adjusted R² by **≥ 0.5pp** on average (not cosmetic)
- No sign instability: `β_3 > 0` in **≥ 60%** of snapshots

## Controls

- **`base_rate_gap_score` as negative control**: expected IC ≤ −0.05 at 21d.
  If it flips positive, battery is contaminated — pause and investigate.
  Kept in sidecar emission; removed from promotion battery only.
- **Shuffled-labels test**: scramble forward returns within snapshot; WS4
  stats must drop to noise. Confirms pipeline integrity before believing
  any positive result.

## Promotion rule

All three required to move EES v3 from diagnostic overlay to a gating role:

1. **Checklist v2 = 5/5** (4/5 currently; WS4 cleared per P1 criteria)
2. **≥ 30 live trading days of P0 sidecar** with:
   - Zero coverage hard-fail flags across the window
   - Filtered-vs-retained 21d return gap significant at one-sided 90%
     (filtered < retained)
3. **P2 incremental test passes** (EES adds value conditional on frozen
   baseline)

Failing any one → EES stays diagnostic-only. No partial promotion.

## Execution order

- **Day 0**: wire P0 sidecar emission into daily pipeline
- **Day +5 earliest**: P0 countdown starts if coverage clean for 5
  consecutive snapshots
- **Day +5**: P1 WS4 stats run — independent of P0 countdown, uses existing
  PIT snapshots
- **Day +35 earliest**: promotion gate evaluable

## Out of scope

- New EES components or reformulations (architecture freeze holds)
- Cross-snapshot rolling-IC analysis (freeze-prohibited)
- Sizing or confidence weighting (ordinal-only policy, 2026-04-04)
- Any promotion of `base_rate_gap_score` (anti-predictive, permanently
  negative-control)

## Non-goals

- This spec is **not** a plan to re-test known-null components
- This spec is **not** a historical alpha claim battery
- This spec does **not** replace forward monitoring with statistics alone
