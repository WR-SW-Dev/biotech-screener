# CLAUDE.md — Wake Robin Capital Management Biotech Screener

## Project Identity
This is an institutional-grade biotech investment screening system.
Outputs must be reproducible, auditable, and deterministic.
Every decision must be traceable to a data source with a timestamp.

## North Star Rule
Backtest systems NEVER directly modify production screening behavior.
They produce evidence and proposals only. Governance review required before
any backtest finding changes a production signal weight.

## CCFT Principles (Non-Negotiable)
All data fixtures must be:
- Canonical: single authoritative source per data type
- Complete: no silent nulls or missing fields without explicit flags
- Frozen: historical snapshots are immutable once written
- Timestamped: data_available_timestamp <= as_of_date always enforced

## Active Ruleset
- **ID**: `69a0c7f8` (v1.12.0)
- **File**: `production_data/decision_rulesets/v1.12.0_cal_alpha_off_candidate.json`
- **Key settings**: optionality anchor, inst_sort w=0.3, buffer=30, cal_alpha OFF, clinical OFF, coinvest OFF
- **Pinned in**: `run_screen.py` AND `run_phase2_snapshot_delta.py` (must stay in sync)
- **Manifest**: 35+ entries, no dup IDs

---

## Current Operating Truths

After correcting PIT financial leakage, historical selector performance materially deteriorates.
Top-20 and Top-30 portfolios now underperform XBI cumulatively, and monthly excess returns are
weak and statistically insignificant. This strongly suggests prior alpha was inflated by financial
look-ahead contamination. Forward true-PIT monitoring is now the only credible performance evidence.

