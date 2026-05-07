# Spec 092 — Bioshort Historical Backfill / Shadow-Alpha Panel (Phase A Draft)

**Status**: DRAFT — Phase A (feasibility/design) only; no implementation
**Date**: 2026-05-07
**Phase**: A (A → B → C → D sequenced; only A is in scope of this document)
**Predecessors**:
- `specs/changes/spec_087_bioshort_producer_restoration_2026_05_06.md` — producer restoration; B1 first-fire validation is a hard prerequisite for Phase C
- `output/hedge_report/` — live operational artifact path (forward-only, must not be mutated by backfill)
- `agents/bioshort_watch/memory/2026-05-03_cron_misescalation_issue.md` — historical context for why the LLM consumer stays suppressed

**Operator framing (recorded)**:
- Goal B (research backfill) approved over Goal A (operational backfill).
- Operational backfill into `output/hedge_report/` is **explicitly NOT approved** at any phase.
- Phase A may be drafted now; Phases B–D blocked until Spec 087 B1b first-fire validation passes.

---

## 1. Goal

Recompute deterministic bioshort hedge-report features across historical snapshots into a separate research surface, without mutating production hedge-report artifacts, so we can later test whether bioshort/hedge features carry alpha, drawdown, squeeze, or risk-overlay value.

This is **diagnostic / research only**. No scoring, ranker, selector, EV, sizing, or cron change at any phase. No promotion of bioshort into live decisions.

---

## 2. Scope summary

| Phase | What it does | Required before next | Blocking dependency |
|---|---|---|---|
| **A** | Feasibility memo + design (this document) | yes — must be approved before B | none |
| **B** | Research-mode flag in `tools/biotech_hedge_report.py` so `--output-dir` actually isolates writes | yes | Spec 087 B1b first-fire validation passes |
| **C** | Historical feature panel build into `artifacts/research/bioshort_backfill/` | yes | Phase B shipped |
| **D** | Alpha/risk analysis (forward returns, drawdown, squeeze) | terminal | Phase C panel exists |

---

## 3. Output surface

```
artifacts/research/bioshort_backfill/
  panel.csv                       # REQUIRED: one row per (as_of_date)
  panel.parquet                   # OPTIONAL: skipped if pyarrow/fastparquet unavailable
  reports/YYYY-MM-DD.json         # per-date hedge_report (research copy)
  reports/YYYY-MM-DD.md           # per-date markdown (research copy)
  backfill_manifest.json          # REQUIRED: code commit, date range, options-source-by-date,
                                  # failures, parquet_status
```

`backfill_manifest.json.parquet_status ∈ {"written", "skipped_missing_dependency"}` so absence of `panel.parquet` is explicit, not silent. (Resolves §7 Q2.)

No writes outside this directory. No writes to `output/hedge_report/`, no writes to `data/snapshots/`, no cron change, no git-tracked scoring or ranker file touched.

---

## 4. Phase A deliverables (this document)

A1. **Inventory of historical inputs** — confirm which snapshot dates have a usable `data/snapshots/YYYY-MM-DD/portfolio_positions.csv`. Snapshot tree currently spans 2024-10-18 → 2026-05-07 (187 dates). Coverage of `portfolio_positions.csv` per date is unverified at draft time and is a Phase A research output.

A2. **Producer-mutation surface map** — confirmed by reading `tools/biotech_hedge_report.py` at draft time:
  - `--output-dir` already exists (line 2961, defaults to `REPO_ROOT/output/hedge_report`). Routes the primary `hedge_report_{date}.{json,md}` and `BIOSHORT_VERDICT.{json,md}` writes correctly.
  - **Archive write at line 2762 is hardcoded** to `REPO_ROOT/output/hedge_report/archive/` and bypasses `--output-dir`. This is the dominant blast-radius risk.
  - `_find_prior_report(archive_dir, ...)` (line 2779) reads from the same hardcoded archive. Across historical backfill dates this would mix research outputs with live archive entries and produce incoherent week-over-week diffs.
  - All other writes (`_write_verdict`, primary JSON/MD, weekly-diff re-write at 2796–2804) use the parameterized `output_dir`.

