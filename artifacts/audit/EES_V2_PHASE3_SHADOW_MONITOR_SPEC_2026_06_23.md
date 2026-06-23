# EES v2 Phase 3 Shadow Monitor — Design Spec

**Date:** 2026-06-23  
**Status:** SPEC_ONLY — no implementation in this step  
**Motivation:** EES forward validation (`e80c3ff2`) returned `PASS_EES_DIAGNOSTIC_PREDICTIVE_SIGNAL_OBSERVED`. Phase 3 cohort drove the signal (5d IC = 0.174, t = 4.97; 20d IC = 0.203, t = 4.33) over the 2026-01-16 to 2026-05-07 gap period. A shadow monitor is needed to gather prospective evidence before any model-weight discussion.  
**Governance:** DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_MODEL_PROMOTION

---

## 1. Purpose

The EES forward validation was retrospective — it used a historical PIT panel to measure
whether `ees_v2_score` correlated with subsequent returns. That panel covers a single
time window (Jan–May 2026). A prospective shadow monitor runs forward from the current
date, accumulating daily observations under live conditions, so any future model-weight
discussion can rest on out-of-sample evidence rather than the in-sample gap-period result.

The monitor is **purely observational**. It appends records and computes statistics. It
does not score portfolios, generate signals, or interact with any production component.

---

## 2. Scope

| Dimension | Value |
|-----------|-------|
| Cohort | Phase 3 names only (`lead_program_phase == 3.0` in rankings.csv) |
| Score | `ees_v2_score` only |
| Horizons | 5d and 20d XBI-excess forward returns |
| Production impact | None — diagnostic-only outputs |
| Activation method | Manual run only — no cron, no scheduled trigger |
| Observation start | First daily run after this spec is implemented |

Phase 2 names and EES v3 are explicitly excluded:

- Phase 2 produced no diagnostic signal (IC = 0.043, t = 0.59) and would dilute
  the Phase 3 signal being monitored.
- EES v3 is not evaluable at current coverage (21.8% row density in the gap panel).
  A separate spec should govern v3 monitoring once coverage improves.

---

## 3. Inputs

All inputs must come from locally cached or already-committed sources. No live API
calls, no yfinance, no IEX, no Tiingo, no Alpaca.

| Input | Source | Notes |
|-------|--------|-------|
| Daily rankings | `data/snapshots/{date}/rankings.csv` | PIT-safe; loaded at run time |
| `ees_v2_score` | Rankings.csv column `ees_v2_score` | Nil rows excluded from IC computation |
| `lead_program_phase` | Rankings.csv column | Filter to `3.0` only |
| `is_hard_catalyst` | Rankings.csv column | Logged per row, not used as filter |
| Ticker close prices | Existing price cache / PIT archive | Same source used by PIT panel script |
| XBI benchmark | Existing price cache / PIT archive | Null XBI rows excluded from excess-return calculation |
| Return windows | Computed from cached closes: anchor close + N trading days forward | 5d = T+5, 20d = T+20 |

The script must refuse to make network requests. Any price lookup that cannot be
satisfied from cached data should produce a null forward return (row included with
null return, excluded from IC calculation, counted in coverage stats).

---

## 4. Outputs

### 4.1 Shadow ledger — append-only JSONL

Path: `artifacts/shadow/ees_v2_phase3_shadow_ledger.jsonl`  
Mode: **append-only**. Never overwrite or delete existing rows.  
One JSON object per (snap_date, ticker) observation. Schema:

```json
{
  "snap_date": "2026-06-24",
  "ticker": "RVMD",
  "ees_v2_score": 0.312,
  "lead_program_phase": 3.0,
  "is_hard_catalyst": true,
  "catalyst_event_type": "P3_INTERIM",
  "anchor_close": 42.17,
  "anchor_date": "2026-06-24",
  "actual_return_5d": null,
  "xbi_return_5d": null,
  "excess_return_5d": null,
  "forward_complete_5d": false,
  "actual_return_20d": null,
  "xbi_return_20d": null,
  "excess_return_20d": null,
  "forward_complete_20d": false,
  "ledger_version": "1.0",
  "run_ts": "2026-06-24T17:00:00Z"
}
```

Rows are written at snapshot time with null returns. A subsequent run fills in
`actual_return_Nd`, `xbi_return_Nd`, `excess_return_Nd`, and sets `forward_complete_Nd =
true` when the forward window closes. This makes the ledger self-healing: any run can
backfill forward returns for prior open rows without touching settled rows.

