# SIP-2026-003 Pre-Activation Validation — Alpaca NO-GO

**Date:** 2026-05-26 20:30 EDT  
**Status:** NO-GO (prepared but not deployable)  
**Decision Point:** 2026-05-27 14:00 ET (14 hours remaining)  
**Recommendation:** Continue stale-cache posture; monitor yfinance recovery

---

## Executive Summary

SIP-2026-003 (Alpaca Markets fallback) pre-activation validation **FAILED** on critical blocker: historical bar data unavailable due to insufficient subscription.

**Finding:** Current Alpaca account credentials can access real-time quotes (`/v2/stocks/quotes`), but **cannot** access historical bar data (`/v2/stocks/bars` returns HTTP 403 Forbidden). Daily snapshot production requires historical OHLCV bars; quote-only access is insufficient.

**Outcome:** Alpaca fallback cannot be deployed until account subscription upgraded or alternative provider evaluated.

---

## Validation Results

### Credential & Authentication
✓ **PASSED**
- APCA_API_KEY_ID found in `.env`
- APCA_API_SECRET_KEY found in `.env`
- Account accessible (not invalid/expired)

### API Connectivity
✓ **PASSED**
- Alpaca servers responding (no 429 rate-limit)
- No authentication failures (401 not returned for operational endpoints)
- Network connectivity confirmed

### Data Subscription
✗ **FAILED**
- **Bars endpoint** (`/v2/stocks/bars`): HTTP 403 Forbidden
  - Error: "subscription does not permit querying recent SIP data"
  - Required for: Daily snapshot price refresh (OHLCV bars)
  - Status: UNAVAILABLE under current account tier

- **Quotes endpoint** (`/v2/stocks/quotes`): HTTP 200 OK
  - Returns: Current bid/ask/last prices
  - Sufficient for: Real-time monitoring only
  - **Insufficient for:** Historical bar reconstruction, drift calculation, 5-day rolling windows

### Assessment

| Requirement | Result | Impact |
|-------------|--------|--------|
| Credentials present | ✓ PASS | Ready to test |
| API responds | ✓ PASS | Server not down |
| Real-time quotes | ✓ PASS | Limited use |
| Historical bars | ✗ FAIL | **BLOCKER** |
| Rate-limiting | ✓ NO | Safe from HTTP 429 |

---

## Root Cause

Current Alpaca account is **paper trading account** (trading/testing, not production data) with limited data subscription. Paper accounts include real-time quote access but restrict historical bar data to protect Alpaca's data licensing costs.

**Paper Account Tier Limits:**
- ✓ Can: Real-time quotes, market status, account operations
- ✗ Cannot: Historical bars, SIP consolidated data, advanced research feeds

---

## Impact on Daily Snapshot Production

Daily snapshot workflow requires:
1. Load previous 5 days of OHLCV bars from yfinance/Alpaca
2. Calculate drift metrics (distribution changes, turnover)
3. Compare with prior snapshot for continuity validation
4. Write new snapshot with fresh market data

