# 13F Q1 2026 Cohort Refresh Preflight

**Date:** 2026-05-14  
**Status:** PREFLIGHT (awaiting 13F files; no action taken)  
**Scope:** Audit current distortion state; prepare validation gates for post-refresh

---

## Current State Summary

### 13F/Institutional Data

| Item | Current | Expected Post-Refresh |
|---|---|---|
| institutional_summary.json mtime | 2026-04-25 13:57 ET | ~2026-05-15 (Q1 2026 filings) |
| manager_registry.json mtime | 2026-04-25 13:57 ET | ~2026-05-15 |
| as_of_date | 2026-04-13 | 2026-04-30 (Q1 2026 cutoff) |
| cache_as_of_date | 2026-04-13 | 2026-04-30 |
| elite_managers_total | 37 (includes 4 cohort additions) | 37+ (pending new filings) |

### Cohort Expansion Context

**Date added:** 2026-04-25 (Saturday, manual --force-overwrite rebuild)  
**4 new managers:** Fairmount Funds, Vestal Point Capital, Kynam Capital, Soleus Capital (CIKs: 0001802528, 0001974915, 0001907884, 0001802630)  
**Quarantine doc:** `data/snapshots/2026-04-25/cohort_state.json` with flags `inst_delta_z_valid: false`, `rank_delta_valid: false`

### Current Distortion Symptoms

**Confirmed as of 2026-05-13:**

| Symptom | Current Value | Pattern |
|---|---|---|
| Mean \|inst_delta_z\| | 0.743 | Stable since 04-25 (no fresh 13F data) |
| Max \|inst_delta_z\| | 4.4235 | Byte-identical Sat→Sun→Mon→...→Wed |
| Coverage | 298/298 (100%) | All tickers populated; no missing values |
| Top-5 \|inst_delta_z\| | [4.42, 3.53, 3.23, 2.64, 2.64] | Same cohort-affected names persist |

**Rank-change monitor alerts (2026-05-13):**
- 2 WARNs: ALMS (rank -61, cohort_entry), ANAB (rank +34, cohort_dropout)
- 10 WATCHes: selector_score_moves + tier/eligibility changes
- Top-30 churn: +1 / -1 (stable; no regime shift)

**Root cause:** No new 13F filings since 2026-04-25 rebuild → inst_delta_z values are stale snapshots of the contaminated cohort state.

---

## Files Requiring Q1 2026 Refresh

| File | Path | Purpose | Current mtime |
|---|---|---|---|
| 13F SEC index | `data/caches/sec_13f_pit_index/<date>/` | Lookup table for manager holdings | 2026-04-13 |
| Institutional summary | `production_data/institutional_summary.json` | Aggregated elite manager scores | 2026-04-25 13:57 ET |
| Manager registry | `production_data/manager_registry.json` | Manager metadata + AUM | 2026-04-25 13:57 ET |
| Coinvest decision rules | `production_data/decision_rulesets/*.json` | Research ruleset variants | N/A (stable) |

**Ingest flow:** SEC 13F → PIT index → institutional_summary.json aggregation → snapshot coinvest/inst_delta recomputation

---

## Pass/Fail Checks — Post-Refresh Validation

### Pre-Refresh Baseline (current state)

```bash
python3 -c "
import json
from pathlib import Path

inst_summary = json.load(open('production_data/institutional_summary.json'))
print(f'Pre-refresh as_of_date: {inst_summary[\"as_of_date\"]}')
print(f'Pre-refresh elite_managers: {inst_summary[\"elite_managers_total\"]}')
print(f'Pre-refresh tickers_with_signal: {inst_summary[\"tickers_with_signal\"]}')
"
```

### Post-Refresh Validation Checklist

**Gate 1: File freshness**
```
✓ institutional_summary.json mtime > 2026-05-14 12:00 ET
✓ manager_registry.json mtime > 2026-05-14 12:00 ET
✓ Cache mtime in SEC PIT index: dates include 2026-04-30 or later
```