**Settled rows must not be modified.** A row is settled when `forward_complete_20d =
true`. The backfill logic must skip settled rows.

### 4.2 Daily summary

Path: `artifacts/shadow/ees_v2_phase3_summary_{date}.json`  
Written on each run. Replaces the prior day's summary file (not append-only — this is
a status file, not evidence). Schema:

```json
{
  "as_of": "2026-06-24",
  "phase3_rows_total": 47,
  "phase3_rows_with_ees_v2": 43,
  "completed_5d": 0,
  "completed_20d": 0,
  "ic_5d_mean": null,
  "ic_5d_n_dates": 0,
  "ic_20d_mean": null,
  "ic_20d_n_dates": 0,
  "hit_rate_5d": null,
  "hit_rate_20d": null,
  "quintile_spread_5d": null,
  "quintile_spread_20d": null,
  "observation_gate_5d": "NOT_MET",
  "observation_gate_20d": "NOT_MET",
  "governance": "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE"
}
```

`observation_gate_Nd` transitions from `NOT_MET` to `MET` when the completed-count
threshold is reached. No action is implied by `MET` — it gates interpretation, not
output.

### 4.3 No production outputs

The monitor must not write to any of the following:

- `data/snapshots/` (any date)
- `data/universe.csv`
- Any ranker, selector, sizing, final_score, or gate file
- Any portfolio, holdings, or watchlist file
- `production_data/`
- Any file outside `artifacts/shadow/`

---

## 5. Metrics

Computed per run across all settled rows in the ledger.

| Metric | Computation | Reported for |
|--------|-------------|-------------|
| Cross-sectional Spearman IC | Per-date rank correlation of `ees_v2_score` vs `excess_return_Nd`; aggregated as mean, median, t-stat | 5d, 20d |
| Top-bottom quintile spread | Top-quintile mean excess return minus bottom-quintile mean excess return, pooled across dates | 5d, 20d |
| IC hit rate | Fraction of dates with positive IC | 5d, 20d |
| Row coverage | Phase 3 rows with non-null `ees_v2_score` / total Phase 3 rows per date | Each date |
| Phase 3 cohort count | Count of distinct tickers with Phase 3 exposure per snapshot date | Each date |
| Completed observations | Count of rows where `forward_complete_Nd = true` | 5d, 20d |
| Dates with IC | Count of snapshot dates with ≥5 valid pairs for Spearman computation | 5d, 20d |

All metrics are computed only over rows where:
1. `forward_complete_Nd = true`
2. `excess_return_Nd` is not null
3. `ees_v2_score` is not null

Rows with null XBI are excluded from excess-return metrics but counted in coverage.

---

## 6. Observation Gates

No interpretation before thresholds are met.

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| 5d interpretation gate | 20 completed 5d observations | Matches Method A 5d acceptance threshold from PIT spec |
| 20d interpretation gate | 20 completed 20d observations | Matches Method A 20d acceptance threshold |
| Per-date IC minimum | 5 valid pairs per date | Same minimum used in gap-period validation |

"Completed" means `forward_complete_Nd = true`. At current cadence (one snapshot per
trading day, ~30 Phase 3 names per snapshot), 20 completed 5d observations arrive after
approximately 1 trading week. 20 completed 20d observations arrive after approximately
1 calendar month.

Until both gates are met, the summary file reports `observation_gate_Nd: NOT_MET` and
no IC or spread statistics are computed. The ledger continues to accumulate.

---

## 7. Success Criteria

Evaluated once both observation gates are met and at regular checkpoints thereafter.

1. **IC direction:** Mean IC remains positive at both 5d and 20d for at least 3 of 4
   rolling 4-week windows.
2. **IC stability:** 5d mean IC does not drop below +0.03 in any rolling 4-week window
   (half the gap-period point estimate).
3. **Phase 3 vs pooled comparison:** Phase 3-only IC remains stronger than all-catalyst-
   pooled IC when computed on the same prospective dates.
4. **Quintile spread direction:** Top-minus-bottom quintile spread is positive at both
   5d and 20d in the aggregate.
5. **Coverage:** Phase 3 row coverage ≥ 50% of Phase 3 names per snapshot date on
   average (indicating sufficient EES v2 population density to support IC computation).

---

## 8. Failure Criteria

