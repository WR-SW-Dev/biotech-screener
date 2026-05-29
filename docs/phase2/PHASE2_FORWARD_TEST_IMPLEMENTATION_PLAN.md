# Phase 2 Forward Paper Test — Implementation Plan

**Status:** Plan-only (no code, no execution, no production changes)  
**Branch:** `phase2-forward-paper-test-plan`  
**Authorization:** Approved for planning; implementation requires separate approval  
**Date:** 2026-05-29

---

## 1. Overview

This document defines the implementation approach for a forward paper test of portfolio transition policies. The test is **read-only**, **paper-only**, and **requires no production changes**. All outputs are diagnostic and do not influence live systems.

### Scope
- **Test period:** 60–90 trading days (pending governance start date approval)
- **Policies tracked:** 5 (current shadow + 4 historical proxies)
- **Data source:** Daily snapshot rankings (read-only)
- **Output:** Daily performance artifacts, transaction-cost estimates, checkpoint memos
- **Live impact:** Zero (all tracking is observational)

---

## 2. Policies to Track

### Policy 1: Current Advisory Behavior (Shadow Portfolio)
- **Description:** Current daily fresh top-30 ranking (status quo)
- **Entry rule:** Daily top-30 on each snapshot
- **Exit rule:** Falls below top-30 on next snapshot
- **Rebalance frequency:** ~175 per period (daily)
- **Baseline purpose:** Current state; shows what is actually running
- **Artifact label:** `current_advisory`

### Policy 2: Weekly Trade Packet Proxy
- **Description:** Historical proxy for weekly rebalancing cadence
- **Entry rule:** Top-30 on entry date (Friday of each week)
- **Exit rule:** Friday of next week or delisting/liquidity drop
- **Rebalance frequency:** ~52 per period (weekly)
- **Purpose:** Test whether weekly is superior to daily/quarterly
- **Artifact label:** `weekly_proxy`

### Policy 3: Quarterly Rebalance Proxy
- **Description:** Historical proxy for quarterly rebalancing cadence (Phase 1 leading policy)
- **Entry rule:** Top-30 on first snapshot of each quarter
- **Exit rule:** First snapshot of next quarter or delisting/liquidity drop
- **Rebalance frequency:** 4 per period (quarterly)
- **Purpose:** Validate Phase 1 finding (+127.4% avg, +11.8pp vs weekly)
- **Artifact label:** `quarterly_proxy`

### Policy 4: Static Inception Hold
- **Description:** Hold first top-30 through end of test without rebalancing
- **Entry rule:** Top-30 on start date
- **Exit rule:** Delisting or end of test
- **Rebalance frequency:** 0 (no rebalancing)
- **Purpose:** Baseline test of pure selector strength
- **Artifact label:** `static_hold`

### Policy 5: Delisting/Liquidity-Only Hold
- **Description:** Hold initial top-30; exit only on delisting or ADV drop below threshold
- **Entry rule:** Top-30 on start date
- **Exit rule:** 10+ calendar days missing from price data OR ADV < $500K
- **Rebalance frequency:** ~2–5 (delisting events only)
- **Purpose:** Test minimal-friction hold strategy
- **Artifact label:** `delisting_only`

---

## 3. Daily Artifact Schema

### File Structure
```
artifacts/portfolio_policy_forward_test/
├── daily/
│   ├── YYYYMMDD_holdings.json          (holdings snapshot for all 5 policies)
│   ├── YYYYMMDD_performance.json       (daily returns, alpha, contribution)
│   └── YYYYMMDD_staleness.json         (rank drift vs current top-30)
├── summaries/
│   ├── YYYYMMDD_weekly_summary.json    (cumulative metrics)
│   └── YYYYMMDD_transaction_costs.json (estimated cost model)
├── checkpoints/
│   ├── 30d_checkpoint_memo.md
│   ├── 60d_checkpoint_memo.md
│   └── 90d_final_memo.md
└── metadata/
    ├── README.md                        (paper-only disclaimer)
    ├── test_config.json                 (test parameters)
    └── stop_conditions_log.txt          (stop condition tracking)
```

