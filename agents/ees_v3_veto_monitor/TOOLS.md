# TOOLS.md — EES v3 Veto Monitor

## Primary command

```bash
python3 scripts/research/ees_v3_raw_veto_shadow_card.py --as-of-date YYYY-MM-DD
```

Reads `data/snapshots/YYYY-MM-DD/rankings.csv`, applies raw_veto_core, settles matured ledger rows,
appends to `artifacts/shadow/ees_v3_raw_veto_shadow_ledger.jsonl`.

## Read shadow ledger

```bash
python3 -c "
import json
rows = [json.loads(l) for l in open('artifacts/shadow/ees_v3_raw_veto_shadow_ledger.jsonl')]
veto_rows = [r for r in rows if r.get('n_vetoed', 0) > 0]
print(f'Total rows: {len(rows)} | Veto-active: {len(veto_rows)}')
settled_20d = [r for r in veto_rows if r.get('veto_alpha_20d') is not None]
print(f'Settled 20d: {len(settled_20d)}')
if settled_20d:
    alpha = sum(r['veto_alpha_20d'] for r in settled_20d) / len(settled_20d)
    print(f'Mean 20d veto alpha: {alpha:.1%}')
"
```

## Check today's snapshot for EES v3 fields

```bash
python3 -c "
import csv
rows = list(csv.DictReader(open('data/snapshots/\$(date +%F)/rankings.csv')))
print('ees_v3_score present:', 'ees_v3_score' in rows[0] if rows else 'NO ROWS')
print('row count:', len(rows))
"
```

## Confirm no production files changed (governance check)

```bash
git diff --name-only run_screen.py event_ev/ production_data/ tools/run_daily_production.py 2>/dev/null
# Expected output: empty (no changes)
```

## Required JSON shadow card schema

```json
{
  "agent": "ees_v3_veto_monitor",
  "as_of_date": "YYYY-MM-DD",
  "created_at_utc": "ISO-8601",
  "freeze_status": "ACTIVE",
  "production_decisioning": false,
  "lead_policy": "raw_veto_core",
  "verdict": "MONITORING_OK",
  "snapshot": {
    "rankings_path": "data/snapshots/YYYY-MM-DD/rankings.csv",
    "row_count": 0
  },
  "base_ranker": {
    "selected_count": 0,
    "tickers": []
  },
  "raw_veto_core": {
    "vetoed_count": 0,
    "vetoed_tickers": [],
    "veto_rate": 0.0,
    "survivor_count": 0,
    "survivor_tickers": []
  },
  "coverage": {
    "priced_move_pct_coverage_all": 0.0,
    "priced_move_pct_coverage_ranker_selected": 0.0,
    "ees_v3_score_coverage_all": 0.0
  },
  "failure_modes": {
    "no_options_coverage_count": 0,
    "dilution_overhang_count": 0,
    "market_already_priced_count": 0,
    "catalyst_too_far_count": 0,
    "stale_or_delisted_count": 0,
    "unknown_failure_mode_count": 0
  },
  "forward_performance": {
    "completed_5d_observations": 0,
    "completed_10d_observations": 0,
    "completed_20d_observations": 0,
    "required_20d_observations": 20,
    "shadow_gate_status": "MET",
    "cumulative_5d_veto_alpha": null,
    "cumulative_10d_veto_alpha": null,
    "cumulative_20d_veto_alpha": null,
    "alpha_positive_rate_20d": null
  },
  "warnings": [],
  "forbidden_actions_checked": {
    "final_score_changed": false,
    "selector_changed": false,
    "sizing_changed": false,
    "production_gate_changed": false
  }
}
```

## Required Markdown memo sections

```
# EES v3 Veto Shadow Status — YYYY-MM-DD

## Verdict
## Governance Status
## Snapshot Inputs
## Raw Veto Core Summary
## Vetoed Names
## Survivor Names
## Coverage Diagnostics
## Failure-Mode Diagnostics
## Forward Performance
## Warnings
## Freeze-Lift Relevance
## What Is Not Approved
```

Required boilerplate in "What Is Not Approved":
```
This monitor does not approve production promotion.
This monitor does not approve freeze lift.
This monitor does not change final_score, ranker, selector, sizing, portfolio
construction, gates, cron, or trading behavior.
EES v3 raw_veto_core remains diagnostic-only.
```

## Allowed write paths

```
artifacts/shadow/ees_v3_veto_shadow_card_*.json
artifacts/readiness/EES_V3_VETO_SHADOW_STATUS_*.md
agents/ees_v3_veto_monitor/memory/
```

## Cadence

Daily after production snapshot, before daily status brief. **CRON NOT YET ENABLED.**
Manual invocation only until operator approves scheduling.
