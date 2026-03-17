# Spec 26: Data Collection Health Orchestrator

**Status**: PROPOSED
**Date**: 2026-03-17
**Depends on**: `run_screen.py`, `tools/run_daily_production.py`, `tools/data_integrity_audit.py`, `audit_ctgov_future_events.py`, `inputs_manifest`, replay bundles

## Goal

Make data-collection quality a first-class, default-on production artifact.

After each successful screen run, generate a compact, snapshot-local health package that answers:

1. what inputs were actually used
2. whether required inputs were present and fresh enough
3. whether key source collections look complete enough
4. whether downstream outputs are consistent with collected inputs
5. whether any source shows early signs of silent degradation

This is a **post-screen QA layer** only:
- no scoring changes
- no ranking changes
- no portfolio logic changes
- no catalyst extraction logic changes

## Why

The repo already has strong pieces of this, but they are not yet unified into one default-on collection-health flow:

- `run_screen.py` can already emit `inputs_manifest.json` with dependency paths, hashes, record counts, required/optional status, and verify/drift-check behavior.
- `tools/data_integrity_audit.py` already validates invariants, price recomputes, catalyst diffs, and root-cause summaries.
- CTGov future-event audit artifacts already exist and have been backfilled across many prior snapshots.
- daily production already has gate infrastructure, but collection completeness is still spread across multiple tools and outputs.

This spec consolidates those into a single post-screen "collection health" stage.

## Non-goals

- Do not rewrite collectors.
- Do not change DEM feature definitions.
- Do not alter ranking or portfolio outputs.
- Do not add external services or databases.
- Do not require cloud infrastructure.

## New behavior

### 1. Default-on collection health stage

After every successful `run_screen.py` snapshot write, run a new post-screen health stage that gathers and writes collection-health artifacts into the snapshot directory.

Default behavior:
- enabled automatically in normal production
- non-blocking for purely informational artifacts
- blocking only when configured hard thresholds fail

Add opt-out only if needed:
- `--no-data-collection-health`

### 2. New snapshot-local artifact family

For each snapshot date, write:

- `inputs_manifest.json`
  - default-on in write mode for production runs
- `data_collection_health.json`
- `data_collection_health.md`

If the underlying tools already emit these, preserve existing artifacts as-is and add summary aggregation rather than duplicating logic:
- `audit/invariants_report.csv`
- `audit/price_recompute_diff.csv`
- `audit/catalyst_diff_sample.csv`
- `audit/root_cause_summary.md`
- `ctgov_future_audit.json`
- `ctgov_future_audit.md`

## New summary artifact

### `data_collection_health.json`

Top-level schema:

```json
{
  "schema_version": "data_collection_health.v1",
  "as_of_date": "YYYY-MM-DD",
  "generated_at": "ISO-8601",
  "status": "PASS|WARN|FAIL",
  "inputs_manifest": {
    "mode": "write|verify",
    "all_required_present": true,
    "required_missing_count": 0,
    "warning_count": 0,
    "dependency_count": 0
  },
  "sources": {
    "core_inputs": {},
    "market_data": {},
    "ctgov": {},
    "sec": {},
    "fda": {},
    "options": {}
  },
  "audit": {
    "exit_code": 0,
    "status": "PASS|WARN|FAIL",
    "invariant_fail_count": 0,
    "price_diff_fail_count": 0,
    "explained_count": 0
  },
  "thresholds": {
    "...": "configured thresholds used for evaluation"
  },
  "flags": [],
  "notes": []
}
```

### `data_collection_health.md`

Human-readable daily summary with these sections:

1. overall status
2. input manifest summary
3. source coverage table
4. audit summary
5. CTGov future audit summary
6. warnings / fail reasons
7. suggested operator actions

## Source health checks

The purpose is not just "schema present," but "did we collect enough plausible data to trust the run?"

### A. Core inputs

Check:

