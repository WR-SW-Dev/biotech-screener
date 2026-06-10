# Daily Monitoring Checklist: Top-15 Biotech Portfolio (2026-06-10)

**Portfolio:** 15 fractional positions, $100.19 gross notional, agentic account 802349084  
**Execution Date:** 2026-06-10 17:11–17:20 UTC  
**Start Equity:** $100.19 | Start Cash:** $99.87 | **Start BP:** $99.87

---

## Pre-Market (Before 9:30 AM ET)

- [ ] **Fetch current quotes:** `get_equity_quotes(symbols=[all 15])` → compare to entry prices
- [ ] **Check for news alerts:** catalyst_events.json, Twitter biotech, Fierce Biotech headlines
- [ ] **Verify no pre-market gaps:** >5% move vs last close = manual review required
- [ ] **Check catalysts due today:** any PDUFA, FDA, earnings, clinical readouts, investor events

**Entry prices (for reference):**
- COGT $31.33 | DNTH $72.08 | NRIX $15.45 | URGN $28.02 | ALMS $20.37
- SYRE $76.06 | RVMD $143.69 | CMPS $11.30 | SLDB $6.49 | DRUG $63.58
- STOK $28.75 | PRAX $242.02 | TRVI $13.44 | ERAS $13.26 | XENE $51.92

---

## Intraday (9:30 AM – 4:00 PM ET)

### 1. Portfolio Health (every 2 hours)

- [ ] **Current equity value:** `get_portfolio()` → equity_value (target: ~$100)
- [ ] **P&L tracking:** (current_equity - $100.19) / $100.19 = **% return**
- [ ] **Drawdown threshold:** if equity < $98 (-2%), flag for review
- [ ] **Buying power check:** `get_portfolio()` → buying_power (alert if <$50)

### 2. Position-Level Checks (daily, once)

For each of 15 tickers:

```
Ticker: [COGT|DNTH|NRIX|URGN|ALMS|SYRE|RVMD|CMPS|SLDB|DRUG|STOK|PRAX|TRVI|ERAS|XENE]

- [ ] Current quote: _____
- [ ] Entry price: _____ | Change: _____ %
- [ ] Position qty: _____ (from get_equity_positions)
- [ ] Current notional: _____ (qty × current quote)
- [ ] Status: ☐ OK ☐ >+15% gain ☐ <-10% loss ☐ TRADE HALT ☐ NEWS
- [ ] Volume: adequate (>100k shares/day)
```

### 3. Catalyst Tracking

- [ ] **Days to next catalyst:** check each position's catalyst_days (should all be ≥8 at entry)
- [ ] **New catalysts emerged?** search news for each ticker
- [ ] **Earnings dates:** any announced for next 30 days?
- [ ] **Clinical trial updates:** ClinicalTrials.gov for trial_ids

### 4. Risk Gates (Governance)

- [ ] **Drawdown vs XBI (biotech ETF):** if portfolio drawdown > +2pp vs XBI, flag
- [ ] **Concentration check:** largest position should be <10% (all are ~$6.67, so OK)
- [ ] **Sector momentum:** XBI price change vs portfolio change (divergence = warning)

---

## Post-Market (After 4:00 PM ET)

- [ ] **Close prices:** final equity value for the day
- [ ] **Day P&L:** log to daily_log.csv: date | equity | pnl | pnl% | activity
- [ ] **Volume review:** low volume (<50k) on any position = liquidity risk
- [ ] **After-hours alerts:** any material news or SEC filings

---

## Weekly (Friday Close or Monday AM)

- [ ] **Turnover check:** any rebalancing needed (drift >±2% per position)?
- [ ] **Catalyst window:** any positions entering critical catalyst phase (<8 days)?
- [ ] **Exit triggers:** any positions hitting -20% loss threshold?
- [ ] **Performance vs benchmark:** portfolio vs XBI vs S&P 500
- [ ] **Weekly artifact:** `weekly_monitoring_YYYY-MM-DD.json` with summary

---

## Exit Triggers (HARD STOPS)

**Automatic review required if:**

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Portfolio drawdown | ≤ -2.00pp | Review all positions, consider partial exit |
| Single position loss | ≤ -20% | Consider exit or hedge |
| Catalyst imminent | catalyst_days < 2 | Review binary risk, set tight stop |
| Trading halt | any ticker | Freeze position, monitor halt reason |
| Liquidity warning | volume < 50k/day | Consider exit if >1% of position |
| Major news | FDA rejection, clinical failure | Immediate review, likely exit |

---

## Daily Log Template

```json
{
  "date": "2026-06-10",
  "time": "16:00 ET",
  "portfolio_equity": 100.19,
  "cash": 99.87,
  "buying_power": 99.87,
  "pnl_dollars": 0.00,
  "pnl_percent": 0.00,
  "xbi_close": 0.00,
  "portfolio_vs_xbi": 0.00,
  "positions": [
    {"ticker": "COGT", "qty": 0.212789, "entry_price": 31.33, "current_price": 0.00, "change_pct": 0.00}
  ],
  "alerts": [],
  "activity": "none"
}
```

---

## Tools Available

```bash
# Quick daily snapshot
python3 -m tools.data_explorer summary --as-of 2026-06-10

# Catalyst check
grep -E "COGT|DNTH|NRIX|URGN|ALMS|SYRE|RVMD|CMPS|SLDB|DRUG|STOK|PRAX|TRVI|ERAS|XENE" catalyst_events.json

# Positions live
mcp_tool("get_equity_quotes", {"symbols": ["COGT", "DNTH", ...]})
mcp_tool("get_equity_positions", {"account_number": "802349084"})
mcp_tool("get_portfolio", {"account_number": "802349084"})

# Weekly rollup
python3 tools/weekly_monitoring.py --portfolio 2026-06-10 --output artifacts/monitoring/weekly_YYYY-MM-DD.json
```

---

## Notes

- **Duration:** Monitor through at least 2026-06-30 (20 trading days post-execution)
- **Frequency:** Daily during market hours; weekly rollup every Friday
- **Escalation:** If drawdown >-2pp or any exit trigger hit, report immediately
- **Rebalancing:** Only if position drift exceeds ±2% and no catalyst imminent
- **No new orders:** this is observation-only for Phase 2

**Start monitoring:** 2026-06-11 (first full trading day post-execution)
