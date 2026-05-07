# Spec 087 — Bioshort Hedge-Report Producer Restoration (Phase B Draft)

**Status**: DRAFT — awaiting operator review before any implementation
**Date**: 2026-05-06
**Phase**: B (B0 → B1 → B2 sequenced)
**Predecessors**:
- `artifacts/audit/bioshort_upstream_p2_finding_2026_05_06.md` — producer ID + suppression rationale
- `artifacts/audit/spec_087_phase_a_bioshort_hedge_governance_decision_2026_05_06.md` — Phase A decision memo
- `agents/bioshort_watch/memory/2026-05-03_cron_misescalation_issue.md` — CLI default failure mode

**Operator decision (recorded)**:
- APPROVED: B — restore deterministic hedge-report producer only
- NOT APPROVED: bioshort_watch LLM reactivation; selector/ranker/EV/sizing/scoring changes; treating bioshort as alpha evidence; immediate promotion into any live decision path

**Sub-phase ordering is mandatory**:
B0 (stop stale body propagation) **must ship before** B1 (producer restoration). B2 (dashboard freshness) ships independently after B1.

**Amendments recorded 2026-05-06 post-review** (affect §3 and §4 below):
1. B1 cron date expression uses `$(date +\%F)` (ISO calendar date), never bare `$(date)`. Plus preflight: if `data/snapshots/{as_of_date}/portfolio_positions.csv` is missing, fail closed — do **not** fall back to `rankings.csv` stub, do **not** emit a hedge_report.
2. B0 must always write `artifacts/bioshort_watch/latest_status.json` so downstream tools can distinguish "skipped this run" from "never ran". The status doc carries `status`, `upstream_as_of_date`, `upstream_age_days`, `threshold_days`, `consumer_status="suppressed"`.
3. The 9-day freshness threshold is **calendar days**, not trading days. Documented as "one weekly cadence + 2-day weekend/holiday grace".

---

## 1. Goal

Restore `tools/biotech_hedge_report.py` as a weekly deterministic producer of hedge-governance evidence, while:

1. Eliminating the misleading daily-fresh-dated / stale-bodied `artifacts/bioshort_watch/{date}_watch.md` stream that `run_screen.py:12407–12422` currently emits unconditionally.
2. Keeping the `bioshort_watch` LLM agent suppressed.
3. Surfacing upstream freshness honestly in the dashboard.

No scoring change. No selector / ranker / EV / sizing / Module 3 / Module 5 / `decision_engine` touch. No `catalyst_delta_score` change.

---

## 2. Scope summary

| Sub-phase | What it does | Required before next | Risk |
|---|---|---|---|
| **B0** | Gate `build_bioshort_watch` invocation in `run_screen.py` so it skips with explicit status when upstream is stale or absent | yes — must ship before B1 | low (skip-only path; preserves manual invocation) |
| **B1** | Restore producer via weekly Friday cron with explicit `--portfolio-csv`; repair CLI default to fail-closed when no snapshot is discoverable | yes — must ship before B2 | low (producer touches no scoring; rollback = comment out one cron line) |
| **B2** | Dashboard staleness presentation + "suppressed LLM consumer" marker | independent | lowest (read-side only) |

---

## 3. Phase B0 — stale propagation guard in `run_screen.py`

### 3.1 Goal

`run_screen.py` must not produce fresh-dated `artifacts/bioshort_watch/{today}_watch.{json,md}` whose body title carries an upstream `as_of_date` more than `STALE_THRESHOLD_DAYS` old, nor when no upstream `hedge_report_*.json` exists at all.

### 3.2 Site

`run_screen.py:12405–12422`. Current code calls `build_bioshort_watch(as_of_date=args.as_of_date)` unconditionally inside a try/except.

### 3.3 Change

Insert a pre-flight upstream check before the existing call. The check **always** writes `artifacts/bioshort_watch/latest_status.json` (FRESH, STALE, or ORPHANED — single source of truth for downstream readers). Pseudocode:

