# SIP-2026-003: yfinance Provider Fallback

**Status:** DRAFT (ready for deployment if escalation threshold reached)  
**Issue Date:** 2026-05-26 20:10 EDT  
**Severity:** CRITICAL (production data pipeline blocked)  
**Decision Authority:** Operator approval required  
**Escalation Threshold:** 2026-05-27 14:00 ET (18 hours remaining)

---

## Executive Summary

yfinance API has been rate-limited since 2026-05-23 14:00 ET (87+ hours). Yahoo Finance servers returning HTTP 429 on all requests. Current posture: production running on May 22 stale snapshot (4+ days old).

**Proposed Solution:** Implement provider fallback to Alpaca API for real-time price data while awaiting Yahoo API recovery.

**Contingency:** If Yahoo still rate-limited at 2026-05-27 14:00 ET (96h threshold), activate this SIP.

---

## Part 1: Problem Statement

### Current Situation

| Metric | Value |
|--------|-------|
| Incident start | 2026-05-23 14:00 ET |
| Duration | 87+ hours |
| Root cause | Yahoo Finance server rate-limiting (HTTP 429) |
| Current data age | 4+ days (May 22 snapshot) |
| Production status | Running on cached data (stale but stable) |
| Impact | No fresh price data; weekly validation blocked |

### yfinance Status (verified 2026-05-26 20:07 EDT)

```
HTTP/2 429 
server: ATS
x-content-type-options: nosniff
content-type: text/html
```

**Evidence:** Direct API test confirms Yahoo servers returning 429 on `/v7/finance/quote` endpoint.

### Why This Matters

1. **Weekly validation gate** (2026-05-31): Requires fresh 13F data + current prices
2. **h20d re-evaluation** (2026-07-01): Needs ≥10 post-refresh snapshots
3. **Cohort monitoring**: Jaccard/inst_delta tracking requires fresh market data
4. **Operational visibility**: stale data makes it impossible to detect signal shifts

---

## Part 2: Provider Fallback Options

### Option A: Alpaca Markets API (Recommended)

**Provider:** Alpaca Markets (APCA-API)  
**Data:** Free tier provides 15-minute delayed quotes; Premium tier provides real-time  
**Coverage:** US equities (all 341 biotech tickers supported)  
**Authentication:** API key-based (already available in infrastructure for options data)  
**Latency:** 15-minute delay acceptable for daily snapshots  
**Cost:** Free tier available (no additional cost)  
**Status:** Alpaca API stable (no known incidents)

**Pros:**
- Free tier sufficient for daily snapshot workflow
- Familiar infrastructure (already used for options_watch agent)
- No rate-limiting observed in production
- Real-time upgrade path if needed (Premium API)

**Cons:**
- 15-minute delay (not critical for daily snapshots)
- Requires API key management
- Less historical data than yfinance (but sufficient for rolling window)

### Option B: IEX Cloud API

**Provider:** IEX Cloud  
**Data:** Real-time + historical data  
**Authentication:** Token-based  
**Cost:** Freemium tier ($0–$9/month)  
**Coverage:** US equities (all supported)  
**Status:** Stable, no known incidents

**Pros:**
- Real-time data available
- Good historical coverage
- Reliable uptime

**Cons:**
- Paid plan required for unlimited requests ($9+/month)
- Less integrated with existing infrastructure
- Separate credential management

### Option C: Wait for Yahoo Recovery (Current)

**Timeline:** Expected 2026-05-27 to 2026-05-28  
**Risk:** Could extend beyond expected window  
**Viability:** Acceptable only if recovery confirmed by 2026-05-27 14:00 ET

---

## Part 3: Implementation Plan (Alpaca Fallback)

### Step 1: Prepare Alpaca Wrapper (2026-05-26, 4 hours)

Create `scripts/alpaca_price_download.py`:

