# HEARTBEAT.md — Policy Shadow Watch

## Cadence

- **Daily**: after shadow portfolio + attribution are built (via run_screen)
- **Weekly**: summarize cumulative policy gap, win rate, excluded names

## Heartbeat check

1. Read `artifacts/policy_shadow/tier_weighted/history.jsonl`
2. Compute rolling cumulative gap (tiered vs current)
3. Flag oversized low-tier positions from latest comparison
4. Flag headwind+drawdown holds from latest comparison
5. Report alert level

## Health indicators

- Latest comparison is < 2 days old
- History has >= 5 rows for meaningful comparison
- Policy gap direction is stable (not oscillating randomly)
- Exit overlay is catching known problem names