### Daily Holdings File Schema (`YYYYMMDD_holdings.json`)
```json
{
  "date": "YYYY-MM-DD",
  "snapshot_available": true,
  "policies": {
    "current_advisory": {
      "tickers": ["NTLA", "ERAS", "PVLA", ...],
      "count": 30,
      "weights": [0.0333, 0.0333, ...],  // equal-weight
      "entry_dates": {"NTLA": "2026-05-29", ...},
      "rebalanced_today": true,
      "rebalance_reason": "daily_snapshot"
    },
    "weekly_proxy": {
      "tickers": [...],
      "count": 30,
      "weights": [0.0333, ...],
      "entry_dates": {...},
      "rebalanced_today": false,
      "last_rebalance": "2026-05-24",
      "next_rebalance": "2026-06-06"
    },
    "quarterly_proxy": {
      "tickers": [...],
      "count": 30,
      "weights": [0.0333, ...],
      "entry_dates": {...},
      "rebalanced_today": false,
      "last_rebalance": "2026-04-01",
      "next_rebalance": "2026-07-01"
    },
    "static_hold": {
      "tickers": [...],
      "count": 30,
      "weights": [0.0333, ...],
      "entry_dates": {"NTLA": "2026-05-29", ...},
      "rebalanced_today": false,
      "inception_date": "2026-05-29"
    },
    "delisting_only": {
      "tickers": [...],
      "count": 28,  // 2 delisted
      "weights": [0.0357, ...],  // reweighted
      "entry_dates": {...},
      "delisted": ["DXCM", "VTRS"],
      "delisting_dates": {"DXCM": "2026-05-15", ...},
      "rebalanced_today": false
    }
  }
}
```

### Daily Performance File Schema (`YYYYMMDD_performance.json`)
```json
{
  "date": "YYYY-MM-DD",
  "policies": {
    "current_advisory": {
      "daily_return": 0.0145,          // +1.45%
      "cumulative_return": 0.0245,     // +2.45% from test start
      "xbi_daily_return": 0.0080,      // +0.80%
      "xbi_cumulative_return": 0.0145, // +1.45% from test start
      "alpha_daily": 0.0065,           // 0.65pp
      "alpha_cumulative": 0.0100,      // 1.00pp
      "n_priced": 30,
      "n_missing": 0,
      "contribution_by_ticker": {
        "NTLA": 0.00048,               // contribution = weight × daily_return
        "ERAS": 0.00051,
        ...
      }
    },
    "weekly_proxy": {...},
    "quarterly_proxy": {...},
    "static_hold": {...},
    "delisting_only": {...}
  }
}
```

### Daily Staleness File Schema (`YYYYMMDD_staleness.json`)
```json
{
  "date": "YYYY-MM-DD",
  "current_top_30": ["NTLA", "ERAS", ...],
  "policies": {
    "weekly_proxy": {
      "holdings": ["NTLA", "ERAS", ...],
      "jaccard_overlap": 0.867,        // 26/30 shared
      "new_entrants": ["CELC"],        // in current, not in weekly
      "dropouts": ["DNTH"],            // in weekly, not in current
      "days_since_rebalance": 3,
      "next_rebalance_in_days": 4
    },
    "quarterly_proxy": {
      "holdings": [...],
      "jaccard_overlap": 0.800,        // 24/30 shared
      "new_entrants": ["CELC", "FATE"],
      "dropouts": ["DNTH"],
      "days_since_rebalance": 58,
      "next_rebalance_in_days": 7
    },
    "static_hold": {
      "holdings": [...],
      "jaccard_overlap": 0.767,        // 23/30 shared
      "new_entrants": ["CELC", "FATE", "CRSP"],
      "dropouts": ["DNTH", "CBPO"],
      "days_since_inception": 58
    },
    "delisting_only": {
      "holdings": [...],
      "jaccard_overlap": 0.833,        // 25/30 (accounting for delistings)
      "new_entrants": ["CELC"],
      "dropouts": ["DNTH"],
      "delisted_since_test_start": ["DXCM", "VTRS"],
      "delistings_this_week": 0
    }
  }
}
```

---

## 4. Performance Metrics

### Cumulative Metrics (Tracked Daily)
- **Return:** Total portfolio return from test start to date
- **XBI return:** Benchmark return (same period)
- **Alpha:** Portfolio return − XBI return
- **Sharpe ratio:** Cumulative return / standard deviation of daily returns
- **Max drawdown:** Peak-to-trough decline from inception

