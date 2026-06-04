# Phase 2 First-Fire Validation Checklist
**Date**: 2026-06-05 (execution day)  
**Time**: After 10:20 AM ET cron run  
**Status**: Ready for operator validation

---

## Pre-Run Setup (Operator)

Before 10:20 AM ET on 2026-06-05:
- [ ] Confirm cron is wired: `crontab -l | grep phase2_daily`
- [ ] Confirm output directory exists: `mkdir -p output/`
- [ ] Clear old logs if needed: `rm -f output/phase2_daily_*.log`

---

## Post-Run Validation (After 10:20 AM ET)

### 1. ✅ Pipeline Execution & Logs

**Command:**
```bash
tail -n 120 output/phase2_daily_$(date +%Y%m%d).log
```

**Acceptance Criteria:**
- [ ] Log file exists: `output/phase2_daily_20260605.log`
- [ ] No Python tracebacks or exceptions in last 50 lines
- [ ] Exit message indicates `exit code=0` or `HEALTH OK`
- [ ] No `fatal`, `ERROR`, `FAIL` in output (WARN is acceptable)

**If FAILED**: Check log for:
- Missing dependencies (`pip install ...`)
- Snapshot data unavailable
- Data directory path issues
- Permission errors on output directory

---

### 2. ✅ Artifacts Generated

**Command:**
```bash
ls -lh data/snapshots/2026-06-04/portfolio_positions.csv \
        data/snapshots/2026-06-04/phase2_health.json \
        artifacts/readiness/phase2_run_delta_* 2>&1 | grep -E "^-|cannot"
```

**Acceptance Criteria:**
- [ ] `portfolio_positions.csv` exists and is > 1 KB (non-empty)
- [ ] `phase2_health.json` exists and is > 100 bytes
- [ ] Daily delta report exists in `artifacts/readiness/` or `data/snapshots/2026-06-04/`
- [ ] All files have recent timestamp (same minute as cron execution)

**If FAILED**: Likely causes:
- Snapshot 2026-06-04 data missing or corrupted
- Output directory permissions issue
- run_screen.py decision-mode phase2 not working

---

### 3. ✅ Portfolio Consistency

**Command:**
```bash
python3 -c "
import json, csv

# Load top-60 from Day 1
with open('data/snapshots/2026-06-04/rankings.csv') as f:
    reader = csv.DictReader(f)
    day1_top60 = set(r['ticker'] for i, r in enumerate(reader) if i < 60)

# Load today's portfolio from daily run
with open('data/snapshots/2026-06-04/portfolio_positions.csv') as f:
    reader = csv.DictReader(f)
    today_portfolio = set(r['ticker'] for r in reader)

print(f'Day 1 top-60 count: {len(day1_top60)}')
print(f'Today portfolio count: {len(today_portfolio)}')
print(f'Overlap: {len(day1_top60 & today_portfolio)}/60')
print(f'New additions: {today_portfolio - day1_top60}')
print(f'Removed: {day1_top60 - today_portfolio}')
"
```

**Acceptance Criteria:**
- [ ] Portfolio count = 60 (or documented explanation if different)
- [ ] Overlap ≥ 58 (≥96.7% stability expected)
- [ ] Any additions/removals are within known tolerance (1-2 tickers)

**If FAILED**: 
- Portfolio composition unstable (possible ranker_v2_score issue)
- Decision model may have regressed
- Escalate to decision-model investigation

---

### 4. ✅ Decision Model Health

**Command:**
```bash
python3 -c "
import json

with open('data/snapshots/2026-06-04/phase2_health.json') as f:
    health = json.load(f)

print('Phase 2 Health Status:')
for key, value in health.items():
    status = '✅' if value.get('pass', False) else '⚠️'
    print(f'  {status} {key}: {value}')
"
```

**Acceptance Criteria:**
- [ ] All health gates show status (PASS or documented WARN)
- [ ] No FAIL gates (would trigger exit code 1)
- [ ] `eligible_count` ≈ 208 (±10 is normal)
- [ ] `ranker_v2_score_stable` = true (or close to Day 1 baseline)

**If FAILED**:
- Health gate regression (possible decision-model issue)
- Requires immediate investigation before next run
- Consider Phase 2 HOLD until root cause found

---

### 5. ✅ Drawdown vs XBI Monitoring (Path C)