**Gate 2: as_of_date advancement**
```
✓ institutional_summary.json as_of_date >= 2026-04-30 (Q1 2026 cutoff)
✓ cache_as_of_date >= 2026-04-30
```

**Gate 3: inst_delta_z normalization**
```
✓ Mean |inst_delta_z| changes vs locked 0.743 value
✓ Max |inst_delta_z| differs from 4.4235
✓ Top-5 tickers show different distribution (not identical byte-for-byte)
✓ New snapshot (2026-05-15 or later) exhibits inst_delta_z drift vs 2026-05-14
```

**Gate 4: SIGNAL_ALERT status**
```
✓ ic_health_monitor SIGNAL_ALERT for inst_delta_z clears at next heartbeat after refresh
✓ If alert persists, investigate: may indicate ingest failure, not normal refresh delay
```

**Gate 5: Top-affected tickers (attribution)**

Tickers showing rank-delta WARNs in 2026-05-13:
- **ALMS** (WARN, rank -61 on 05-13): was cohort_entry due to 04-25 rebuild; post-refresh should revert if 13F filings don't support inclusion
- **ANAB** (WARN, rank +34 on 05-13): was cohort_dropout; post-refresh inst_delta_z change may stabilize this

**Expectation:** If ALMS/ANAB rank deltas reverse post-refresh, confirms cohort artifact recovery. If they persist, indicates sustained 13F support for the new cohort state.

**Gate 6: No model changes**
```
✓ Selector weights unchanged (0.65 coinvest, 0.35 inst_delta)
✓ Ranker v2 logic unchanged (2-feature pairwise)
✓ No snapshot regeneration or reranking
✓ Ranking re-runs only on next organic daily snapshot (2026-05-15 or later)
```

---

## Architecture & Safety Notes

### Why This Matters
The 13F refresh is a **data-governance event**, not a model logic event. The distortion window (04-25 → ~05-15) is a known regime with understood causes and expected recovery triggers. Preparing for post-refresh validation ensures:
1. We can distinguish true signal recovery from artifact coincidence
2. We don't confuse data-quality changes with model performance changes
3. We preserve audit trail for future cohort management decisions

### What NOT to Do
- ❌ Do NOT recompute inst_delta_z during or after the refresh
- ❌ Do NOT change selector/ranker weights to "correct" the distortion
- ❌ Do NOT regenerate or edit historical snapshots (2026-04-25 through 2026-05-14)
- ❌ Do NOT interpret post-refresh rank changes as signal validation until SIGNAL_ALERT clears

### What WILL Happen Automatically
- ✓ Next organic daily snapshot (2026-05-15 or later) will recompute inst_delta_z against fresh institutional_summary.json
- ✓ Rank recomputation will reflect new inst_delta_z values naturally
- ✓ ic_health heartbeat will detect the change and clear SIGNAL_ALERT (if alert logic is functioning)

---

## Execution Notes

**When 13F files are available:**
1. Verify Gate 1 (file freshness) + Gate 2 (as_of_date) manually
2. Run production snapshot on 2026-05-15 (or next trading day) — this will ingest new institutional_summary.json
3. Run `python tools/production_qa_check.py --as-of-date 2026-05-15` (covers Spec 105 closure)
4. Verify Gates 3–5 (inst_delta normalization, SIGNAL_ALERT, top-ticker attribution)
5. Commit post-refresh audit to `artifacts/audit/13f_q1_2026_refresh_postmortem_YYYY_MM_DD.md`

**Timeline expectation:** 13F filings typically available by end of business 2026-05-15; processing and validation complete by 2026-05-16.

---

## References

- Distortion regime memo: `memory/regime_post_cohort_change_distortion_2026_04_28.md`
- Cohort expansion analysis: `artifacts/manager_cohort_expansion_2026_04_27.md`
- Cohort quarantine flags: `data/snapshots/2026-04-25/cohort_state.json`
- Current rank-change alerts: `data/snapshots/2026-05-13/rank_change_alerts.md`
