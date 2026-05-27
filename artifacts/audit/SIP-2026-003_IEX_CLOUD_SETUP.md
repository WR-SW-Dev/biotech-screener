# SIP-2026-003 IEX Cloud Fallback — Quick Setup Guide

**Status:** READY FOR DEPLOYMENT  
**Timeline:** 15 min (sign-up) + 5 min (validate) = 20 min total  
**Trigger:** Deploy if yfinance recovery NOT detected by 2026-05-28 09:00 ET  

---

## Phase 1: Sign-up (10 min)

1. **Visit:** https://iexcloud.io
2. **Create free account** (email only, no credit card)
3. **Generate API token:**
   - Dashboard → Account → API Tokens
   - Copy "Publishable Token" (starts with `pk_...`)
4. **Set environment variable:**
   ```bash
   export IEX_CLOUD_API_KEY="pk_xxxxxxxxxxxxx"
   ```
   (Add to `~/.bashrc` or `.hermes/.env` for persistence)

---

## Phase 2: Validation (5 min)

Test connectivity:

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Single ticker
python3 scripts/iex_cloud_price_download.py AAPL

# Multiple tickers
python3 scripts/iex_cloud_price_download.py AAPL TSLA GOOG

# Expected output:
#   ✓ AAPL: 60 bars
#   ✓ TSLA: 60 bars
#   ✓ GOOG: 60 bars
#   180 rows, 3 symbols
```

**Success criteria:**
- ✓ No HTTP 401 (auth error)
- ✓ No HTTP 429 (rate-limit)
- ✓ Data has Open, High, Low, Close, Volume columns
- ✓ Dates are in YYYY-MM-DD format

---

## Phase 3: Integration (FUTURE)

Once validated, integrate into production pipeline:

```bash
# Test snapshot with IEX primary (yfinance fallback)
python3 tools/run_daily_production.py --as-of-date 2026-05-28 --test-iex

# Force IEX only (no yfinance)
python3 tools/run_daily_production.py --as-of-date 2026-05-28 --force-iex
```

---

## Pricing & Quota

| Tier | Price | Monthly Limit | Status |
|------|-------|---------------|--------|
| **Free** | $0 | 100 messages | ← Current |
| **Starter** | $9/mo | 8,000 messages | Sufficient |
| **Growth** | $99/mo | Unlimited | Enterprise |

**Note:** 341 tickers × 1 call = 341 messages/run. Free tier (100) = ~0.3 runs/month (test-only).  
For production: Upgrade to Starter ($9/mo) = 8,000 messages ≈ 23 production runs.

---

## Fallback Logic

Script will use this order:

1. **Primary (Production):** yfinance (current)
2. **Secondary (if yfinance fails):** IEX Cloud
3. **Tertiary (if both fail):** Use cached May 22 snapshot

---

## Deployment Decision Point

**IF** yfinance still rate-limited at **2026-05-28 09:00 ET**:

1. Run Phase 1 sign-up (10 min)
2. Run Phase 2 validation (5 min)
3. Trigger production with `--force-iex` flag
4. Monitor snapshot output for data quality

**ELSE (yfinance recovered by 2026-05-28 09:00 ET):**

Archive SIP-2026-003. Resume normal operations. No action needed.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `IEX_CLOUD_API_KEY not set` | Env var not exported | `export IEX_CLOUD_API_KEY="pk_..."` |
| `HTTP 401: Invalid token` | Token copied wrong | Verify token starts with `pk_` |
| `HTTP 429: Rate-limited` | Free tier (100/mo) exhausted | Upgrade to Starter ($9/mo) |
| `No data retrieved` | Symbol invalid or no history | Verify ticker is valid (e.g., AAPL) |

---

## Documentation

- **Design:** `artifacts/audit/SIP-2026-003_provider_fallback.md`
- **Validation:** `artifacts/audit/SIP-2026-003_validation_report_alpaca_nogo.md`
- **Script:** `scripts/iex_cloud_price_download.py`
- **Setup:** This file

---

**Status:** STANDBY (awaiting yfinance recovery verdict 2026-05-28 09:00 ET)
