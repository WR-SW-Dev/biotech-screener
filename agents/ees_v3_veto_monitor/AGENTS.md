# AGENTS.md — EES v3 Veto Monitor

## Overview

Daily shadow-policy monitor for EES v3 `raw_veto_core`. Tracks whether EES v3 bottom-quintile
vetoes on ranker top-Q names are producing cumulative alpha separation. Writes two artifacts per
run: JSON shadow card + Markdown status memo. **No production decisioning. No mutation authority.**

Governance state: `FREEZE_ACTIVE | DIAGNOSTIC_ONLY | CRON_NOT_ENABLED`

---

## Session Startup

1. Confirm freeze state: `FREEZE_ACTIVE`. If not, emit MONITORING_FAIL immediately.
2. Load the shadow ledger: `artifacts/shadow/ees_v3_raw_veto_shadow_ledger.jsonl`
3. Load today's snapshot: `data/snapshots/{as_of_date}/rankings.csv`
4. Verify EES v3 fields present in rankings.csv (`ees_v3_score`). If missing: DATA_UNAVAILABLE.

---

## Daily Workflow

### Step 1 — Run the shadow card script

```bash
python3 scripts/research/ees_v3_raw_veto_shadow_card.py --as-of-date YYYY-MM-DD
```

Reads today's snapshot, applies `raw_veto_core`, settles any matured ledger rows, appends today's
veto card. Read-only with respect to all production files.

### Step 2 — Parse shadow card output

From script stdout or the appended ledger row:
- `n_ranker_top_q`, `n_vetoed`, `n_selected`, `vetoed_tickers`
- `failure_modes`: no_options_coverage / dilution_overhang / market_already_priced / catalyst_too_far / other
- `priced_move_pct_coverage`

### Step 3 — Compute cumulative shadow performance

Read `artifacts/shadow/ees_v3_raw_veto_shadow_ledger.jsonl`.
Filter rows where `n_vetoed > 0` (gate denominator only).
For each settled horizon (5d / 10d / 20d):
- `veto_alpha = mean_selected_excess - mean_vetoed_excess` (both vs XBI)
- `alpha_positive_rate = fraction(row_level_veto_alpha > 0)`
- Report gate: `shadow_gate_status = MET if completed_20d >= 20`

### Step 4 — Warning conditions

**Data warnings:**
- `ees_v3_score` missing from rankings → MONITORING_FAIL
- `n_vetoed == 0` → MONITORING_WARN
- `veto_rate < 5%` or `> 30%` → MONITORING_WARN
- Vetoed set >60% `no_options_coverage` → MONITORING_WARN

**Performance warnings:**
- 20d veto alpha negative over last 10 completed obs → MONITORING_WARN
- `catalyst_too_far` count >= 3 among vetoed names → MONITORING_WARN

**Governance warnings (force MONITORING_FAIL):**
- `freeze_status != ACTIVE`
- `production_decisioning` appears enabled
- EES v3 fields detected influencing `final_score`
- Any unexpected write to production files

### Step 5 — Determine verdict

```
governance_warning  → MONITORING_FAIL
data_missing        → DATA_UNAVAILABLE
fwd_missing         → INSUFFICIENT_FORWARD_OBSERVATIONS
perf_warning        → MONITORING_WARN
gate_met + alpha>5% → MONITORING_OK_REQUIRES_OPERATOR_REVIEW
else                → MONITORING_OK
```

`MONITORING_OK_REQUIRES_OPERATOR_REVIEW` signals evidence is strong but does NOT recommend
promotion — operator must initiate freeze-lift review separately.

### Step 6 — Write artifacts

```
artifacts/shadow/ees_v3_veto_shadow_card_{YYYY_MM_DD}.json
artifacts/readiness/EES_V3_VETO_SHADOW_STATUS_{YYYY_MM_DD}.md
agents/ees_v3_veto_monitor/memory/{YYYY_MM_DD}_status.md
```

---

## Memory entry format

```
[YYYY-MM-DD HH:MM UTC] Veto Watch: {VERDICT}
  vetoed={n} | veto_rate={pct}% | dominant_mode={mode}
  20d alpha={value}% | alpha+={pct}% | gate={MET/IN_PROGRESS}
  warnings={list or NONE}
```

---

## Verdict → Operator action

| Verdict | Action |
|---------|--------|
| MONITORING_OK | None |
| MONITORING_WARN | Review warnings; no production action |
| MONITORING_FAIL | Investigate immediately; governance check |
| MONITORING_OK_REQUIRES_OPERATOR_REVIEW | Freeze-lift review eligible; operator must initiate |
| INSUFFICIENT_FORWARD_OBSERVATIONS | Normal; continue accumulating |
| DATA_UNAVAILABLE | Check snapshot generation |

---

## Red Lines (NEVER)

- Change `final_score`, ranker, selector, sizing, portfolio, gates, cron, or trading behavior
- Lift freeze
- Enable cron without explicit operator approval
- Commit or push autonomously
- Write outside allowed artifact paths
- Emit PROMOTE, LIFT_FREEZE, TRADE, or CHANGE_* verdicts

## Downstream consumers

- Operator freeze-lift review (human-initiated only)
- `docs/agent_runbooks/EES_V3_VETO_MONITOR_RUNBOOK.md`
