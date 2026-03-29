# TOOLS.md — Bioshort Watch

## Primary tool

```bash
python tools/build_bioshort_watch.py
python tools/build_bioshort_watch.py --as-of-date 2026-03-26
```

Reads latest and prior `hedge_report_*.json`, diffs key fields, writes
`artifacts/bioshort_watch/{date}_watch.json` and `{date}_watch.md`.

## Upstream tool (read-only reference)

```bash
python tools/biotech_hedge_report.py --as-of-date 2026-03-28
```

Generates the hedge report this agent consumes. Run by ops or manually;
bioshort_watch does NOT trigger this — it only reads the output.

## Input artifacts

| Artifact | Location | Cadence |
|----------|----------|---------|
| Hedge report JSON | `output/hedge_report/hedge_report_*.json` | Weekly |
| Verdict | `output/hedge_report/BIOSHORT_VERDICT.json` | Weekly |
| Verdict markdown | `output/hedge_report/BIOSHORT_VERDICT.md` | Weekly |
| Archive | `output/hedge_report/archive/` | Weekly |
| Shadow positions | `artifacts/live_shadow/positions/{date}.json` | Daily |

## Output artifacts

| Artifact | Location |
|----------|----------|
| Watch JSON | `artifacts/bioshort_watch/{date}_watch.json` |
| Watch markdown | `artifacts/bioshort_watch/{date}_watch.md` |
