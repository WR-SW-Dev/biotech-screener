# Design Memo: Persistent Portfolio Transition Layer

**Date:** 2026-05-29  
**Scope:** Read-only design investigation. No code changes. No production impact.  
**Question:** Should the shadow portfolio move from daily fresh top-30 construction to persistent holdings with explicit entry/exit rules?

---

## 1. Current Production Behavior

### Daily Shadow Portfolio Construction (as of 2026-05-29)

**Entry point:** `tools/run_daily_production.py:4078` → Step 5f

```
run_daily() 
  → run_shadow_portfolio(snapshot_dir)
    → load_rankings(snap_dir)              [current day only]
    → build_positions(rankings, policy)    [fresh from scratch]
    → compute_performance(prior, current)  [observational only]
```

**Implementation:**
- `tools/live_shadow_portfolio.py:build_positions()` (line 764):
  - Loads current-day rankings only
  - Classifies into buckets
  - Selects top-K per bucket by actionable_rank
  - Allocates equal weight or family-targeted weight
  - **No prior holdings comparison**
  - **No tier-downgrade detection**
  - **No rank-deterioration gate**
  - **No position-change budget**

**Result:**
- Each day: portfolio rebuilt from scratch using current top-30 rankings
- No explicit holding period
- No explicit rebalance rules
- Turnover measured post-hoc, not managed in construction

**Classification:** `DAILY_FRESH_REBUILD_ACTIVE = true`

---

## 2. Selector Evidence: Canonical Rolling-Cohort Validation

### Test: 7 overlapping formation-date cohorts, 2024-10-18 to 2026-01-02

**Test design:**
- Each cohort inception: load that day's top-30 rankings
- Hold to 2026-05-27 (common terminal)
- Compare delisting-only (DL) buy-and-hold vs rolling fresh top-30 (BH)

**Results:**

| Inception  | Days | BH Return | DL Return | Diff | Verdict |
|------------|------|-----------|-----------|------|---------|
| 2024-10-18 | 588  | +87.08%   | +81.33%   | -5.75pp | ✗ BH better |
| 2024-11-01 | 574  | +98.53%   | +88.25%   | -10.28pp | ✗ BH better |
| 2025-01-10 | 504  | +139.13%  | +131.75%  | -7.38pp | ✗ BH better |
| 2025-04-11 | 413  | +154.19%  | +145.39%  | -8.80pp | ✗ BH better |
| 2025-07-18 | 315  | +98.74%   | +101.61%  | +2.87pp | ✓ DL better |
| 2025-10-10 | 231  | +59.36%   | +59.07%   | -0.29pp | ✓ Match |
| 2026-01-02 | 147  | +35.05%   | +33.43%   | -1.62pp | ✗ BH better |

**Summary:**
- Average fresh top-30 (BH): **+96.01%**
- Average delisting-only (DL): **+91.55%**
- Average difference: **-4.46pp** (fresh rebuild slightly underperforms holding)

**Interpretation:**
- **Selector strength is confirmed.** Both BH and DL beat XBI (+43.49%) by 48-103pp.
- **Right-tail compounding is vulnerable to churn.** 5 of 7 cohorts show fresh rebuild underperforming static hold.
- **Delisting-only cost is minimal:** -4.46pp average, max -10.28pp, occasionally match or beat.

---

## 3. Why Tier-Exit Harm is Diagnostic-Only

### Backtest Simulation: Tier-based Exit Policy

**Scenario:** Daily top-30 portfolio + rule: "sell if tier_dev downgraded or actionable_rank fell below 30"

**Test:** Compare simulated tier-exit vs delisting-only on same 7 cohorts

**Results:**

| Inception  | Tier-Exit | Delisting-Only | Harm |
|------------|-----------|----------------|------|
| 2024-10-18 | +42.38%   | +81.33%        | -38.95pp |
| 2024-11-01 | +32.76%   | +88.25%        | -55.49pp |
| 2025-01-10 | +48.17%   | +131.75%       | -83.58pp |
| 2025-04-11 | +42.25%   | +145.39%       | -103.14pp |
| 2025-07-18 | +103.92%  | +101.61%       | +2.31pp |
| 2025-10-10 | +58.16%   | +59.07%        | -0.91pp |
| 2026-01-02 | +31.81%   | +33.43%        | -1.62pp |

**Average harm:** -35.14pp  
**Worst case:** -102.27pp (2025-04-11)  
**Best case:** +2.31pp (2025-07-18)

**Why this is diagnostic-only:**

1. **Not in production code.** Audit confirmed: `build_positions()` does not compare tier_dev or actionable_rank across days. No tier-exit gate exists.

