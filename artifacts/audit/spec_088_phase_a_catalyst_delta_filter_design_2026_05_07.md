# Spec 088 Phase A — `catalyst_delta` Artifact-Level Filter Design Memo

**Date**: 2026-05-07
**Phase**: A (read-only design)
**Status**: design only; **no code, cron, or artifact mutation**
**Concurrent context**: Spec 087 bioshort wrapper running as `bk0rrr57y`; Phase A scope explicitly excludes any bioshort, scoring, or production touch

## Bottom line

**Disposition recommendation: Option B — filtered companion artifact (raw+filtered dual-output).** Phase B should add `{date}_delta_filtered.json` alongside the existing `{date}_delta.json`, leave the raw artifact byte-identical, and allow consumers to opt in. Avoids the forensic loss of Option C (destructive filter) while solving the noise problem.

---

## 1. Where catalyst_delta artifacts are produced

| Field | Value |
|---|---|
| Producer | `tools/build_catalyst_delta.py` (486 lines, 17 KB, mtime 2026-04-09) |
| Entry function | `build_catalyst_delta(as_of_date, *, prior_date=None, snapshots_dir, artifacts_dir)` |
| Schema version | `catalyst_delta.v1` |
| Outputs | `artifacts/catalyst_delta/{date}_delta.json` and `{date}_delta.md` |
| Invocation | inside `run_screen.py` daily; CLI shipped (`--as-of-date`, `--prior-date`, `--snapshots-dir`, `--artifacts-dir`) |
| Read-only inputs | `data/snapshots/{date}/rankings.csv` and `{prior_date}/rankings.csv`; `artifacts/live_shadow/positions/{date}.json`; `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv`; `artifacts/ctgov_daily/{date}_diff.json` (if present) |
| Producer-side scoring touch | NONE — never writes to rankings, never modifies `catalyst_delta_score` (that's Module 3's separate computation, see §3) |

Today's artifact: `artifacts/catalyst_delta/2026-05-07_delta.json` exists, mtime 2026-05-07 08:41 (generated mid-wrapper-run).

## 2. Artifact schema (`catalyst_delta.v1`)

Top-level keys (verified against producer source at `build_catalyst_delta.py:358–375`):

```json
{
  "schema": "catalyst_delta.v1",
  "as_of_date": "YYYY-MM-DD",
  "prior_date": "YYYY-MM-DD",
  "generated_at": "ISO-8601 UTC",
  "n_raw_changes": <int>,         // pre-noise-filter count
  "n_filtered": <int>,             // post-noise-filter count = len(deltas)
  "n_noise_suppressed": <int>,     // n_raw_changes - n_filtered
  "code_counts": { "<CODE>": <int>, ... },
  "context": {
    "n_current_tickers": <int>,
    "n_prior_tickers": <int>,
    "n_positions": <int>,
    "n_trade_plan": <int>,
    "n_ctgov_merged": <int>
  },
  "deltas": [ { ...per-ticker change... } ]
}
```

Per-`deltas[]` row fields (varies by code path; minimum guarantee `ticker` + `codes[]`):

| Field | Always present | Notes |
|---|---|---|
| `ticker` | yes | upper-case |
| `codes[]` | yes | one or more of: `NEW_ENTRANT`, `EXITED`, `DATE_PUSHED_BACK`, `DATE_PULLED_FORWARD`, `DATE_SHIFTED`, `FAMILY_CHANGED`, `SOURCE_CHANGED`, `EVENT_TYPE_CHANGED`, `BECAME_HARD`, `BECAME_SOFT`, `EVENT_RESOLVED`, `NEW_EVENT_APPEARED`, `EVENT_BECAME_FAR`, `MODE_CHANGED`, plus `CTGOV_*` prefixed variants merged from CTgov daily diff |
| `tier` | most | from `tier_dev`; missing if EXITED-only |
| `rank` | most | from `actionable_rank`; missing if EXITED-only |
| `catalyst_days` | most | string, may be empty/NaN |
| `catalyst_family` | most | one of `REGULATORY`, `CLINICAL`, `IR_EVENTS`, `CONFERENCE`, others |
| `prior_*` / `current_*` | conditional | populated only when the corresponding field changed (e.g., `prior_family`/`current_family` only present when `FAMILY_CHANGED`) |
| `nct_id`, `trial_detail` | conditional | only present for CTgov-merged rows |

