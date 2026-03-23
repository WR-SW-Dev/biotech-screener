# Change Spec: Principal Investigator Trial Count Signal

**Status**: RESEARCH COMPLETE / NO SIGNAL
**Author**: Claude / operator
**Date**: 2026-03-21
**Ruleset impact**: NO (auxiliary feature first, promotion requires separate spec)

---

## Objective

Extract investigator-level trial history from the existing AACT snapshot and compute
per-ticker PI experience metrics as a new clinical auxiliary signal. The goal is to
capture **investigator quality and program execution depth** — a genuinely new information
source not already represented in any existing DEM factor.

## Motivation

The repo has now tested quality tiebreaks at three scopes (less_binary, build_window,
binary_now) using existing signals, and all were structurally valid but economically
immaterial. The conclusion is that new scoring improvement requires a **new information
source**, not rearranging existing ones.

PI trial count is the cleanest missing source because:
- CT.gov pipeline is already mature and PIT-aware
- AACT facility_investigators.txt (221K rows, 16MB) is already on disk
- trial_records.json provides nct_id → ticker linkage (18,760 trials)
- No new external data feed or API integration required
- Low PIT risk: trial registration data is public from filing date

## PIT / Data Constraints

- [x] No lookahead — PI data gated by trial's `last_update_posted <= as_of_date`
- [x] Data source: AACT `facility_investigators.txt` (bulk download, snapshot-dated)
- [x] Historical availability: AACT snapshot dated 2026-02-02; CT.gov API v2 for refresh
- [x] Known gaps: not all trials list investigators (~1-2% missing); name dedup is imperfect

### PIT Rule

A PI's trial history is admitted iff EACH counted trial satisfies the existing PIT gate:
```
pit_date = first_posted OR last_update_posted (priority order)
admitted iff pit_date <= as_of_date
```
This inherits directly from `build_clinical_features_pit.py`'s `_is_pit_admitted()`.

### AACT Snapshot Dating

The AACT bulk download is a point-in-time export. For PIT-correct evaluation:
- Current snapshot: 2026-02-02
- Use this snapshot for all `as_of_date >= 2026-02-02`
- For historical as_of_dates: use the AACT snapshot that was current at that time
  (or accept the conservative bias that the snapshot overstates PI history)
- Document the AACT snapshot date in output metadata for audit trail

## Data Source: AACT facility_investigators.txt

### Schema

| Column | Type | Description |
|--------|------|-------------|
| `id` | int | Unique row ID |
| `nct_id` | str | ClinicalTrials.gov trial ID |
| `facility_id` | int | AACT facility ID |
| `role` | enum | `PRINCIPAL_INVESTIGATOR` or `SUB_INVESTIGATOR` |
| `name` | str | Free-text name with titles (e.g., "Ashley L Lynch, M.D.") |

### Name Normalization (v1 — conservative)

PI names are free-text with inconsistent formatting. V1 uses deterministic normalization:

1. Strip leading/trailing whitespace
2. Lowercase
3. Remove credential suffixes: M.D., MD, Ph.D., PhD, DO, MBBS, etc.
4. Remove honorific prefixes: Dr., Prof., etc.
5. Collapse internal whitespace to single space
6. Trim trailing commas/periods

This yields a `normalized_name` used as the dedup key. V1 accepts undercounting
(different spellings of the same person treated as different PIs) as conservative.
Overcounting (same name for different people) is mitigated by the fact that PI names
in biotech trials are relatively unique.

### Linkage

```
AACT facility_investigators.txt (nct_id)
  → trial_records.json (nct_id → ticker)
  → universe.json (ticker filter)
```

## Features

### Per-PI (intermediate, not persisted)

| Feature | Computation | PIT Gate |
|---------|-------------|----------|
| `total_trial_count` | Count of distinct nct_ids where PI is listed | Each trial PIT-admitted |
| `late_stage_count` | Count where phase in (Phase 2, Phase 2/Phase 3, Phase 3, Phase 4) | Each trial PIT-admitted |
| `completed_count` | Count where status in (Completed, Terminated with results) | Each trial PIT-admitted |

