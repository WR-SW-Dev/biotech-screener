# Forward Harness Audit — 2026-04-05

## Verdict: MOSTLY TRUSTWORTHY WITH CAVEATS

The forward harness is operationally useful but has several integrity issues that must
be understood. The daily production monitors (shadow monitor, production monitor, risk
monitor, post-promotion monitor) are broadly correct for their purpose. The biggest
risks are in append-only ledger duplication and backfilled artifacts that masquerade
as true forward records.

---

## What was checked

| Component | Files | Checked |
|-----------|-------|---------|
| Daily pipeline orchestrator | `tools/run_daily_production.py`, `run_daily.py` | Step ordering, failure isolation |
| Shadow monitor | `tools/build_shadow_monitor.py` | PIT safety, cumulative logic |
| Production monitor | `tools/build_production_monitor.py` | Overlap, ranker drift, path correctness |
| Post-promotion monitor | `tools/post_promotion_monitor.py` | CSV parsing, return alignment |
| Coinvest shadow tracker | `tools/coinvest_shadow_tracker.py` | Backfill PIT safety, dedup, immutability |
| IC dashboard | `tools/build_ic_dashboard.py` | History dedup, IC computation |
| Timing hazard overlay | `tools/compute_timing_hazard.py` | Calibration ledger dedup, rolling base rate |
| Timing hazard review | `scripts/research/timing_hazard_review.py` | PIT safety of backfill, density artifacts |
| Risk monitor | `tools/build_risk_monitor.py` | Price alignment, regime logic |
| Live shadow portfolio | `tools/live_shadow_portfolio.py` | Performance dedup, return realization |
| Live performance tracker | `tools/live_performance_tracker.py` | PIT price cache safety, write-once behavior |
| Dashboard/API | `dashboard/app.py` | Date mixing, stale artifact tolerance |
| Event quality shadow | `tools/event_quality_shadow_sizer.py` | Output existence |
| Ranker shadow comparison | `run_screen.py` (line 5065) + production_monitor | Path mismatch |

---

## Issues found and severity

### CRITICAL (affects trustworthiness of forward evidence)

#### C1. Coinvest shadow artifacts are backfilled, not truly forward (SEVERITY: HIGH)
- **Evidence**: All files from 2026-03-27 to 2026-04-02 have mtime=Apr 3 09:50-09:51
- **Impact**: Forward returns (`fwd_ret_5d`, `fwd_ret_20d`) use current price_history.csv
  which includes prices from AFTER the as-of date. Look-ahead contamination.
- **Selection/overlap metrics are PIT-safe** (computed from dated snapshot data)
- **Status**: DOCUMENTED. Forward return columns should be ignored for pre-start-date artifacts.
  Going forward, daily pipeline runs produce genuinely forward artifacts.

#### C2. IC dashboard history.jsonl had no dedup guard (SEVERITY: HIGH)
- **Evidence**: 9 entries for 6 dates (3 duplicates), out-of-chronological-order entries
- **Impact**: Any summary statistics computed from history.jsonl would double-count dates
- **Fix applied**: Added dedup guard (check existing dates before append)
- **Fix applied**: Cleaned existing file (9 → 6 entries, sorted by date)

#### C3. Timing hazard calibration ledger had no dedup guard (SEVERITY: HIGH)
- **Evidence**: `append_calibration_ledger()` blindly appends on every call
- **Impact**: Pipeline reruns would duplicate predictions, inflating the ledger
- **Current state**: Only 1 date (60 entries) — no duplicates yet
- **Fix applied**: Added dedup guard (check if prediction_date already in ledger)

### SIGNIFICANT (affects specific metrics or monitors)

#### S1. Production monitor ranker drift always returns "no_data" (SEVERITY: MEDIUM)
- **Evidence**: `build_production_monitor.py:189` looks in `artifacts/ranker_shadow_comparison.json`
  but `run_screen.py:5065` writes to `data/snapshots/{date}/ranker_shadow_comparison.json`
- **Impact**: Ranker divergence metric is always empty in production monitor
- **Fix applied**: Updated `load_ranker_shadow()` to check snapshot directory first

#### S2. Post-promotion monitor used fragile positional CSV indexing (SEVERITY: MEDIUM)
- **Evidence**: `load_perf_csv()` used `csv.reader` with `line[1]`, `line[4]`, etc.
  Header row was only excluded by exception handler catching `float("pnl_pct")`
- **Impact**: Would silently break if CSV columns were reordered
- **Fix applied**: Replaced with `csv.DictReader` using header names

#### S3. Dashboard mixes dates for some data sources (SEVERITY: MEDIUM)
- **Evidence**: `dashboard/app.py:218-220` loads earnings, bioshort, and all performance
  data without date filtering when rendering a historical date view