A3. **Phase B requirement (design only)** — add a `--research-mode` (or equivalent) flag whose effect is:
  - Redirect the archive write at line 2762 to `{output_dir}/archive/`.
  - Redirect the prior-report lookup at line 2779 to read from `{output_dir}/archive/` only. **No reads from or writes to live `output/hedge_report/archive/`** when research mode is active. (Resolves §7 Q1.)
  - Redirect `BIOSHORT_VERDICT.{json,md}` writes so they land **only inside the research `--output-dir`**. In research mode the live `output/hedge_report/BIOSHORT_VERDICT.{json,md}` must not be touched. (Resolves §7 Q4.)
  - Tag the emitted JSON with `mode: "research_backfill"` so downstream readers cannot mistake research artifacts for live operational ones.
  - Suppress any side effects that would write outside `output_dir`.
  - No behavior change in default (operational) mode.

A4. **Per-date row schema (Phase C target)**:

```
as_of_date
verdict
recommendation
hedge_score
confidence
best_vehicle
xbi_beta
xbi_r2
ibb_beta
ibb_r2
primary_cost_bps
options_source                # massive | cached | bs | realized_vol_proxy | missing
portfolio_n
portfolio_weight_sum
top_contributors              # JSON-encoded list
error_status                  # ok | skipped_no_portfolio | skipped_no_options | partial
```

Forward-return / risk targets (`forward_{1,5,20}d_return`, `max_drawdown_20d`, `realized_vol_20d`, `post_catalyst_return`) are joined in a **second pass** after the feature panel is built. Phase A does not bake forward targets into the feature row to keep features and labels separable for later IC/Brier work.

**Phase C explicitly does NOT join forward returns.** The forward-return / risk-target join is deferred to Phase D, which must declare its target-price source separately before any analysis runs. The preferred source is the same PIT-safe market-data cache used elsewhere in the screener (no ad hoc yfinance / live pulls). This keeps the feature panel a clean, label-free artifact that can be re-joined against different label sets without re-running the producer. (Resolves §7 Q3.)

A5. **Safety-check checklist (Phase C run-time gate)**:
  - No writes to `output/hedge_report/` (assert via path check before exec).
  - No writes to `data/snapshots/`.
  - No cron change; backfill is a one-shot offline driver.
  - No git-tracked scoring file touched (assert via `git status --porcelain` clean on those paths).
  - Missing `portfolio_positions.csv` → skip date, record reason in manifest.
  - Missing options data → record fallback source per date, do not fail whole backfill.
  - `backfill_manifest.json` records: code commit SHA, ruleset id at time of run, date range attempted, per-date status, per-date options source, failures with reason.

A6. **PIT-honesty caveat** — Phase C is **pseudo-PIT**. We are recomputing features today using current `tools/biotech_hedge_report.py` logic against historical snapshot inputs. This is acceptable for descriptive panel work but:
  - Forward-return analysis in Phase D must label results as pseudo-PIT.
  - No promotion claim can be made from Phase D output. Promotion requires Checklist v2 on a forward shadow, not a backfill panel. (Same constraint that closed EES v3 — see `ees_v3_structural_failure_2026_04_30.md`.)

A7. **What this spec does NOT do** (explicit non-goals, mirrored from operator framing):
  - No writes into `output/hedge_report/`.
  - No cron changes.
  - No reactivation of `bioshort_watch` LLM agent.
  - No scoring / ranker / selector / EV / sizing change.
  - No use of LLM narrative as signal evidence.
  - No promotion of bioshort into live decisions.
  - No copy-after-write loop into `output/hedge_report/`. The producer must be invoked with isolation built in (Phase B), not patched up after the fact.

---

## 5. Sequencing and gating

```
[Phase A approved]                    ← this document
       ↓
[Spec 087 B1b first-fire validation passes]   ← external gate
       ↓
[Phase B: --research-mode flag + tests, gated to research path only]
       ↓
[Phase B verified: invoke producer in research mode against ONE historical date,
 confirm zero mutation under output/hedge_report/ and zero mutation under data/snapshots/]
       ↓
[Phase C: enumerate snapshots → write panel.csv + per-date reports + manifest]
       ↓
[Phase D: join forward returns, run descriptive analysis with pseudo-PIT caveat]
```