```python
#!/usr/bin/env python3
"""
Alpaca Markets price data downloader.
Fallback provider for yfinance during rate-limit incidents.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import requests
import pandas as pd

ALPACA_BASE_URL = "https://data.alpaca.markets/v2/stocks/quotes"
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")

def download_alpaca(symbols: list, start_date: str, end_date: str) -> pd.DataFrame:
    """Download price data from Alpaca Markets API."""
    
    if not ALPACA_API_KEY:
        raise ValueError("ALPACA_API_KEY env var not set")
    
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
    }
    
    results = []
    
    for symbol in symbols:
        try:
            params = {
                "start": f"{start_date}T00:00:00Z",
                "end": f"{end_date}T23:59:59Z",
                "limit": 10000,  # max per request
            }
            
            resp = requests.get(
                f"{ALPACA_BASE_URL}/{symbol}",
                headers=headers,
                params=params,
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if "quotes" in data and data["quotes"]:
                    for quote in data["quotes"]:
                        results.append({
                            "symbol": symbol,
                            "date": quote["t"],
                            "open": quote.get("o"),
                            "high": quote.get("h"),
                            "low": quote.get("l"),
                            "close": quote.get("c"),
                            "volume": quote.get("v"),
                        })
            elif resp.status_code == 429:
                print(f"  ⚠ {symbol}: Rate-limited")
                return None
            else:
                print(f"  ✗ {symbol}: HTTP {resp.status_code}")
                
        except Exception as e:
            print(f"  ✗ {symbol}: {e}")
    
    if not results:
        return pd.DataFrame()
    
    df = pd.DataFrame(results)
    df["date"] = pd.to_datetime(df["date"])
    return df

def main():
    if len(sys.argv) < 2:
        print("Usage: alpaca_price_download.py <symbol1> [symbol2] ...")
        sys.exit(1)
    
    symbols = sys.argv[1:]
    start_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    df = download_alpaca(symbols, start_date, end_date)
    print(df)

if __name__ == "__main__":
    main()
```

**Tests:** 5 unit tests covering:
- API auth handling
- Rate-limit detection
- Symbol batch processing
- Data frame validation
- Fallback error handling

### Step 2: Update Price Refresh Logic (2026-05-26 to 2026-05-27, 2 hours)

Modify `tools/run_daily_production.py`:

```python
# In refresh_prices() function:

try:
    # Try yfinance first
    prices = safe_download_yfinance(symbols)
    if prices is not None and not prices.empty:
        return prices
    
    # If yfinance fails, try Alpaca fallback
    print("INFO: yfinance unavailable, switching to Alpaca fallback...")
    prices = download_alpaca_fallback(symbols)
    
    if prices is not None and not prices.empty:
        print(f"INFO: Alpaca fallback successful, {len(prices)} rows retrieved")
        return prices
    else:
        print("ERROR: Both yfinance and Alpaca failed; using stale snapshot")
        return None
        
except Exception as e:
    print(f"ERROR: Price refresh failed: {e}")
    return None
```

**Changes:**
- Add Alpaca import at top
- Add fallback logic in exception handler
- Log provider used for audit trail

### Step 3: Verify API Credentials (2026-05-26 to 2026-05-27, 30 min)

```bash
# Verify Alpaca API key is available in production environment
grep -r "ALPACA_API_KEY" production_data/ .env 2>/dev/null || echo "Need to add ALPACA_API_KEY"

# Test credentials
export ALPACA_API_KEY="your-key-here"
python3 scripts/alpaca_price_download.py AAPL TSLA
```

### Step 4: Test Fallback (2026-05-26 to 2026-05-27, 2 hours)

**Test 1: Single symbol download**
```bash
python3 scripts/alpaca_price_download.py AAPL
# Expect: 1 row of price data
```

**Test 2: Batch symbols**
```bash
python3 scripts/alpaca_price_download.py AAPL TSLA GOOG AMZN
# Expect: 4 rows (or more if multiple time periods)
```

**Test 3: Integration with run_daily_production.py**
```bash
python3 tools/run_daily_production.py --as-of-date 2026-05-27 --test-alpaca
# Expect: Snapshot runs using Alpaca prices
```

**Test 4: Fallback chain**
```bash
# Disable yfinance, verify Alpaca is used
python3 tools/run_daily_production.py --as-of-date 2026-05-27 --force-alpaca
# Expect: Log shows "using Alpaca fallback"
```

### Step 5: Deploy to Production (2026-05-27, 1 hour)

**If Yahoo still rate-limited at 2026-05-27 14:00 ET:**

```bash
# 1. Commit fallback code to main
git add scripts/alpaca_price_download.py tools/run_daily_production.py
git commit -m "feat(fallback): add Alpaca Markets provider fallback (SIP-2026-003)

yfinance rate-limited since 2026-05-23 14:00 ET (96h+).
Alpaca fallback activated for price refresh.

Provider: Alpaca Markets (APCA-API, free tier)
Data: US equities, 341 tickers covered
Latency: 15-minute delay (acceptable for daily snapshots)
Cost: Free

Fallback chain: yfinance → Alpaca → stale cache

Activation time: 2026-05-27 14:00 EDT
Escalation ID: SIP-2026-003"

# 2. Run test snapshot with Alpaca
python3 tools/run_daily_production.py --as-of-date 2026-05-27 --force-alpaca

# 3. If test PASS, enable automatic fallback in production
# (yfinance will fail, Alpaca will be used transparently)

# 4. Monitor Alpaca API during daily production run
# Check logs for "Alpaca fallback" messages
```

---

## Part 4: Rollback Plan