**Existing producer-side noise filter** (`passes_noise_filter`, lines 216–243) — already running, OR-logic:
- tier ∈ {A, B}, OR
- `catalyst_days ≤ 30`, OR
- `FAMILY_CHANGED` in codes, OR
- ticker in shadow positions or trade plan

So the artifact today is **already noise-filtered at the producer level**. The filter Spec 088 proposes is a **second, tighter filter** layered on top.

## 3. Downstream consumers

Three classes of consumer, with **production scoring confirmed independent**:

### 3.1 Artifact-file consumers (read `*_delta.json`)

| Consumer | Site | What it reads | Use |
|---|---|---|---|
| `tools/build_options_watch.py` | line 355–367 | `cd_data["deltas"][].ticker` → `catalyst_delta_tickers: Set[str]` | passes set into `_build_candidate_set()`; ticker membership in this set is one of several reasons to flag a name for options coverage (line 158) |
| `agents/catalyst_delta/` LLM agent | reads `{prior_date}_delta.json` per `TOOLS.md` | full delta JSON | "carried-over detection" — comparing today's events against what was surfaced yesterday |
| `agents/options_watch/` LLM agent | reads `{date}_delta.json` per `TOOLS.md` | full delta JSON | "names with event changes today" |
| `agents/intraday_mover_watch/`, `agents/price_action_watch/`, `agents/grok_biotech_watch/` LLM agents | per their `TOOLS.md` / `SOUL.md` | full delta JSON or just ticker list | event-context reference for narrative |

### 3.2 NOT consumers despite grep matches

`module_3_schema.py`, `module_3_schema_v2.py`, `module_3_scoring.py`, `module_3_scoring_v2.py`, `module_5_composite.py`, `module_5_composite_v2.py`, `module_5_scoring_v3.py` — all reference the field name `catalyst_delta_score`, which is a **numerical Module 3 score**, computed inline from raw catalyst comparison. **It does NOT read the artifact JSON.** The score and the artifact are independent code paths.

Verified by grep: zero references to `artifacts/catalyst_delta/` or `_delta.json` in any module_3/module_5/ranker/selector/decision_engine file.

**Implication for Phase B**: artifact-level filter changes do not touch `catalyst_delta_score`, Module 3 / Module 5 output, ranker/selector/EV/sizing. The "no scoring touched" boundary holds mechanically.

### 3.3 Specs / docs / agent definition files

Pure references in `specs/changes/`, `docs/`, `agents/*/AGENTS.md`. No read-side dependency on artifact content.

## 4. Is raw+filtered dual-output feasible?

**Yes, low-risk.** The producer already has a clean separation between the change classifier (`classify_change`, lines 105–210) and the surfacing/filter (`passes_noise_filter`, lines 216–243). A second filter pass operating on the already-emitted `result["deltas"]` would:

- Read no new inputs
- Produce a parallel `{date}_delta_filtered.json` with the same schema but `deltas[]` further pruned and a `n_filtered_v2`/`n_v2_suppressed` count for visibility
- Leave `{date}_delta.json` byte-identical to today's behavior
- Add ~30 lines to the producer + a Markdown twin if symmetry is wanted

No state change, no schema break for existing consumers. `build_options_watch.py` continues reading `{date}_delta.json` until/unless explicitly re-pointed in a separate Phase C ticket.

## 5. Candidate filter — operator-proposed criterion

**Spec 088 candidate**:

```
in_universe
AND catalyst_days <= 60
AND (HARD events OR family-changing codes)
```

Mapping each clause to artifact-level signals available in `deltas[]`:

| Clause | Implementable from `deltas[]`? | Source |
|---|---|---|
| `in_universe` | yes | `EXITED` code excluded; `NEW_ENTRANT` and post-entrance rows kept |
| `catalyst_days <= 60` | yes | `_sf(c["catalyst_days"]) <= 60` (NaN → exclude) |
| HARD events | yes | `c.get("catalyst_family")` ∈ `{REGULATORY, CLINICAL}` (matches `HARD_FAMILIES` constant at producer line 47); fallback to `is_hard_catalyst` not directly in artifact but inferable from `BECAME_HARD` / `BECAME_SOFT` codes |
| family-changing codes | yes | `codes[]` ∩ `{FAMILY_CHANGED, BECAME_HARD, BECAME_SOFT}` ≠ ∅ |

