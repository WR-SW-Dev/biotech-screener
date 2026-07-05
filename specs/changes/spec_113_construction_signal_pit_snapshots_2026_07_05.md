# Spec 113 — PIT Snapshotting of Construction Output + Coinvest Signal

**Status:** DRAFT — SPEC / MEMO ONLY. No code changes. No model / ranker / selector / scorer / sizing changes. No cron edits. No production mutation. Defines an *instrumentation* (data-capture) change and the acceptance gate any implementation must pass. Requires explicit operator approval to move DRAFT -> IN PROGRESS.

**Proposed number:** 113 (next free after spec_112; confirm before merge).
**Date:** 2026-07-05
**Author:** Town assistant (Warrenpoobear), on operator request.
**Priority:** Governance / instrumentation. No production runtime impact. Not an alpha change.

**Origin:** YTD acquisitions review (2026-07-05). An attempt to compute a portfolio-level takeout hit rate for six model-relevant 2026 takeouts (ACLX, CNTA, APLS, KALV, NUVL, APGE) failed because the repo retains no per-run construction or ranking history — only a single 2026-06-10 top-15 plan (`artifacts/trading/robinhood_top15_plan_2026-06-10.json`, commit `fed64cd8`) and a single as-of 2026-05-22 coinvest signal file (`production_data/coinvest_signals.json`) exist. PIT membership as-of each announcement date is therefore unreconstructable. Companion analysis: Town docs "Biotech Model Acquisitions — Logged YTD 2026" and "Watchlist Rate + Top-60 Conviction Check."

## 1. Problem
- The production run computes a full ranked construction (B6 coinvest-only selector v1.14.0 -> pairwise_minimal ranker -> EW Top-30 construction) but only the truncated top-15 pick list is ever persisted, and only for a single date.
- `coinvest_signals.json` is overwritten on each refresh (single as-of snapshot), so the signal state that drove any given run is lost.
- Consequence: no PIT-safe way to measure forward outcomes (takeout hit rate, premium capture, IC on the actual constructed book), because neither the ranking nor its input signal is versioned per run.
- This is the same class of gap the CT.gov archiver (`archive_daily_snapshot.py`) already solved for trial data: build our own history because the source only exposes current state.

## 2. Goal / Non-goals
**Goal:** Persist, per production run, an immutable PIT snapshot of (a) the full ranked construction output and (b) the coinvest signal used, so forward evaluation (next quarter onward) is reconstructable.

**Non-goals:** No change to how anything is scored, ranked, selected, gated, or sized. No change to the live book. No backfill of pre-existing runs — they cannot be reconstructed; accept the gap and start history at first-fire.

## 3. Proposed change (instrumentation only)
Write two artifacts into the existing per-run snapshot dir `data/snapshots/<as_of_date>/` (which already houses `run_manifest.json` and `cohort_state.json`), and extend the manifest:

1. `construction_snapshot.json` — the FULL ranked table the engine already produces (not truncated to top-15/30). One row per eligible name.
2. `coinvest_signal_snapshot.json` — the coinvest signal record used for the run (copy of the as-of `coinvest_signals.json`, or a `{ref, sha256}` pointer when byte-identical to the committed file).
3. Extend `run_manifest.json` with pointers, record counts, and SHA256 for each artifact.

Mirror `archive_daily_snapshot.py` conventions: `as_of_date` required (no `datetime.now()` default), immutable (never overwrite an existing dated snapshot), deterministic (sorted keys, canonical JSON), SHA256 verification, manifest updated.