**If Alpaca fails or creates new issues:**

```bash
# Revert to yfinance + stale cache (original posture)
git revert <alpaca-commit>
git push origin main

# Keep stale snapshot workflow until Yahoo recovers
python3 tools/run_daily_production.py --as-of-date 2026-05-28 --skip-price-refresh
```

**Triggers for rollback:**
- Alpaca returns corrupt/incomplete data
- Alpaca rate-limited or service degraded
- API key issues / credential failures
- Production snapshot fails with Alpaca enabled

---

## Part 5: Decision Gate

**Activation condition:**

```
IF (yfinance HTTP 429 still at 2026-05-27 14:00 ET) 
AND (no other recovery signs)
THEN activate SIP-2026-003 (Alpaca fallback)
```

**Approval required from:** Operator (D. Schulz)

**Decision timeline:**
- **2026-05-27 13:45 ET** — Final yfinance check (15 min before threshold)
- **2026-05-27 14:00 ET** — Escalation decision point (activate if still blocked)
- **2026-05-27 14:30 ET** — SIP-2026-003 deployment (30 min to deploy)
- **2026-05-27 15:30 ET** — Alpaca fallback live in production

---

## Part 6: Risk Assessment

### Risks

| Risk | Mitigation |
|------|-----------|
| Alpaca API key not available | Verify credential availability before 2026-05-27 14:00 ET |
| Alpaca rate-limited | Fallback gracefully to stale cache; monitor Alpaca status |
| Data quality difference | Compare Alpaca vs yfinance prices on test symbol (AAPL) |
| 15-min delay impact | Acceptable for daily snapshots; monitor for signal shifts |
| Integration bugs | Comprehensive testing before production activation |

### Mitigation

1. **Pre-activation validation** — Test Alpaca API with real credentials NOW (2026-05-26)
2. **Graceful degradation** — Fallback chain: yfinance → Alpaca → stale cache
3. **Monitoring** — Log all provider switches; alert on failures
4. **Rollback ready** — Keep stale cache as final safety net

---

## Part 7: Timeline

| Date/Time | Action | Owner |
|-----------|--------|-------|
| 2026-05-26 20:10 | SIP-2026-003 drafted | Operator |
| 2026-05-26 21:00 | Test Alpaca API credentials | Engineer |
| 2026-05-26 22:00 | Implement Alpaca wrapper | Engineer |
| 2026-05-27 09:00 | Run integration tests | Engineer |
| 2026-05-27 13:45 | Final yfinance check | Operator |
| 2026-05-27 14:00 | Escalation decision | Operator |
| 2026-05-27 14:30 | Deploy to production (if activated) | Engineer |
| 2026-05-27 15:30 | Alpaca fallback live (if activated) | Monitor |

---

## Part 8: Success Criteria

**SIP-2026-003 succeeds if:**

✅ Alpaca prices retrieved for ≥90% of universe (310+ tickers)  
✅ Daily snapshot completes with fresh Alpaca data  
✅ Drift report shows <10% distribution shift vs May 22 snapshot  
✅ Weekly validation (2026-05-31) uses fresh Alpaca prices  
✅ No rate-limiting from Alpaca API  
✅ Rollback available and tested  

**SIP-2026-003 fails if:**

❌ Alpaca API also rate-limited  
❌ Data quality issues detected  
❌ >10% tickers fail to download  
❌ Production snapshot fails with Alpaca enabled  
❌ API credentials unavailable

---

## Part 9: Related Documentation

- **yfinance incident:** `artifacts/yfinance_rate_limit_incident_2026_05_23.md`
- **Production runner:** `tools/run_daily_production.py`
- **Safe wrapper (yfinance):** `scripts/yfinance_safe.py`
- **Recovery log:** `artifacts/yfinance_recovery_log.txt`

---

## Approval

**Status:** DRAFT (ready for deployment)  
**Approval required:** YES (operator sign-off to activate)  
**Decision point:** 2026-05-27 14:00 ET (18 hours remaining)

**To activate SIP-2026-003:**

```
OPERATOR APPROVAL — SIP-2026-003 (Alpaca Fallback)

yfinance status at 2026-05-27 14:00 ET: [STILL RATE-LIMITED / RECOVERED]

If STILL RATE-LIMITED:
  Approve SIP-2026-003 activation: YES ☐  NO ☐

If recovered:
  Cancel SIP-2026-003, use native yfinance

Approval ID: _________________
Operator Name: _________________
Date/Time: 2026-05-27 ___:___ EDT
```

---

**Document Status:** READY FOR DEPLOYMENT  
**Next Review:** 2026-05-27 14:00 ET (escalation threshold)  
**Contingency:** Production continues on stale snapshot until resolved
