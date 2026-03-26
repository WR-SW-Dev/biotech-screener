# TOOLS.md — Options Watch Agent (Phase 2)

## Data sources (read-only)

### Rankings & model context (primary)
- `data/snapshots/{date}/rankings.csv`
  - Columns used: ticker, tier_dev, actionable_rank, catalyst_days, catalyst_family,
    is_hard_catalyst, opt_has_data, opt_liquidity_ok, opt_use_for_judgment,
    opt_atm_iv, opt_front_iv, opt_back_iv, opt_term_slope, opt_put_call_skew,
    opt_rr_25d, opt_iv_regime, opt_event_premium, actual_implied_move_pctile,
    atm_iv_change_5d

### Review queue & trade context
- `data/snapshots/{date}/review_queue.csv` — hard-catalyst review queue
- `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv` — trade plan
- `artifacts/live_shadow/positions/{date}.json` — shadow positions

### Catalyst delta (if available)
- `artifacts/catalyst_delta/{date}_delta.json` — names with event changes today

### Coverage & freshness
- `data/snapshots/{date}/coverage_quality.json` — options_data_freshness
- `data/snapshots/{date}/options_diagnostics_summary.json` — diagnostic basis,
  credential status, coverage percentages

### Prior watch (for delta detection)
- `artifacts/options_watch/{prior_date}_watch.json`

## Output location

```
artifacts/options_watch/
  {date}_watch.json    — structured watch (schema options_watch.v1)
  {date}_watch.md      — human-readable summary
```

## JSON schema (options_watch.v1)

```json
{
  "schema": "options_watch.v1",
  "as_of_date": "YYYY-MM-DD",
  "watchlist_size": 24,
  "n_eligible": 18,
  "n_flagged": 5,
  "n_suppressed": 3,
  "thresholds": {
    "event_premium_slope": -0.10,
    "surface_move_high": 0.80,
    "surface_move_med": 0.60,
    "iv_ramp_high": 0.10,
    "iv_ramp_med": 0.05,
    "drift_risk_high_pctile": 0.85,
    "drift_risk_high_iv": 0.12,
    "extreme_skew": 0.15,
    "priority_cap": 3
  },
  "rows": [
    {
      "ticker": "PVLA",
      "tier": "A",
      "actionable_rank": 9,
      "catalyst_days": 5,
      "is_hard_catalyst": 1,
      "opt_atm_iv": 1.14,
      "opt_term_slope": -0.18,
      "opt_rr_25d": -0.21,
      "actual_implied_move_pctile": 0.84,
      "atm_iv_change_5d": 0.13,
      "opt_iv_regime": "ELEVATED",
      "opt_event_premium": "YES",
      "flags": ["EVENT_PREMIUM", "SURFACE_MOVE_HIGH", "IV_RAMP_HIGH", "EXTREME_SKEW"],
      "priority_score": 3,
      "why": "hard catalyst 5d with rising IV and backwardation"
    }
  ],
  "suppressed": [
    {"ticker": "GMAB", "reason": "opt_iv_regime=EXTREME, not hard-catalyst"}
  ]
}
```

## Markdown sections

1. **Header**: date, watchlist size, flagged count, coverage status
2. **Flagged names table**: ticker | rank | tier | days | flags | priority | why
3. **Top backwardation**: names with strongest negative term slope
4. **Top IV movers**: names with largest atm_iv_change_5d
5. **Suppressed**: names skipped and why

## Environment

- WSL2 Ubuntu, Python 3.12
- All reads are file-based — no API calls
- Schedule: 5:40 PM ET weekdays (40 17 * * 1-5), after production packet
- Phase 3 (future): add pre-open pass at ~8:45 AM ET once noise is proven manageable