Each gate writes a verdict artifact under `artifacts/research/bioshort_backfill/gates/` before the next phase starts.

---

## 6. Phase A acceptance criteria

A is complete when:
1. This memo is approved by operator.
2. Phase A inventory of `portfolio_positions.csv` coverage across `data/snapshots/*` is produced as a read-only artifact (`artifacts/research/bioshort_backfill/phase_a_inventory.json`) — enumeration only, no producer invocation.
3. The Phase B design (research-mode flag) has explicit operator sign-off before any code change in `tools/biotech_hedge_report.py`.

No code change ships in Phase A.

---

## 7. Phase A closure (2026-05-07)

Phase A is complete and accepted.

- Spec committed at `f51b943a` (`docs(bioshort): draft historical backfill research spec`).
- Phase A inventory generated at `artifacts/research/bioshort_backfill/phase_a_inventory.json` (gitignored research artifact).
- No producer invocation. No `output/hedge_report/` mutation. No cron change.

**Inventory headline:**

| metric | value |
|---|---|
| canonical snapshots scanned | 162 |
| usable `portfolio_positions.csv` | 142 |
| missing | 20 |
| └ with `decision_portfolio.csv` fallback candidate | 18 |
| └ with no portfolio artifact | 2 |
| unusable | 0 |
| weight column observed | `target_weight_pct` (142/142) |
| date range | 2024-10-18 → 2026-05-07 |

### 7.1 Phase B scope confirmed

Research-mode isolation only:
- archive writes redirected to `output_dir/archive`
- prior-report lookup redirected to `output_dir/archive`
- `BIOSHORT_VERDICT.{json,md}` redirected to research `output_dir`
- emit `mode: "research_backfill"` in JSON
- no behavior change in operational mode
- **no schema fallback** in Phase B

### 7.2 Phase C policy — `decision_portfolio.csv` fallback (locked, do not auto-enable in Phase B)

The 18 missing dates that carry `decision_portfolio.csv` instead of `portfolio_positions.csv` (cluster 2026-01-19 → 2026-02-17, schema-migration boundary) are **not** to be picked up by an automatic fallback in Phase B.

Phase C policy:
- **Default backfill uses only `portfolio_positions.csv`.**
- `decision_portfolio.csv` fallback requires an **explicit, tested compatibility check** before use.
- If compatible, those dates run as a **separate labeled cohort** with `source_schema = "decision_portfolio_legacy"` recorded in both per-date report JSON and `backfill_manifest.json`.
- Cohort outputs from the legacy-schema cohort must remain analytically separable from the main cohort in Phase D.

Reason: the Spec 087 B1a/B1b work was specifically about eliminating silent portfolio fallback. Introducing a new fallback in Phase B — even one that "just helps" — would directly undermine that. The hold here is principled, not bureaucratic.

### 7.3 Hold

No further Spec 092 work until **Spec 087 B1b first-fire validation passes**. Phases B/C/D remain blocked.

---

## 8. Resolved clarifications (operator decisions, 2026-05-07)

1. **Weekly-diff handling** — In research-backfill mode, weekly / prior-report diffs must use only the research archive under the requested `--output-dir`. No reads from or writes to live `output/hedge_report/archive/`. Wired into A3 above.
2. **Parquet output** — Parquet is optional; CSV + JSON manifest are required. If `pyarrow`/`fastparquet` is unavailable, skip parquet and record `parquet_status="skipped_missing_dependency"` in `backfill_manifest.json`. Wired into §3 above.
3. **Forward-return price source** — Phase C feature panel does NOT join forward returns. Phase D defines its target-price source separately, with strong preference for the existing PIT-safe market-data cache used elsewhere in the screener (no ad hoc yfinance / live pulls). Wired into A4 above.
4. **BIOSHORT_VERDICT redirection** — In research-backfill mode, `BIOSHORT_VERDICT.{json,md}` must be written only inside the research output dir. Live `output/hedge_report/BIOSHORT_VERDICT.{json,md}` must not be touched. Wired into A3 above.
