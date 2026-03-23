# TOOLS.md — Ruleset Sentinel Agent

## Health monitor (primary check)

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 tools/ruleset_health_monitor.py --as-of-date YYYY-MM-DD
```

## Read drift artifacts

| Artifact | Path |
|----------|------|
| Drift report | `data/snapshots/YYYY-MM-DD/drift_guardrails/drift_report.json` |
| Drift markdown | `data/snapshots/YYYY-MM-DD/drift_guardrails/drift_report.md` |
| Phase-2 health | `data/snapshots/YYYY-MM-DD/phase2_health.json` |
| Ruleset health sidecar | `data/snapshots/YYYY-MM-DD/ruleset_health.json` |
| Health history | `artifacts/ruleset_health_history.jsonl` |

## Read promotion/rollback receipts

```bash
ls artifacts/promotions/
cat artifacts/promotions/latest_receipt.json
```

## Rollback command (only when human requests)

```bash
python3 scripts/promote_ruleset.py --rollback --reason "REASON_HERE"
```

Auto-discovers last-known-good (LKG) from receipt chain.

## Key metrics to compare vs baseline

| Metric | Source | Concern threshold |
|--------|--------|------------------|
| top-60 overlap | drift_report.json | < 90% |
| mean rank shift | drift_report.json | > 5.0 |
| turnover | phase2_health.json | > 40% |
| catalyst coverage | phase2_health.json | < 80% |
| consecutive WARNs | health_history.jsonl | >= 3 |

## Decision matrix

| WARNs | Overlap | Recommendation |
|-------|---------|---------------|
| 0 | >= 90% | OK |
| 1 | >= 85% | WATCH |
| 2 | >= 85% | WATCH (escalate) |
| 2+ | < 85% | ROLLBACK_RECOMMENDED |
| 3+ | any | ROLLBACK_RECOMMENDED |
