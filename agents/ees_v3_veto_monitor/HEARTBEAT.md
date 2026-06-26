# HEARTBEAT.md — EES v3 Veto Monitor

On heartbeat, run this checklist. Reply HEARTBEAT_OK only if all checks clear.

## Checklist

1. **Shadow ledger exists**: `artifacts/shadow/ees_v3_raw_veto_shadow_ledger.jsonl` is present
   - If missing → STALE (no veto cards generated yet)

2. **Today's veto card**: check ledger for today's `snap_date`
   - If missing → run `python3 scripts/research/ees_v3_raw_veto_shadow_card.py --as-of-date $(date +%F)`

3. **Veto count sanity**: `n_vetoed` for today's card in expected range (3–15)
   - If 0 → flag MONITORING_WARN: veto dormant
   - If > 15 → flag MONITORING_WARN: unusually high veto rate

4. **Failure mode check**: dominant mode for today
   - If >60% `no_options_coverage` → flag MONITORING_WARN

5. **Shadow gate**: check completed 20d observations (filter n_vetoed > 0 rows only)
   - Report: `completed_20d / 20` — MET or IN_PROGRESS

6. **Governance check**:
   - `freeze_status == ACTIVE`? If not → MONITORING_FAIL immediately
   - `production_decisioning == false`? If not → MONITORING_FAIL immediately

## Status codes

- `HEARTBEAT_OK` — veto card present, governance clean, veto count in range
- `STALE` — no ledger or no card for today
- `MONITORING_WARN` — veto count / mode anomaly
- `MONITORING_FAIL` — governance violation detected
