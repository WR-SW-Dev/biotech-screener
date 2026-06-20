# LangGraph Observation Runbook
## LG3 Wrapper + LG4A Dashboard (2026-06-20 → 2026-07-03)

**Purpose:** Make the 14-day observation window auditable and evidence-based.

**Scope:** Read-only checks only. No code changes, no new phases, no production integration.

---

## Daily Audit Checklist (Mon–Fri, ~5 min)

### 1. LG3 Wrapper Execution (08:05 AM ET cron)

Check immediately after 08:15 AM ET:

```bash
# Check cron executed
tail -20 /home/arrenchulz/.hermes/cron/logs/scientific_cartography_lg3_cron.log

# Verify JSONL append
tail -5 artifacts/scientific_cartography/scheduled_review_cron.jsonl | jq .

# Count today's executions
grep "$(date +%Y-%m-%d)" artifacts/scientific_cartography/scheduled_review_cron.jsonl | wc -l
```

Expected:
- ✓ One entry per day (or catch-up if missed)
- ✓ `execution_status` ∈ {success, partial, non_blocking_failure}
- ✓ `automation_approval` = false
- ✓ No `production_hook_triggered`

---

### 2. LG4A Dashboard Regeneration (2–3 times per week)

Regenerate against latest artifacts to confirm readability:

```bash
# Find latest dated artifact dir
LATEST_ARTIFACT=$(ls -td artifacts/scientific_cartography/2026-* | head -1)

# Regenerate dashboard
python3 tools/generate_scientific_cartography_dashboard.py \
  --artifact-dir "$LATEST_ARTIFACT" \
  --output-dir /tmp/sc_lg4a_dashboard_check

# Check manifest
jq '.governance_flags, .forbidden_data_sources_used' \
  /tmp/sc_lg4a_dashboard_check/dashboard_manifest.json
```

Expected:
- ✓ All pages generate without error
- ✓ `read_only_diagnostic` = true
- ✓ `automation_approval` = false
- ✓ `forbidden_data_sources_used` = [] (empty array)
- ✓ `runtime_server_started` = false
- ✓ `production_hook_enabled` = false

---

### 3. Artifact Growth (weekly check)

Monitor artifact directory size to catch unbounded growth:

```bash
# Weekly snapshot
du -sh artifacts/scientific_cartography/ >> /tmp/artifact_growth_log.txt
date >> /tmp/artifact_growth_log.txt

# Show growth
tail -10 /tmp/artifact_growth_log.txt
```

Expected:
- ✓ Slow, linear growth (1–3 new artifact dirs per week)
- ✗ Rapid growth (>100MB/week suggests infinite loops or storage bugs)

---

### 4. Governance Flag Integrity (daily, automated)

Each JSONL entry in `scheduled_review_cron.jsonl` must have:

```bash
# Check all entries for forbidden flags
jq -r '.governance_flags | 
  select(.automation_approval != false or 
         .trading_or_portfolio_action != false or 
         .production_model_change != false)' \
  artifacts/scientific_cartography/scheduled_review_cron.jsonl

# Should return nothing (no violations)
```

Expected:
- ✓ Zero violations
- ✗ Any entry with `automation_approval=true` = STOP immediately and escalate

---

## Failure Classification (LG3 non-blocking failures)

When `execution_status` = `non_blocking_failure`, classify:

| Failure Type | Example | Action |
|--------------|---------|--------|
| **Data unavailable** | SEC API outage, yfinance 429 | Log and continue (expected) |
| **Missing artifact** | LG2 decision JSONL missing | Expected (first days); monitor for persistence |
| **Governance violation** | automation_approval=true detected | ESCALATE immediately |
| **Unbounded growth** | /tmp/sc_lg4a_dashboard >500MB | STOP and investigate |
| **Template error** | HTML generation fails | Check disk space, review template code |

---

## Weekly Spot Checks