### 3.1 `construction_snapshot.json` schema (v1)
```
{
  "schema_version": "construction_snapshot.v1",
  "as_of_date": "YYYY-MM-DD",
  "run_id": "<existing run id>",
  "ruleset_version": "v1.14.0",
  "selector": "B6_coinvest_only",
  "ranker": "pairwise_minimal",
  "construction": "EW_Top30",
  "universe_count": <int>,
  "eligible_count": <int>,
  "rows": [
    {
      "ticker": "STR",
      "rank": <int>,                              // full dense rank 1..N (not truncated)
      "in_top_k": {"top15": bool, "top30": bool, "top60": bool},
      "composite_score": <num>,                   // whatever the engine already emits; do NOT invent
      "decision_tier": "A|B|C",
      "gates_passed": [...],
      "gates_failed": [...],
      "catalyst_days": <int|null>,
      "target_weight": <num|null>,                // construction weight if produced
      "coinvest_holders": [...],                  // as used by the run
      "reason": "..."                             // existing reason string
    }
  ]
}
```
Every field must be exactly what the construction engine already computes — the snapshot *serializes existing state*, it does not derive anything new. The `top60` flag aligns with the existing top-60 evaluation scope (spec_095).

### 3.2 `coinvest_signal_snapshot.json`
Copy of the `coinvest_signals.json` object as-of the run (same `coinvest_features.v1` schema), OR `{"ref": "production_data/coinvest_signals.json", "sha256": "..."}` when byte-identical to the committed file, to avoid duplication.

## 4. Hook point
The construction/plan generator that writes `artifacts/trading/robinhood_top*_plan_<date>.json` (documented in `docs/TRADING_READINESS.md` / `docs/ROBINHOOD_TRADING_GUIDE.md`) already holds the full ranked list in memory before truncating to top-15. Add a single serialization call there — or a thin post-run archiver invoked by the daily pipeline — to emit the two artifacts + manifest entry. No change to the ranking that precedes it.

## 5. Governance
- **Classification:** data capture / instrumentation. Read-only w.r.t. all model logic. Does not touch `decision_engine.py`, ranker models, `portfolio_policy.json`, or any scorer.
- **Freeze compliance:** consistent with the v1.14.0 freeze (no ruleset change).
- **Fail policy:** a snapshot-write failure logs WARN and is surfaced in the EOD health check; it must NOT block or alter the run (fail-open on instrumentation, but alert). Determinism + immutability enforced as in the CT.gov archiver.
- **Retention:** immutable dated dirs; no pruning without a separate spec.
- **Relationship to existing specs:** complements spec_110 (pipeline provenance graph) and spec_112 (Phase-2 daily monitoring automation); consumes the top-60 scope from spec_095. Supersedes none.

## 6. Acceptance criteria
1. A daily run produces `data/snapshots/<date>/construction_snapshot.json` + `coinvest_signal_snapshot.json`, with `run_manifest.json` updated (counts + SHA256).
2. Re-running the same `as_of_date` does NOT overwrite (immutability check).
3. `construction_snapshot.rows` length == engine's `eligible_count`; ranks are dense 1..N; `in_top_k` flags are consistent with `rank`.
4. Byte-for-byte determinism across two dry-runs on identical inputs (hash match).
5. No diff in any model / ranker / scorer output vs. a pre-change run (instrumentation-only proof).
6. A read-only reconstruction script can, given a date, list the constructed top-K and the signal that drove it.

## 7. Rollout
- **Phase A (shadow):** emit artifacts for N daily runs; verify schema / immutability / determinism. No consumer.
- **Phase B (evaluation):** after ~one quarter of accumulated snapshots, build a read-only forward takeout-hit-rate + premium-capture report keyed off `corporate_actions.json` effective dates vs. construction membership at the pre-announcement snapshot. This is the report that answers "what is the true portfolio-level takeout rate" with real PIT data instead of today's proxies.

## 8. Out of scope
- Reconstructing pre-2026-07 history (not possible; accept the gap).
- Any change to selection / ranking / sizing.
- Wiring the Phase-B evaluation report (separate spec once data exists).

## Held Ledger Disposition
- **Proposed:** add as `[DRAFT] Spec 113 — construction + coinvest PIT snapshots` (instrumentation; no runtime impact). Move DRAFT -> IN PROGRESS only on explicit operator approval. No first-fire scheduled until approved.
