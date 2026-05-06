# P0 #2 Step B — `ruleset_health_monitor.py` stale-baseline reader bug (2026-05-06)

**Status:** Read-only investigation per user direction (Step B before Step A). **No code, ruleset, manifest, or sentinel-memory changes implemented.** Fix proposal at §6 — implementation gated on user approval.

**Headline:** Sentinel's 2026-05-05 17:15 ET memory file reports active ruleset `bebe73f8` (v1.10.0) because **two compounding bugs** in the receipt-based monitor produce a 7+ week stale answer regardless of the live manifest. The fix is a narrow one-function change in `tools/ruleset_health_monitor.py`. No scoring impact.

---

## 1. Why sentinel's 2026-05-05 memory says `bebe73f8`

`agents/sentinel/SOUL.md:28` directs the sentinel agent to run `tools/ruleset_health_monitor.py`. `agents/sentinel/TOOLS.md:7` shows the canonical invocation:

```
python3 tools/ruleset_health_monitor.py --as-of-date YYYY-MM-DD
```

No `--active-ruleset-id` is passed. The script's CLI default for that flag is `None` (`tools/ruleset_health_monitor.py:334-337`). With no override, the script falls back to `_find_active_receipt(receipts_dir, None)` which scans `artifacts/promotions/` and returns "the most recent receipt by filename sort" (line 62 docstring; lines 67–82 implementation).

Output of the monitor is what sentinel writes verbatim into its memory header. So whatever `_find_active_receipt` returns, sentinel reports.

---

## 2. What's actually in `artifacts/promotions/`

```
artifacts/promotions/
├── bebe73f8_flatten_tier_91_180/        (subdir, March 9)
├── promotion_2026-02-27_cand1.json
├── promotion_2026-02-27_retired1.json
├── promotion_2026-03-01_e549e067.json
├── promotion_2026-03-02_873e65e0.json
├── promotion_2026-03-02_fb0af0ac.json
├── promotion_2026-03-03_4f12a7f8.json
├── promotion_2026-03-03_82982998.json
├── promotion_2026-03-06_e966af9d.json
├── promotion_2026-03-09_bebe73f8.json
├── promotion_2026-03-09_ddf59b03.json
├── promotion_2026-03-10_7177a4ea.json
├── promotion_2026-03-10_9f1f4587.json
└── rollback_2026-03-09_bebe73f8.json
```

**Most recent receipt is from 2026-03-10.** No receipt was written for the 2026-05-04 v1.14.0 promotion (id `8887576e`) or for the prior 2026-04-06 v1.13.0 promotion (id `2a3e79eb`). The receipt directory is **8 weeks stale**.

---

## 3. Bug 1 — sort precedence

`_find_active_receipt` (lines 67–71):

```python
candidates = sorted(receipts_dir.glob("promotion_*.json"), reverse=True)
candidates.extend(sorted(receipts_dir.glob("rollback_*.json"), reverse=True))
candidates.sort(key=lambda p: p.name, reverse=True)   # re-sort all by name desc
```

After the re-sort by filename descending, **rollback files always win same-date ties** because `'r' > 'p'` lexicographically. Worse: in the current state of `artifacts/promotions/`, the alphabetic re-sort across the whole list places `rollback_2026-03-09_bebe73f8.json` BEFORE `promotion_2026-03-10_*.json` if both contained "rollback" or "promotion" prefixes — actually let me be precise: the full re-sort by name desc gives:

```
rollback_2026-03-09_bebe73f8.json    ← winner (r > p)
promotion_2026-03-10_9f1f4587.json
promotion_2026-03-10_7177a4ea.json
promotion_2026-03-09_ddf59b03.json
promotion_2026-03-09_bebe73f8.json
...
```

So the function returns the **rollback** for `bebe73f8` (March 9, 2026). Verified by simulation:

```python
>>> _find_active_receipt(Path('artifacts/promotions'), None)
{'new_active_id': 'bebe73f8', 'created_at_utc': '2026-03-09', ...}
```

---

## 4. Bug 2 — missing recent receipts