Observation gates met; the following patterns, if observed, indicate the gap-period
signal does not generalize and should trigger a design-session review.

1. **IC collapse:** Mean 5d IC falls below 0.00 in any 4-week rolling window.
2. **Signal reversal:** Mean 5d IC is negative for 3 consecutive weeks.
3. **Coverage failure:** Average Phase 3 coverage drops below 30% per date (insufficient
   EES v2 population for meaningful IC).
4. **Outlier dependence:** Removing the top-1 return observation per date changes the
   sign of mean IC (signal driven by single outlier events, not rank ordering).
5. **Phase 3 premium disappears:** Phase 3-only IC is no better than Phase 2-only IC
   for 3 consecutive weeks.

Failure criteria do not trigger automatic actions. They trigger a design-session review
to decide whether the signal was gap-period-specific or whether a structural change has
occurred. No model changes result from failure criteria without a separate approval.

---

## 9. Governance

| Constraint | Status |
|-----------|--------|
| Production model freeze | ACTIVE — no ranker/selector/sizing/final_score/gate/snapshot changes |
| Monitor scope | `artifacts/shadow/` only |
| Cron/scheduling | NOT authorized — manual activation only |
| No live data fetch | Required — cached prices only |
| No API calls | Required |
| No portfolio output | Required |
| No trading or action language | Required |
| No alpha claims | Required |
| No model promotion | Required — a separate design memo + operator approval required |
| No freeze lift | Required — not implied by any success outcome |

**Model-use decision gate:** If success criteria are met after the observation window,
the appropriate next step is a **design memo** proposing a specific weight or gate change
to the model. That design memo requires:
1. Prospective IC evidence from this ledger (not just gap-period)
2. A proposed mechanism for how EES v2 Phase 3 would be incorporated (additional weight,
   new gate, tie-breaker, etc.)
3. Operator approval before any code is written

The shadow monitor does not authorize any of those steps on its own.

---

## 10. Implementation Notes (for the implementation step)

These notes are forward guidance only. No code is written in this step.

**Script location:** `scripts/research/ees_v2_phase3_shadow_monitor.py`

**Design constraints:**
- Must be runnable as a standalone script with no arguments (picks up today's snapshot)
- Must be idempotent: running twice on the same date should not create duplicate ledger rows
- Must skip settled rows during backfill
- Must not fail hard on missing prices — null forward return is the correct behavior
- Must log governance label (`DIAGNOSTIC_ONLY`) in every run header

**Ledger deduplication key:** `(snap_date, ticker)` — composite primary key for
idempotency check.

**Price lookup:** Reuse the price-cache pattern from `scripts/research/pit_gap_forward_returns.py`.
Do not add new price fetch logic.

**Run frequency:** Not scheduled. Operator runs manually, e.g., after market close when
prices for prior open return windows become available. Daily is sufficient.

---

## 11. Relationship to Existing Artifacts

| Artifact | Relationship |
|----------|-------------|
| `gap_panel_method_a_2026-06-23.csv` | Historical validation panel — provides the baseline IC this monitor should replicate prospectively |
| `EES_FORWARD_VALIDATION_2026_06_23.md` | Source evidence — the gap-period analysis this monitor extends forward |
| `pit_gap_forward_returns.py` | Price-cache pattern to reuse |
| `ees_forward_validation.py` | IC/Spearman computation functions to reuse |

---

## 12. Open Questions (for implementation step)

1. **Snapshot timing:** Does daily snapshot always exist by the time the monitor runs
   (e.g., if run at 5 PM ET, is today's snapshot committed)? If not, the script should
   fall back to the most recent available date and log the gap.

2. **XBI source:** The PIT panel retrieved XBI from the price archive. Confirm the
   archive contains XBI closes at the same timestamp as ticker closes to avoid
   look-ahead bias.

3. **Phase field normalization:** `lead_program_phase = 3.0` (float) in the gap panel.
   Confirm rankings.csv stores this consistently. The filter should handle both `3` and
   `3.0` string forms.

4. **EES v3 readiness:** If EES v3 coverage improves significantly over the observation
   window, a separate note should be added to extend the monitor to v3. This spec does
   not pre-authorize that extension.

---

*SPEC_ONLY — no implementation in this step. Next step: implement
`scripts/research/ees_v2_phase3_shadow_monitor.py` under separate operator instruction.*

*Governance: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_MODEL_PROMOTION*