### Per-Ticker Metrics (Tracked Daily)
- **Weight:** Current position weight (equal-weight adjusted for delistings)
- **Entry date:** Date ticker entered the portfolio
- **Days held:** Calendar days since entry (cumulative across spells if exited/re-entered)
- **Price:** Close price on date
- **Daily return:** (Today's price − yesterday's price) / yesterday's price
- **Contribution:** Weight × daily return (additive to portfolio return)
- **Cumulative contribution:** Sum of all daily contributions since entry
- **Realized P&L:** If exited, (exit price − entry price) / entry price

### Weekly Aggregates (Computed Each Friday)
- **Weekly return:** Sum of daily returns for the week
- **Turnover:** (Sum of exits + sum of entries) / 2 / average portfolio value
- **Number of names exiting:** Count of holdings that fell below top-30 or delisted
- **Number of names entering:** Count of new holdings added
- **Average position weight:** Mean weight across holdings
- **Portfolio concentration:** Herfindahl-Hirschman Index (HHI) = Σ(weight²)
- **Realized transaction cost (estimate):** See Section 5

---

## 5. Transaction-Cost Model Assumptions

### Assumptions (to be validated against actual market data)
- **Borrow cost:** 15 bps per annum on short biotech names (assumed via financials; actual rate varies by name/date)
- **Slippage on entry:** 5 bps (assuming execution at top-of-book average during rebalance day)
- **Slippage on exit:** 5 bps (same)
- **Bid-ask spread proxy:** 10 bps (proxy for illiquidity; actual spread varies by liquidity tier)
- **Market impact:** 0 (assumed small positions, <5% of daily volume)

### Estimated Cost per Trade
- **Entry cost:** 5 (slippage) + 5 (bid-ask half) = 10 bps
- **Exit cost:** 5 (slippage) + 5 (bid-ask half) = 10 bps
- **Total cost per trade (round-trip):** 20 bps = 0.20%

### Annualized Cost Estimate
- **Quarterly:** 4 rebalances/year × 30 names × 20 bps ≈ 24 bps/year
- **Weekly:** 52 rebalances/year × 30 names × 20 bps ≈ 312 bps/year = 3.12%
- **Current (daily):** 175 rebalances/year × 30 names × 20 bps ≈ 1050 bps/year = 10.5%

### Daily Calculation
```
transaction_cost_daily = (names_entering + names_exiting) × 0.10% × average_position_size
```

### Tracking Method
1. Log all entry/exit events by date
2. Compute transaction cost for each event
3. Accumulate over week and month
4. Compare net return (return − transaction cost) to benchmark
5. Flag if transaction cost > 50% of alpha

---

## 6. Attribution Fields

### Shared Holdings Attribution
- **Holdings count:** Number of tickers in both policy and current top-30
- **Jaccard overlap:** (Shared holdings) / (Union of holdings)
- **Return on shared holdings:** Portfolio return if only shared tickers; isolates the benefit of being in common names

### Policy-Specific Attribution
- **Weekly-only holdings:** Tickers in weekly but not in quarterly (or current)
- **Weekly-only return contribution:** Return attributed to weekly-only positions
- **Quarterly-only holdings:** Tickers in quarterly but not in weekly (or current)
- **Quarterly-only return contribution:** Return attributed to quarterly-only positions

### Turnover-Adjusted Attribution
- **Cost-adjusted return:** Cumulative return − estimated transaction cost
- **Cost-adjusted alpha:** Alpha after transaction cost

### Spell-Based Timeline Attribution (if policy exits and re-enters)
- **Entry dates:** All dates a ticker entered (first entry + re-entries)
- **Exit dates:** All dates a ticker exited
- **Spells:** List of [entry_date, exit_date] holding periods
- **Total exposure days:** Sum of days held across all spells
- **Number of spells:** Count of separate holding periods

---

## 7. Stop Conditions

### Hard Stop (Immediate termination required)
- Data source breaks: Daily snapshots unavailable for > 2 consecutive business days
- XBI benchmark data missing for > 2 consecutive business days
- Production system accidentally modified (any rebalance, ranking change, or pipeline change detected)
- Artifacts are NOT clearly marked "paper-only" (governance violation)
- Test accidentally influences live advisor behavior