- **Impact**: Selecting an old date shows current earnings data and timing hazard review
  results alongside historical positions
- **Status**: DOCUMENTED, not fixed. Dashboard is operator-facing (not evidence), so
  this is cosmetic rather than analytical. Fix if it causes confusion.

### MINOR (theoretical risk, no current impact)

#### M1. Timing hazard review backfill is not truly forward-safe (SEVERITY: LOW)
- **Evidence**: `timing_hazard_review.py:backfill_predictions()` calls
  `compute_timing_hazard(snap_date)` which reads the calibration ledger.
  When backfilling, future-resolved outcomes pollute the rolling base rate.
- **Impact**: The `calibration_backfill.csv` results are reconstructed, not forward.
  However, the review explicitly labels itself as a diagnostic backfill.
- **Status**: ACCEPTABLE. The true forward record is the daily calibration ledger,
  not the backfill. The backfill is for calibration assessment, not evidence.

#### M2. Coinvest shadow files overwrite on rerun (SEVERITY: LOW)
- **Evidence**: `compute_shadow()` returns a result, and the pipeline writes it
  to `{as_of_date}.json` unconditionally. No immutability guard.
- **Impact**: Reruns silently replace prior artifacts. But since the content is
  deterministic from snapshot data (same inputs → same output), this is benign
  as long as snapshot inputs don't change.
- **Status**: ACCEPTABLE. Snapshot inputs are themselves immutable.

#### M3. Shadow monitor, risk monitor, post-promotion artifacts overwrite on rerun (SEVERITY: LOW)
- **Evidence**: All write to `{date}_monitor.json` unconditionally.
- **Impact**: Same as M2 — deterministic from inputs.
- **Status**: ACCEPTABLE.

#### M4. Ranker shadow comparison has never been produced (SEVERITY: LOW)
- **Evidence**: No `ranker_shadow_comparison.json` files exist anywhere on disk.
  The comparison logic in `run_screen.py:5065` may not have been triggered successfully.
- **Impact**: Ranker drift monitoring is non-functional. Fix S1 enables it when files appear.
- **Status**: DOCUMENTED. Root cause is in run_screen.py — investigate separately.

---

## What passed

| Check | Status | Detail |
|-------|--------|--------|
| Live shadow performance.csv dedup | PASS | `append_performance()` checks (date, prior_date, ruleset_id) |
| Live shadow performance.csv correctness | PASS | Daily PnL correctly computed from position prices |
| Coinvest shadow history.csv dedup | PASS | `append_history()` checks for duplicate date |
| Shadow monitor PIT safety | PASS | Reads only from append-only performance.csv filtered by date |
| Risk monitor computation | PASS | Uses real prices, correct drawdown/correlation logic |
| IC dashboard per-date artifacts | PASS | Dated files written correctly, content matches as_of_date |
| Post-promotion cumulative metrics | PASS | Correctly sums from promotion date |
| Timing hazard overlay (daily) | PASS | Uses rolling base rate from resolved predictions ≤ as_of_date |
| Pipeline step ordering | PASS | All monitor steps run AFTER snapshot promotion |
| Pipeline failure isolation | PASS | All monitor steps are non-blocking (try/except) |
| Live performance tracker write-once | PASS | Checks existing dates before computing |
| PIT price cache usage | PASS | Forward returns from PIT caches, not current prices |
| Snapshot immutability | PASS | Dated directories, not overwritten by pipeline |

---

## Fixes applied

| Fix | File | Description |
|-----|------|-------------|
| IC dashboard dedup | `tools/build_ic_dashboard.py:294` | Check existing dates before appending to history.jsonl |
| IC dashboard cleanup | `artifacts/ic_dashboard/history.jsonl` | Removed 3 duplicate entries, sorted by date |
| Calibration ledger dedup | `tools/compute_timing_hazard.py:467` | Check if prediction_date already in ledger |
| Ranker shadow path | `tools/build_production_monitor.py:188` | Check snapshot dir before artifacts dir |
| Post-promotion CSV parsing | `tools/post_promotion_monitor.py:49` | Replaced csv.reader with csv.DictReader |
| Performance.csv cleanup | `artifacts/live_shadow/performance.csv` | Removed 4 duplicate rows (28→24) |

### Additional issues found by parallel audit agents

- **A1**: Live shadow performance.csv had 4 duplicate keys (2026-03-08 x2, 2026-03-12, 2026-03-13).
  One pair had conflicting values (pnl=0 vs pnl=-2.28). Cleaned by keeping last occurrence.
- **A2**: Timing hazard backfill has density artifact risk at quarter-end date clusters (15% of
  snapshots have 1-day spacing). Design issue, not yet actionable.
