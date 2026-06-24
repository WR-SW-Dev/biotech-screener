# Spec 112: Phase 2 Daily Monitoring Automation

**Status:** NEW  
**Created:** 2026-06-12  
**Author:** Hermes Phase 2 operations  
**Severity:** MEDIUM (operational efficiency)  
**Timeline:** Implementation through 2026-06-17 Phase 2 window

---

## Summary

Automate Phase 2 daily monitoring checklist to reduce manual operator effort and ensure consistent gate verification. Create unified monitoring dashboard covering:

1. **Governance gates** (drawdown, 13F Jaccard, IC observable, emergency exit)
2. **Data freshness** (price data, signals, snapshots)
3. **Portfolio metrics** (PnL, excess, drawdown, position concentration)
4. **Fleet health** (agent status, heartbeat, signal monitoring)
5. **Risk indicators** (volatility, correlation drift, outlier detection)

---

## Problem Statement

### Current State
- Manual daily checklist (tools/daily_path_c_monitoring.sh exists but outdated)
- Operator must run multiple commands to verify gate status
- No unified dashboard or report generation
- Risk of missing critical alerts if checks skipped
- Heartbeat checks run separately from governance gate checks

### Target State (Phase 2)
- Automated morning/evening check-in (cron-scheduled)
- Unified HTML/JSON report with gate status, alerts, recommendations
- Operator approval required for critical decisions (but monitoring auto-verified)
- Daily email/Slack summary with traffic-light status
- 5-10 minute operator review vs. 30-40 minute manual verification

---

## Solution Design

### Tier 1: Automated Gate Verification (5-10 min operator review)

**Morning Check (08:00 ET):**
```
✓ Data freshness
  - Price data: latest date = today
  - Snapshot generated: yes/no
  - Herald digest: produced/missing
  - IC dashboard: updated with current signals
```

**Intraday Check (14:00 ET):**
```
✓ Governance gates status
  - Drawdown vs XBI: ___ pp (PASS/FAIL_HARD_EXIT)
  - 13F Jaccard: 0.___ (PASS/DEFERRED)
  - IC observable: expected ~Jun 17 (ON_TRACK/RISK)
  - Emergency exit: ARMED/TRIGGERED
```

**Evening Check (18:00 ET):**
```
✓ Fleet health & signals
  - Heartbeat anomalies: N/29 agents
  - Layer B signals: 8/8 restored post-trading
  - ic_health_monitor: OK/ALERT/FAIL
  - shadow_monitor: MAX_DRAWDOWN status
```

**Post-Trading Check (22:00 ET):**
```
✓ Risk metrics summary
  - Daily PnL: ___% (portfolio + shadow)
  - Max drawdown: ___% vs threshold 8%
  - Position concentration: largest 5 = ___%
  - Volatility drift: within/outside 2σ
```

### Tier 2: Operator Decision Points (2026-06-17)

**IC Observable Window Decision:**
- If IC_UNOBSERVABLE (expected): recommend extension until ~June 17
- If IC becomes observable: proceed to Phase 3 planning or revert

**Portfolio Status Decision:**
- If drawdown > -2.00pp: hard emergency exit
- If 13F Jaccard < 0.70: re-quarantine and reassess
- If all gates passing: continue Phase 2 through June 17

### Implementation Components

#### 1. Monitoring Script (`tools/phase2_daily_monitor.sh`)

```bash
#!/bin/bash
# Phase 2 unified daily monitoring (2026-06-01 to 2026-06-17)
# Run: 08:00, 14:00, 18:00, 22:00 ET

WINDOW_START="2026-06-01"
WINDOW_END="2026-06-17"
TODAY=$(date +%Y-%m-%d)

# Tier 1: Governance gates
python3 tools/verify_phase2_gates.py --date "$TODAY" --window-start "$WINDOW_START" --window-end "$WINDOW_END"

# Tier 2: Fleet health
python3 tools/agent_heartbeat_checks.py --summary-only

# Tier 3: Risk metrics
python3 tools/compute_daily_risk_metrics.py --as-of-date "$TODAY"

# Tier 4: Report generation
python3 tools/generate_phase2_daily_report.py --as-of-date "$TODAY" --output-format html,json
```

#### 2. Gate Verification Tool (`tools/verify_phase2_gates.py`)

Checks:
- Drawdown vs XBI (hard exit at -2.00pp)
- 13F Jaccard ≥ 0.70 (deferred if below)
- IC observable (expected ~June 17)
- Emergency exit armed
- All signals operational