Even if the sort were fixed, the most recent receipt is for `9f1f4587` (March 10) — also wrong. The receipt source is **fundamentally out of date** because the 2026-05-04 v1.14.0 promotion (canonical hash `8887576e`) did NOT write a receipt to `artifacts/promotions/`.

The receipt-writer is `scripts/promote_ruleset.py:263` (writes `"new_active_id": new_active_id` into JSON). Either this script wasn't used for the 2026-05-04 promotion, OR it was used but the output went elsewhere. Looking at the rotation commits (`26dd60744 → 28b86b22a → c34e600d3 → 980c02b55 → bd91b523d`), the manifest was updated by `980c02b55` "fix(manifest): register 622edb77 (v1.14.0) and retire 2a3e79eb (v1.13.0)" — a `fix(manifest)` commit, suggesting manual edits, not the standard `promote_ruleset.py` flow.

Whether to backfill receipts for `2a3e79eb` and `8887576e` is a process question. The fix below makes the monitor robust regardless.

Verified by simulation:

```python
>>> _find_active_receipt(Path('artifacts/promotions'), '8887576e')
None    ← no receipt exists for canonical 8887576e
```

---

## 5. Other consumers of the same source

| Consumer | Behavior | Risk |
|---|---|---|
| `tools/run_daily_production.py:check_ruleset_health` (line 1555) | Calls `run_health_check(...)` with `active_ruleset_id=None`, `receipts_dir=artifacts/promotions/` (defaults). Invoked from `_safe_gate("ruleset_health", check_ruleset_health, staging_date_dir)` at line 4585 — no override. **Same bug** — daily production drift gate evaluates against `bebe73f8` baseline. | High — affects every daily run's ruleset_health gate. |
| `tools/weekly_health_packet.py:300` | Reads `ruleset_health.get("active_ruleset_id", "unknown")` — consumes the OUTPUT of `ruleset_health_monitor.py`. Downstream of the bug. Will report `bebe73f8` weekly. | Medium — wrong ID in weekly health reports. |
| `tools/build_ops_digest.py:607` | `if rd.get("new_active_id") == ruleset_id` — requires caller to pass an explicit `ruleset_id` for filtering. Looking at the surrounding context would tell us whether the caller passes the canonical id; quick read suggests it does (file is large; needs deeper inspection). | Likely low. |
| `agents/sentinel` (LLM agent) | Reads tool output verbatim into memory. | Symptom-level, not source. |

The bug propagates from the monitor to: sentinel memory, daily ruleset_health gate, weekly health packet. **All three reports an 8-week-stale ruleset id.**

The bug does NOT propagate to: scoring (`run_screen.py`, `module_*`, ranker, EV), manifest, snapshot stamping (rankings.csv `decision_engine_ruleset_id` column is correctly `8887576e`).

---

## 6. Minimal fix proposal (NOT IMPLEMENTED — pending approval)

Two separable changes. Recommend doing both; either alone is incomplete.

### Fix 1 — `_find_active_receipt` reads manifest as source of truth when no id provided

Replace the lexicographic-sort fallback with a manifest-aware fallback. New behavior:

```python
def _find_active_receipt(receipts_dir, active_ruleset_id=None, manifest_path=None):
    if active_ruleset_id is None and manifest_path is not None:
        # Auto-detect canonical from manifest (status="active")
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            active = next((r["id"] for r in manifest.get("rulesets", [])
                           if r.get("status") == "active"), None)
            if active:
                active_ruleset_id = active
        except (json.JSONDecodeError, OSError):
            pass
    # ... existing receipt-glob loop ...
    # If active_ruleset_id is set but no receipt matches → return a stub
    # indicating the canonical id is known but the receipt is missing
    # (so callers can still report the right id without crashing).
```

