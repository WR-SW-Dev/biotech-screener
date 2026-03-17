# Spec 25: Long Call Candidate Selector

**Status**: PROPOSED
**Date**: 2026-03-16
**Depends on**: run_screen.py snapshot outputs, options_review_queue, chain artifacts/cache, crush analytics

## Goal

Build a post-screen execution artifact that identifies the best **long call** candidates among top-ranked names and recommends a specific **primary** and **backup** contract for each name.

This is **post-screen only**:
- no DEM scoring changes
- no ranking changes
- no queue-priority changes

It reads the existing snapshot outputs and writes a new execution-oriented artifact.

## Why

The repo now has enough information to do this correctly:
- DEM ranking / tier / catalyst context from `rankings.csv`
- options trigger context from `options_review_queue`
- directional signal from `opt_rr_25d`
- surface pricing context from `actual_implied_move_pctile`, `surface_move_extreme`, `iv_ramp_flag`
- crush-aware economics from `iv_crush_breakeven_pct`, `crush_adjusted_implied_move`

The key directional filter is **bullish RR / skew**, not generic cheap-vol screening.

## New script

`scripts/research/build_long_call_candidates.py`

## Inputs

Per snapshot date:
- `data/snapshots/{date}/rankings.csv`
- `data/snapshots/{date}/options_review_queue.json` or `.csv`
- nearest chain artifact/cache already produced for that date
- any chain analytics fields already written into `rankings.csv`

Required name-level fields:
- `ticker`
- `tier_dev` or equivalent tier field
- `composite_score`
- `is_hard_catalyst`
- `catalyst_days`
- `opt_rr_25d`
- `actual_implied_move_pctile`
- `surface_move_extreme`
- `iv_ramp_flag`
- `iv_crush_breakeven_pct`
- `crush_adjusted_implied_move`

Required contract-level fields if available:
- `expiry`
- `strike`
- `option_type`
- `delta`
- `open_interest`
- `volume`
- `bid`
- `ask`
- `last`
- `mark` or enough fields to estimate mid
- contract freshness / timestamp if available

## Outputs

Write:
- `data/snapshots/{date}/long_call_candidates.csv`
- `data/snapshots/{date}/long_call_candidates.json`
- `data/snapshots/{date}/long_call_candidates.md`

## Candidate filter cascade

Apply in this order.

### 1. Rank / conviction filter
Start from top-ranked names only:
- default: Tier A + Tier B
- fallback: top quartile by `composite_score`

### 2. Hard catalyst filter
Require:
- `is_hard_catalyst = 1`

### 3. Catalyst timing window
Default target window:
- `30 <= catalyst_days <= 120`

Allow override flags later if needed, but keep default narrow.

### 4. Bullish directional filter
Prefer:
- `opt_rr_25d > 0`
Strong preference:
- `opt_rr_25d >= 0.15`

If RR trend fields are available in the snapshot/cache, allow them as a tiebreaker:
- rising bullish skew improves rank
- bearish skew removes candidate unless explicitly overridden

### 5. Entry-price discipline
Prefer names where:
- `surface_move_extreme` is not already `high`
- `actual_implied_move_pctile` is not in the most expensive bucket
- `crush_adjusted_implied_move` remains positive / acceptable

### 6. Liquidity discipline
Reject names/contracts where liquidity is clearly poor.

If exact spread fields are unavailable, use best available proxies and state the limitation.

## Contract selection rules

For each surviving ticker, choose:
- `primary_contract`
- `backup_contract`
- or `NO_TRADE`

### Expiry selection
Base rule:
- first liquid expiry **after** catalyst date
- with `14-35` calendar days of post-event cushion

If `catalyst_days` is `21-45`, allow tighter post-event cushion:
- `7-21` days

Rules:
- never choose expiry before catalyst
- avoid very long expiries unless nearer expiries are illiquid
- prefer standard monthlies over odd weeklies when otherwise similar

### Strike selection
Target call delta:
- default band: `0.30-0.50`
- higher conviction: `0.40-0.50`
- lower conviction / higher-IV: `0.30-0.40`

Rules:
- avoid ultra-OTM lottery calls
- avoid deep ITM unless liquidity/spread is clearly superior

### Liquidity filter
Reject a contract if any of these are true:
- open interest too low
- volume too low
- spread too wide
- pricing looks stale

If spread is unavailable:
- use OI + volume + quote freshness as proxy
- explicitly log `spread_unavailable_proxy_used = true`

### Entry economics
For each candidate contract compute or estimate:
- premium or mid
- DTE
- delta
- breakeven move to expiry
- event-date implied move
- crush-adjusted move if available

Prefer contracts where:
- directional thesis is confirmed by RR
- implied move is not already extreme
- expected move after crush still leaves room to profit
- premium at risk is reasonable

## Contract ranking priority

Choose `primary_contract` by:
1. expiry covers catalyst appropriately
2. strongest liquidity
3. delta in target band
4. best breakeven vs thesis
5. cleanest spread / execution quality

Choose `backup_contract` as either:
- one nearby strike on same expiry, or
- next-best expiry with similar delta

## Output schema

Each row/object must include:

- `ticker`
- `tier`
- `composite_score`
- `catalyst`
- `catalyst_days`
- `thesis_summary`
- `opt_rr_25d`
- `surface_move_extreme`
- `actual_implied_move_pctile`
- `iv_crush_breakeven_pct`
- `crush_adjusted_implied_move`

Primary contract:
- `primary_expiry`
- `primary_dte`
- `primary_strike`
- `primary_option_type`
- `primary_delta`
- `primary_premium_or_mid`
- `primary_open_interest`
- `primary_volume`
- `primary_spread_or_liquidity_proxy`
- `primary_breakeven_move_pct`
- `primary_reason`

Backup contract:
- same fields prefixed with `backup_`

No-trade fields:
- `no_trade`
- `no_trade_reason`

## Markdown summary

The `.md` file should group names into:
- strongest directional candidates
- acceptable but expensive
- no-trade / liquidity failures

For each ticker include a 1-2 line rationale.

## Safety / constraints

- Do not change DEM scoring
- Do not change ranking outputs
- Do not modify review queue priority logic
- Do not silently invent chain fields that are missing
- If contract recommendation is constrained by missing bid/ask or stale chain data, say so explicitly
- If no contract passes the liquidity/economics filters, emit `NO_TRADE`

## Acceptance checklist

- Script runs on a real snapshot date without changing production outputs
- Produces all 3 artifacts
- Only selects names already supported by DEM + options context
- Chooses expiry after catalyst date
- Chooses deltas in target band when liquid contracts exist
- Emits `NO_TRADE` when chain quality is insufficient
- Clearly states when liquidity/spread is proxy-based
- No production code paths changed

## Not in scope

- automated order placement
- DEM score changes
- portfolio sizing changes
- call spread / put / straddle recommendations
- strategy optimization beyond single-leg long calls
