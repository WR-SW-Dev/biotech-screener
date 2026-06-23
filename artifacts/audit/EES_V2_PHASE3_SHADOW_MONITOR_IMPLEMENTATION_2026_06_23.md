# EES v2 Phase 3 Shadow Monitor — Implementation Memo

**Date:** 2026-06-23  
**Spec commit:** `c35fc1ba`  
**Implementation commit:** this PR  
**Status:** IMPLEMENTED — SPEC_COMPLETE  
**Governance:** DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON

---

## 1. Open Questions Resolved

### 1.1 Snapshot timing (Spec §12 Q1)

**Resolution:** `--as-of-date` is required. The script aborts if the rankings.csv for
that date is not found. No partial-snapshot protection is needed beyond this — if the
snapshot has not been promoted, the file will not exist and the run will fail cleanly
with an error log rather than silently writing incomplete rows.

The operator should run the monitor after daily snapshot promotion (typically post-4:30
PM ET).

### 1.2 XBI source (Spec §12 Q2)

**Resolution:** XBI is loaded from the same `data/pit_archives/{date}/price_history.csv`
used by `pit_gap_forward_returns.py`. This is the accepted PIT/cached source from the
evidence review. No alternate benchmark source, no live fetch. If XBI is absent in the
archive, `xbi_return_Nd` and `excess_return_Nd` are stored as null; the row remains in
the ledger and is counted in coverage statistics but excluded from IC computation.

### 1.3 Phase normalization (Spec §12 Q3)

**Resolution:** `is_phase3(value)` accepts:
- Any numeric or numeric-string that parses to float ≥ 3.0
- Case-insensitive strings containing `"phase 3"`, `"phase3"`, or `"p3"`

This handles the `3` vs `3.0` string ambiguity and any variant spellings (e.g.,
`"Phase 3b"`). Non-parseable values and empty strings return False (excluded).

---

## 2. Implementation

### 2.1 Script

**Path:** `scripts/research/ees_v2_phase3_shadow_monitor.py`

**Usage:**
```
python3 scripts/research/ees_v2_phase3_shadow_monitor.py --as-of-date YYYY-MM-DD
python3 scripts/research/ees_v2_phase3_shadow_monitor.py --as-of-date YYYY-MM-DD --dry-run
```

`--dry-run` computes and logs all stats without writing the ledger or summary file.
Use for testing and pre-flight checks.

**Key functions:**

| Function | Purpose |
|----------|---------|
| `is_phase3(value)` | Phase normalization (open question 3) |
| `filter_phase3_ees(rows)` | Filter rankings to Phase 3 with valid ees_v2_score |
| `resolve_archive(snap_date)` | Find best archive on or before snap_date |
| `load_prices(arch_date)` | Load price_history.csv from archive |
| `resolve_anchor(ticker, snap_date, ...)` | Find anchor close (same pattern as PIT script) |
| `compute_return(ticker, anchor_date, N, ...)` | Compute N-day return from archive |
| `load_ledger(path)` | Read JSONL; return rows + existing_keys + settled_keys |
| `write_ledger(rows, path)` | Write all rows; settled rows guaranteed unchanged by caller |
| `make_new_row(snap_date, ranking_row, ...)` | Construct a new ledger row with anchor prices |
| `backfill_open_rows(rows, prices, ...)` | Fill open rows; pass settled rows through unchanged |
| `compute_summary(all_rows, as_of_date)` | Summary stats + gate enforcement |

### 2.2 Key control: settled-row immutability

The primary safety control. Implementation:

1. `load_ledger()` identifies `settled_keys` — all (snap_date, ticker) pairs where
   `forward_complete_20d = True`.
2. `backfill_open_rows()` checks `row.get("forward_complete_20d") is True` before
   processing each row. Settled rows return via `result.append(raw_row)` — no copy,
   no modification.
3. After backfill, `main()` runs an integrity assertion:
   ```python
   for old, new in zip(existing_rows, updated_existing):
       if old.get("forward_complete_20d") is True:
           assert old == new
   ```
   This assertion will raise `AssertionError` if any settled row was modified,
   halting the run before writing the ledger.