**Behavior change:**
- When called without explicit id AND with `manifest_path` arg → reads manifest, returns receipt for canonical id, OR a stub `{"new_active_id": <canonical>, "missing_receipt": True}` if no receipt exists.
- When called explicitly with id → unchanged.
- When called without id AND without manifest_path → unchanged (preserves old behavior for callers we don't know about).

### Fix 2 — wire the manifest path through callers

- `tools/ruleset_health_monitor.py:main()` — add `--manifest-path` CLI arg, default `production_data/decision_rulesets/manifest.json`, pass through to `_find_active_receipt` and `run_health_check`.
- `tools/run_daily_production.py:check_ruleset_health` (line 1555) — add `manifest_path` parameter, default to the standard location, pass through.
- `agents/sentinel/TOOLS.md:7` — update the example CLI to mention the new auto-detection (no flag change required since it's a default).

### What this does NOT fix

- The missing receipts for `2a3e79eb` and `8887576e` — that's a separate hygiene concern. After the manifest fallback, the monitor will report the canonical id correctly, but `gate` baseline metrics (top60_overlap, max_rank_shift, mean_turnover) will be `None` because no receipt has them. The `evaluate_health` function (line 138) already handles `not receipt` as cold-start PASS — extending the stub-receipt path to "PASS, baseline missing, recommend backfilling receipt" would be a small additional change.

### Risks

- **None to scoring.** Monitor is read-only diagnostic.
- **Drift-detection regression risk:** if the new path returns a stub receipt without baseline metrics, the existing `evaluate_health` logic that compares today's drift against baseline will not flag drift. **This is actually the current behavior already (since the receipt is stale by 8 weeks, the baseline metrics are meaningless).** Net: equivalent or better.
- **Behavior change for existing CI / tests:** `tests/test_acceptance_replay_ruleset.py` and `tests/test_pre_trade_ruleset_gate.py` use `bebe73f8` as fixture — those are isolated test data, not affected.

---

## 7. Tests / smoke (after Fix 1+2 land)

```bash
# Sentinel-style invocation, expect 8887576e
python3 tools/ruleset_health_monitor.py --as-of-date 2026-05-06
# Expect output: active_ruleset_id="8887576e"

# Explicit id override still works
python3 tools/ruleset_health_monitor.py --as-of-date 2026-05-06 --active-ruleset-id 2a3e79eb
# Expect output: active_ruleset_id="2a3e79eb" (returns receipt or stub)

# Sentinel agent re-run (after the tool fix)
# Expect agents/sentinel/memory/<today>.md to header "Active ruleset: 8887576e (v1.14.0, ...)"
```

**Snapshot row-hash invariance:** rerun `tools/build_rank_change_monitor.py` against `data/snapshots/2026-05-06/` pre/post — row hashes must be byte-identical (this fix is read-only diagnostic; cannot move scores).

---

## 8. Before / after expected sentinel output

**Before (current 2026-05-05 sentinel memory):**
```
**Active ruleset**: bebe73f8 (v1.10.0, promoted 2026-03-09)
**Days since promotion**: 57 days
```

**After (next sentinel run post-fix):**
```
**Active ruleset**: 8887576e (v1.14.0, promoted 2026-05-04)
**Days since promotion**: <today minus promotion date>
**Note**: baseline metrics unavailable — no promotion receipt for 8887576e in artifacts/promotions/. Recommend backfilling.
```

---

## 9. Rollback path

Each fix is a single-file change:
- Fix 1: `tools/ruleset_health_monitor.py` — `git revert <commit>`.
- Fix 2: `tools/ruleset_health_monitor.py` (CLI flag) + `tools/run_daily_production.py` (param plumb-through) — same `git revert`.

If reverted, monitor returns to current (broken) behavior; no scoring/state damage.

---

## 10. Open questions for human review

1. **Backfill missing receipts?** Writing `promotion_2026-04-06_2a3e79eb.json` and `promotion_2026-05-04_8887576e.json` would restore monitor data fidelity. But synthetic baselines (since the original promotion runs are not reproducible) might be misleading. Skip-and-log seems safer.
2. **Why didn't `scripts/promote_ruleset.py` run for the 2026-05-04 promotion?** The `fix(manifest)` commit suggests manual edit. Worth confirming whether the standard promotion process should be enforced going forward — separate from this fix.
3. **Sentinel-memory cleanup:** do NOT auto-edit `agents/sentinel/memory/2026-05-05.md`. Once the reader fix lands, the next sentinel run will write a correct memory file. The historical 2026-05-05 file documents what was reported on that date — leave as evidence.

---

_Generated by P0 #2 Step B read-only investigation. Fix proposal awaits user approval._
