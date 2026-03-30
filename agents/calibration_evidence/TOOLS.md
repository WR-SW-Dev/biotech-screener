# TOOLS.md — Calibration Evidence Accumulator

## Builder

```
python tools/build_calibration_evidence.py --as-of-date 2026-03-30
```

## Data sources (read-only)

- `artifacts/postmortem/{date}/{ticker}.json` — resolved event records
- `data/snapshots/{date}/rankings.csv` — pre-event model state
- `artifacts/live_shadow/positions/{date}.json` — shadow portfolio membership
- `production_data/price_history.csv` — post-event returns

## Output location

```
artifacts/calibration_evidence/
  {date}_evidence.json    — structured evidence (signal tracker + threshold audit + calibration curve)
  {date}_evidence.md      — human-readable summary
  ledger.jsonl            — rolling evidence ledger
```