1. **Historical alpha story has collapsed.** PIT-financial-corrected benchmarks show Top-20 at -28.2pp and Top-30 at -25.1pp excess vs XBI (was +93.7pp / +110.5pp on survivorship-only). Monthly excess is +0.58pp/mo with t-stat 0.65 (not significant).
2. **All pre-correction benchmark claims are deprecated.** Do not cite survivorship-only numbers for any purpose.
3. **DEM is a selector, not a ranker.** Within-top-30 IC is zero. EW is the correct weighting. But the selector itself now lacks historical evidence of alpha.
4. **Forward monitor is the only credible evidence.** Everything historical is pseudo-PIT (today's code applied retroactively with corrected financials). True PIT accumulates daily.
5. **The governance hold worked.** It prevented a false positive from being institutionalized.
6. **Construction v2 (EW Top-30) remains the active construction** — fixed sleeve budgets are retired. But the selector feeding it is unproven on corrected data.
7. **The selector may still have real alpha** — but the historical evidence no longer supports the claim. Only forward monitoring can re-establish confidence.

---

## Trust Buckets

### Safe to use now
- Snapshot overwrite protection, CTGov fallback PIT safety net, production data archiver
- PIT validation audit framework, PIT financial regeneration infrastructure
- Live risk / rebalance / execution controls
- Forward monitor results (true PIT) — the only credible performance evidence
- EW Top-30 as active construction (construction choice is separate from selector alpha)

### Deprecated (contaminated — do not cite)
- **All survivorship-only benchmark numbers** (+93.7pp, +110.5pp, etc.)
- **All pre-PIT-financial historical alpha claims**
- "Top-30 is the sweet spot" narrative from contaminated data
- "Bear IR 3.35" regime story from contaminated data
- Any construction conclusion based on long-history regenerated snapshots
- Any promotion memo that cites the contaminated 2020+ history

### Current corrected evidence (weak, not promotion-grade)
- PIT-financial-corrected benchmarks: Top-20 -28.2pp, Top-30 -25.1pp excess vs XBI
- Monthly excess +0.58pp/mo (t=0.65, not significant)
- Top-30 still beats Top-20 by +3.1pp but both underwater
- Regime split: bear flat (IR 0.00), bull weak (IR +0.15)

---

## Do Not Reopen Without New Evidence

These lanes have been tested and either died or were superseded. Do not spend research
hours here unless genuinely new data or a structural model change creates a reason to revisit.

| Lane | Status | Why closed |
|------|--------|-----------|
| Options surface-shape as systematic ranker | DEAD | 50-month backtest IC negative at all horizons |
| `total_volume_z` | DEAD | IC=-0.10 on PIT-native data (109 obs), original +0.134 was retro-classified look-ahead bias |
| Always-on rank-weighting (Top-20 or Top-30) | NOT PROMOTED | RW does not beat EW net of costs; within-top-30 IC is zero |
| Top-20 / pruner promotion story | DEPRECATED | PIT-financial correction shows both Top-20 and Top-30 underwater vs XBI |
| Historical alpha narrative (+93pp / +110pp) | DEPRECATED | Inflated by financial look-ahead contamination; corrected numbers are -28pp / -25pp |
| `cal_alpha` | REMOVED in v1.12.0 | Confirmed no-op, zero deltas at all horizons |
| Clinical sort signal | OFF | Insufficient IC |
| Coinvest signal | REJECTED | IC below promotion bar |
| Quality tiebreaks (Specs 030/031) | EXHAUSTED | All economically immaterial |
| 91-180d drawdown gate | DEAD | Counterproductive at all thresholds |
| Dynamic caps | DEAD | Identical to plain EW |
| Fixed sleeve budgets | RETIRED | Primary construction damage mechanism (+153.6pp drag) |

---

## Current Promotion Story

1. DEM's historical alpha is **unproven** after PIT financial correction. Prior claims were inflated by look-ahead.
2. **EW Top-30 remains the active construction** — the construction choice is still sound even if the selector feeding it lacks historical proof.
3. **Forward true-PIT monitor is the only credible evidence source.** Accumulate daily. Evaluate after 30+ trading days.
4. Do not promote any model changes based on historical benchmarks until forward evidence accumulates.
5. `inst_delta_z` PROMOTE verdict was based on survivorship-only data — **requires re-evaluation** on PIT-financial snapshots.
6. The governance hold **succeeded**: it prevented institutionalizing a false positive.

---

## PIT Rules

1. **Never call the historical set "true PIT"** unless archived raw inputs, archived code, AND archived derived artifacts all exist as-of each date.
2. Historical benchmark outputs must carry `pseudo_pit_version` (1=contaminated, 2=cleaned).
3. Benchmark reruns must use the PIT-aware paths: `--pit-mode survivorship` or `--pit-mode full`.
4. Long-history conclusions are **provisional** until PIT-v2 financial rerun lands.
5. The forward monitor is the only true out-of-sample evidence. Accumulate it.

---

## Canonical Benchmark Commands

```bash
# Survivorship-cleaned selection benchmark (current baseline)
python3 scripts/research/build_selection_benchmark.py --pit-mode survivorship --top-n 20 --also-top30

# Monthly IC / selection benchmark
python3 scripts/research/selection_benchmark.py --pit-mode survivorship

# Ranker evaluation (inst_delta_z within top-30)
python3 scripts/research/ranker_evaluation_harness.py --signal inst_delta_z --pit-mode survivorship

# Construction v2 benchmark (all variants)
python3 scripts/research/construction_v2_benchmark.py --pit-mode survivorship

# PIT-financials snapshot regeneration (heavy lift, ~2h)
python3 scripts/research/regenerate_pit_v2_snapshots.py

# Run benchmarks on PIT-financial-corrected snapshots
python3 scripts/research/build_selection_benchmark.py --pit-mode survivorship --top-n 20 --also-top30 --snapshot-dir data/snapshots_pit_v2
```

---

## Heavy-Lift Jobs

- **PIT financial regeneration is COMPLETE.** 76 monthly dates in `data/snapshots_pit_v2/`, 72/72 OK, 0 errors.
- **Result: historical alpha collapsed.** All pre-correction claims are deprecated.
- **Next heavy lift: forward monitor accumulation.** No compute needed — just time. Evaluate after 30+ trading days of true-PIT daily production.
- **If forward evidence is positive:** re-establish selector thesis from clean data. Do not backfill from historical.
- **If forward evidence is negative:** the selector needs structural re-examination.

---

## What to Update After Every Session

- [ ] Current benchmark winner (Top-20 vs Top-30, any new candidate)
- [ ] Trust bucket changes (provisional → safe, or new invalid entries)
- [ ] Dead-lane list (add any newly killed signals/lanes)
- [ ] PIT version / contamination status
- [ ] Active heavy-lift job status

## Decision Engine Architecture
**File**: `decision_engine.py` (~620 lines, pure post-processing)

Layers: L0 (eligibility) → L2 (overlays) → L4a (dev tier) → L4b (commercial tier) → L3 (sizing)

All downstream consumers use DE outputs (`tier_dev`, `actionable_rank`, `target_weight_pct`), not Module 5's `composite_rank`.

## Promotion Governance
- **Manifest**: `production_data/decision_rulesets/manifest.json` — all rulesets tracked with status (active/candidate/retired)
- **Promotion battery**: `scripts/research/run_promotion_battery.py` → bucketed verdicts + weekly live-sim → PASS/FAIL
- **Promote script**: `scripts/promote_ruleset.py` — blocks promotion unless battery PASS
- **Health monitor**: `tools/ruleset_health_monitor.py` — post-promotion drift detection
- **Rollback**: `scripts/promote_ruleset.py --rollback --reason "..."` — first-class with auto-LKG discovery

## Event Ledger & Cache Warming
- **Event ledger**: `build_event_ledger()` in `event_ledger.py` — 7+ sources (CTGov, merged trials, SEC 8-K, SEC multi-form, FDA ADCOM, FDA regulatory, PDUFA manual, EMA)
- **Cache warmer**: `warm_caches.py --sources sec_8k,ctgov,sec_13f,fda_adcom,fda_regulatory,euctr,ctis,isrctn,merged_trials`
- **EU/EEA registries**: `euctr_collector.py`, `ctis_collector.py`, `isrctn_collector.py` in `wake_robin_data_pipeline/collectors/`
- **Trial merger**: `trial_registry_merger.py` — cross-registry dedup by NCT/EudraCT IDs
- Always warm 8-K cache BEFORE running screen

## Daily Production Pipeline
- **Runner**: `tools/run_daily_production.py` — 13-step orchestrator
- **Cron**: 5:30 PM ET weekdays + `@reboot` catch-up for missed runs
- **Steps**: price refresh → cache warm (incl. FDA) → screen (with `--inputs-manifest write`) → audit → gates → manifest + promotion → drift report → action packet → shadow portfolio → trade plan → portfolio report → readiness scorecard → ops digest → PIT backfill (optional)
- **Ops digest**: `tools/build_ops_digest.py` → `artifacts/ops_digest/YYYY-MM-DD_digest.md` — single-screen actionable summary
- **Readiness**: `tools/weekly_readiness_scorecard.py` → READY / REVIEW / HOLD verdict
- **Health checks**: collection health (INFO/WARN/FAIL with weekend-safe price fallback), phase-2 health, exposure metrics

## OpenClaw Ops Agent
- **Workspace**: `agents/ops/` — SOUL.md (boundaries), TOOLS.md (daily working set), HEARTBEAT.md (3-check)
- **Role**: read-mostly operator — runs pipeline, reads digest, surfaces action items, refuses to modify rulesets
- **Gateway**: 127.0.0.1:18789, loopback only, auth via setup token

## Shadow Portfolio
- **File**: `tools/live_shadow_portfolio.py` (902 lines)
- **Policy**: `production_data/portfolio_policy.json` (v3), $500k, 55/25/10/10 bucket split
- **Family sleeves**: REGULATORY/CLINICAL split per bucket with time-ladder sub-buckets
- **Regulatory sleeve A/B**: +1.85pp 63d, +1.59pp 84d (positive but coverage-limited)

## Before Writing Any Code
1. State which module this change belongs to
2. Identify whether this is a new signal, validation change, or infrastructure change
3. Write the failing test FIRST — show me the red test before any implementation
4. Confirm no look-ahead bias: what is the data_available_timestamp?

## Coding Standards
- All outputs: encoding='utf-8', lineterminator='\n', quoting=csv.QUOTE_MINIMAL
- SHA256 hash every scored output for audit trail
- Identical inputs must produce byte-identical outputs — no random seeds, no datetime.now()
- Use Point-in-Time fixtures — never fetch live data in tests

## What NOT To Do
- Do not refactor and add features in the same commit
- Do not change production agent weights without an ablation test showing Sharpe delta
- Do not use PubMed h-index API, options flow, or CapIQ — see approved data sources
- Do not introduce survivorship bias — graveyard list is at data/graveyard/

## Test Requirements
Every new signal must include:
1. Unit test with known fixture input → expected output
2. Leakage test confirming data_available_timestamp compliance
3. Ablation test stub showing Sharpe contribution ≥ 0.1

## Long-Call Contract Recommendations (Post-Screen)

When producing long-call candidates from the screen output, also recommend the best executable long-call contract for each surviving candidate.

**Goal:** For every name that passes the long-call filter, recommend:
1. One primary contract
2. One backup contract
3. Or explicitly mark `NO_TRADE` if no contract is liquid / priced well enough

Do NOT just say "buy calls." Pick an actual strike + expiry from the chain data available in the repo/output.

### Step 1 — Expiry selection
- Base case: choose the first liquid expiry that is AFTER the catalyst date and still leaves 14–35 calendar days of cushion after the event
- If catalyst_days is 21–45: allow tighter post-event cushion of 7–21 days
- Avoid expiries that occur BEFORE the catalyst
- Avoid very long expiries unless all nearer expiries are illiquid or the event date is uncertain
- Prefer standard monthly expiries over odd weeklies when liquidity is similar

### Step 2 — Strike selection
- Target call delta between 0.30 and 0.50
- Higher-conviction names: prefer 0.40–0.50 delta
- Lower-conviction / higher-IV names: prefer 0.30–0.40 delta
- Avoid ultra-OTM lottery strikes unless premium is tiny and liquidity is still acceptable
- Avoid deep ITM unless spread/liquidity is clearly superior and thesis is very high conviction

### Step 3 — Liquidity filter
Reject contracts if any of these are true:
- open_interest is too low
- volume is too low
- bid/ask spread is too wide
- pricing looks stale

If the repo does not have exact spread fields, use the best liquidity proxies available and state the limitation.

### Step 4 — Entry economics
For each candidate contract, compute or estimate:
- mid premium
- breakeven move to expiry
- event-date implied move
- crush-adjusted move if available
- delta
- DTE

Prefer contracts where:
- directional thesis is confirmed by RR / skew
- implied move is not already extreme
- the contract still has room to profit after likely post-event IV compression
- premium at risk is reasonable relative to conviction

### Step 5 — Rank contracts
Choose the primary contract by this priority:
1. Expiry appropriately covering the catalyst
2. Strongest liquidity
3. Delta in target band
4. Best breakeven vs thesis
5. Cleaner spread / execution quality

Choose one backup contract that is either:
- one strike lower/higher with similar expiry, or
- next best expiry with similar delta profile

### Output format for each candidate
```
ticker:
  catalyst: <event_type> in <N> days
  thesis: <1-2 lines>
  primary_contract:
    expiry:
    DTE:
    strike:
    option_type: CALL
    delta:
    premium_or_mid:
    open_interest:
    volume:
    spread_or_liquidity_proxy:
    breakeven_move_pct:
    why_this_contract:
  backup_contract:
    <same fields>
  no_trade_reason: <if applicable>
```

### Important constraints
- If exact contract-chain data is unavailable from the snapshot alone, look for the nearest chain artifact/cache already produced by the repo for that date
- If the contract recommendation depends on missing chain fields, say so explicitly and give the best constrained recommendation possible
- Do not change DEM scoring or ranking logic
- This is a post-screen execution recommendation only

## Key File Locations
| Area | File |
|------|------|
| Main orchestrator | `run_screen.py` |
| Decision Engine | `decision_engine.py` |
| Calendar Alpha | `common/clinical_calendar_alpha.py` |
| Options Provider | `common/options_history_massive.py` |
| Daily Production | `tools/run_daily_production.py` |
| Shadow Portfolio | `tools/live_shadow_portfolio.py` |
| Trade Plan | `tools/build_trade_plan.py` |
| Portfolio Report | `tools/build_portfolio_report.py` |
| Readiness Scorecard | `tools/weekly_readiness_scorecard.py` |
| Ops Digest | `tools/build_ops_digest.py` |
| Collection Health | `tools/build_data_collection_health.py` |
| Hedge Report | `tools/biotech_hedge_report.py` |
| Promotion Battery | `scripts/research/run_promotion_battery.py` |
| Signal Evidence | `scripts/run_signal_evidence.py` |
| Ruleset Manifest | `production_data/decision_rulesets/manifest.json` |
| Cache Warmer | `warm_caches.py` |
| Event Ledger | `event_ledger.py` |
| Cron Wrapper | `tools/cron_daily_production.sh` |
| Ops Agent Workspace | `agents/ops/` |