### Per-Ticker (output features)

| Feature | Computation | Range | Interpretation |
|---------|-------------|-------|----------------|
| `pi_count` | Count of unique normalized PIs across all PIT-admitted trials for ticker | int >= 0 | Program breadth / site scale |
| `pi_experience_max` | Max `total_trial_count` among ticker's PIs | int >= 0 | Best investigator depth |
| `pi_experience_median` | Median `total_trial_count` among ticker's PIs | float >= 0 | Typical investigator depth |
| `pi_late_stage_max` | Max `late_stage_count` among ticker's PIs | int >= 0 | Late-stage execution track record |
| `pi_completed_max` | Max `completed_count` among ticker's PIs | int >= 0 | Completion track record |
| `pi_concentration_ratio` | Top-1 PI trial count / total PI trial count (1/N if uniform) | float [0, 1] | Single-PI dependency risk |
| `pi_experience_z` | Cross-sectional z-score of `pi_experience_max` | float | Standardized for DEM consumption |

### Design Choices

**Why max, not mean**: A single highly experienced PI (e.g., 50+ trials) is a stronger
quality signal than a team of average investigators. Max captures the best available
expertise. Median captures the typical level. Both are reported.

**Why concentration ratio**: A ticker with 1 PI running all trials has single-point-of-failure
risk. A ticker with 20 diverse PIs has distributed execution. This is analogous to
`clinical_program_depth` but at the investigator level.

**Why z-score**: Cross-sectional z-scoring normalizes for universe-wide PI count
distributions. This is the standard pattern for DEM feature consumption (see
`coinvest_score_z`, `inst_delta_z`, `clinical_score_v2_z`).

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| facility_investigators.txt | AACT bulk export | Pipe-delimited, 5 columns |
| trial_records.json | production_data/ | JSON array, nct_id + ticker linkage |
| universe.json | production_data/ | Ticker filter |
| as_of_date | Caller | YYYY-MM-DD |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| PI features per ticker | `data/caches/pi_features/` | JSON, schema `pi_features.v1` |
| `pi_experience_z` | rankings.csv (via run_screen.py) | float column |
| Coverage metadata | Output JSON | `n_tickers_with_pi`, `n_tickers_missing`, `aact_snapshot_date` |

## Implementation Plan

### Phase 1: Feature Builder (this spec)

1. **`common/pi_features.py`** — pure functions:
   - `load_facility_investigators(path)` → dict[nct_id, list[PI]]
   - `normalize_pi_name(raw_name)` → str
   - `compute_pi_features(ticker_trials, pi_index, as_of_date)` → dict
   - `compute_pi_features_universe(trial_records, pi_index, universe, as_of_date)` → dict[ticker, features]
   - `z_score_pi_features(features_by_ticker)` → adds `pi_experience_z`

2. **`scripts/build_pi_features.py`** — CLI wrapper:
   - `--aact-dir` (default: `aact/`)
   - `--trial-records` (default: `production_data/trial_records.json`)
   - `--universe` (default: `production_data/universe.json`)
   - `--as-of-date` (required)
   - `--out-dir` (default: `data/caches/pi_features/`)
   - Writes JSON output with schema version and metadata

3. **Tests** (write BEFORE implementation):
   - `test_normalize_pi_name` — credential stripping, whitespace, determinism
   - `test_pi_count_basic` — ticker with known PIs → correct count
   - `test_pi_experience_max` — max selection across PIs
   - `test_pit_gate_inherited` — future trials excluded from PI history
   - `test_missing_investigators` — ticker with no AACT data → graceful zero
   - `test_z_score_deterministic` — same inputs → same z-scores
   - `test_concentration_ratio` — single-PI vs distributed team

### Phase 2: Integration (separate spec if Phase 1 shows signal)

1. Wire `pi_experience_z` into `run_screen.py` as an external sort field
2. Add to `clinical_quality_composite` as a 5th component (replacing or augmenting
   `program_depth` at 20% weight)