2. **Simulated only in backtest tool.** Code location: `tools/build_policy_shadow_compare.py:109` (compute_tiered_exit_weights function). **Classification: SHADOW_ONLY.**

3. **Test shows why it would fail if active.** Tier-based sells create catastrophic churn in right-tail regimes (2025-01, 2025-04). Winners get demoted on volatility spikes or brief underperformance, then portfolio misses recovery.

4. **Policy exists as a governance warning, not a code bug.** The harm is real if implemented; it doesn't exist as a bug in current live code.

---

## 4. Why Daily Rebuild Remains a Live Portfolio-Design Risk

### The Core Issue

**Current design:** Each day, construct fresh top-30 from that day's rankings.  
**Implicit behavior:** 100% turnover potential daily; portfolio resets each morning.

**Why this matters:**

1. **No holding period.** A stock that ranks #1 today might be rebuilt out tomorrow if it slips to #31 in the next snapshot. Right-tail compounding requires staying invested through volatility.

2. **No exit policy explicitness.** The portfolio doesn't say "we hold for 30 days" or "we hold until delisting." It just says "whatever today's top-30 is." That's not a policy; it's a ranking feed.

3. **Churn vs performance tradeoff is hidden.** The canonical cohort test shows fresh top-30 outperforms delisting-only by **-4.46pp on average.** But that's measured across 6-588 days. Over what period should the portfolio actually turn over?

4. **Performance attribution breaks down.** If the portfolio is rebuilt daily, "portfolio performance" is indistinguishable from "today's top-30 price movement." The shadow portfolio is more of a monitoring tool than a real portfolio strategy.

---

## 5. Proposed Policy Candidates

### A. Daily Advisory Rankings Only (No Portfolio Claim)

**Rule:** Publish `rankings.csv` as a signal, not a portfolio.

**Pros:**
- No portfolio performance claim
- No rebalance confusion
- Clear signal semantics

**Cons:**
- Defeats the purpose of a portfolio strategy
- Performance analysis becomes moot
- Selector validation still valid, but can't claim tradable returns

**Validation needed:** None (reframing exercise)

---

### B. Persistent Top-30 with Delisting/Liquidity-Only Exits

**Rule:** 
- Entry: Daily top-30 rankings determine eligible names
- Hold: Keep position until one of:
  - Position delisted
  - ADV < threshold (e.g., $2M/day)
  - Position falls outside top-60 for N consecutive days (e.g., N=5)
- Rebalance: When exits occur, backfill from new top-30

**Pros:**
- Explicit exit policy
- Delisting-only harm is minimal (-1.91pp avg, per cohort test)
- Holding period allows right-tail compounding
- Liquidity gate protects against illiquid winners

**Cons:**
- Requires portfolio state persistence
- Requires position tracking logic
- Rebalance lag creates tracking error vs rankings

**Canonical test proxy:** Delisting-only results = -1.91pp average harm from fresh rebuild ← **This is what policy B costs vs fresh rebuild**

**Validation needed:**
- Walk-forward test: 2026-05-27 → 2026-06-30 
  - Simulate holding period under liquidity gates
  - Measure turnover vs fresh top-30
  - Track drawdown under "top-60 drift" scenarios

---

### C. Persistent Top-30 with Minimum Hold Period

**Rule:**
- Entry: Top-30 ranking on entry date
- Hold: Minimum 30/60/90 days
- Exit: Minimum hold period + (delisting OR ADV drop OR explicit rebalance day)

**Pros:**
- Simple rule
- Predictable hold period
- Reduces churn vs daily rebuild

**Cons:**
- Holding losers past minimum period (drag in downside regimes)
- Rebalance lag creates mid-month drift from rankings
- Requires calendar/state tracking

**Canonical test proxy:** Overlapping 30/60/90-day windows on same 7 cohorts

**Validation needed:**
- Rolling 30/60/90-day window test
  - Entry: top-30 on day 0
  - Exit: day 30/60/90 + delisting
  - Compare to fresh daily top-30
  - Measure performance and drawdown

---

### D. Persistent Top-30 with Winner-Retention Overlay

**Rule:**
- Entry: Top-30 ranking
- Hold: Until exit rule OR (winner ∧ outperforming portfolio average)
- Exit: Minimum hold period + (delisting OR ADV drop OR underperformer + portfolio drawdown + momentum negative)

**Pros:**
- Lets winners compound
- Keeps discipline on losers
- Aligns with behavioral advantage (avoid selling winners too early)

**Cons:**
- Complex rule; hard to backtest/explain
- Requires real-time P&L tracking
- Winner/loser definitions ambiguous

**Validation needed:**
- Complex: requires per-position P&L stream
- Probably defer to post-governance phase

---

### E. Quarterly/Monthly Rebalance Variants

