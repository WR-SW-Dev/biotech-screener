# TOOLS.md — AACT Trial Ingest Agent

## Builder scripts

```bash
# Download latest AACT snapshot (pipe-delimited flat files)
python tools/fetch_aact_snapshot.py --as-of-date 2026-04-01

# Build normalized trial master from AACT snapshot
python tools/build_aact_trial_master.py --as-of-date 2026-04-01

# Compute deltas vs prior snapshot
python tools/build_aact_trial_deltas.py --as-of-date 2026-04-01

# Build sponsor-linked timing priors
python tools/build_aact_priors.py --as-of-date 2026-04-01

# Full pipeline (all steps)
python tools/fetch_aact_snapshot.py --as-of-date 2026-04-01 --full-pipeline

# Health check only
python tools/fetch_aact_snapshot.py --health-check
```

## Data sources (read-only)

- AACT daily database dump: `https://aact.ctti-clinicaltrials.org/pipe_files`
- `production_data/sponsor_alias_map.json` — ticker ↔ sponsor mapping
- `production_data/aact_manual_overrides.json` — manual linkage overrides
- Existing `collect_ctgov_data.py:TICKER_TO_SPONSORS` — seed mapping source

## Output locations

```
data/aact/
  snapshots/{as_of_date}/
    trial_master.parquet             — normalized trial table
    trial_status_deltas.jsonl        — status/completion/enrollment changes
    trial_results_deltas.jsonl       — newly posted results
    trial_timing_priors.parquet      — phase/sponsor timing distributions
    aact_health.json                 — ingest health report
  linked/
    ticker_trial_map_{date}.parquet  — sponsor-resolved trial linkage
    sponsor_trial_summary_{date}.parquet — sponsor execution stats
    phase_completion_priors_{date}.parquet — phase-specific timing priors
```

## Environment variables

- `AACT_DATABASE_URL` — PostgreSQL connection string (optional, for direct DB access)
- `AACT_DOWNLOAD_DIR` — override download directory for flat file snapshots
