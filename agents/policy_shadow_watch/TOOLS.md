# TOOLS.md — Policy Shadow Watch

## Primary tool

```bash
python tools/build_policy_shadow_compare.py
python tools/build_policy_shadow_compare.py --as-of-date 2026-03-28
```

Compares current flat-weight positions against tier-weighted and
tier+exit counterfactual policies. Writes daily comparison + appends
to rolling history.

Already wired into `run_screen.py` as a post-pipeline step.

## Input artifacts

| Artifact | Location | Cadence |
|----------|----------|---------|
| Shadow positions | `artifacts/live_shadow/positions/{date}.json` | Daily |
| Rankings | `data/snapshots/{date}/rankings.csv` | Daily |
| Attribution | `artifacts/live_shadow/attribution/{date}/` | Daily |
| Price history | `production_data/price_history.csv` | Daily |
| Policy history | `artifacts/policy_shadow/tier_weighted/history.jsonl` | Append |

## Output artifacts

| Artifact | Location |
|----------|----------|
| Daily comparison | `artifacts/policy_shadow/tier_weighted/{date}_comparison.json` |
| Daily markdown | `artifacts/policy_shadow/tier_weighted/{date}_comparison.md` |
| Rolling history | `artifacts/policy_shadow/tier_weighted/history.jsonl` |

## Research reference

| Script | Purpose |
|--------|---------|
| `scripts/research/backtest_tier_weighted_policy.py` | Full historical replay |