### 5.1 How this filter relates to the existing producer noise filter

The existing producer noise filter is **OR-logic**: A/B tier OR ≤30 days OR `FAMILY_CHANGED` OR shadow/plan. It already excludes most truly low-signal rows.

The Spec 088 candidate is **AND-logic** layered on top: even after surviving the producer filter, a row only passes if all three clauses hold. Concretely:

- A C-tier name with `catalyst_days=45`, `catalyst_family=IR_EVENTS`, no codes — currently surfaces if in shadow/plan, **filtered out** by Spec 088 (not HARD, no family-changing codes).
- A B-tier name with `catalyst_days=20`, `catalyst_family=CONFERENCE`, no family-change — currently surfaces (B tier), **filtered out** by Spec 088 (not HARD, no family-changing codes).
- An A-tier `REGULATORY` name with `catalyst_days=14` — surfaces in both.

Net effect estimate: Spec 088 filter is roughly 3–5× more aggressive than the producer filter. Expected to retain only "hard catalyst events with timing within a quarter" plus all family-change events. Consistent with Spec 088's stated "reduce noise without changing scoring" goal.

### 5.2 Edge cases / design questions (for Phase B operator review)

1. **Should `EXITED` rows pass `in_universe`?** The candidate text says no, but exits ARE relevant for hedge/options if they were recent positions. Phase B should pick: `in_universe == True` (drop EXITED) or `in_universe OR was_in_position` (keep EXITED of names we held).
2. **NaN `catalyst_days`** — exclude (consistent with `_sf` returning NaN, `<= 60` evaluates False).
3. **`NEW_ENTRANT`** — has `catalyst_days` from the current row; passes the days clause normally.
4. **CTgov-merged rows** — codes are prefixed `CTGOV_*`. Phase B should decide whether `CTGOV_FAMILY_CHANGED` counts as "family-changing"; recommend: yes (treat prefix-stripped code as the canonical code).

## 6. Implementation options A / B / C

| Option | Description | Risk | Recommended? |
|---|---|---|---|
| **A. LLM-only** | filter applied at LLM agent prompt level (already done) | none | already in place; not the gap Spec 088 solves |
| **B. Filtered companion artifact** | producer emits `{date}_delta_filtered.json` alongside existing `{date}_delta.json`; raw preserved verbatim; consumers opt in | low — additive output; rollback = stop emitting the companion file | **YES — recommended** |
| **C. Destructive artifact filter** | replace existing artifact's `deltas[]` with the filtered subset; consumers see only the smaller list | medium — forensic data loss; harder rollback (would need to keep an unfiltered shadow file anyway, which collapses to Option B) | NO |

### 6.1 Why B over A

A doesn't solve the problem for non-LLM consumers (`build_options_watch.py`). The Spec 088 motivation is artifact-level reduction so deterministic consumers also see the tighter set when wired in.

### 6.2 Why B over C

C destroys the audit trail. The 2026-04-30 ranker hygiene work and the EES v3 structural-failure investigation both relied on retroactive forensic reads of full artifacts. Throwing away `n_noise_suppressed` rows in C would foreclose that capability for future investigations. C also makes A/B comparison impossible: you can't measure "how much did we filter" if you don't keep what you filtered.

### 6.3 What Phase B looks like (concrete, not yet approved)

- One file edited: `tools/build_catalyst_delta.py`, ~30 lines added at end of `build_catalyst_delta()`:
  - New function `apply_v2_filter(deltas: List[dict]) -> Tuple[List[dict], List[dict]]` returning (passed, suppressed)
  - Emit `{date}_delta_filtered.json` with same schema + extra fields `n_v2_filtered`, `n_v2_suppressed`, `v2_filter_definition` (string)
  - Optionally emit `{date}_delta_filtered.md`
