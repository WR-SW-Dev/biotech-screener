# Scientific Cartography Phase 13A — Artifact Review Runbook

**Status:** `OPERATIONALLY_VALIDATED_READY_FOR_HUMAN_REVIEW`  
**Date:** 2026-06-18  
**Operational Review:** 9/9 gates PASS  

---

## Overview

This runbook provides a **read-only, human-centered workflow** for reviewing Scientific Cartography diagnostic artifacts. It is **not** a production deployment guide, nor does it include cron automation or scoring integration.

**Purpose:** Validate that the diagnostic stack produces useful, interpretable artifacts before any automated or production-adjacent workflow decisions.

---

## Authority & Boundaries

### What This Runbook Covers

```text
✅ How to run the diagnostic stack
✅ How to interpret disease map artifacts
✅ How to conduct human review
✅ What the governance boundaries are
✅ When to stop and escalate
```

### What This Runbook Does NOT Cover

```text
❌ Cron automation
❌ Production pipeline wiring
❌ Scoring integration
❌ Ranker/selector/sizing changes
❌ Dashboard implementation
❌ Deployment authorization
```

---

## Quick Start: Run Diagnostics Once

### Prerequisites

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Verify tests pass
python3 -m pytest tests/scientific_cartography/ -q
# Expected: 323/323 PASS

# Check repo is clean
git status -sb
# Expected: main synced with origin/main
```

### Generate Artifacts (Read-Only)

```bash
# Choose a snapshot date
SNAPSHOT_DATE="2026-06-18"
OUTPUT_DIR="/tmp/scientific_cartography_review/${SNAPSHOT_DATE}"

# Run diagnostics
python3 tools/run_scientific_cartography_diagnostics.py \
  --as-of-date ${SNAPSHOT_DATE} \
  --snapshot-dir data/snapshots_pit/${SNAPSHOT_DATE} \
  --ctgov-cache cache/ctgov \
  --output-dir ${OUTPUT_DIR} \
  --quiet

# Verify
ls -la ${OUTPUT_DIR}/
# Expected: disease_map_summary.json, landscape_features.jsonl, etc.
```

### Review Disease Maps Manually

```bash
# Pick a disease map
cat ${OUTPUT_DIR}/disease_map_summary.md | head -100

