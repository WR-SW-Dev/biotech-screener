# HEARTBEAT.md — Ops Supervisor Agent

## Checklist

1. Verify `artifacts/ops_supervisor/{today}_supervisor.json` exists
2. If missing and past 20:45 ET: report missing verdict (do not reply HEARTBEAT_OK)
3. If present: one-line summary of `final_severity` and `final_action`
4. Confirm upstream inputs were available when the verdict was produced:
   - `artifacts/heartbeat/{today}_anomalies.md`
   - `artifacts/ops_digest/{today}_digest.json`

## Reply rules

- **GREEN** with healthy inputs → `HEARTBEAT_OK`
- **YELLOW** → include severity; no action required unless user asks
- **ORANGE** or **RED** → surface severity, action, and top fix_prompt

## Do not

- Re-run or mutate production artifacts on heartbeat alone
- Downgrade RED/YELLOW without reading today's supervisor JSON