3. Create candidate ruleset with PI-enhanced scoring
4. Run signal evidence harness

### Phase 3: Evaluation

- IC test on PIT panel dates (monthly, 2020-2025)
- Bucket/family splits (CLINICAL vs REGULATORY, binary_now vs less_binary)
- Comparison against existing `clinical_program_depth` (are they redundant?)
- Forward return discrimination at 20d/63d/84d horizons

## Invariants

1. PIT-safe: only count trials whose pit_date <= as_of_date
2. Deterministic: same inputs → same outputs
3. Default OFF: no DEM impact until promoted via separate spec
4. Graceful degradation: missing AACT data → pi_count=0, pi_experience_z=0.0
5. AACT snapshot date tracked in output metadata

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| Ticker has no trials in trial_records | pi_count=0, all features=0 |
| Trial has no investigators in AACT | Trial excluded from PI aggregation (not from trial count) |
| AACT snapshot older than as_of_date | Conservative: overstates PI history slightly. Documented. |
| Name dedup fails (same person, different spellings) | Undercounts — conservative, acceptable for v1 |
| Name collision (different people, same normalized name) | Overcounts — rare in biotech PI population |

## Validation Plan

### Tests (write BEFORE implementation)

- [ ] `test_normalize_pi_name_credentials` — "John Smith, M.D." → "john smith"
- [ ] `test_normalize_pi_name_whitespace` — extra spaces, trailing punctuation
- [ ] `test_normalize_pi_name_deterministic` — same input → same output
- [ ] `test_pi_count_basic` — known ticker → correct PI count
- [ ] `test_pi_experience_max` — selects correct maximum
- [ ] `test_pi_concentration_ratio` — single PI=1.0, uniform=1/N
- [ ] `test_pit_gate_excludes_future` — future trials not counted in PI history
- [ ] `test_missing_aact_data_graceful` — ticker with no AACT matches → zeros
- [ ] `test_z_score_deterministic` — cross-sectional z-score stable
- [ ] `test_linkage_coverage` — report % of universe tickers with PI data

### Evaluation (Phase 2, if signal exists)

- [ ] IC vs forward returns at 20d/63d/84d on PIT panel
- [ ] Correlation with existing clinical_quality_composite (redundancy check)
- [ ] Bucket-local IC splits (binary_now, build_window, less_binary)
- [ ] Primary bar: meaningful positive IC at any horizon with t-stat >= 2.0
- [ ] Integration into clinical_quality_composite or standalone sort contribution

## Expected Effect Size

**Unknown — genuinely new signal.** Unlike the quality tiebreak specs (030, 031) where we
could predict the effect from existing data, PI count is a new information axis. The
hypothesis is that trials run by experienced investigators (many prior trials, late-stage
experience, high completion rates) are more likely to produce informative outcomes. This
is plausible but unproven in this universe.

The honest expectation is:
- **Coverage**: 80-90% of universe tickers (based on AACT trial linkage rates)
- **Correlation with existing signals**: moderate with program_depth (both measure scale),
  low with optionality (different axis)
- **Forward return IC**: genuinely unknown — this is research, not a known-positive candidate

If IC is flat, the feature is still useful as a **diagnostic / risk flag** (single-PI
dependency, inexperienced investigator teams) even without DEM integration.

## Non-Goals

- Do NOT build a PI reputation model (publication history, h-index, success rates)
- Do NOT scrape PubMed or external sources — AACT only for v1
- Do NOT modify the decision engine or rankings — Phase 1 is feature-only
- Do NOT attempt name dedup beyond basic normalization in v1
- Do NOT integrate into DEM without passing signal evidence (Phase 2/3)
- Do NOT refresh AACT data as part of this spec — use existing 2026-02-02 snapshot

---

## Implementation Log

### 2026-03-21 — Spec drafted
- AACT facility_investigators.txt confirmed on disk: 221K rows, 16MB, dated 2026-02-02
- trial_records.json provides nct_id → ticker linkage for 18,760 trials
- Existing PIT infrastructure in build_clinical_features_pit.py provides the pattern
- Name normalization is the main v1 challenge — conservative dedup approach chosen
- Phase 1 is feature-only (no DEM changes), evaluation in Phase 2