```python
# --- Bioshort watch (read-only hedge monitor) ---
try:
    from common.bioshort_freshness import check_upstream_freshness, write_status_artifact

    _bw_report_dir = REPO_ROOT / "output" / "hedge_report"
    _bw_artifacts_dir = REPO_ROOT / "artifacts" / "bioshort_watch"
    _bw_freshness = check_upstream_freshness(_bw_report_dir)
    write_status_artifact(_bw_artifacts_dir, _bw_freshness)  # always writes latest_status.json

    if _bw_freshness.status == "ORPHANED":
        logger.info("[BIOSHORT_WATCH] SKIPPED_ORPHANED_UPSTREAM — no hedge_report_*.json")
    elif _bw_freshness.status == "STALE":
        logger.info(
            "[BIOSHORT_WATCH] SKIPPED_STALE_UPSTREAM — latest=%s age=%dd threshold=%dd",
            _bw_freshness.latest_as_of_date, _bw_freshness.age_days, _bw_freshness.threshold_days,
        )
    else:  # FRESH
        from tools.build_bioshort_watch import build_bioshort_watch
        _bw = build_bioshort_watch(as_of_date=args.as_of_date)
        # ... existing log lines unchanged
except Exception as _bw_exc:
    logger.debug("[BIOSHORT_WATCH] skipped: %s", _bw_exc)
```

New helper `common/bioshort_freshness.py` exports:

```python
STALE_THRESHOLD_DAYS = 9  # CALENDAR days; one weekly cadence + 2-day weekend/holiday grace

@dataclass(frozen=True)
class FreshnessResult:
    status: str               # FRESH | STALE | ORPHANED
    latest_as_of_date: str | None  # YYYY-MM-DD or None
    age_days: int | None
    threshold_days: int

def check_upstream_freshness(report_dir: Path, *, threshold_days=STALE_THRESHOLD_DAYS, today=None) -> FreshnessResult: ...
def write_status_artifact(artifacts_dir: Path, result: FreshnessResult) -> Path: ...
```

`latest_status.json` schema:

```json
{
  "status": "FRESH | STALE | ORPHANED",
  "upstream_as_of_date": "YYYY-MM-DD or null",
  "upstream_age_days": 41,
  "threshold_days": 9,
  "consumer_status": "suppressed"
}
```

**Threshold is calendar days, not trading days.** A weekend does not extend the window. `age_days = (today - upstream_as_of_date).days`; `FRESH` iff `age_days <= threshold_days`.

### 3.4 Constraints

