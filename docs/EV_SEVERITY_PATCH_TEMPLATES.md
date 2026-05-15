# ev_severity_score Blank — Patch Templates

After 16:30 diagnostics run, use this document to identify the exact failure mode and apply the right patch.

## Evidence Interpretation

Run: `python tools/diagnose_ev_severity.py --date 2026-05-15`

### Case 1: Column Does Not Exist (Critical Evidence)
**Diagnostic output:** "ev_severity_score column exists: False"

**Root cause:** `enrich_csv_rows()` was never called, or the import failed silently.

**Patch target:** `run_screen.py:6458-6461`

**Likely fixes:**
1. Import statement failed → check for circular import or missing module
2. Condition gates the call → check if there's a try/except that swallows the call
3. Wrong csv_rows object being passed → verify list vs generator

**Template patch (assume import is working):**
```python
# run_screen.py around line 6461

# BEFORE:
_runway_overlays_for_sidecar = _enrich_runway(csv_rows, as_of_date)

# AFTER (add debug log before call):
logger.debug(f"Before enrich_runway: {len(csv_rows)} rows, type={type(csv_rows)}")
_runway_overlays_for_sidecar = _enrich_runway(csv_rows, as_of_date)
logger.debug(f"After enrich_runway: 'ev_severity_score' in first row = {'ev_severity_score' in csv_rows[0] if csv_rows else 'EMPTY'}")
```

---

### Case 2: Column Exists But All Blank (Severity Issue)
**Diagnostic output:** "ev_severity_score: 0/X rows have non-blank values"

**Root cause:** `score_batch()` computed None for all rows, or there's a type/conversion issue.

**Patch targets:**
- `event_ev/runway_severity.py:507` (score_batch call)
- `event_ev/runway_severity.py:509-517` (write-back loop)

**Sub-cases to check:**

#### Case 2a: score_batch returns None scores
**Check:** Run diagnostic; if it says "score_batch() returned None. May be upstream data issue."

**Likely causes:**
- Missing input fields (months_to_cash_out, catalyst timing)
- PIT financials not loaded for the as_of_date
- All tickers in batch have None runway

**Patch approach (defensive):**
```python
# event_ev/runway_severity.py:509-517

# Log which rows got None scores
for row, ov in zip(csv_rows, overlays):
    if ov.ev_severity_score is None:
        logger.warning(f"Row {row['ticker']}: ev_severity_score computed as None")
        
    row["ev_severity_score"] = ov.ev_severity_score
    # ... other assignments
```

#### Case 2b: Write-back doesn't persist (mutation issue)
**Check:** If score_batch() works but values don't appear in csv_rows.

**Likely causes:**
- csv_rows is a generator, not a list (zip() consumed it)
- csv_rows is a list of immutable objects
- The dict mutation isn't visible to the caller

**Patch approach (verify before write):**
```python
# event_ev/runway_severity.py:506-507

model = RunwaySeverityModel()
overlays = model.score_batch(csv_rows, as_of_date)

if not overlays:
    logger.error(f"score_batch returned empty. csv_rows type={type(csv_rows)}, len={len(csv_rows)}")
    return overlays
```

---

### Case 3: Direct Test Works, But Snapshot Doesn't (Integration Issue)
**Diagnostic output:** "score_batch() returned scores. Sample: 0.45" BUT column is blank in snapshot.

**Root cause:** Enrichment is called in write_snapshot flow, but the wrong csv_rows object is written to disk.

**Patch targets:**
- `run_screen.py:6509+` (where csv_rows is written to disk)
- Check if a different csv_rows object is being used after enrichment

**Patch approach:**
```python
# run_screen.py after enrichment block

# Verify the SAME csv_rows object is being written
logger.debug(f"About to write {len(csv_rows)} rows to disk")
logger.debug(f"'ev_severity_score' in rows[0]: {'ev_severity_score' in csv_rows[0] if csv_rows else 'EMPTY'}")

# [Write to CSV happens here]
# Then verify what was written
with open(output_csv, 'r') as f:
    written_rows = list(csv.DictReader(f))
    written_ev = sum(1 for r in written_rows if 'ev_severity_score' in r and r.get('ev_severity_score'))
    logger.info(f"Wrote {written_ev}/{len(written_rows)} rows with ev_severity_score values")
```

---

## Testing Plan

After patch:

1. Run the snapshot manually:
   ```bash
   python run_screen.py --as-of-date 2026-05-15 --output data/snapshots/2026-05-15/rankings.csv
   ```

2. Check results:
   ```bash
   python tools/diagnose_ev_severity.py --date 2026-05-15
   ```

3. Run production QA:
   ```bash
   python tools/production_qa_check.py --as-of-date 2026-05-15
   ```

4. Commit with message:
   ```
   Fix Spec 101: ev_severity_score blank (runtime export-path diagnosis)
   
   Diagnosis: [describe which case: column missing / values None / mutation issue]
   Root cause: [one sentence]
   Fix: [one sentence]
   
   Tests: [count] pass; QA check passes.
   ```

---

## Do NOT Do

- Do not manually edit snapshots
- Do not backfill with test data
- Do not lower production QA thresholds to mask the issue
- Do not change ranker/selector logic as a workaround