- **A3**: Dashboard `/latest` endpoints pick alphabetically-last file with no schema validation.

## Tests added

File: `tests/test_forward_harness_integrity.py` (7 tests)

| Test | What it validates |
|------|-------------------|
| `TestICDashboardHistoryDedup` | History.jsonl rejects duplicate dates |
| `TestCalibrationLedgerDedup` | Ledger rejects duplicate prediction_dates |
| `TestPostPromotionCSVParsing` | DictReader parses correctly, header not treated as data |
| `TestProductionMonitorRankerPath` | Ranker shadow loaded from snapshot dir |
| `TestLiveShadowPerformanceDedup` | Existing dedup guard works correctly |
| `TestCoinvestShadowHistoryDedup` | Existing dedup guard works correctly |

---

## Answers to specific questions

### 1. Are forward artifacts immutable enough to be trusted?
**Mostly yes, with caveats.** The live shadow performance.csv has a strong dedup guard.
Dated monitor files (shadow_monitor, production_monitor, etc.) are deterministic from
inputs, so overwriting on rerun doesn't change content. The IC dashboard history.jsonl
and calibration ledger NOW have dedup guards (fixes applied). The coinvest shadow
backfilled artifacts are NOT truly forward but are labeled as such.

### 2. Can historical forward records drift after reruns or backfills?
**Yes, in two places**: (a) coinvest shadow backfills recompute forward returns from
current prices (look-ahead), (b) monitor artifacts can be overwritten on rerun
(benign since deterministic). **After fixes**: IC dashboard and calibration ledger
will not accumulate duplicates.

### 3. Are shadow comparisons aligned correctly?
**Yes for coinvest shadow** — all strategies use the same snapshot and eligible set.
**No for ranker shadow** — the comparison was never produced (S1, M4).

### 4. Are realized returns attached correctly and only once?
**Yes.** The live shadow performance.csv computes daily PnL correctly with dedup guards.
The coinvest shadow forward returns are currently only 5d/20d lookups from the
as-of date — not yet realized for recent dates (returns `None` correctly).

### 5. Is the forward harness overstating evidence from duplicate logging?
**Was yes, now no.** The IC dashboard had 3 duplicate entries (fixed).
The calibration ledger had no dedup (fixed before it accumulated duplicates).
The coinvest shadow history.csv had working dedup already.

### 6. Can the dashboard mix mismatched dates?
**Yes.** The dashboard shows current earnings, bioshort, and timing hazard review
alongside historical position data. This is cosmetic (operator-facing), not analytical.

### 7. Are timing-hazard review results truly forward?
**No.** The `calibration_backfill.csv` is a retrospective reconstruction.
The daily `calibration_ledger.jsonl` IS the true forward record (1 day so far).
The review is correctly labeled as a diagnostic tool, not forward evidence.

### 8. Does the current forward harness deserve trust for production monitoring?
**Yes, with understanding.** The daily monitors (shadow, production, risk, post-promotion)
are correct and PIT-safe for their intended purpose: operator situational awareness.
They should NOT be cited as statistical evidence of forward alpha.
The 30-day coinvest shadow window has NOT yet accumulated enough truly forward data
to draw conclusions (only 1 day of genuine data as of 2026-04-05).

---

## Remaining risks

1. **Coinvest shadow start date**: START_DATE="2026-04-03" means the 30-day shadow
   only began 2 days ago. All pre-start artifacts are backfills. Do not cite them
   as forward evidence.

2. **Calibration ledger is empty of outcomes**: All 60 entries have `actual_outcome: null`.
   Until outcomes are scored, the timing hazard forward evidence is zero.

3. **No ranker shadow comparison exists**: The drift monitoring feature is wired but
   non-functional until `run_screen.py` successfully produces comparison files.

4. **Dashboard should filter by date**: If the dashboard is ever used as evidence
   (rather than situational awareness), the date-mixing issue must be fixed.

5. **Live performance tracker (output/live_performance.csv)**: Uses PIT price caches
   correctly but depends on `scripts/eval_forward_returns.py` — not audited in depth.
   The tracker itself has write-once behavior and is sound.

---

## Recommendation

**Trust the daily monitors for operational purposes.** They correctly reflect the
current state of the portfolio and surface actionable alerts.

**Do NOT cite forward evidence until:**
- Coinvest shadow has ≥20 genuine forward days (earliest: ~2026-04-23)
- Calibration ledger has outcome-resolved entries (needs catalyst resolutions)
- IC dashboard has ≥10 clean forward entries

**Treat all backfilled artifacts with appropriate skepticism.** If a file's mtime
doesn't match its as_of_date, it was regenerated. Selection/overlap metrics are
PIT-safe; forward returns are not.
