# TOOLS.md — IC Health Monitor Agent

## Primary data source

```bash
cat artifacts/ic_dashboard/$(date +%Y-%m-%d)_dashboard.json
```

## History for trend analysis

```bash
cat artifacts/ic_dashboard/history.jsonl
```

## Manual IC dashboard rebuild (if stale)

```bash
python tools/build_ic_dashboard.py --as-of-date $(date +%Y-%m-%d)
```

## Key fields in dashboard JSON

- `attention`: LOW / MEDIUM / HIGH
- `signals`: dict of signal_name → {latest_ic, health, hit_rate, n_snapshots}
- `health` values: HEALTHY / WEAK / WARN / ALERT

## Load-bearing signal check

The two signals that affect live rankings:
1. `clinical_optionality_pct_dev` — optionality anchor
2. `inst_delta_z` — institutional delta sort weight

If either of these degrades to WARN or ALERT, that is a CRITICAL alarm
because it means the primary sort drivers are losing predictive power.

## Cadence

- Daily after production run (17:45 ET, after ops/sentinel/qa)
