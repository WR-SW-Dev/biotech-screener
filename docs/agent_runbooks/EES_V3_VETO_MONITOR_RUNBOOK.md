# EES v3 Veto Monitor — Runbook

**Agent:** `ees_v3_veto_monitor`
**Registry:** `agents/AGENT_REGISTRY.json`
**Status:** `shadow` | `CRON_NOT_ENABLED` | `FREEZE_ACTIVE`
**Governance:** DIAGNOSTIC_ONLY — no production decisioning, no mutation authority

---

## Purpose

Daily shadow-policy monitor for EES v3 `raw_veto_core`. Answers one question each day:

> If EES v3 were used as a bottom-quintile veto on ranker-selected names,
> what names would have been removed, and how is that policy performing?

Does not trade, modify rankings, lift freeze, or enable autonomous behavior.

---

## Manual Invocation

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

python3 scripts/research/ees_v3_raw_veto_shadow_card.py --as-of-date $(date +%F)
```

For a specific date:
```bash
python3 scripts/research/ees_v3_raw_veto_shadow_card.py --as-of-date 2026-06-25
```

---

## Artifacts Written

| Path | Contents |
|------|----------|
| `artifacts/shadow/ees_v3_raw_veto_shadow_ledger.jsonl` | Append-only ledger of daily veto cards + settled returns |
| `artifacts/shadow/ees_v3_veto_shadow_card_{YYYY_MM_DD}.json` | Per-day JSON shadow card (agent output) |
| `artifacts/readiness/EES_V3_VETO_SHADOW_STATUS_{YYYY_MM_DD}.md` | Per-day Markdown status memo |
| `agents/ees_v3_veto_monitor/memory/` | Agent memory notes |

---

## Governance Boundaries

**Allowed:**
- Read `data/snapshots/*/rankings.csv`
- Read `artifacts/shadow/ees_v3_raw_veto_shadow_ledger.jsonl`
- Write `artifacts/shadow/ees_v3_veto_shadow_card_*.json`
- Write `artifacts/readiness/EES_V3_VETO_SHADOW_STATUS_*.md`
- Write `agents/ees_v3_veto_monitor/memory/`

**Forbidden:**
- Any write to `event_ev/`, `production_data/`, `data/snapshots/`, `run_screen.py`
- Any change to `final_score`, ranker, selector, sizing, gates, portfolio, or trading behavior
- Cron activation without explicit operator approval
- Autonomous git commit or push
- Production promotion of EES v3

---

## Dry Run Acceptance Criteria

Before cron activation, confirm all 10 criteria pass:

1. Agent reads latest snapshot (`data/snapshots/{date}/rankings.csv`)
2. Agent writes JSON shadow card to `artifacts/shadow/`
3. Agent writes Markdown memo to `artifacts/readiness/`
4. Agent reports `freeze_status: ACTIVE`
5. Agent reports `production_decisioning: false`
6. Agent returns one allowed verdict (not PROMOTE/LIFT_FREEZE/TRADE/CHANGE_*)
7. `git diff --name-only run_screen.py event_ev/ production_data/` → empty
8. No autonomous git commit or push
9. `forbidden_actions_checked` block in JSON card all `false`
10. `git status` shows only expected artifact files

---

## Allowed Verdicts

| Verdict | Meaning |
|---------|---------|
| `MONITORING_OK` | Normal operation |
| `MONITORING_WARN` | Anomaly in veto count, failure modes, or performance |
| `MONITORING_FAIL` | Governance violation — investigate immediately |
| `MONITORING_OK_REQUIRES_OPERATOR_REVIEW` | Gate MET + strong alpha — operator review eligible |
| `INSUFFICIENT_FORWARD_OBSERVATIONS` | Pre-maturity; continue accumulating |
| `DATA_UNAVAILABLE` | Snapshot or EES fields missing |

---

## Escalation Procedure

### MONITORING_FAIL
1. Run `git diff --name-only` — confirm no production file changes.
2. Check `run_screen.py` for unexpected EES veto wiring.
3. Confirm `freeze_status` still ACTIVE in latest snapshot metadata.
4. Alert operator before any further production runs.

### MONITORING_OK_REQUIRES_OPERATOR_REVIEW
1. Read `artifacts/readiness/EES_V3_FREEZE_LIFT_REVIEW_MEMO_2026_06_25.md`.
2. Operator initiates freeze-lift review independently.
3. Agent continues daily monitoring — verdict does NOT trigger automatic promotion.

---

## Shadow Gate Status (as of 2026-06-25)

| Gate | Required | Complete | Status |
|------|----------|----------|--------|
| 20d observations | 20 | 35 | **MET** |

Cumulative performance (35 veto-active obs):

| Horizon | Veto Alpha | Alpha+ Rate |
|---------|-----------|-------------|
| 5d | +2.3% | 61.7% |
| 10d | +4.2% | 78.6% |
| 20d | +7.4% | 81.2% |

---

## Cron Activation Gate

Cron is **not enabled**. Activation requires:

1. Operator reviews dry run artifacts.
2. Operator confirms daily artifacts are useful.
3. Operator explicitly approves scheduling.
4. Agent confirmed read-only at activation.
5. Scheduled after daily production snapshot (~17:30 ET).

Suggested crontab line (do not add without operator approval):
```
45 17 * * 1-5 cd /mnt/c/Projects/biotech_screener/biotech-screener && python3 scripts/research/ees_v3_raw_veto_shadow_card.py --as-of-date $(date +\%F) >> /tmp/ees_v3_veto_monitor.log 2>&1
```

---

## Evidence Package

| Commit | Contents |
|--------|----------|
| `149c8f56` | Promotion simulator — raw_veto_core selected as lead |
| `6123739c` | Veto autopsy — 55.6% true-negative, LATE 60.5% |
| `0d47544f` | Conditional veto simulator — RAW_VETO_REMAINS_BEST |
| `c56b2c2a` | Shadow card Day 1 — 8 vetoed, 0× no_options_coverage |
| `22e7312b` | Backfill + gate counting fix — 35/20 MET |
| `a42d3396` | Freeze-lift review memo — READY_FOR_OPERATOR_FREEZE_LIFT_REVIEW |

---

## What Is Not Approved

This runbook does not approve production promotion.
This runbook does not approve freeze lift.
EES v3 raw_veto_core remains diagnostic-only until operator explicitly approves.
