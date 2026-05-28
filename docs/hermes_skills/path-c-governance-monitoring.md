---
name: path-c-governance-monitoring
triggers:
  - "Path C override status"
  - "catalyst timing policy"
  - "forward eval IC monitoring"
  - "2026-06-03 governance decision"
  - "IC_UNOBSERVABLE handling"
description: >
  Governance framework for Path C temporary policy override (2026-05-28 to 2026-06-03).
  Catalyst timing policy temporarily relaxed due to real institutional consensus on near-term
  catalysts. Monitored via forward eval IC floor (0.0200). Includes IC_UNOBSERVABLE contingency
  for when PIT price cache horizons have not yet filled (expected until mid-June).
---

# Path C Governance Monitoring — Temporary Policy Override

## Purpose

Monitor and govern the temporary catalyst-timing policy override (Path C) active from 2026-05-28 through 2026-06-03. This skill documents:

1. **Why Path C was approved** — institutional consensus on near-term catalysts is real, policy/signal mismatch is not a data failure
2. **How it's monitored** — forward eval IC floor (0.0200) as guardrail
3. **What happens at window close** — decision logic including IC_UNOBSERVABLE handling
4. **What happens before window close** — emergency revert conditions

**Context:** This is a governance override of Phase 2 health gates due to catalyst concentration (0-7d weight 40.83% vs 10% policy). The override is conditional, time-bounded, and monitored.

---

## 1. Path C Decision Summary

**Effective period:** 2026-05-28 snapshot through 2026-06-03 (forward eval IC window close)

**What's being overridden:**
- 0–30d binary catalyst exposure: allowed up to 40–45% (vs legacy 10% policy)
- 91–180d exposure: allowed to fall to observed regime level 26.7% (vs legacy 55%)
- Phase 2 health gates: `catalyst_7d_weight_high` and `catalyst_7d_count_high` FAIL verdicts accepted

**Why it's valid:**
- Institutional data contamination remediated: 49 elite managers loaded from Q1 2026 cache (vs stale 42-manager version)
- Near-term concentration confirmed as real institutional consensus (COGT, RVMD, SYRE, PRAX high coinvest scores), not selector bias
- Selector tier assignment already favors 8–90d catalysts (38.2% A-tier vs 25.5% near-term); ranker correctly reflects institutional signal strength
- Readiness HOLD is caused by policy/signal mismatch, not data quality failure

**Governance stance:** Accepts near-term event-risk concentration as intentional opportunity. Explicit accountability for daily monitoring and transparent handling of measurement gaps.

---

## 2. Forward Eval IC Monitoring Framework

### IC Ledger Infrastructure

**Location:** `artifacts/forward_eval_ic_ledger.jsonl`

**Tool:** `tools/forward_eval_ic_ledger.py` — Extracts mean_ic from forward_eval gate results

**Integration:** Automatically wired into `tools/run_daily_production.py` Step 5a (post-snapshot promotion)

**Data source:** Forward eval gate computes rolling Spearman IC over 10+ snapshots with filled 20-day return horizons. Extracts mean_ic, median_ic, and date-by-date IC values.

### Monitoring Schedule

- **Daily:** After each production snapshot (post-promotion), IC ledger auto-updates
- **Real-time:** Can run `python3 tools/monitor_forward_eval_ic.py` anytime to check current trend
- **Window close:** 2026-06-03 (mandatory operator decision)

### Guardrail Threshold

**Floor:** mean_ic >= 0.0200 (5d forward returns)

**Interpretation:**
- IC >= 0.0200 → Institutional consensus (near-term concentration) is generating positive predictive power
- IC < 0.0200 → Institutional consensus is not translating to return predictability; policy override is unwarranted
- IC unavailable (IC_UNOBSERVABLE) → See section 3

---

## 3. Window Close Decision Logic (2026-06-03)

### Scenario A: IC is Observable

**If mean_ic >= 0.0200:**
- Path C remains valid
- Window closes successfully
- Continue with next governance cycle

**If mean_ic < 0.0200:**
- Path C revoked immediately
- Revert to HOLD pending Path A (durable portfolio timing gates)
- Escalate to operator with evidence summary

### Scenario B: IC is Unobservable (Expected)

**Classification:** IC_UNOBSERVABLE

**Cause:** PIT cache does not have filled 20-day forward-return horizons by 2026-06-03. This is expected because:
- Forward eval gate requires 10+ snapshots with 20-day price data filled
- Market data for the full 20-day forward horizon doesn't arrive until ~2026-06-17
- Real-time monitoring lag: observable IC ~2 weeks after observation date

