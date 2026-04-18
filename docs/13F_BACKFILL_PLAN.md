# 13F Historical Backfill — PIT Remediation Plan

Status: plan (not yet implemented)
Author context: 2026-04-17 PIT provenance upgrade follow-up
Related: `docs/MODEL_DOCUMENTATION.md` §PIT Data Architecture, `docs/PIT_BUNDLE_WORKFLOW.md`, commit `c11deb2b`

## Why this exists

The 2026-04-17 snapshot-input archive (commit `c11deb2b`) captures `universe`,
`trial_records`, `holdings_detailed`, `short_interest`, and `ipo_dates` into
`data/snapshots/{date}/inputs/` **going forward**. That closes the forward
contamination path but leaves one major historical hole: **institutional /
13F state for pre-2026-04-17 dates is still sourced from whatever lives in
`production_data/` at regen time.**

The agent dependency map (2026-04-17) confirms the contamination point:
`run_screen.py:8788-8833` tries `{data_dir}/coinvest_signals.json` first, then
falls back to `{data_dir}/holdings_detailed.json`. When
`scripts/research/regenerate_pit_v2_snapshots.py` runs for a 2020-2024 date, it
passes `--data-dir production_data/` (or an archived dir that doesn't exist),
so the fallback reads the **current** quarter's holdings as if they were
historical. Every regenerated coinvest_score_z / inst_delta_z for those dates
is therefore anchored to present-day institutional state, not the state as
known on the as-of date.

## Current state (what already exists)

| Artifact | Location | Coverage | Notes |
|----------|----------|----------|-------|
| Backfill tool | `tools/backfill_13f_history.py` | quarterly, configurable lookback | works; reuses `warm_13f_cache.py` PIT selection |
| PIT 13F cache | `data/caches/sec_13f/PIT/{date}/` | 55 date dirs; 2024+ ≥90%, 2020-2023 ~0-8% | Older-date dirs are stubs; default lookback too shallow for pre-2023 filings |
| Per-quarter governed holdings | `production_data/holdings_history/holdings_{date}.json` | 2 quarters only (2025-06, 2025-09) | Built by `scripts/extract_13f_history.py` |
| PIT bundles | `data/bundles/PIT/{date}/coinvest_features.json` | 44 quarterly dates 2020-Q1 → 2024-Q4 at 75-95% coverage | Built by `scripts/build_pit_bundle.py` |
| Bundle-native screen path | `scripts/run_screen_from_bundle.py` | exists, takes bundle dir as input | Not currently used by `regenerate_pit_v2_snapshots.py` |
| Current-state holdings | `production_data/holdings_detailed.json` | 1 quarter (latest) | Shape: `{"_schema","tickers","managers","stats",...}` |

## The contamination path, concretely

```
scripts/research/regenerate_pit_v2_snapshots.py
  → subprocess call: python run_screen.py --as-of-date 2022-06-30 \
                                          --data-dir production_data \
                                          --pit-mode degrade
      → run_screen.py:8790  {data_dir}/coinvest_signals.json → does not exist
      → run_screen.py:8797  {data_dir}/holdings_detailed.json → EXISTS (current)
      → run_screen.py:8832  _convert_holdings_to_coinvest(current_holdings)
      → coinvest_score_z derived from 2025-12-31 holdings applied to a 2022-06-30 screen
```

This is **silent**. No warning, no source tag in the snapshot manifest saying
"institutional data is stale." The regen completes and writes `rankings.csv`.

## Institutional feature dependency map

| Feature | Computed at | Raw inputs | Primary read |
|---------|-------------|------------|--------------|
| `coinvest_score_z` | `run_screen.py:4620-4672` | tier1_count, conviction_overlap, days_since_latest_filing, position_pct, change_type | `coinvest_signals.json` → `holdings_detailed.json` fallback |
| `coinvest_score` | same | same (pre-z raw) | same |
| `inst_delta_z` | `run_screen.py:4708-4780` | elite_new/exit/add/trim counts, net_elite_holders_delta | `institutional_summary_delta.json` sidecar |
| `inst_delta_net/new/exit` | same | same | same |
| `inst_score_z` (sidecar) | `institutional_summary.py` | holdings_detailed tickers | validation, not selector |

Selector impact (per 2026-04-06 audit, `scoring_model_identity_2026_04_06.md`):
**institutional block = 92.7% of selector variance.** This is the dominant
input to selection. Historical contamination here is the single most important
PIT gap.

## Plan — two viable implementations

### Option A — Bundle-native regen (lowest risk, lowest coverage)

**What:** Modify `regenerate_pit_v2_snapshots.py` to call
`scripts/run_screen_from_bundle.py` when `data/bundles/PIT/{date}/manifest.json`
exists, falling back to the current path otherwise.

**Why good:** `run_screen_from_bundle.py` already consumes
`coinvest_features.json` from the bundle — no shape translation needed. The
bundle's provenance is already SHA-256 pinned.

**Why limited:** Bundles are quarterly (44 dates, quarter-ends 2020-Q1 →
2024-Q4). Regen currently runs monthly (one snapshot per month, last available).
Bundle-native regen would shrink PIT v2 coverage from ~60 monthly dates to ~20
quarter-ends — a real loss of statistical power.

### Option B — Stage bundle data into data_dir before run_screen (higher coverage, translation required)

**What:** Before each regen call:
1. Find the closest-prior bundle (`data/bundles/PIT/{bundle_date}/`) where
   `bundle_date <= as_of_date` and `(as_of_date - bundle_date) <= 95 days`
2. Convert `coinvest_features.json` → a synthesized `coinvest_signals.json`
   matching the schema `run_screen.py` expects at line 8790
3. Write it to a per-date staging dir (or into archived inputs)
4. Pass `--data-dir` pointing to that staging dir

**Why good:** Keeps monthly cadence; uses every bundle; no change to
`run_screen.py`; staging dir is idempotent + inspectable.

**Why harder:**
- Need to verify the synthesized `coinvest_signals.json` produces the same
  `coinvest_score_z` as the bundle-native path. This is a correctness test
  requiring a dual-run comparison on a handful of dates.
- Bundle `coinvest_features.v1` schema has per-ticker `tier1_count`,
  `conviction_overlap`, etc., but `coinvest_signals.json` is expected in a
  different wrapper (`_convert_holdings_to_coinvest` is not the right
  adapter — `coinvest_features.json` is *already* converted).
- The `inst_delta_z` path needs a parallel solution — bundles don't currently
  carry `institutional_summary_delta.json`.

### Recommended path

**Option A for immediate honest coverage**, **Option B as a follow-up** once
the staging adapter is tested. Rationale:

- Option A is a ~20-line change and uses data that's already been audited
  (bundle SHA-256s are in the manifest).
- Option B captures more dates but introduces a schema translation that could
  silently disagree with bundle-native output. That's a new contamination
  vector unless proven equivalent.

## Build-ready spec

### Source inputs

- Bundles: `data/bundles/PIT/{date}/manifest.json` + components
- SEC fetcher: `SEC13FFetcher` from `sec_13f/edgar_13f.py`
- Manager registry: `elite_managers.get_all_managers()` (44 managers)
- CUSIP map: `production_data/cusip_static_map.json`
- Universe: prefer `{snapshot}/inputs/universe.json` when archived, else current

### Storage layout (no new storage required for Option A)

For Option B only, add:
```
data/staging/pit_regen/{as_of_date}/
  coinvest_signals.json         # synthesized from nearest bundle
  institutional_summary_delta.json  # TBD — may need new builder
  _source.json                  # {bundle_date, lag_days, method}
```

### Date resolution logic

1. Lookup `data/bundles/PIT/{as_of_date}/manifest.json` → use directly (Option A)
2. Else find closest-prior bundle_date within 95 days → stage (Option B)
3. Else: mark this date as **institutional-contaminated** in the regen log
   and skip (or run with explicit warning tag in manifest)

### Fallback behavior

- If no bundle within 95 days: regen should log
  `data_source="current_holdings_contaminated"` in the output manifest rather
  than silently using current state. This is a one-line addition to
  `regenerate_pit_v2_snapshots.py` even before the bundle path is wired.

### Integration points

| Consumer | Change required |
|----------|-----------------|
| `tools/run_daily_production.py` | Forward-only: add `coinvest_signals.json` + `institutional_summary_delta.json` to the archive list **if** they exist in production_data (they currently don't live there — would need the pipeline to write them to production_data first, OR archive from the snapshot output dir) |
| `scripts/research/regenerate_pit_v2_snapshots.py` | Add bundle-aware branch; log `data_source={bundle,archived,current}` per date |
| `research/full_current_model_backtest.py` | Same bundle-aware lookup for clinical injection; already has 3-tier fallback for trial_records |
| `run_screen.py` | No change under Option A. Under Option B, optionally add strict-mode check that refuses fallback to `holdings_detailed.json` without an explicit `--allow-current-holdings` flag |
| `tools/backfill_13f_history.py` | Re-run with `--lookback-filings 40 --date-from 2020-01-01 --date-to 2024-12-31 --manager-set coinvest --resume` to fill the 2020-2023 cache gap |

### Validation strategy

1. **Coverage audit:** After any cache backfill run, re-check
   `data/caches/sec_13f/PIT/{date}/index.json` coverage_pct for all
   historical quarters. Target: ≥80% manager coverage for every quarter-end
   2020-Q1 → 2024-Q4.
2. **Schema equivalence test (Option B only):** For 3 dates with existing
   bundles, synthesize `coinvest_signals.json` from the bundle and compare
   regenerated rankings against `run_screen_from_bundle.py` output for the
   same ruleset. Passing criterion: rank correlation ≥0.99 and top-30
   overlap ≥28/30.
3. **Contamination detector:** Add a check to `regenerate_pit_v2_snapshots.py`
   that surfaces `data_source=current` in the regen log summary — any such
   entry means the regen for that date is still pseudo-PIT and its
   institutional features must be labeled as such.
4. **Forward vs backfilled coinvest comparison:** For dates where both the
   archived snapshot input AND a bundle exist (will apply to future
   quarter-ends after 2026-04-17), compare the two to detect any drift in
   the bundle builder over time.

### Expected limitations

- **Still pseudo-PIT for ruleset/code:** Even with full 13F backfill, the
  model code and decision ruleset are the current versions applied to
  historical data. This is acknowledged in `MODEL_DOCUMENTATION.md` §
  Intellectual Honesty.
- **Manager registry is not historical:** `elite_managers.get_all_managers()`
  returns the **current** 44 managers. If a manager was added in 2024,
  their 2020 filings will be backfilled even though they weren't considered
  "elite" in 2020. This is a second-order PIT violation that the existing
  bundle/cache architecture does not correct.
- **Bundle cadence ≠ regen cadence:** Option A gives correct but sparser
  evidence. Option B gives denser but translation-dependent evidence. Neither
  makes the historical backtest decision-grade on its own.
- **Forward live monitoring remains primary evidence.** This plan improves
  historical provenance; it does not convert historical returns into
  deployable alpha claims.

## Phased execution

| Phase | Effort | Risk | Status | Deliverable |
|-------|--------|------|--------|-------------|
| 0 | trivial | none | **DONE** (`6c78665a`) | Log `data_source=current\|archived\|bundle` in regen output |
| 1 | low | low | **DONE** (2026-04-17, 17 dates) | `backfill_13f_history.py --lookback-filings 40` for 2020-2024Q1; cache coverage 82-93% per quarter |
| 2 | low | low | **DONE** (`b5f58cce`), **not promoted** | Option A: bundle-native regen branch. Schema mismatch (111/314 cols) — unusable as drop-in. |
| 3 | medium | medium | **DONE** (`df914cd4`) + quarter-end default promotion (2026-04-17) | Option B-lite: staging adapter reuses `build_coinvest_features_from_13f.py`; default-on for dates with PIT cache ≥50% coverage |
| 4 | medium | medium | pending | Forward archive of `coinvest_signals.json` once the pipeline writes it to a stable path |
| 5 | high | high | pending | Strict-mode guard in `run_screen.py` that refuses current-holdings fallback |

Phases 0-3 shipped. Phases 4-5 are follow-up upgrades.

## Option B-lite validation (19-date quarter-end set, 2026-04-17)

Validation dates: all quarter-ends 2020-Q1 through 2025-Q4 that are trading days with exact PIT cache match (2022-Q4, 2023-Q3, 2023-Q4, 2024-Q1, 2024-Q2 excluded — weekend-only quarter-ends whose cache keys don't align with trading days).

Aggregate results:
- 19/19 dates completed cleanly (no failures in either path)
- 19/19 schema preserved (identical 312-column set baseline vs OB-lite)
- 19/19 row counts identical (180-308 per date)
- 100.0% of tickers changed `coinvest_score_z` on every date (mean/median/min/max)
- 0.0% of tickers changed `inst_delta_z` — delta sidecar is not yet staged (known limitation, Phase 4 scope)
- Top-30 overlap: mean 16.3 / median 15 / range 11-24 (older dates diverge more; recent dates converge)
- Top-10 overlap: mean 3.4 / median 3 / range 1-7
- 0 suspicious dates

Sanity examples (baseline → OB-lite coinvest_score_z):
- 2020-06-30 NGNE (Neurogene, IPO'd 2023 via SPAC): +3.10 → -0.68 — leaked 2025 holdings erased
- 2022-09-30 IRON (Disc Medicine, IPO'd 2020-08): +3.14 → -1.08 — had almost no institutional base by 2022
- 2024-12-31 JBIO (Jade Biosciences, IPO'd 2024-06): +2.78 → -1.11 — six months post-IPO, not yet a smart-money name

Report artifact: `output/pit/qe_validation/qe_validation_report.json`

## Known limitations preserved

- `institutional_summary_delta.json` is still sourced from current state; `inst_delta_z` in OB-lite output reflects current-quarter deltas, not historical. Phase 4.
- Non-quarter-end monthly dates fall through to the current contamination path. Nearest-prior cache lookup is explicitly out of scope per the validation spec.
- Weekend-only quarter-ends (5 cases in the 2020-2025 window) are excluded from OB-lite coverage.
- Manager registry is current-state (`elite_managers.get_all_managers()`); a manager added in 2024 is treated as "elite" in 2020 backfill — second-order PIT violation.
- Historical regen is **pseudo-PIT** overall. Live forward monitoring remains the primary deployable evidence source.

## Non-goals

- This plan does **not** reconstruct historical manager registries. Treating
  the current elite list as retroactively elite is a known second-order PIT
  violation and is out of scope.
- This plan does **not** attempt to generate historical
  `institutional_summary_delta.json` beyond what the existing
  `compute_institutional_delta()` can derive from two consecutive cached
  quarters. Cross-quarter delta from the backfilled cache is feasible but
  requires ordering and is a separate workstream.
- This plan does **not** promote any historical return claim to decision-grade.
  Pseudo-PIT labeling stays.

## One-line summary

The 13F backfill path exists in pieces (`backfill_13f_history.py`,
`build_pit_bundle.py`, `run_screen_from_bundle.py`); the gap is that
`regenerate_pit_v2_snapshots.py` doesn't wire them together and silently falls
back to current `holdings_detailed.json` for historical dates. Wiring is a
small amount of code; correctness validation is where the real work is.
