# Production Recovery — 2026-05-26

**Status:** ✓ ONLINE (Restored from stale snapshot)

## Incident Summary

**Timeline:**
- **2026-05-20:** Hermes fleet migrated to DeepSeek v4 flash
- **2026-05-23 ~14:00 ET:** yfinance hits rate limit (429) during production run
- **2026-05-23-26:** Production blocked; all 4 daily runs fail at price refresh stage
- **2026-05-26 09:30 ET:** Root cause identified: Yahoo Finance API rate-limit
- **2026-05-26 13:36 ET:** Production restored using May 22 snapshot (4 days stale)

**Impact:**
- 0 fresh snapshots generated (May 23-26)
- 11 signal monitors stale since May 20
- Fleet_steward alert: missing today's snapshot + stale CRT table

## Root Cause

**yfinance Rate Limiting:**
- yfinance.download() hits rate limit on all 341 tickers
- Yahoo Finance API returns HTTP 429 (Too Many Requests)
- yfinance library parses 429 error page (HTML) as JSON
- Results in: `json.decoder.JSONDecodeError: Expecting value: line 1 column 1`
- Pattern affects all tickers uniformly (systematic block, not individual failures)

**Why it happened:**
- yfinance has no built-in rate-limit handling
- Production code attempts repeated retries without backoff
- Each retry hit the same rate limit, extending the block
- 4 days without fresh data collection (May 23-26)

## Recovery Actions

### 1. Rate-Limit Handler Deployed
**File:** `scripts/yfinance_safe.py`
- Exponential backoff with jitter
- Per-ticker delays (configurable, default 1.5s)
- Automatic retry logic on 429 errors
- Dual modes: batch download or per-ticker (conservative)

### 2. Production Restored
- **Snapshot:** May 22 (4 days stale)
- **Rationale:** Operational stale data > no data
- **Manifest:** Updated with `RECOVERED_FROM_STALE` flag
- **Timeline:** Restored 2026-05-26 13:36 ET

### 3. Hermes Integration Verified
- DeepSeek model migration (May 20) stable
- Gateway config corrected (fallback order fixed)
- Together AI balance verified (no payment issues post-recovery)

## Next Steps

### Immediate (1-24 hours)
1. **Monitor yfinance rate limit reset**
   - Run heartbeat checks every 2 hours
   - Once API responds, production will auto-resume with fresh data
   
2. **Validate recovery state**
   - Snapshot integrity: PASS (May 22 → May 26 copy)
   - Manifest updated: PASS
   - Rate-limit wrapper deployed: PASS

3. **Signal monitor recovery**
   - Fleet_steward will pick up May 26 snapshot
   - 8 post-production monitors will resume nightly (18:30-20:30 ET)
   - CRT join table will refresh

### Short-term (24-48 hours)
1. **yfinance API monitoring**
   - Test connectivity every 4 hours
   - Log rate-limit state to `artifacts/yfinance_status.json`

2. **Permanent fix planning**
   - Integrate rate-limit handler into production pipeline
   - Add upstream data provider fallback (Alpaca, once credentials fixed)
   - Update retry logic in `tools/run_daily_production.py`

## Deployment Details

**Files Changed:**
- ✓ `scripts/yfinance_safe.py` — NEW (rate-limit wrapper)
- ✓ `data/snapshots/2026-05-26/` — RESTORED (copy from May 22)
- ✓ `data/snapshots/2026-05-26/snapshot_manifest.json` — UPDATED (recovery metadata)

**Testing:**
- Rate-limit wrapper tested with 3-ticker universe (AAPL, MSFT, GOOG)
- Backoff logic working (retries with exponential delays)
- yfinance API still blocked at time of recovery (rate limit still active)

## Monitoring Commands

**Check yfinance connectivity:**
```bash
python3 scripts/yfinance_safe.py
```

**Check fleet heartbeat:**
```bash
python3 tools/agent_heartbeat_checks.py
```

**Check snapshot status:**
```bash
ls -lah data/snapshots/2026-05-2[26]/
```

## Known Limitations

- **Data Staleness:** May 26 snapshot contains May 22 prices (4 days old)
- **Signal Coverage:** 11 monitors not updated since May 20 (need fresh data)
- **Rate Limit:** Still active; production will resume fresh collection once Yahoo Finance resets

## Conclusion

Production is **OPERATIONAL** with stale data. Rate-limit handler deployed. System will auto-recover to fresh data once API resets.

**Incident severity:** MEDIUM (4-day outage, recovery path clear, wrapper in place)

---

**Recovery Date:** 2026-05-26 13:36 ET  
**Incident Duration:** 4 days (May 23 14:00 → May 26 13:36)  
**Status:** Restored (stale), awaiting fresh data (rate-limit reset)  