**Alpaca quote-only fallback cannot:**
- Reconstruct 5-day history (quotes don't include volume/OHLC)
- Calculate accurate drift (requires multi-day bars)
- Support rolling price windows (daily snapshot uses T-5 to T+0)

**Result:** Alpaca fallback would fail on snapshot completion gate even if deployed.

---

## Escalation Choices at 2026-05-27 14:00 ET

### **Choice A: Upgrade Alpaca Subscription**

**Action:** Request/upgrade Alpaca account to Standard or Professional tier  
**Prerequisites:** Upgrade credentials with historical bar access  
**Timeline:** 1-2 hours (if account upgrade instant) to 24+ hours (if requires manual Alpaca support)  
**Cost:** Free for Standard tier (vs Paper)  
**Viability:** **POSSIBLE** if initiated immediately  
**Risk:** Alpaca support may require business verification, delaying past escalation window  

**If chosen:** Rerun validation (30 min) before 2026-05-27 14:00 ET

---

### **Choice B: Evaluate Alternative Provider**

**Candidates:**
- IEX Cloud (freemium, $0–$9/month)
- Tiingo (free tier, sufficient for daily snapshots)
- Twelve Data (real-time + historical)
- Alpha Vantage (free tier, rate-limited but functional)

**Timeline:** 3–4 hours to implement + test  
**Viability:** **TOO SLOW** for 2026-05-27 14:00 ET escalation  
**Recommendation:** Use only if yfinance shows no recovery signs by 2026-05-27 09:00 ET (5-hour prep window)

**If chosen:** Initiate now to have fallback ready by 2026-05-28

---

### **Choice C: Continue Stale-Cache Posture (Recommended)**

**Action:** Keep current operational state (May 22 snapshot, stale but stable)  
**Timeline:** No additional work required  
**Monitoring:** Continue yfinance recovery checks every 30 min  
**Expected recovery:** 2026-05-27 to 2026-05-28 (within 24-36h)  
**Risk:** If yfinance recovery extends beyond 2026-05-28, data age becomes critical  

**Contingency if recovery delayed:**
- Escalate to Choice A or B at 2026-05-28 09:00 ET (backup escalation point)
- Implement faster evaluation track

---

## Recommended Path Forward

**PRIMARY: Choice C — Continue monitoring yfinance**

Rationale:
1. Expected recovery window (2026-05-27 to 2026-05-28) is imminent
2. Alpaca blocker discovered; attempting upgrade adds risk without guarantee
3. Alternative providers require longer evaluation timeline
4. Current stale-cache posture is stable and acceptable for 24-36 hour window
5. If yfinance recovers, SIP-2026-003 can be archived (no fallback needed)

**SECONDARY CONTINGENCY: Choice A — Upgrade Alpaca (if recovery not detected by 2026-05-27 15:00 ET)**

If yfinance still rate-limited at escalation point:
- Attempt immediate Alpaca account upgrade (fastest fallback)
- Rerun validation if upgrade successful
- Deploy SIP-2026-003 if bars endpoint becomes available

**TERTIARY CONTINGENCY: Choice B — Alternative provider (if upgrade fails or delayed)**

If Alpaca upgrade blocked/delayed:
- Shift to IEX Cloud or Tiingo evaluation
- Longer timeline (~3-4h) but viable as 2026-05-28 fallback
- Document for future SIP versions

---

## SIP-2026-003 Status

| Aspect | Status |
|--------|--------|
| **Prepared** | ✓ YES (design document complete) |
| **Validation** | ✗ NO (Alpaca blocker identified) |
| **Deployable** | ✗ NO (subscription insufficient) |
| **Authorized** | ✗ NO (validation failed) |
| **Production Switch** | ✗ NOT AUTHORIZED |
| **Escalation Ready** | ⚠ CONDITIONAL (Choice A or B if needed) |

---

## Next Actions

**Before 2026-05-27 14:00 ET (14 hours):**

1. ✓ Continue yfinance recovery monitoring (every 30 min)
2. ✓ If recovery detected: Archive SIP-2026-003, resume normal operations
3. ⏳ If still blocked at 2026-05-27 14:00 ET:
   - Decision point: Activate Choice A (upgrade Alpaca) or Choice B (alternative provider)
   - Do NOT activate Alpaca fallback under current credentials

**Operator approval NOT required** — SIP-2026-003 remains on standby; stale-cache posture unchanged.

---

## Documentation

- **SIP design:** `artifacts/audit/SIP-2026-003_provider_fallback.md`
- **Validation report:** `artifacts/audit/SIP-2026-003_validation_report_alpaca_nogo.md` (this file)
- **Recovery log:** `artifacts/yfinance_recovery_log.txt`
- **Incident:** `artifacts/yfinance_rate_limit_incident_2026_05_23.md`

---

**Status: NO-GO (Alpaca blocker confirmed)**  
**Recommendation: Choice C (stale-cache, monitor yfinance)**  
**Escalation point: 2026-05-27 14:00 ET**  
**Next review: 2026-05-27 13:45 ET (final yfinance status check)**