**Operator decision required. Choose one:**

1. **Extend window** (recommended if conviction remains):
   - Extend Path C until first observable IC print (~2026-06-17)
   - Evaluate IC floor at that date
   - Document extension rationale

2. **Revert to HOLD** (conservative if uncertain):
   - Revert to HOLD pending Path A
   - Closes override immediately
   - Trigger Path A portfolio timing gate design (post-freeze)

**Documentation:** Whichever option is chosen, document decision and rationale in governance ledger with timestamp.

### Emergency Exits (Any Time Before 2026-06-03)

**Hard trigger 1: Drawdown threshold**
- If portfolio drawdown > 2pp relative to XBI → revoke Path C immediately
- Escalate with drawdown evidence

**Hard trigger 2: Cohort instability**
- If 13F cohort Jaccard < 0.70 or new quarantine triggers → escalate for review
- May trigger either HOLD revert or cohort re-validation depending on investigation

---

## 4. Operational Checklist

### Daily Monitoring (through 2026-06-03)

- [ ] Check IC ledger for new observations: `tail -5 artifacts/forward_eval_ic_ledger.jsonl`
- [ ] If IC observable: verify mean_ic >= 0.0200 (or note below-floor trend)
- [ ] Monitor portfolio drawdown vs XBI daily
- [ ] Flag any cohort instability (13F manager additions/removals)
- [ ] Log any anomalies in governance ledger

### 2026-06-03 Operator Decision

- [ ] Run `tools/monitor_forward_eval_ic.py` to get latest IC status
- [ ] Check PIT cache horizon status: `python3 -c "import json; idx=json.load(open('data/caches/price_pit/PIT/2026-06-03/index.json')); print(idx.get('horizons_filled'))"`
- [ ] If IC observable:
  - [ ] mean_ic >= 0.0200 → Document Path C valid closure
  - [ ] mean_ic < 0.0200 → Trigger revert to HOLD + Path A design
- [ ] If IC unobservable:
  - [ ] Decide: Extend to ~2026-06-17 or revert to HOLD?
  - [ ] Document decision with rationale
  - [ ] Update governance ledger

---

## 5. Related Governance Decisions

| Decision | Date | Status | Link |
|----------|------|--------|------|
| Path C override approval | 2026-05-28 | ACTIVE | `artifacts/readiness/GOVERNANCE_DECISION_PATH_C_2026_05_28.md` |
| Institutional contamination fix | 2026-05-28 | RESOLVED | 49-manager cohort deployed (commit 8cbe1648) |
| Catalyst concentration diagnosis | 2026-05-27 | LOCKED | `artifacts/readiness/CATALYST_CONCENTRATION_DIAGNOSIS.md` |
| IC tooling correction (Spec 100) | 2026-05-17 | RESOLVED | composite_score IC marked invalid; final_score default |
| IC evidence hold | 2026-05-13 | ACTIVE | Do not use prior IC claims until Spec 100 corrected (resolved) |
| 13F cohort quarantine | 2026-05-24 | CLEARED | Jaccard 0.875 >= 0.70 threshold |

---

## 6. Key Metrics & Triggers

| Metric | Normal | Warning | Critical |
|--------|--------|---------|----------|
| mean_ic | >= 0.0200 | 0.0100–0.0200 | < 0.0100 |
| Portfolio drawdown (vs XBI) | < 1pp | 1–2pp | > 2pp |
| 13F cohort Jaccard | >= 0.70 | 0.50–0.70 | < 0.50 |
| IC observability | Observable | Cold-start | Unobservable (>2 weeks lag) |

---

## 7. Contacts & Escalation

**Governance decision owner:** dschulz@wakerobin.co (Operator)

**Escalation path:**
1. Drawdown breach → Operator immediate decision
2. IC below floor → Operator + governance review
3. IC unobservable → Operator decision point on extend/revert
4. Cohort instability → Governance escalation + potential 13F re-validation

**Monitoring system:** Hermes ops_supervisor + IC_MONITOR agent (flagged for 2026-06-03)

---

## 8. Forward Reference

**Durable fix (Path A):** Portfolio timing gates to enforce max 30% in 0–7d, min 40% in 90+d. Design target post-freeze (2026-06-01+). This removes the policy/signal mismatch by decoupling institutional signal strength from portfolio timing distribution.

**Timeline:** Path C window closes 2026-06-03. Path A design begins post-freeze. Portfolio timing gates in place by Phase 2 Step 5 completion.