### 2026-03-21 — Phase 1 COMPLETE / Signal HOLD

#### What succeeded
- `common/pi_features.py` — feature builder with name normalization, PIT gate, CRO filter
  (cap=100 trials), cross-company PI experience, z-scoring. 280 lines.
- `scripts/build_pi_features.py` — CLI wrapper with coverage stats and distribution report.
- `tests/test_pi_features.py` — 34 tests: normalization (17), PIT gate (5), universe
  computation (8), z-score (4). All pass.
- CRO contamination discovered and handled: top PI had 2,306 trials (site network
  investigator). Cap at 100 drops max from 349 → 96.
- Output: `data/caches/pi_features/pi_features_{date}.json`, schema `pi_features.v1`

#### What failed to clear
- **Coverage too low**: 148/341 tickers (43.4%). AACT facility_investigators.txt only
  covers a fraction of CT.gov trials. 152 tickers have trials in trial_records but no
  AACT PI match.
- **Top-book variance too weak**: 11/20 top-ranked names have PI data, but most have
  pi_max_trial_count of 1-4. Only REPL stands out (z=+2.79, 61 trials).
- **High-z dominated by large-cap**: TECH (+4.63), DNA (+4.63), REGN (+4.48) are
  large-cap pharma/CRO companies outside the active ranking focus.
- **Bucket coverage**: binary_now 67%, build_window 61%, less_binary 37%, core 29%.

#### Decision: DEM integration NOT APPROVED (AACT-only)
- Coverage too low for DEM. Next step: CT.gov API v2 enrichment.

### 2026-03-21 — CT.gov API v2 PI enrichment

#### What was done
- `scripts/enrich_pi_from_ctgov_api.py` — fetches `overallOfficials` from CT.gov API v2
  for all 17,029 NCT IDs missing from AACT. Batches of 20, rate-limited, ~4 min runtime.
- `common/pi_features.py` — added `load_pi_supplement()`, `merge_pi_indices()` for
  combining AACT + API data sources.
- `scripts/build_pi_features.py` — added `--supplement` flag for merged operation.
- Output: `data/caches/pi_features/ctgov_api_pi_supplement.json` (5,310 trials, 6,315 PIs)

#### Coverage improvement
| Metric | AACT Only | AACT + API v2 | Gain |
|--------|-----------|---------------|------|
| Universe coverage | 43.4% (148/341) | **68.6% (234/341)** | +25.2pp |
| binary_now | 67% | **93%** | +26pp |
| build_window | 61% | **85%** | +24pp |
| less_binary | 37% | **63%** | +26pp |
| Top-20 with data | 11/20 | **18/20** | +7 names |

#### Signal characteristics (enriched)
- pi_max_trial_count: min=1, median=2, max=14 (CRO filter effective)
- pi_experience_z range in top-20: -0.84 to +2.38 (real spread)
- Standout names: CELC (z=+1.66, 8 trials), RVMD (z=+2.38, 10 trials)
- binary_now at 93% coverage is strong enough for IC evaluation

### 2026-03-21 — Covered-subset IC check → NO SIGNAL

- **20d IC**: +0.007, t=+0.66, pos/neg 19/15 — indistinguishable from zero
- **63d IC**: -0.006, t=-1.11, pos/neg 10/21 — slightly negative (wrong direction)
- **Quintile spread (63d)**: -2.73pp (top Q underperforms bottom Q, 11/31 positive dates)
- **Per-bucket**: insufficient sample size for bucket-local IC
- **Root cause**: PI experience captures company scale (large-cap pharma), not drug quality.
  Names with experienced PIs (REGN, TECH, DNA) are large-cap, not the small-cap biotech
  names that drive top-K returns.
- **Decision**: RESEARCH COMPLETE, NO SIGNAL. Do not pursue DEM integration.
  Infrastructure stays (clean, tested, PIT-safe) but the signal lane is closed.

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