- **Skip path is artifact-suppression only.** When SKIPPED, no `_watch.{json,md}` is written for `today`. (Today's filename neither created nor overwritten.)
- **`latest_status.json` is always written.** FRESH, STALE, or ORPHANED — every production run refreshes it. This is the machine-readable signal that distinguishes "skipped this run" from "guard never executed". Atomically written via `tempfile`+`os.replace` (matches existing producer pattern at `tools/biotech_hedge_report.py:2755–2767`).
- **Manual invocation preserved.** `python tools/build_bioshort_watch.py` invoked directly remains unchanged — the gate is in `run_screen.py`, not in the tool.
- **No deletion of historical artifacts.** `artifacts/bioshort_watch/2026-05-04→-06_watch.{json,md}` (the existing stale-body sequence) stays in place as audit trail. A stop-line note may be added (Phase B0 ship date) — preserve, don't sweep.
- **Log lines must be greppable.** Operators inspecting `logs/cron.log` need a stable token (`SKIPPED_ORPHANED_UPSTREAM`, `SKIPPED_STALE_UPSTREAM`) to confirm the guard fires.

### 3.5 Tests

- New test `tests/test_bioshort_freshness_guard.py`:
  - empty / missing `output/hedge_report/` → `ORPHANED`
  - latest report `as_of_date == today` → `FRESH`, `age_days=0`
  - boundary: `as_of_date == today - 9d` → `FRESH` (≤ threshold)
  - one past boundary: `as_of_date == today - 10d` → `STALE`
  - production-state reproduction: `as_of_date=2026-03-26`, `today=2026-05-06` → `STALE`, `age_days=41`
  - calendar-days semantics: weekend does not extend the window
  - `write_status_artifact` writes the documented schema atomically and overwrites prior status
- Existing `test_biotech_hedge_report.py` and bioshort-watch tests continue to pass unchanged.

### 3.6 B0 acceptance

- Day-after-ship `artifacts/bioshort_watch/{today}_watch.md` either does not exist (today, since upstream is currently 41d stale → SKIPPED_STALE_UPSTREAM) or, after B1 ships, reflects the actual fresh upstream.
- `artifacts/bioshort_watch/latest_status.json` exists after every production run; `status="STALE"` and `upstream_age_days≈41` until B1 ships fresh data.
- `cron.log` shows `[BIOSHORT_WATCH] SKIPPED_STALE_UPSTREAM` once per production run until B1 ships fresh data.

---

## 4. Phase B1 — deterministic producer restoration

### 4.1 Goal

Restore `tools/biotech_hedge_report.py` as a scheduled producer with explicit, fail-closed inputs.

### 4.2 CLI default repair (in-tool)

Change `--portfolio-csv` resolution at `tools/biotech_hedge_report.py:2908–2912` (and `load_portfolio_weights` at `:254–319`) to:

1. If `--portfolio-csv` is provided → use it (current behavior).
2. If `--portfolio-csv` is `None` → **auto-discover** the latest `data/snapshots/[0-9]*-*/portfolio_positions.csv`.
3. If no snapshot CSV exists anywhere → **fail closed** with explicit error listing the directories searched. **Do not** fall through to the `rankings.csv` 3-line stub.

This matches the cron-misescalation memo §B Option A (operator-confirmed in this Phase B as the right path).

### 4.3 Cron

Single weekly entry, Friday after production-snapshot completion:

```cron
# Spec 087 B1 — weekly bioshort hedge-report producer (deterministic, no LLM consumer)
0 18 * * 5 cd /mnt/c/Projects/biotech_screener/biotech-screener && source .env 2>/dev/null && /usr/bin/python3 tools/biotech_hedge_report.py --as-of-date $(date +\%F) --portfolio-csv data/snapshots/$(date +\%F)/portfolio_positions.csv >> logs/biotech_hedge_report.log 2>&1
```

- Use `$(date +\%F)` — the ISO calendar date. **Never** bare `$(date)` (cron expands that to a full timestamp with spaces, which would corrupt path arguments).
- `--options-source auto --backtest-mode auto` are the argparse defaults at `tools/biotech_hedge_report.py:2941, 2948`; intentionally omitted to keep the cron line short and greppable.
- Dedicated `logs/biotech_hedge_report.log` (not shared `logs/cron.log`) — operator-confirmed 2026-05-06: this is a newly restored producer; dedicated logging makes first-fire and rollback diagnosis cleaner. The daily B0 freshness token `[BIOSHORT_WATCH] SKIPPED_*` continues to flow into `logs/cron.log` via `cron_daily_production.sh`.

Timing rationale (verify during impl):
- `cron_daily_production.sh` runs `30 16 * * 1-5`; production_qa runs `35 17 * * 1-5`. `0 18 * * 5` runs ≥25 min after Friday QA, leaving Friday's `portfolio_positions.csv` written.
- Producer reads only — does not block any other cron.

`--portfolio-csv` is **passed explicitly even though B1 also adds auto-discovery**. Belt-and-suspenders: cron is unambiguous; tool default is fail-closed for ad-hoc invocation.

### 4.3.1 Preflight (in-tool, fail-closed)

Before the producer does any work, `tools/biotech_hedge_report.py` must verify the resolved `--portfolio-csv` exists. If the path resolves but the file is missing for the as-of date:

- **Fail closed.** Exit non-zero with explicit error: `"portfolio_positions.csv missing for {as_of_date} at {resolved_path}; refusing to emit hedge_report"`.
- **Do not** fall back to the `rankings.csv` 3-line stub (the 2026-05-03 cron-misescalation root cause).
- **Do not** emit a `hedge_report_*.json` for that date.
- **Do not** overwrite `BIOSHORT_VERDICT.json` with stale evidence.

This preflight applies to both explicit (`--portfolio-csv path`) and auto-discovery resolutions.

### 4.4 Constraints

- **Weekly only.** No daily cron. No Mon-Thu producer runs. Ad-hoc manual runs are fine.
- **No LLM consumer wired.** Do not uncomment the suppressed `10 18 * * 5 ... bioshort_watch HEARTBEAT` line. The B0 guard will let `run_screen.py`'s daily deterministic builder pick up Friday's fresh report on Mon-Thu of the following week.
- **Output append-only.** `output/hedge_report/hedge_report_{date}.{json,md}` + `output/hedge_report/archive/hedge_report_{date}.json`. Existing March artifacts preserved unchanged.
- **No retention sweep in B1.** Future spec may add `archive > N weeks` policy; not in scope here.

### 4.5 Tests

Extend `tests/test_biotech_hedge_report.py`. New `TestPortfolioCsvResolution` class — six required cases:

1. **explicit existing path resolves** — `--portfolio-csv /existing/path` → returns that path
2. **explicit missing path fails closed** — `--portfolio-csv /does/not/exist` → `SystemExit`, message names the path
3. **omitted discovers latest snapshot** — no `--portfolio-csv`; `snapshots/2026-05-04`, `-05`, `-06` exist → resolves `2026-05-06/portfolio_positions.csv`
4. **omitted, no snapshots → fails closed** — no `--portfolio-csv`; snapshots root empty → `SystemExit`
5. **never falls back to rankings.csv stub** — sanity: even when `rankings.csv` is present alongside, resolver never looks at it; `SystemExit` when no `portfolio_positions.csv`
6. **explicit same-date missing fails closed** (cron regression) — `as_of_date=2026-05-07`, `snapshots/2026-05-06/portfolio_positions.csv` exists, `snapshots/2026-05-07/portfolio_positions.csv` missing, explicit `--portfolio-csv data/snapshots/2026-05-07/portfolio_positions.csv` → `SystemExit`. **Must not** silently fall through to `2026-05-06`. This protects the Friday cron case: Friday must fail (and log loudly) if Friday's portfolio file is missing — not silently emit a hedge report against Thursday's book.

Plus one regression test for `load_portfolio_weights`:

- **unknown columns fail closed** — portfolio CSV has only a `ticker` column, no `weight` / `market_value` / `target_weight_pct` → `SystemExit`, message lists the expected column names.

Existing tests requiring change in `tests/test_biotech_hedge_report.py`:

| Test (current line) | Action |
|---|---|
| `TestFallbackBehavior.test_fallback_to_rankings` (319) | DELETE — rankings.csv portfolio fallback is removed |
| `TestFallbackBehavior.test_fallback_no_data` (327) | REWRITE — assert `pytest.raises(SystemExit)` against missing portfolio path |
| `TestFallbackBehavior.test_portfolio_csv_with_weight` (332) | UPDATE signature — drop the `None` second arg |
| `TestFallbackBehavior` class name | RENAME → `TestPortfolioWeightsLoading` (no fallback semantics anymore) |

All other producer tests (60+) continue unchanged — none depend on the removed rankings.csv portfolio fallback.

### 4.6 B1 acceptance

- First Friday post-ship: `output/hedge_report/hedge_report_{friday}.json` exists, mtime ≈ Friday 18:00 ET.
- `BIOSHORT_VERDICT.{json,md}` regenerated with current `as_of_date`.
- Following Monday's `cron_daily_production.sh`: `[BIOSHORT_WATCH] FRESH` in log; `artifacts/bioshort_watch/{monday}_watch.md` body title shows that Friday's date, not 2026-03-26.
- `crontab -l | grep -E 'bioshort_watch.*HEARTBEAT' | grep -v '^#'` → empty.
- `crontab -l | grep biotech_hedge_report | grep -v '^#'` → exactly one weekly entry.

---

## 5. Phase B2 — dashboard / consumer hygiene

### 5.1 Goal

Dashboard endpoints must surface upstream freshness so consumers (operator, IC, anyone manually invoking) cannot mistake a stale or orphaned hedge report for live signal.

### 5.2 Sites

`dashboard/app.py:693–735` — four endpoints:
- `/api/bioshort/verdict`
- `/api/bioshort/report`
- `/api/bioshort/watch`
- `/api/bioshort/archive`

Plus the frontend panels that consume them (verify during impl; likely under `frontend/` or `dashboard/templates/`).

### 5.3 Changes

1. Each endpoint response wraps the underlying payload in:
   ```json
   {
     "as_of_date": "<from payload>",
     "freshness": "FRESH|STALE|ORPHANED",
     "age_days": <int>,
     "consumer_status": "deterministic_producer_only_llm_suppressed",
     "data": { ...original payload... }
   }
   ```
2. `freshness` computed via the same `common/bioshort_freshness.py` helper used in B0 — single source of truth for the staleness threshold.
3. Frontend bioshort panels: when `freshness != "FRESH"`, prepend a banner: `"Hedge report is N days old (last fresh: YYYY-MM-DD). Deterministic producer only — LLM consumer suppressed."`

### 5.4 Constraints

- **No implication that hedge report is live alpha.** Banner copy must say "IC-discussion evidence" or "hedge-governance evidence", not "signal" or "alpha".
- **No hiding stale state behind generated timestamps.** Display `as_of_date` (the data's own date), not `generated_at` (when the file was written).
- **Read-side only.** No producer change. No `output/hedge_report/` mutation.

### 5.5 Tests

- `tests/test_dashboard_bioshort_endpoints.py`:
  - mock `output/hedge_report/` empty → `freshness=ORPHANED`, `age_days=null`
  - mock 5 days old → `freshness=FRESH` (≤9d), `age_days=5`
  - mock 12 days old → `freshness=STALE`, `age_days=12`
  - all four endpoints return the wrapper structure consistently

### 5.6 B2 acceptance

- All four endpoints return `{as_of_date, freshness, age_days, consumer_status, data}` envelope.
- Frontend banner visible in browser when STALE/ORPHANED.

---

## 6. Out of scope (explicit)

| Item | Reason |
|---|---|
| `bioshort_watch` LLM agent reactivation | Operator NOT APPROVED. Cron stays commented; `SUPPRESSED_AGENTS["bioshort_watch"]` stays. B → C reactivation question deferred to a separate spec after 2–4 weeks of fresh reports. |
| Selector / ranker / EV / sizing / scoring changes | Phase A confirmed empty production-scoring dependency. Producer is read-only against `rankings.csv`. |
| Module 3 / Module 5 / `decision_engine` / `catalyst_delta_score` | None of these consume hedge_report. No file in those paths modified. |
| `event_ev/` / `common/ranker_active_contract.py` | Same — empty. |
| Bioshort-as-alpha research | Carved off as Spec 087C (§9). Not in scope for B0/B1/B2. |
| Retention sweep on `output/hedge_report/` | Future spec; B1 leaves files append-only. |
| Massive vs Tasty options-source policy change | Phase A noted Tasty absent today, Massive available. `--options-source auto` handles it. If `MASSIVE_API_KEY` proves unreliable in B1's first runs, file a follow-up — not a B1 blocker. |

---

## 7. Commit / smoke gate criteria

Before any commit lands on `origin/main`:

| # | Check | How verified |
|---|---|---|
| 1 | No `bioshort_watch` LLM cron reactivated | `crontab -l \| grep -E 'bioshort_watch.*HEARTBEAT' \| grep -v '^#'` returns empty |
| 2 | Producer cron is weekly only | `crontab -l \| grep biotech_hedge_report \| grep -v '^#'` returns exactly one line, day-of-week is `5` |
| 3 | Explicit `--portfolio-csv` is used | the cron line from #2 contains `--portfolio-csv data/snapshots/` |
| 4 | `run_screen` no longer emits fresh-dated stale bioshort_watch bodies | dry-run `run_screen.py` against current state → log contains `SKIPPED_STALE_UPSTREAM` (or `_ORPHANED_UPSTREAM`); no new `artifacts/bioshort_watch/{today}_watch.md` written |
| 5 | Dashboard read paths show hedge_report `as_of_date` | hit `/api/bioshort/verdict` and `/api/bioshort/report` → response includes `as_of_date`, `freshness`, `age_days`, `consumer_status` |
| 6 | `rankings.csv` row-hash unchanged | `tools/verify_snapshot_integrity.py` against pre/post; rankings hash byte-equal |
| 7 | No alpha-stack file changed | `git diff --name-only origin/main` does not touch `module_3*.py`, `module_4*.py`, `module_5*.py`, `ranker_*.py`, `selector_engine.py`, `decision_engine.py`, `event_ev/`, `common/ranker_active_contract.py`, `pos_*.py` |
| 8 | Test suite green | `pytest tests/test_bioshort_freshness_guard.py tests/test_biotech_hedge_report*.py tests/test_dashboard_bioshort_endpoints.py` all pass; full suite has no new failures |

Gates 1–4 protect against the most likely silent regressions (LLM reactivation, daily producer, stub fallback, stale body propagation surviving B0). Gate 7 enforces the "no scoring touched" boundary mechanically.

---

## 8. Rollback path

| Scenario | Rollback step |
|---|---|
| B0 guard misfires (false `SKIPPED_STALE_UPSTREAM` despite fresh upstream) | revert the `run_screen.py:12405–12422` change; B0 helper file becomes orphaned but harmless |
| B1 producer fails on first Friday | comment out the cron line; no state to clean up — `output/hedge_report/` is append-only |
| B1 producer writes corrupted output | delete that day's `hedge_report_{date}.{json,md}` and `archive/hedge_report_{date}.json` only; prior reports untouched |
| B2 dashboard envelope breaks frontend | revert `dashboard/app.py` endpoint changes; frontend reverts to current behavior (which is "display stale data without warning" — equivalent to current state) |
| Any of B0/B1/B2 needs to be unwound entirely | each sub-phase is one commit; revert in reverse order |

No DB migration, no scoring state, no model-artifact dependency. Rollback is git revert + `crontab -e`.

---

## 9. Forward link — Spec 087C (separate, later)

```
Spec 087C — Bioshort shadow-alpha viability study

Status: NOT STARTED. Hard-gated on B1 producing ≥4 fresh weekly reports.

Question:
Is there evidence that the deterministic hedge-report verdict / structure
delta has any forward predictive content for the long biotech book?

Inputs:
- ≥4 fresh weekly hedge_report time series from B1 (minimum 2026-05 through
  2026-06)
- optional: historical reconstruction from price_history.csv if methodology
  is PIT-honest

Allowed:
- shadow IC computation
- attribution-only analysis
- per-snapshot, not cross-snapshot, comparisons

Not allowed:
- selector/ranker integration
- sizing tilt
- promotion path of any kind
- treating shadow IC as Checklist v2 evidence (would require independent
  forward-shadow protocol)

Out of scope:
- alpha promotion (frozen architecture, Spec 086)
- combination with coinvest / inst_delta / financial_score
```

087C is **not** Phase B; it is a separate later spec to prevent scope creep and the EES-style mistake of tying alpha investigation to infrastructure restoration.

---

## 10. Implementation order — strict

1. **B0 ships first.** Land the `run_screen.py` guard + `common/bioshort_freshness.py` + tests. Verify gate criteria #4 in production for one Mon–Thu cycle (4 cron runs) showing `SKIPPED_STALE_UPSTREAM` consistently.
2. **B1 ships second.** Land the producer cron + CLI default repair + tests. Verify gates #1–#3 immediately; verify on the first Friday post-ship that `output/hedge_report/hedge_report_{friday}.json` is written.
3. **B2 ships third.** Land dashboard envelope + frontend banner + tests. Verify gate #5 against live dashboard.
4. **Observe 2–4 weeks** of B0+B1+B2 in production before considering Spec 087C.

Each sub-phase is a separate commit. Each sub-phase has its own gate-criteria check before merge.

---

## 11. Operator action requested

Review this draft. On approval, I will:

1. Implement B0 only as the first commit, with tests.
2. Wait for one Mon–Thu cycle of `cron.log` showing `SKIPPED_STALE_UPSTREAM`.
3. Then implement B1, then B2, sequenced as above.

No execution starts until this spec is approved.

---

_Draft 2026-05-06 per operator confirmation of Disposition B with B0/B1/B2 split. No code, cron, or artifact changes made beyond writing this spec file and the Phase A memo._