### Week 1 (2026-06-20 → 2026-06-26)
- [ ] LG3 cron ran at least 4 times (Mon–Thu, Fri optional if late)
- [ ] All 4 executions logged to JSONL
- [ ] Dashboard regenerated successfully from 2 artifact dirs
- [ ] No governance violations in JSONL
- [ ] Artifact size < 100MB
- [ ] governance_flags file unchanged (no code drifts)

### Week 2 (2026-06-27 → 2026-07-03)
- [ ] LG3 cron ran at least 3–4 times (depends on calendar)
- [ ] Cumulative 7–8 JSONL entries for the full window
- [ ] Dashboard regenerated from latest
- [ ] No governance violations
- [ ] Artifact size <150MB
- [ ] automation_approval = false in all entries

---

## Checkpoint Template (~2026-07-03)

Use this template to prepare the July 3 decision memo:

```markdown
# LangGraph Observation Checkpoint — 2026-07-03

## LG3 Wrapper Health
- Total executions: [N]
- Successful: [N]
- Non-blocking failures: [N] ([types])
- Governance violations: [N/0]

## LG4A Dashboard
- Regenerations tested: [N]
- All pages generate: [Y/N]
- Governance flags intact: [Y/N]
- forbidden_data_sources_used always empty: [Y/N]

## Artifact Growth
- Size at start (2026-06-20): [X MB]
- Size at checkpoint (2026-07-03): [Y MB]
- Growth rate: [Y-X MB / 14 days]
- Bounded (< 200MB): [Y/N]

## Governance Integrity
- automation_approval violations: [0/N]
- production_model_change violations: [0/N]
- trading_or_portfolio_action violations: [0/N]
- Any governance flags drifted: [Y/N]

## Decision
- All checks passed: [Y/N]
- Recommendation for LG5: [PROCEED / DEFER / INVESTIGATE]
- Notes: [...]
```

---

## Observation Window Boundaries

**Active:** 2026-06-20 to 2026-07-03 (14 calendar days, ~10 business days)

**Frozen:**
- ✗ No LG5 implementation
- ✗ No LG4 enhancements
- ✗ No cron additions
- ✗ No agent runtime expansion
- ✗ No production hook wiring

**Allowed:**
- ✓ Documentation updates (like this runbook)
- ✓ Read-only spot checks
- ✓ Manual dashboard regeneration
- ✓ Governance flag audits
- ✓ Artifact growth monitoring

---

## Escalation Triggers

Stop the observation window immediately if:

1. **Governance violation detected**
   - `automation_approval=true` anywhere in JSONL
   - Action: escalate, investigate, revert if necessary

2. **Unbounded artifact growth**
   - Size grows >200MB total
   - Action: investigate infinite loop or storage bug

3. **LG4A dashboard generation failure**
   - No pages generated for 2+ consecutive runs
   - Action: debug, check disk space, review template

4. **Missing JSONL entries for >2 business days**
   - Cron did not execute (not scheduled, not running)
   - Action: check cron logs, restart if needed

---

## Notes

- **No code review:** These checks are read-only. Do not commit code changes during the window.
- **Evidence over vibes:** Every decision at July 3 checkpoint should cite JSONL entries and manifest flags.
- **Non-blocking failures expected:** First few days may have "missing artifact" entries. This is normal during initial LG2/LG3 stabilization.
- **Dashboard readability:** HTML is meant for human review. If pages don't render in browser or look broken, note but don't fix (read-only window).

---

## Checkpoint Decision Matrix (for ~2026-07-03)

| Outcome | Recommendation |
|---------|-----------------|
| All checks passed, no violations | **PROCEED to LG5 design** (late July) |
| All checks passed, 1–2 non-blocking failures | **PROCEED with caution** (monitor one more week) |
| Governance violations detected | **STOP, revert, investigate** |
| Unbounded growth or failures | **STOP, diagnose, fix** |
| Cron/JSONL stopped executing | **STOP, debug infrastructure** |

---

**Observation Window Status:** ACTIVE (2026-06-20)  
**Next Review:** ~2026-07-03  
**Owner:** [Your name]  
**Last Updated:** 2026-06-20