# Or inspect JSON
python3 -c "
import json
data = json.load(open('${OUTPUT_DIR}/disease_map_summary.json'))
print(f\"Diseases mapped: {data['disease_count']}\")
print(f\"Programs: {data['program_count']}\")
print(f\"Coverage: {data['unique_tickers']} tickers\")
"
```

---

## Review Protocol

### Step 1: Health Check

Run gates 1–9 from the operational review:

```bash
# Gate 1: tests pass
python3 -m pytest tests/scientific_cartography/ -q

# Gate 2: artifacts generate without side effects
python3 tools/run_scientific_cartography_diagnostics.py \
  --as-of-date 2026-06-18 \
  --snapshot-dir data/snapshots_pit/2026-06-18 \
  --ctgov-cache cache/ctgov \
  --output-dir /tmp/sc_review

# Gate 7: no production files changed
git status -sb
git diff --name-only | grep -E 'run_screen|run_daily_production|ranker|selector|sizing|final_score' || echo "✓ Clean"

# Gate 6: no scoring fields
grep -RniE '\b(score|alpha|rank|ranking|buy|sell|recommend)\b' /tmp/sc_review/diseases/ 2>/dev/null | grep -v "not an investment recommendation" || echo "✓ No forbidden fields"
```

### Step 2: Sample Review (Pick 3–5 Diseases)

For each disease, ask:

```text
1. Can you understand the disease identity?
   - MONDO ID present?
   - Therapeutic area clear?
   - Raw names preserved for audit trail?

2. Can you see the competitive landscape?
   - Program count makes sense?
   - Company/ticker coverage reasonable?
   - Mechanism/target/modality listed?

3. Are unknowns transparent?
   - Missing MONDO mapped or marked?
   - Missing ticker/mechanism/target noted?
   - Warnings visible?

4. Are source refs sufficient?
   - Can you trace back to primary sources?
   - Multi-source or single-source evident?

5. Is the governance clear?
   - Disclaimer present?
   - No investment-action language?
   - Not misleading as a scoring tool?
```

### Step 3: Coverage Validation

```bash
# Check summary counts
python3 -c "
import json
data = json.load(open('/tmp/sc_review/disease_map_summary.json'))
print('Programs:', data['program_count'])
print('Assets:', data['asset_count'])
print('Companies:', data['company_count'])
print('Tickers:', data['unique_tickers'])
print('Mapped MONDO:', data.get('unique_mondo_ids', 0))
print('Unknown diseases:', data['program_count'] - data.get('unique_mondo_ids', 0))
"
```

### Step 4: Boundary Verification

```bash
# Ensure no production integration happened
git diff --name-only | wc -l
# Expected: 0 (no files changed)

# Ensure no scoring fields snuck in
grep -r "final_score\|ranker\|selector\|sizing" /tmp/sc_review/diseases/ || echo "✓ No scoring integration"
```

---

## Interpretation Guide

### Disease Map Structure

Each disease artifact contains:

**disease_identity**
- MONDO ID (primary key if mapped)
- Therapeutic area (Phase 8 ontology)
- Parent disease (hierarchy)
- Raw names observed (audit trail)

**summary**
- program_count: total asset-indication records
- approved_incumbent_count: approved programs
- cluster_count: competitive clusters
- mechanism/target/modality counts

**standard_of_care**
- Approved assets, companies, tickers
- Approved mechanisms
- Source references

**observed_tickers**
- Public tickers in disease (diagnostic only)

**unknowns_and_low_coverage**
- Missing MONDO ID count
- Missing ticker/mechanism/target/stage
- Explicit warnings

**governance**
- read_only_diagnostic: true
- production_model_change: false
- All scoring/ranking fields: false

### What Disease Maps Are

```text
✅ Diagnostic reference for research review
✅ Transparent competitive landscape view
✅ Audit trail via source refs
✅ Unknown/gap identification
✅ Deterministic, reproducible outputs
```

### What Disease Maps Are NOT

```text
❌ Portfolio construction signals
❌ Scoring or ranking inputs
❌ Investment recommendations
❌ Replacement for due diligence
❌ Automated decision triggers
```

---

## Workflow Example: Review One Disease

```bash
# 1. Run diagnostics (once, reusable)
OUTPUT_DIR="/tmp/sc_review_2026-06-18"
python3 tools/run_scientific_cartography_diagnostics.py \
  --as-of-date 2026-06-18 \
  --snapshot-dir data/snapshots_pit/2026-06-18 \
  --ctgov-cache cache/ctgov \
  --output-dir ${OUTPUT_DIR} \
  --quiet

# 2. Pick a disease (e.g., Acute Pain)
DISEASE="acute-pain"

# 3. Read the human-readable map
cat ${OUTPUT_DIR}/diseases/${DISEASE}/disease_map.md

# 4. Inspect the structured data
python3 -c "
import json
artifact = json.load(open('${OUTPUT_DIR}/diseases/${DISEASE}/disease_map.json'))
print('Disease:', artifact['disease']['normalized_disease_name'])
print('MONDO ID:', artifact['disease']['mondo_id'])
print('Programs:', artifact['summary']['program_count'])
print('Tickers:', ', '.join(artifact['observed_tickers']))
print('Unknowns:', artifact['unknowns'])
print('Governance:', artifact['governance'])
"

# 5. Export for spreadsheet review
python3 -c "
import pandas as pd
df = pd.read_csv('${OUTPUT_DIR}/diseases/${DISEASE}/disease_map.csv')
print(df[['ticker', 'company_name', 'asset_name', 'clinical_stage', 'mechanism_class']].to_string())
"

# 6. Assess interpretability
echo "Review checklist:"
echo "[ ] Can you understand the disease?"
echo "[ ] Are unknowns clear?"
echo "[ ] Are source refs sufficient?"
echo "[ ] Is the governance statement visible?"
echo "[ ] Does it help your review?"
```

---

## Known Limitations

### By Design (Governance)

- **No scoring:** Diagnostics are descriptive, never numeric scores
- **No ranker integration:** This layer does not feed portfolio construction
- **No automation:** All artifact generation is manual and read-only
- **Unknown preservation:** Records with missing MONDO/ticker/mechanism are kept and flagged, not dropped

### By Phase Scope

- **Phase 12:** Per-disease artifacts only, not real-time updates
- **Phase 13A:** Runbook and manual review, not cron or dashboard
- **Phase 13B+:** Dashboard or automation deferred until Phase 13A validation is complete

### Known Open Questions

- Do disease maps help research review in practice?
- Are the categories (mechanism novelty, white-space, crowding) useful descriptors?
- Should any disease maps be hidden or filtered from future users?
- Are source refs sufficient to audit claims?

---

## Escalation

### When to Stop and Escalate

Stop the review and escalate if:

```text
1. Artifacts contain forbidden scoring/ranking fields
   → Report governance violation immediately

2. Unknowns are silently dropped instead of preserved
   → Report data loss

3. Production files changed (ranker, selector, sizing, final_score)
   → Report integration outside scope

4. Disease map makes unsupported causal claims
   → Recommend governance update

5. Artifact is misleading or could be misinterpreted as investment signal
   → Recommend disclaimer revision
```

### Escalation Path

```text
1. Document the issue (what, where, why it matters)
2. Note the governance boundary it violates
3. Report to project owner with artifact examples
4. DO NOT merge or automate until resolved
```

---

## Next Decision: Phase 13B+

This runbook is valid as long as:

```text
✅ All 323 tests pass
✅ No production integration occurs
✅ Governance boundaries remain locked
✅ Artifacts remain read-only diagnostic
```

**When to move to Phase 13B (dashboard/automation):**

- At least one complete real-world disease review has been conducted
- Governance review has been signed off
- Use case for automated generation has been validated
- No governance violations found in Phase 13A
- Team agrees that the workflow is useful before scaling

---

## Reference

- **Phase 8:** Disease Ontology (MONDO mapping)
- **Phase 9:** Asset Indication Map (company|asset|disease)
- **Phase 10:** Enhanced Clusters (competitive grouping)
- **Phase 11:** Landscape Context (competition/novelty categories)
- **Phase 12:** Disease Map Artifacts (this layer)

**Operational Status:**
- Code: COMMITTED (commit 8d2f2757)
- Tests: 323/323 PASS
- Review: 9/9 gates PASS
- Governance: READ_ONLY_DIAGNOSTIC, NO_PRODUCTION_WIRING
- Status: **READY_FOR_HUMAN_VALIDATION**