### Soft Stop (Escalate to governance; awaiting decision)
- Quarterly underperforms weekly/current by > 10pp cumulative alpha (re-evaluate hypothesis)
- Advantage disappears after transaction costs (outcome: archive results, no implementation)
- Max drawdown exceeds −30% (risk concern; governance may request pause or restart)
- Staleness (Jaccard overlap) drops below 0.60 (policies diverging too far from current state)
- Missing data or execution edge case occurs (unclear outcome, governance decides continuation)

### Checkpoint Pause (Scheduled review, continue unless told otherwise)
- 30-day checkpoint (governance reviews and can request modifications)
- 60-day checkpoint (governance reviews; can extend to 90 or stop)
- 90-day final checkpoint (governance decides: implement, archive, or run extended test)

---

## 8. Checkpoint Structure

### 30-Day Checkpoint (Scheduled ~30 trading days after test start)

**Deliverable:** `artifacts/portfolio_policy_forward_test/checkpoints/30d_checkpoint_memo.md`

**Contents:**
1. Test setup confirmation (start date, policies, data source status)
2. Cumulative results table (return, alpha, Sharpe, max DD by policy)
3. Turnover comparison (quarterly: ~1 rebalance vs weekly: ~7 vs current: ~30)
4. Early findings:
   - Quarterly leading/lagging vs weekly
   - Impact of transaction costs (estimated)
   - Any unexpected behavior or data issues
5. Staleness report (Jaccard overlap by policy)
6. Governance checkpoint decision options:
   - Continue to 60 days
   - Pause and investigate anomaly
   - Stop and archive results
   - Modify scope (e.g., add HOLD_30 policy)

### 60-Day Checkpoint (Scheduled ~60 trading days after test start)

**Deliverable:** `artifacts/portfolio_policy_forward_test/checkpoints/60d_checkpoint_memo.md`

**Contents:**
1. Cumulative results table (update with 60 days of data)
2. Attribution breakdown (shared holdings, policy-specific, cost-adjusted)
3. Timeline staleness trends (has divergence widened?)
4. Transaction cost tracking (actual vs estimated)
5. Any stop conditions triggered? (if yes, governance decision point)
6. Governance decision options:
   - Continue to 90 days
   - Stop now and finalize results
   - Extend beyond 90 days
   - Implement quarterly if leading by > 5pp after costs

### 90-Day Final Checkpoint (Scheduled ~90 trading days after test start)

**Deliverable:** `artifacts/portfolio_policy_forward_test/checkpoints/90d_final_memo.md`

**Contents:**
1. Full 90-day results table (return, alpha, Sharpe, max DD, turnover by policy)
2. Final attribution summary (shared holdings, policy-specific, cost-adjusted alpha)
3. Transaction cost analysis (estimated vs observed, if measurable)
4. Mechanism analysis:
   - Is quarterly advantage from entry timing? (timeline analysis)
   - Or from hold duration? (spell analysis)
   - Or from exposure concentration? (weight/Herfindahl analysis)
5. Governance final decision options:
   - Implement quarterly rebalancing (requires separate Phase 3 approval)
   - Keep current daily advisory (reject quarterly hypothesis)
   - Run extended test (request additional data period)
   - Archive results and revisit later

---

## 9. Files to Be Created (If Implementation Later Approved)

### Code/Harness Files
- `scripts/phase2_forward_test_harness.py` (main tracking script)
- `tools/phase2_transaction_cost_model.py` (transaction cost estimation)
- `tools/phase2_staleness_calculator.py` (Jaccard overlap, rank drift)
- `tools/phase2_checkpoint_generator.py` (automated checkpoint memo generation)

### Configuration Files
- `config/phase2_test_config.json` (test parameters, start date, end date, policies)
- `config/phase2_artifacts_schema.json` (JSON schema for daily artifacts)
- `config/phase2_stop_conditions.json` (stop condition thresholds)

### Artifact Directories
- `artifacts/portfolio_policy_forward_test/daily/` (daily holdings, performance, staleness)
- `artifacts/portfolio_policy_forward_test/summaries/` (weekly/monthly summaries)
- `artifacts/portfolio_policy_forward_test/checkpoints/` (30/60/90-day memos)
- `artifacts/portfolio_policy_forward_test/metadata/` (README, config, logs)