**Command:**
```bash
ls -lh data/snapshots/2026-06-04/drawdown* artifacts/readiness/*drawdown* 2>&1 | head -5
```

**Acceptance Criteria:**
- [ ] Drawdown metric file exists or logged in phase2_health.json
- [ ] Drawdown status is clear (e.g., "within limits" or "risk: -1.2pp")
- [ ] No hard-exit breach (would trigger Path C HOLD)
- [ ] Timestamp ≤ 5 min after cron start

**If FAILED**:
- Path C monitoring may not be wired correctly
- Check 10:15 AM ET cron execution
- Not a Phase 2 blocker if Path C monitoring separate

---

### 6. ✅ Composite Score Non-Blocking Confirmation

**Command:**
```bash
grep -i "composite" output/phase2_daily_$(date +%Y%m%d).log | head -3
```

**Acceptance Criteria:**
- [ ] No "composite_score.*HOLD" or "composite.*FAIL" messages
- [ ] If composite_score logged, it's marked as diagnostic/non-blocking
- [ ] No escalation of composite_score into decision-path HOLD

**If FAILED**:
- Guardrail may have triggered
- Check log for decision-path consumption evidence
- If composite_score is affecting final_score/ranker/eligibility, escalate to Phase 2 HOLD

---

### 7. ✅ Git Status Clean

**Command:**
```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener && \
git status --short | grep -v "^??" | head -10
```

**Acceptance Criteria:**
- [ ] No modified files (M flag)
- [ ] Expected untracked files only (? flag, mostly in output/ and artifacts/)
- [ ] No merge conflicts or rebasing state

**If FAILED**:
- Unexpected file modifications may indicate a bug
- Review the diff to understand what changed
- May need to investigate Phase 2 runner

---

## Operator Decision Tree

```
After validation, operator chooses:

✅ ALL CHECKS PASS
   → Phase 2 is operational ✓
   → Confirm cron will run tomorrow at 10:20 AM ET
   → Next check: 2026-06-10 (5 trading days in)

⚠️ WARN GATES (portfolio churn, health non-critical)
   → Phase 2 continues with noted conditions
   → Monitor daily until issue resolves
   → Re-check after 3 days

❌ FAIL GATES (missing artifacts, decision regression, composite holds)
   → Phase 2 HOLD (do NOT continue cron)
   → Investigate root cause
   → Revert to manual runs or rollback
   → Escalate to development
```

---

## Quick Operator Command

Paste this to verify all steps in one go:

```bash
#!/bin/bash
set -e
cd /mnt/c/Projects/biotech_screener/biotech-screener

echo "=== Phase 2 First-Fire Validation ==="
echo ""
echo "1. Logs & Exit Code:"
tail -n 30 output/phase2_daily_$(date +%Y%m%d).log | tail -10
echo ""
echo "2. Artifacts Generated:"
ls -lh data/snapshots/2026-06-04/portfolio_positions.csv \
        data/snapshots/2026-06-04/phase2_health.json 2>&1 | tail -3
echo ""
echo "3. Portfolio Count & Stability:"
python3 -c "
import json, csv
with open('data/snapshots/2026-06-04/rankings.csv') as f:
    day1_top60 = set(r['ticker'] for i, r in enumerate(csv.DictReader(f)) if i < 60)
with open('data/snapshots/2026-06-04/portfolio_positions.csv') as f:
    today = set(r['ticker'] for r in csv.DictReader(f))
print(f'Top-60 count: {len(today)}, Overlap: {len(day1_top60 & today)}/60')
"
echo ""
echo "4. Health Status:"
python3 -c "
import json
with open('data/snapshots/2026-06-04/phase2_health.json') as f:
    h = json.load(f)
    for k in ['eligible_count', 'ranker_v2_score_stable', 'top60_overlap']:
        print(f'  {k}: {h.get(k, \"N/A\")}')
"
echo ""
echo "5. Git Status:"
git status --short | grep -v "^??" | wc -l
echo ""
echo "=== Validation Complete ==="
```

---

## Escalation Contacts

If validation **FAILS**:
1. Check this checklist step-by-step
2. Review `output/phase2_daily_*.log` for error details
3. If unclear, contact development team with:
   - [ ] Log output
   - [ ] Which validation step failed
   - [ ] Date/time of cron attempt

---

**Next Milestone: 2026-06-05 after 10:20 AM ET**

This is the first live proof that Phase 2 daily tracking is operational.
