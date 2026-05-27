# Choice B — Alternative Provider Assessment

**Date:** 2026-05-27 09:09 EDT
**Status:** READY FOR IMPLEMENTATION

## Candidates

### 1. Tiingo
- Tier: Free
- Historical bars: Yes (daily, free tier)
- Rate limit: 500/hr (free)
- Setup: 10 min (create account)
- Integration: 30 min (wrapper)
- Auth: API key (query param)

### 2. IEX Cloud
- Tier: Freemium ($0-$9/mo)
- Historical bars: Yes (daily, free tier)
- Rate limit: 100/sec (free)
- Setup: 5 min
- Integration: 30 min
- Auth: API token

### 3. Twelve Data
- Tier: Freemium
- Historical bars: Yes (daily)
- Rate limit: 800/day (free)
- Setup: 5 min
- Integration: 30 min
- Auth: API key

### 4. Alpha Vantage
- Tier: Free
- Historical bars: Yes (daily, free)
- Rate limit: 5/min (free)
- Setup: 5 min
- Integration: 30 min
- Auth: API key

## Recommendation

**PRIMARY:** Tiingo (free tier, 500 req/hr, comprehensive daily data)
**SECONDARY:** IEX Cloud (freemium, high rate limit)

## Implementation Timeline

Phase 1: Account setup — 10 min
Phase 2: Wrapper development — 30 min
Phase 3: Integration — 15 min
Phase 4: Validation — 10 min

**Total: ~1 hour (within escalation window decision buffer)**

## Risk Assessment

- Setup risk: LOW (straightforward API signup)
- Integration risk: MEDIUM (data format matching required)
- Production risk: LOW (fallback chain maintains stale cache safety)

## Decision Gate

If yfinance still blocked at 14:00 ET and Choice A (Alpaca) is inconclusive:
**PROCEED WITH CHOICE B IMPLEMENTATION**