4. The assertion covers the exact rows that were settled at load time — a new row
   that settles during this run's backfill is not checked (it was open, which is
   correct behavior).

### 2.3 Append-only semantics

"Append-only" in the spec means:
- No rows are deleted from the ledger
- Settled rows are immutable (see §2.2)
- Open rows can have null return fields backfilled

The implementation rewrites the full file rather than using OS-level append mode,
because OS append cannot update open rows. The settled-row invariant enforces the
logical guarantee. The write is atomic in the sense that it writes a complete valid
ledger — a failed write leaves the old file intact (not a partial overwrite).

### 2.4 Outputs

| File | Location | Committed? |
|------|----------|-----------|
| Ledger | `artifacts/shadow/ees_v2_phase3_shadow_ledger.jsonl` | No — gitignored |
| Daily summary | `artifacts/shadow/ees_v2_phase3_shadow_summary_{date}.json` | No — gitignored |
| `.gitkeep` | `artifacts/shadow/.gitkeep` | Yes — creates directory |

Both generated files are gitignored via `.gitignore` rule `artifacts/shadow/*`.

### 2.5 Observation gates (Spec §6)

`compute_summary()` enforces:
- If `completed_5d < 20` **or** `completed_20d < 20`, all IC/spread/hit_rate fields
  are set to `None` and `interpretation_status` is set to
  `OBSERVATION_WINDOW_INCOMPLETE_NO_INTERPRETATION`.
- Gates are checked independently — if 5d is met but 20d is not, 20d metrics remain
  null.
- "Completed" is defined strictly: `forward_complete_20d = True` for 20d gate,
  `forward_complete_5d = True` for 5d gate.

---

## 3. Tests

**Path:** `tests/test_ees_v2_phase3_shadow_monitor.py`  
**Count:** 37 tests, all passing.

| Test class | What it pins |
|-----------|-------------|
| `TestIsPhase3` | Phase normalization for 13 distinct input cases |
| `TestFilterPhase3Ees` | Combined phase + ees_v2_score filter |
| `TestDuplicatePrevention` | Same (snap_date, ticker) not added twice |
| `TestSettledRowImmutability` | Settled rows pass through byte-for-byte; open rows can be filled; integrity check raises on violation |
| `TestObservationGate` | IC is null before threshold; gate counts are accurate; open rows excluded from completed count |
| `TestLedgerRoundTrip` | Write/reload preserves all rows; empty-file handled; malformed lines skipped |

---

## 4. Governance Checks

| Check | Status |
|-------|--------|
| Production model freeze | ACTIVE — no ranker/selector/sizing/final_score/gate/snapshot/portfolio changes |
| No live fetch | PASS — no requests/yfinance/IEX/Tiingo imports |
| No cron registration | PASS — script does not register itself with any scheduler |
| No CLI auto-discovery | PASS — requires explicit `--as-of-date` argument |
| No production file writes | PASS — writes only to `artifacts/shadow/` |
| No model promotion | PASS |
| No freeze lift | PASS |
| No alpha claims | PASS |
| No trading/action language | PASS |
| Ledger/summary gitignored | PASS — confirmed via `git check-ignore` |

---

## 5. Usage after merge

**First run (no prior ledger):**
```bash
python3 scripts/research/ees_v2_phase3_shadow_monitor.py --as-of-date 2026-06-24
```

**Subsequent runs (backfill open rows + append new date):**
```bash
python3 scripts/research/ees_v2_phase3_shadow_monitor.py --as-of-date 2026-06-25
```

**Dry-run (no file writes):**
```bash
python3 scripts/research/ees_v2_phase3_shadow_monitor.py --as-of-date 2026-06-24 --dry-run
```

The monitor should be run once per trading day after snapshot promotion, manually by
the operator. It is not scheduled.

---

## 6. What this does not do

- Does not modify any production model file
- Does not change rankings, scoring, or selection
- Does not register a cron job or scheduler
- Does not push results to any external system
- Does not claim or imply alpha
- Does not recommend or imply a model-weight change

Any future model-use discussion requires a separate design memo and operator approval.
See Spec §9 (Governance) and §7 (Success Criteria) for the decision gate.

---

*Implementation by Claude Sonnet 4.6 assistant, 2026-06-23.*  
*DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON*