* required manifest dependencies present
* hash recorded when applicable
* record counts available where meaningful
* required dependency drift absent in verify mode

Fields:

* dependency_count
* required_present_count
* required_missing_count
* optional_missing_count
* verify_mode
* drift_error_count

### B. Market data

Check:

* `price_history.csv` freshness through `as_of_date`
* market data schema gate status
* market data coverage gate status
* percent of ranked names with usable prices
* count of tickers with missing or stale prices

Suggested fields:

* latest_price_date
* universe_ticker_count
* price_covered_ticker_count
* price_coverage_pct
* stale_ticker_count
* schema_ok

### C. CTGov

Check:

* CTGov cache present for `as_of_date`
* trial record count
* tickers covered
* future PCD count and pct
* malformed-date count
* `pcd_after_cd_count`
* missing `disclosed_at` count
* far-future count

Suggested fields:

* cache_present
* trial_count
* tickers_covered
* future_pcd_count
* future_pcd_pct
* malformed_count
* pcd_after_cd_count
* missing_disclosed_at_count
* far_future_count

### D. SEC

Check:

* SEC cache present when enabled
* SEC-derived catalyst artifact exists
* record count / filing count if available
* percent of ranked names with SEC-derived context if measurable

Suggested fields:

* cache_present
* sec_8k_artifact_present
* filing_count
* catalyst_row_count

### E. FDA

Check:

* FDA cache present when enabled
* FDA catalyst/adcom artifact exists if expected
* record count if available

Suggested fields:

* cache_present
* adcom_artifact_present
* record_count

### F. Options

Check:

* options chain coverage for ranked names
* options chain coverage for top-N ranked names
* long-call report chain coverage if that artifact is enabled
* contracts available vs no-chain/no-trade reasons

Suggested fields:

* ranked_with_chain_count
* ranked_with_chain_pct
* top60_with_chain_count
* top60_with_chain_pct
* option_report_tradeable_count
* option_report_no_chain_count

## Threshold policy

Use explicit thresholds rather than implicit heuristics.

### Default thresholds

Store defaults in a new config file, for example:

`production_data/data_collection_health_thresholds.json`

Suggested defaults:

* `market_data_min_coverage_pct`: 0.95
* `ctgov_min_tickers_covered`: 250
* `ctgov_max_malformed_count`: 0
* `ctgov_max_pcd_after_cd_count`: 0
* `ctgov_max_missing_disclosed_at_count`: 0
* `options_top60_min_chain_coverage_pct`: 0.60
* `inputs_manifest_required_missing_max`: 0
* `audit_fail_max`: 0

### Severity rules

* FAIL:
  * missing required input dependency
  * market data coverage below hard floor
  * CTGov malformed count > 0
  * CTGov `pcd_after_cd_count` > 0
  * audit exit code critical
* WARN:
  * options chain coverage below soft floor
  * CTGov coverage unusually low but structurally valid
  * optional source/cache missing
  * audit warnings only
* PASS:
  * all hard thresholds pass and no warnings

## Integration plan

### 1. `run_screen.py`

Make production runs default to:

* `--inputs-manifest write` unless explicitly disabled
* writing `inputs_manifest.json` sidecar into snapshot dir

After snapshot save:

* invoke collection-health builder
* pass snapshot dir, as_of_date, and any already-computed metadata
* log warnings instead of crashing if non-critical summary generation fails

Add opt-out only if needed:

* `--no-data-collection-health`

### 2. `tools/run_daily_production.py`

Integrate collection health into the existing 5-step workflow as an explicit post-screen stage:

1. Price Refresh
2. Run Screen
3. Integrity Audit
4. Collection Health Summary
5. Post-Screen Gates / Promotion

Behavior:

* include collection-health status in `run_manifest.json`
* allow gates to consume `data_collection_health.json`
* promote snapshot only if hard collection-health checks pass

### 3. Reuse existing tools, do not fork logic

Do not re-implement:

* manifest building
* audit recomputation
* CTGov future audit logic