- One file edited (optional, separate Phase C): `tools/build_options_watch.py` — gain a CLI flag `--use-filtered-delta` to read the filtered artifact instead. Default OFF until verified.
- No edits to: any module_3/module_4/module_5 file, ranker, selector, decision_engine, EV, sizing, `catalyst_delta_score`, raw catalyst extraction.
- Tests: extend `tests/test_build_catalyst_delta.py` (or create if absent) with the 4 edge cases from §5.2 plus a "raw artifact byte-identical" snapshot test.

## 7. Required safety checks for Phase B (operator's list + additions)

Operator-listed gates:
1. **raw artifact preserved** — `{date}_delta.json` content unchanged byte-for-byte vs. pre-Phase-B baseline (snapshot test)
2. **filtered artifact diff shown** — Phase B PR description must include before/after summary: `n_filtered` (existing) vs `n_v2_filtered` (new), with a per-ticker delta of which rows are dropped
3. **build_options_watch impact diffed** — for the same as_of_date, run `build_options_watch.py` against (a) raw artifact only and (b) hypothetical filtered artifact; show ticker-set diff. Document any name that would be dropped from options coverage
4. **rankings.csv row-hash unchanged** — `data/snapshots/{date}/rankings.csv` SHA256 byte-identical pre/post Phase B run
5. **Module 5 composite output unchanged** — no file in `module_5_*.py` touched; Module 5 composite output for the same as_of_date byte-identical

I'd add three more (defensive):

6. **LLM agent prompt audit** — confirm none of `agents/catalyst_delta/`, `agents/options_watch/`, `agents/intraday_mover_watch/`, `agents/price_action_watch/`, `agents/grok_biotech_watch/` were silently re-pointed to read the filtered artifact without operator approval
7. **Rollback path is one commit** — Phase B reverts cleanly: removing `apply_v2_filter` + the second `json.dump` returns producer to current behavior; raw artifact untouched throughout
8. **Filter definition is parameterized** — Phase B should encode the filter as a constant or CLI flag, not hardcoded magic numbers, so tuning thresholds (e.g., `catalyst_days <= 60` → `<= 90`) doesn't require touching producer logic

## 8. What Phase B should NOT do

- Modify the existing `passes_noise_filter` function (existing behavior preserved)
- Change `classify_change` (the codes vocabulary stays)
- Modify `module_3_*`, `module_5_*`, `ranker_*`, `selector_engine.py`, `decision_engine.py`, `event_ev/`, `common/ranker_active_contract.py`, `pos_*.py`
- Touch `catalyst_delta_score` (Module 3's separate score field; not artifact-driven)
- Re-point `build_options_watch.py` consumer in the same commit as the producer change (split into a separate, observable Phase C)
- Delete or rewrite any historical artifact under `artifacts/catalyst_delta/`
- Run any production job, including `tools/build_catalyst_delta.py` against today's date — Phase B is implementation; observation comes from the next natural production run
- Touch any bioshort file or cron while the Spec 087 wrapper is in flight

## 9. Open questions for operator (before Phase B kicks off)

1. **EXITED handling** (§5.2 #1) — drop or keep when the exited ticker was recently held?
2. **Filter parameters** — is `catalyst_days <= 60` the right threshold, or should it be wired as a CLI/config arg with the default at 60?
3. **Filtered Markdown twin** — emit `{date}_delta_filtered.md` for symmetry, or JSON-only?
4. **Phase C consumer rewiring** — is `build_options_watch.py` wiring a separate spec or part of Spec 088 Phase C? My read of the operator's Spec 088 description suggests separate.
5. **Backfill of historical filtered artifacts** — leave 2020–2026 unfiltered (as today), or backfill `_filtered.json` for the full series? My recommendation: do NOT backfill; only emit going forward.

## 10. Out-of-scope confirmations (re-stated for the record)

- No selector / ranker / EV / sizing / eligibility / scoring change in any sub-phase of Spec 088.
- `catalyst_delta_score` (the Module 3 numerical score) is independent of these artifacts — confirmed empty grep against `module_3_*` for artifact paths.
- No bioshort, hedge_report, B0/B1 surface touched. Spec 087 work continues independently.
- No `output/hedge_report/` mutation.
- No production runs triggered by Phase A.

---

_Generated 2026-05-07 as Spec 088 Phase A read-only investigation. No code, cron, or artifact changes made beyond writing this memo._
