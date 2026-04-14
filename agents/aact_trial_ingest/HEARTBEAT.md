# HEARTBEAT.md — AACT Trial Ingest Agent

## Schedule

- **Weekly**: runs inside daily production (16:30 ET) on Mondays, or if latest snapshot >7 days stale
- Download is 2.3GB per run; weekly cadence is sufficient for trial-level data
- Lightweight ctgov cache (`warm_caches.py --sources ctgov`) still runs daily at 14:00 ET
- Heartbeat check: OK if latest snapshot within 8 days

## Weekly checklist

- [ ] Download or verify AACT source availability
- [ ] Validate schema (column presence, types, enum drift)
- [ ] Write `trial_master.parquet` snapshot
- [ ] Compute trial deltas vs prior snapshot
- [ ] Compute timing priors (phase completion, sponsor execution)
- [ ] Resolve sponsor → ticker linkage
- [ ] Emit `aact_health.json`
- [ ] Log failures, unmatched sponsors, schema drift
