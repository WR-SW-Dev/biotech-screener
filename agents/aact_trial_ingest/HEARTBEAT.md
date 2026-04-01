# HEARTBEAT.md — AACT Trial Ingest Agent

## Schedule

- **Daily**: 5:30 AM ET weekdays (before ctgov_poller and production run)
- **Catch-up**: on boot, fill missing dates (last 5 weekdays)
- **Pre-production check**: verify latest snapshot exists before daily model run

## Daily checklist

- [ ] Download or verify AACT source availability
- [ ] Validate schema (column presence, types, enum drift)
- [ ] Write `trial_master.parquet` snapshot
- [ ] Compute trial deltas vs prior snapshot
- [ ] Compute timing priors (phase completion, sponsor execution)
- [ ] Resolve sponsor → ticker linkage
- [ ] Emit `aact_health.json`
- [ ] Log failures, unmatched sponsors, schema drift
