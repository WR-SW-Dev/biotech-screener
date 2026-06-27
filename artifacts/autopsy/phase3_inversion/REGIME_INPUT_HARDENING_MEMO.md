# Regime Input Hardening — Diagnostic Memo

> Classification: `REGIME_SNAPSHOT_REFRESH_AND_STALENESS_GATE_NO_MODEL_CHANGE`  
> Date: 2026-06-26  
> Scope: `tools/refresh_market_snapshot.py` · `tools/check_market_snapshot_freshness.py`

---

## Root Cause

The Phase 3 inversion autopsy identified `regime_label = UNKNOWN` on 100% of tickers across all 16 snapshots (2026-05-18 – 2026-06-09). The cause was **not** a bad regime theory — it was broken regime input plumbing.

`data/market_snapshot.json` was frozen at 2026-05-19 with all signals zeroed:

```json
{
  "provenance": { "as_of_date": "2026-05-19" },
  "vix": "0",
  "xbi_vs_spy_30d": "0",
  "xbi_momentum_10d": "0"
}
```

**Why zeros?** `refresh_market_snapshot.py` had a silent failure mode: `_fmt(None)` returned `"0"` instead of `None`. When all yfinance feeds failed (coinciding with the May 23–26 rate-limit incident), the script wrote a plausible-looking snapshot full of zeros and reported success. The regime engine received VIX=0 and correctly returned UNKNOWN — but nothing surfaced that as an operational fault.

The snapshot then drifted stale for 21 calendar days. No staleness gate existed to block the pipeline from proceeding silently on broken regime input.

**This is an operational hardening issue, not a model research issue.** The regime detector logic was never exercised during Phase 3. Any conclusions about "the model was wrong during recovery" must be conditioned on the fact that the model's regime awareness was simply offline.

---

## What Changed

### 1. `tools/refresh_market_snapshot.py` — fail-closed write guard

| Before | After |
|---|---|
| `_fmt(None)` → `"0"` | `_fmt(None)` → `None` |
| Writes snapshot unconditionally | Validates before writing; raises `SnapshotValidationError` on failure |
| Failed refresh silently overwrites with zeros | Failed refresh preserves existing valid snapshot |
| No plausibility checks | VIX=0, VIX outside [5,90], null VIX, all-zero signals → validation FAIL |

The prior snapshot is preserved and the error is surfaced. The caller (cron job, pipeline wrapper) sees the exception and can alert.

### 2. `tools/check_market_snapshot_freshness.py` — preflight staleness gate

Standalone CLI and importable function:

```bash
python tools/check_market_snapshot_freshness.py --as-of-date 2026-06-09
# Exit 1: REGIME_INPUT_STALE_OR_INVALID
# • snapshot is 15 trading days old (as_of=2026-05-19, reference=2026-06-09); limit is 2
# • vix = 0 — impossible for live market data
# • all regime signal fields are 0.0 — indicates wholesale feed failure
```

If this had existed, Phase 3 would have been classified as `REGIME_INPUT_STALE_UNOBSERVABLE` rather than silently treating zeros as a real regime signal.

**Gate logic:**
- `as_of_date` must be ≤ 2 trading days behind the pipeline run date
- VIX must be non-null and in plausible range [5, 90]
- Not all signal fields can be zero simultaneously

---

## What This Does Not Fix

- The regime detector's underlying logic (frozen, not changed)
- The yfinance rate-limit root cause (handled separately by `scripts/yfinance_safe.py`)
- The cron job that runs `refresh_market_snapshot.py` — schedule not changed
- Phase 3 performance — this is a diagnostic finding, not a backtest adjustment

---

## Follow-On: Option B (Deferred)

```
REGIME_PRICE_HISTORY_FALLBACK_SHADOW_DIAGNOSTIC_NO_MODEL_CHANGE
```

Once the primary refresh path is confirmed stable (≥ 20 production runs), consider building a shadow regime detector that derives XBI momentum directly from `price_history.csv` as a fallback when `market_snapshot.json` is stale. **Shadow-only, no production verdict effect, no gating effect.** Compare fallback regime vs primary for 30–60 trading days before any promotion decision.

---

## Tests

| File | Tests | Coverage |
|---|---|---|
| `tests/test_market_snapshot_refresh.py` | 14 | validate_snapshot unit; write guard; fail-closed; no model mutation |
| `tests/test_market_snapshot_staleness_gate.py` | 17 | trading-day counter; fresh/stale/boundary; VIX=0; all-zero; missing file; bad JSON; custom threshold |

All 31 tests pass.

---

## Governance Verdict

```
Classification:    REGIME_SNAPSHOT_REFRESH_AND_STALENESS_GATE_NO_MODEL_CHANGE
Model change:      NO
Ranker change:     NO
Selector change:   NO
Sizing change:     NO
Regime thresholds: NO (validation only — plausibility bounds, not classification bounds)
Cron change:       NO

Status: OPERATIONAL HARDENING COMPLETE
        REGIME DETECTOR INPUT PLUMBING REPAIRED
        OPTION B (PRICE-HISTORY FALLBACK) DEFERRED TO SHADOW DIAGNOSTIC
```