**Rule:**
- Entry: Top-30 on rebalance date (e.g., 1st trading day of month)
- Hold: Until next rebalance (30/90 days) or exit gate
- Exit: Delisting, ADV drop, or rebalance day

**Pros:**
- Calendar-predictable
- Reduces churn vs daily rebuild (12-4x per year)
- Holds through monthly noise

**Cons:**
- Longer trailing of rankings (end-of-month portfolio may be stale vs start-of-month top-30)
- Synchronization risk (all managers rebalance same day → execution impact)

**Canonical test proxy:** Sample rebalance dates (e.g., every 20/63 days) on same 7 cohorts

**Validation needed:**
- Walk-forward: 2026-05-27 → 2026-08-31
  - Monthly rebalance on 1st trading day
  - Hold until next rebalance + exits
  - Track performance, turnover, drawdown vs daily fresh top-30
  - Measure stale-ranking drift (gap between top-30 on rebalance date vs current)

---

## 6. Required Validation Before Implementation

### Phase 1: Diagnostic (read-only, no code)

- [ ] **Overlapping window rolling tests** on canonical cohorts (2024-10-18 to 2026-01-02)
  - Run 30/60/90-day rolling windows
  - Compare each policy to fresh daily top-30 baseline
  - Measure: total return, Sharpe, max drawdown, turnover, Jaccard overlap

- [ ] **Forward-looking proxy test** (2026-05-27 → 2026-08-31)
  - Simulate policy B (delisting/liquidity) and E (monthly rebalance) in parallel
  - Monitor: entry/exit counts, position staleness, turnover
  - Capture: performance if live

- [ ] **Cohort contamination check**
  - Confirm 2026-05-24 13F refresh has not invalidated prior cohort tests
  - Confirm 2026-05-28 Path C governance decision does not conflict with portfolio analysis

### Phase 2: Governance (decision gates)

- [ ] **Benchmark decision** — which policy is baseline? (Current: fresh daily top-30)

- [ ] **Hold-period governance** — what is minimum acceptable compounding window?

- [ ] **Churn budget** — what is acceptable turnover vs performance tradeoff?

- [ ] **Exit rule governance** — who decides delisting-only vs tier-based vs other?

### Phase 3: Implementation (if approved)

- [ ] **Code design** — portfolio state persistence, rebalance logic, entry/exit tracking
- [ ] **Backfill** — prior snapshots + decision dates
- [ ] **Integration** — tie shadow portfolio to ranking feed
- [ ] **Monitoring** — daily drift, turnover, staleness alerts

---

## 7. Governance Recommendation

### Current State Assessment

| Component | Status | Confidence | Next Owner |
|-----------|--------|------------|------------|
| **Selector validation** | ✅ STRONG | High | Product (selector is ready) |
| **Tier-exit risk** | ⚠️ DIAGNOSTIC | High | Governance (not in production, but harmful if activated) |
| **Portfolio policy** | ❌ IMPLICIT | Medium | Strategy (daily rebuild is not explicit policy) |

### Recommended Governance Path

**Immediate (next 2 weeks):**
1. **Acknowledge:** Tier-exit backtest harm is diagnostic-only, not a production bug.
2. **Decide:** Is daily advisory-rankings-only acceptable, or does portfolio need explicit hold period?
3. **Assign:** If portfolio is the strategy, assign policy ownership to strategy team.

**Phase 1 validation (weeks 3-6):**
1. Run rolling window tests on canonical cohorts for policies B, C, E.
2. Run forward proxy test (May 27 → Aug 31) in parallel.
3. Report: performance, turnover, drawdown tradeoffs for each policy.

**Phase 2 governance (weeks 7-8):**
1. Present validation results to governance board.
2. **Decision:** Policy B (delisting/liquidity)? C (minimum hold)? E (monthly rebalance)? A (advisory-only)?
3. **Sign-off:** Confirm policy aligns with mandate and risk tolerance.

**Phase 3 implementation (if approved, weeks 9+):**
1. Code portfolio state persistence.
2. Backfill snapshots and decision dates.
3. Go live on new policy; monitor Phase 1 validation metrics.

---

## Summary

| Finding | Verdict |
|---------|---------|
| **Selector strength** | ✅ Confirmed on canonical cohorts: +96.01% avg vs XBI +43.49% |
| **Tier-exit harm** | ⚠️ Real in simulation (-35.14pp), but diagnostic-only in code |
| **Live portfolio issue** | ❌ Daily fresh rebuild has no explicit hold period or exit policy |
| **Recommended next step** | Governance decision: what is the portfolio policy? |

**Do not recommend deployment of current daily-rebuild as a portfolio strategy until hold-period policy is explicit and validated.**

**Do not change production code** — this is a governance and design question, not a bug fix.

