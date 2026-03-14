# Spec 8: Options Data Freshness Tracking on Every Screen Run

**Status**: COMPLETE (2026-03-14)

## What Was Built

### Phase 1 — Freshness preflight in run_screen.py
- Credential checks for Tastytrade (TT_SECRET/TT_REFRESH) and Massive (MASSIVE_API_KEY) before options enrichment
- Post-fetch freshness update: if TT credentials present but zero data returned, status demotes to "stale"
- `options_data_freshness` block emitted to `coverage_quality.json`:
  ```json
  {"tastytrade_status": "ok|stale|no_credentials|failed",
   "tastytrade_as_of": "2026-03-14",
   "massive_status": "ok|no_credentials|not_available",
   "massive_as_of": "2026-03-14",
   "all_fresh": true}
  ```
- Log line: `[OPTIONS_WARM] Tastytrade: ok, Massive: ok`

### Phase 2 — Staleness warning in coverage_quality.md
When `all_fresh = false`, a prominent warning appears at the top of the markdown:
```
**OPTIONS DATA STALE** — Tastytrade: STALE, Massive: OK
Options signals (quality composite, disagreement overlay, term structure flags)
may be unreliable for this run.
```

### Phase 3 — Guards on action-oriented outputs
When options data is stale:
- `market_model_disagreement = "high"` demoted to `"medium"` (prevents acting on stale IV data)
- `ts_flag_type = "BLIND_SPOT"` demoted to `"BLIND_SPOT_UNCONFIRMED"` (prevents false positive catalyst surfacing)
- Mismatch flags (`MARKET_SEES_SOONER`, `MARKET_NOT_PRICING_EVENT`) preserved (lower stakes)

## CCFT Compliance
- Freshness block always written, even on failure
- Audit trail records warm attempt and outcome
- No silent staleness — either data is confirmed fresh or diagnostics are visibly degraded
