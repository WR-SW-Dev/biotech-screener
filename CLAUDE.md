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
- **ID**: `7177a4ea` (v1.11.0)
- **File**: `production_data/decision_rulesets/v1.11.0_b91_clinical_quality_w05_candidate.json`
- **Key settings**: clinical_quality sort for b91 CLINICAL w=0.5, flatten_tier_91_180, optionality anchor, cal_alpha w=0.3, inst_sort w=0.3, clinical OFF, coinvest OFF, buffer=30
- **Pinned in**: `run_screen.py` AND `run_phase2_snapshot_delta.py` (must stay in sync)
- **Candidate**: `2b1c8959` (v1.13.0) — catalyst tilt enabled, shadowing for 3-5 weeks

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
- **Cache warmer**: `warm_caches.py --sources sec_8k,fda_adcom,fda_regulatory,euctr,ctis,isrctn,merged_trials,sec_13f`
- **EU/EEA registries**: `euctr_collector.py`, `ctis_collector.py`, `isrctn_collector.py` in `wake_robin_data_pipeline/collectors/`
- **Trial merger**: `trial_registry_merger.py` — cross-registry dedup by NCT/EudraCT IDs
- Always warm 8-K cache BEFORE running screen

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
| Promotion Battery | `scripts/research/run_promotion_battery.py` |
| Ruleset Manifest | `production_data/decision_rulesets/manifest.json` |
| Cache Warmer | `warm_caches.py` |
| Event Ledger | `event_ledger.py` |