Output: JSON with gate status, alerts, timestamps

#### 3. Risk Metrics Tool (`tools/compute_daily_risk_metrics.py`)

Computes:
- Daily portfolio PnL (real + shadow)
- Cumulative excess vs policy
- Max drawdown (vs threshold 8%)
- Position concentration (Herfindahl)
- Volatility drift (rolling 20d vs baseline)

#### 4. Report Generator (`tools/generate_phase2_daily_report.py`)

Produces:
- HTML dashboard (operator-friendly, browser-viewable)
- JSON structured data (system-consumable)
- Email summary (morning + evening)
- Slack notifications (alerts only)

### Cron Schedule

```
# Morning check (8:00 AM ET)
0 8 * * 1-5 cd $REPO && bash tools/phase2_daily_monitor.sh >> logs/phase2_monitor.log 2>&1

# Intraday check (2:00 PM ET)
0 14 * * 1-5 cd $REPO && bash tools/phase2_daily_monitor.sh >> logs/phase2_monitor.log 2>&1

# Evening check (6:00 PM ET)
0 18 * * 1-5 cd $REPO && bash tools/phase2_daily_monitor.sh >> logs/phase2_monitor.log 2>&1

# Post-trading check (10:00 PM ET)
0 22 * * 1-5 cd $REPO && bash tools/phase2_daily_monitor.sh >> logs/phase2_monitor.log 2>&1
```

---

## Success Criteria

### Automation Quality
- ✓ All 4 gate checks automated (no manual calculation)
- ✓ Report generated in <30 seconds
- ✓ HTML dashboard renders correctly in Chrome/Firefox
- ✓ JSON output machine-readable (valid schema)

### Operator Experience
- ✓ Morning review: <5 minutes to scan report + approve
- ✓ Evening review: <5 minutes to spot alerts
- ✓ Decision triggers clearly labeled (hard stop vs. FYI)
- ✓ False positive rate < 5% (tuning via thresholds)

### Coverage
- ✓ All 4 governance gates monitored
- ✓ All 29 agents in heartbeat included
- ✓ Both portfolio + shadow monitor tracked
- ✓ Cron execution logging (success/failure)

---

## Testing & Validation

### Pre-Production (2026-06-12 to 2026-06-16)
- Unit tests: gate logic, metrics computation, report formatting
- Integration test: full morning/evening run end-to-end
- Accuracy check: manual verification of 2-3 days reports vs. actual metrics
- Load test: can report be generated 4x/day without side effects?

### Production (2026-06-17 onwards)
- Daily review by operator (post-trading)
- Weekly report accuracy audit (spot-check vs. manual calculation)
- Alert sensitivity tuning (false positives > 10% → adjust thresholds)

---

## Artifacts

**Phase 2 Daily Reports:** `artifacts/phase2_monitoring/daily/`
- `2026-06-XX_morning_report.html` (08:00 ET)
- `2026-06-XX_evening_report.html` (22:00 ET)
- `2026-06-XX_metrics.json` (consolidated data)

**Cron Logs:** `logs/phase2_monitor.log`
**Gate Status History:** `artifacts/phase2_monitoring/gate_history.jsonl`

---

## Ownership & Dependencies

**Implementation:** Claude Code + Hermes automation  
**Verification:** Operator daily review  
**Escalation:** If any gate FAIL → immediate operator alert (Slack/email)  
**Sunset:** 2026-06-17 (Phase 2 decision point) — extend or revert to manual

---

## Rollout Timeline

| Date | Task | Status |
|------|------|--------|
| 2026-06-12 | Design spec (this doc) | ✓ COMPLETE |
| 2026-06-13 | Implement monitoring scripts | TODO |
| 2026-06-14 | Test full morning/evening runs | TODO |
| 2026-06-15 | Tuning + accuracy validation | TODO |
| 2026-06-16 | Operator handoff + training | TODO |
| 2026-06-17 | Phase 2 decision day (extend/revert) | TODO |

---

## Notes

- This spec complements the existing daily_path_c_monitoring.sh but extends scope to full Phase 2 + fleet health
- Builds on established heartbeat infrastructure (tools/agent_heartbeat_checks.py)
- Risk metrics leverage existing shadow_monitor and ic_health_monitor outputs
- Designed for Phase 2 window (2026-06-01 to 2026-06-17); can be extended post-Phase-2 if gates remain relevant

---

**Next Step:** Operator approval to proceed with implementation (2026-06-13 target)
