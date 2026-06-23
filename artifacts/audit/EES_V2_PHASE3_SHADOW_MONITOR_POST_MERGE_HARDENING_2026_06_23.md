# EES v2 Phase 3 Shadow Monitor — Post-Merge Hardening Audit

**Date:** 2026-06-23  
**Audited commits:** `e80c3ff2`, `c35fc1ba`, `60876b11` (landed on `main` directly)  
**Hardening commit:** this commit  
**Status:** PASS_POST_MERGE_HARDENING_SETTLED_ROW_IMMUTABILITY

---

## 1. Context

The shadow monitor implementation (`60876b11`) bypassed the intended review-gated PR
flow: commits were pushed directly to `main` via `ALLOW_AGENT_PUSH=1` before a feature
branch was established. The pre-push guard functioned correctly — it blocked the
automated push and required the explicit override — but the commits landed on `main`
rather than a branch.

This memo documents a post-merge audit of the critical control (settled-row
immutability) and the narrow hardening patch applied to close the identified gap.

---

## 2. Issue Identified

**Location:** `backfill_open_rows()` and the integrity assertion in `main()`

**Original code:**
```python
if raw_row.get("forward_complete_20d") is True:
    result.append(raw_row)
    continue
```

**Gap:** `is True` uses Python identity comparison, which only matches the singleton
`True`. A manually edited ledger row with `"forward_complete_20d": 1` or
`"forward_complete_20d": "true"` would fall through to the copy-and-backfill branch,
potentially overwriting settled return data.

**Risk level:** Low in normal operation. The ledger is only written by `write_ledger()`
which uses `json.dumps`, which serializes Python `True` as JSON `true` → loads back as
Python `True`. The gap only opens if the JSONL file is edited by hand.

**Decision:** Harden anyway. The cost is two lines; the benefit is that the settled-row
guarantee holds against any realistic manual intervention.

---

## 3. Patch Applied

### 3.1 New helper: `_is_settled(value)`

```python
def _is_settled(v: object) -> bool:
    """
    Return True if a forward_complete_Nd field indicates a settled (immutable) row.

    Accepts JSON boolean True, numeric 1, and common truthy string forms so that
    manually edited ledger rows are protected identically to script-generated ones.
    Rejects everything else, including None and missing fields.
    """
    if v is True or v == 1:
        return True
    if isinstance(v, str) and v.strip().lower() in ("true",):
        return True
    return False
```

Accepted as settled: `True`, `1`, `"true"`, `"True"`, `"TRUE"`  
Rejected (open): `False`, `0`, `"false"`, `None`, missing field, `"1"` (string)

Note: `"1"` as a string is deliberately excluded. The only source of string-form truthy
values in a manually edited JSONL is someone typing `"true"` or `"True"`, not `"1"`.
Including `"1"` would risk over-broad matching.

### 3.2 Call sites updated

| Location | Before | After |
|----------|--------|-------|
| `load_ledger()` — settled_keys set comprehension | `is True` | `_is_settled(...)` |
| `backfill_open_rows()` — outer settled guard | `is True` | `_is_settled(...)` |
| `backfill_open_rows()` — inner per-horizon guard | `is True` | `_is_settled(...)` |
| `compute_summary()` — settled_5d/20d filters | `is True` | `_is_settled(...)` |
| `main()` — integrity assertion | `is True` | `_is_settled(...)` |

---

## 4. Tests Added

**17 new tests** in `tests/test_ees_v2_phase3_shadow_monitor.py`:

**`TestIsSettled` (11 tests)** — unit tests for `_is_settled()`:
- `True`, `1`, `"true"`, `"True"`, `"TRUE"` → settled
- `False`, `0`, `"false"`, `None`, missing field, `"1"` → not settled

**`TestBoolishSettledRowImmutability` (6 tests)** — integration tests confirming
`backfill_open_rows()` respects the new helper:
- Rows with `forward_complete_20d = True` → unchanged (JSON boolean)
- Rows with `forward_complete_20d = 1` → unchanged (numeric)
- Rows with `forward_complete_20d = "true"` → unchanged (string)
- Rows with `forward_complete_20d = False` → open, backfilled
- Rows with `forward_complete_20d = 0` → open, backfilled
- Rows with `forward_complete_20d = "false"` → open, backfilled

**Total test count:** 54 (was 37, +17 hardening tests), all passing.

---

## 5. Dry-Run Validation

```
as_of_date=2026-06-23 | dry_run=True
Phase 3 with valid ees_v2_score: 186 / 291 total rankings
Loaded archive 2026-06-23: 391 tickers, 11176 trading dates
Loaded ledger: 0 rows (0 existing keys, 0 settled)
New rows: 186 | Skipped (duplicate): 0 | Settled (immutable): 0
Backfill: 0 newly completed 5d, 0 newly completed 20d
completed_5d=0 (gate=NOT_MET)
completed_20d=0 (gate=NOT_MET)
interpretation_status=OBSERVATION_WINDOW_INCOMPLETE_NO_INTERPRETATION
DRY RUN — no files written
```

Monitor correctly identifies 186 Phase 3 rows in today's snapshot, loads the correct
archive, and reports `OBSERVATION_WINDOW_INCOMPLETE_NO_INTERPRETATION`. No files
written. This is the expected status — the observation gates (20 completed 5d + 20d
observations) will not be met until sufficient trading days have elapsed.

---

## 6. Governance

| Check | Status |
|-------|--------|
| Production model freeze | ACTIVE — no ranker/selector/sizing/final_score/gate/snapshot/portfolio changes |
| No live fetch | PASS |
| No cron registration | PASS |
| No production file writes | PASS — hardening patch touches only script + tests + this memo |
| Settled-row immutability | HARDENED — `_is_settled()` covers JSON bool, numeric 1, and string forms |

---

## 7. Verdict

```
PASS_POST_MERGE_HARDENING_SETTLED_ROW_IMMUTABILITY
```

The narrow gap identified in the post-merge review is closed. The settled-row
immutability guarantee now holds against script-generated JSON, numeric `1`, and
human-typed string forms. No model changes. Freeze remains ACTIVE.

Next action: run the monitor daily after snapshot promotion. No interpretation until
observation gates are met.

---

*DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON*