Instead:

* call or import existing logic where possible
* summarize outputs into one compact artifact

## New code

Add a new orchestrator, for example:

`tools/build_data_collection_health.py`

Responsibilities:

* load snapshot-local artifacts if present
* derive summary metrics from manifest + audit + CTGov audit + options outputs
* evaluate thresholds
* write `data_collection_health.json`
* write `data_collection_health.md`
* return structured status for callers

Provide a programmatic entry point such as:

* `run_from_screen(snapshot_dir: Path, as_of_date: str, ...) -> Dict[str, Any]`

This should be safe to call from `run_screen.py` without aborting the main run unless a hard-fail mode is requested.

## Markdown report layout

`data_collection_health.md` should include:

### Overall

* PASS / WARN / FAIL
* one-line reason summary

### Inputs Manifest

* dependency counts
* required missing count
* verify/drift results if relevant

### Source Coverage

| Source      | Status         | Key metrics | Notes |
|-------------|----------------|-------------|-------|
| Core Inputs | PASS           | ...         | ...   |
| Market Data | PASS/WARN/FAIL | ...         | ...   |
| CTGov       | PASS/WARN/FAIL | ...         | ...   |
| SEC         | PASS/WARN/FAIL | ...         | ...   |
| FDA         | PASS/WARN/FAIL | ...         | ...   |
| Options     | PASS/WARN/FAIL | ...         | ...   |

### Audit Summary

* invariant failures
* price recompute failures
* explained mismatches
* root-cause summary present / absent

### CTGov Future Audit

* total trials
* tickers covered
* future PCD count / pct
* malformed count
* PCD-after-CD count
* missing disclosed_at count
* far-future count

### Actions

Examples:

* "Rebuild CTGov cache for as_of_date"
* "Investigate market_data_coverage gate"
* "Options chain coverage low for top-60 names"
* "Manifest drift vs prior bundle; replay not comparable"

## Testing

Add tests covering:

### Unit tests

* manifest summary parsing
* threshold evaluation
* PASS / WARN / FAIL classification
* markdown/json writer behavior
* missing optional artifacts handled gracefully

### Integration tests

* successful `run_screen.py` writes collection-health artifacts
* missing `inputs_manifest` produces WARN/clear note, not crash
* CTGov audit present gets summarized correctly
* missing CTGov audit produces WARN only if CTGov itself ran but audit absent
* hard threshold breach propagates FAIL status to daily production gate
* opt-out flag skips artifact generation cleanly

### Replay / regression tests

* replay bundle run preserves deterministic manifest behavior
* collection-health summary is stable under replay for the same inputs
* threshold-only changes do not silently alter historical PASS/WARN/FAIL without explicit config diff

## Acceptance checklist

- [ ] Production runs write `inputs_manifest.json` by default
- [ ] Production runs write `data_collection_health.json`
- [ ] Production runs write `data_collection_health.md`
- [ ] Existing audit outputs are reused, not duplicated
- [ ] Existing CTGov future audit outputs are reused, not duplicated
- [ ] Missing optional artifacts degrade gracefully
- [ ] Missing required inputs produce FAIL
- [ ] Threshold config is explicit and version-controlled
- [ ] `run_daily_production.py` can consume collection-health status
- [ ] Replay / manifest workflows remain deterministic
- [ ] No DEM scoring or ranking behavior changed

## Suggested operator workflow

Normal production:

* run daily production as usual
* inspect `data_collection_health.md`
* only investigate deeper files when status is WARN or FAIL

Replay / debugging:

* run with manifest verify / replay bundle
* compare collection-health summaries across baseline vs current
* use source-level sections to isolate whether drift came from inputs, collectors, or downstream derivations

## Not in scope

* new external data vendors
* automated collector retries
* order execution changes
* ranking methodology changes
* alpha / portfolio threshold changes
* rebuilding CTGov/SEC/FDA collectors from scratch
