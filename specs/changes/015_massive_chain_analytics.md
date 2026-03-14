# Spec 15: Massive Chain Analytics

**Status**: MODULE BUILT, PHASES 2-3 PENDING

## Discovery

`fetch_chain_snapshot()` in options_history_massive.py is dead code —
defined but never called. Per-strike IV, Greeks, OI, and prices are
available from the Massive REST API but have never been consumed.

Current division of labor:
- Tastytrade → live coarse diagnostics (ATM IV, term slope, event premium)
- Massive day aggs → research panel volume totals only
- Massive chain snapshot → **unused**

## What Was Built (Phase 1)

`common/massive_chain_analytics.py` — full chain analytics module:
- `find_25delta_contracts()` → identifies 25-delta put/call by delta
- `compute_rr_25d()` → risk reversal (call IV - put IV at 25-delta)
- `compute_put_call_skew()` → (put IV - call IV) / avg IV
- `compute_atm_straddle()` → actual straddle price from contract close prices
- `compute_oi_concentration()` → total OI, max OI strike, put/call OI ratio
- `compute_volume_by_expiry_bucket()` → volume distribution across 0-30/31-90/91-180/180+ buckets
- `compute_chain_analytics()` → single entry point returning all analytics

15 tests in `test_massive_chain_analytics.py`.

## Pending Phases

### Phase 2: Wire into warm pass and populate opt_rr_25d / opt_put_call_skew
- Call `fetch_chain_snapshot()` during options warm
- Run `compute_chain_analytics()` on the result
- Populate currently-empty `opt_rr_25d` and `opt_put_call_skew` in sidecar
- Add OI/volume metrics to sidecar or new chain_analytics sidecar

### Phase 3: Feed crowding panel and straddle pricing
- `build_precatalyst_options_panel.py` uses OI + volume-by-strike to populate crowding metrics
- `straddle_mispricing.py` uses actual_straddle_price when available (IV fallback otherwise)

### Gate: Massive API credentials required
Phases 2-3 require `MASSIVE_API_KEY` environment variable.
`fetch_chain_snapshot()` will raise EnvironmentError without it.
