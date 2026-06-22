# BIOTECH_MCP_PATH_MAP — 2026_06_22

Concise reference: artifact paths for the biotech-mcp read-only server.

## Tool → Artifact Mapping

| Tool | Resolved Path / Glob | Format | Latest Example | Missing Behavior | Notes |
|------|---------------------|--------|-----------------|------------------|-------|
| `list_snapshots` | `data/snapshots/` | dir (YYYY-MM-DD dated subdirs) | `data/snapshots/2026-06-18/` | UNAVAILABLE (dir not found); empty list | Filters non-date dirs; all read-only |
| `read_latest_snapshot_manifest` | `data/snapshots/<YYYY-MM-DD>/snapshot_manifest.json` | JSON | `data/snapshots/2024-12-27/snapshot_manifest.json` | MISSING (file not found); path included | Keys: snapshot_dir, files (array with name, size_bytes, sha256) |
| `read_gate_verdicts` | `artifacts/gate_verdict_ledger.jsonl` | JSONL (historical ledger) | `artifacts/gate_verdict_ledger.jsonl` | MISSING (file not found); fallback note to ees_gate_diagnostics.json | One verdict per line; limit 1–50 (default 5) |
| `read_phase2_health` | `data/snapshots/<YYYY-MM-DD>/phase2_health.json` | JSON | `data/snapshots/2024-12-27/phase2_health.json` | MISSING (file not found); path included | Keys: status, reasons, metrics (dict with exposure dict), thresholds |
| `read_rankings_schema` | `data/snapshots/<YYYY-MM-DD>/rankings.csv` | CSV | `data/snapshots/2024-12-27/rankings.csv` | MISSING (file not found); path included | Returns: column_count, columns (full header array); 100+ columns |
| `read_event_ev_feature_coverage` | `artifacts/scientific_cartography/<YYYY-MM-DD>/landscape_feature_coverage_report.json` | JSON | `artifacts/scientific_cartography/2026-06-17/landscape_feature_coverage_report.json` | MISSING (file not found); path included | Keys: as_of_date, program_records, crowding/white-space scores, warnings |
| `read_forward_eval_ic_ledger` | `artifacts/readiness/forward_eval_ic_baseline.json` | JSON | `artifacts/readiness/forward_eval_ic_baseline.json` | MISSING (file not found); note about tools/forward_eval_ic_ledger.py | Keys: window_start, window_end, floor, path_c_status, observations (array) |
| `read_scientific_cartography_status` | `artifacts/scientific_cartography/<YYYY-MM-DD>/scientific_cartography_status.json` | JSON | `artifacts/scientific_cartography/2026-06-17/scientific_cartography_status.json` | MISSING (file not found); path included | Keys: as_of_date, status, artifacts_written, warnings, governance (dict) |
| `list_disease_map_artifacts` | `artifacts/scientific_cartography/<YYYY-MM-DD>/` | dir + JSONL files | `artifacts/scientific_cartography/2026-06-17/` | MISSING (dir not found); path included | Files: disease_map_summary.json, program_records.jsonl, competitive_clusters.jsonl, etc. |
| `read_semgrep_findings` | `.semgrep/governance.yml` | YAML rules file (rules exist) | `.semgrep/governance.yml` | NOT_FOUND (findings artifact not persisted); rules status reported | Findings generated dynamically by GitHub Actions; no static JSON/SARIF in repo |
| `run_readonly_diagnostics` | (in-process; no script execution) | (read-only rollup) | (returns check status) | UNAVAILABLE if no snapshots/cartography | Returns mode, executes_scripts: false, mutates: false, network: false |

## Date Validation

All date-accepting tools validate input against `^\d{4}-\d{2}-\d{2}$` (YYYY-MM-DD).
Defaults to latest snapshot/cartography dir when date omitted (lexicographic sort).

## Safety Constraints (by construction)

- ✓ No shell escape (no subprocess)
- ✓ No arbitrary file read (pinned to fixed subtrees)
- ✓ No writes (all tools read-only)
- ✓ No git / config / job mutations
- ✓ No network
- ✓ Bounded output (ledger tails, CSV row caps, dir entry caps)

## Real Snapshot Structure

```
data/snapshots/2026-06-18/
├── snapshot_manifest.json
├── phase2_health.json
├── rankings.csv
├── decision_portfolio.json/csv
├── ees_gate_diagnostics.json
├── expectation_error_overlay.json
├── metadata.json
└── audit/, action_lists/, drift_guardrails/, inputs/ (subdirs)
```

## Real Scientific Cartography Structure

```
artifacts/scientific_cartography/2026-06-17/
├── scientific_cartography_status.json
├── landscape_feature_coverage_report.json
├── disease_map_summary.json
├── program_records.jsonl
├── competitive_clusters.jsonl
├── landscape_features.jsonl
└── diseases/, review/ (subdirs, typically empty)
```

## Test Coverage

File: `tests/test_biotech_mcp_server.py`
- 25 hermetic tests (all paths use tmp fixtures)
- Covers: date validation, missing files, valid reads, JSON/CSV parsing, JSONL tails, JSON-RPC dispatch, path traversal protection, read-only safety
- Status: all passing ✓