### Cron Job (if execution later approved)
- Daily cron job to run harness at EOD after snapshot ingestion
- Checkpoint generator cron jobs (30, 60, 90-day reminders to governance)

### Monitoring/Dashboard (if visualization later approved)
- `docs/phase2/FORWARD_TEST_DASHBOARD.md` (read-only status page)
- Optional: Jupyter notebook for interactive checkpoint review

---

## 10. Guardrails and Constraints

### Code Constraints
- ✓ **Read-only:** No production code modification
- ✓ **No live rebalancing:** Paper tracking only
- ✓ **No state persistence:** No portfolio state in production systems
- ✓ **No pipeline changes:** Daily snapshot ingestion unchanged
- ✗ **NOT allowed:** Cron modification, selector/ranker changes, live trading

### Artifact Constraints
- ✓ **Paper-only label:** All artifacts marked "Paper-only; no trading instruction"
- ✓ **Versioned:** Daily artifacts timestamped and archived
- ✗ **NOT allowed:** Artifacts used for live decisions without governance approval

### Governance Constraints
- ✓ **Checkpoint review:** Governance reviews at 30, 60, 90 days
- ✓ **Stop conditions monitored:** Hard stops trigger immediate escalation
- ✓ **Decision gates:** Implementation requires Phase 3 approval after Phase 2 completes
- ✗ **NOT allowed:** Automatic deployment of quarterly policy

---

## 11. Success Criteria for Phase 2

### Phase 2 Successfully Completes If
1. **Test period satisfied:** Full 60–90 trading days of data collected
2. **All artifacts generated:** Daily, weekly, and checkpoint memos complete
3. **No stop conditions triggered:** Or all triggered conditions escalated and resolved
4. **Data quality maintained:** < 1% missing price data, XBI always available
5. **Governance checkpoints met:** 30, 60, 90-day reviews completed

### Results Eligible for Phase 3 (Implementation) If
1. **Quarterly demonstrates consistent advantage:** > 5pp net alpha after transaction costs
2. **Advantage not driven by one name:** Top-5 holdings < 40% of alpha
3. **Staleness acceptable:** Jaccard overlap vs current top-30 remains > 0.70
4. **Drawdown tolerable:** Max DD < −25% (or comparable to current)
5. **Mechanism understood:** Attribution shows clear entry/hold/churn effect

### Results Archived (No Phase 3) If
1. **Quarterly underperforms:** Alpha < 3pp net of costs
2. **Advantage disappears after costs:** Transaction cost > 60% of alpha
3. **High staleness:** Policy diverges materially from current top-30 (Jaccard < 0.60)
4. **High concentration risk:** One or two names drive > 50% of advantage
5. **Drawdown spike:** Exceeds −30% or causes regret-indexed underperformance

---

## 12. Implementation Dependencies

### Before Phase 2 Can Start
- [ ] Governance approves this plan
- [ ] Test start date confirmed (first trading day after approval)
- [ ] Test end date confirmed (60 or 90 trading days)
- [ ] Data source verified (daily snapshots available and stable)
- [ ] XBI benchmark data confirmed available
- [ ] No production changes to ranking/selector/rebalance logic

### Before Phase 2 Code Can Be Committed
- [ ] This plan is approved (in writing by governance)
- [ ] Implementation review complete (code design, dependencies, logging)
- [ ] Pre-test dry run on historical data (Phase 1 harness extended to Phase 2 schema)

### Before Phase 2 Goes Live
- [ ] Dry run completed without errors
- [ ] Artifacts confirm paper-only and governance labels present
- [ ] Governance final sign-off (this plan + readiness confirmation)

---

## 13. Next Steps

1. **Governance review:** Submit this plan to governance for approval
2. **Clarify test start date:** Confirm first trading day after approval
3. **Assign implementation owner:** Who will code the harness?
4. **Assign governance review owner:** Who will author checkpoint memos?
5. **Code design review:** Propose implementation approach for plan
6. **Dry run:** Extend Phase 1 harness to Phase 2 schema, validate on historical data
7. **Go-live:** First trading day, begin daily artifact collection

---

**Status: Plan-only. Ready for governance review. No code, no execution, no production impact.**

*Last updated: 2026-05-29*  
*Prepared by: Phase 1 Diagnostic Harness (Plan-only deliverable)*
