# Phase 2 Daily Monitoring Index

**Current Status:** Day 2 monitoring live (2026-06-11) — 2 gap alerts, drawdown gate needs manual check  
**Portfolio:** Top-15 live (from top-30 decision portfolio)  
**Operator:** dschulz@brooks.us.com  
**Frequency:** Daily Mon–Fri through ~2026-06-30 (IC window + governance checkpoints)

---

## Quick Access

### Today's Report (2026-06-11) — Day 2
- **Full Markdown Report:** [`PHASE2_DAY2_MONITORING_2026_06_11.md`](./PHASE2_DAY2_MONITORING_2026_06_11.md)
- **Machine-Readable JSON:** [`daily_2026_06_11.json`](./daily_2026_06_11.json)

### Key Findings (Day 2)
- **Portfolio Performance (price-avg):** -10.27% avg P&L vs entry (yfinance); prior equity basis: -14.73%
- **GAP ALERTS:** DNTH -9.64% (2.27x vol), DRUG -9.20% (1.49x vol) — manual news check required
- **Governance Gates:** ⚠️ CONDITIONAL TRIP on Drawdown (-6.70pp price-avg; manual equity check required) | Jaccard 0.875 ✓
- **Critical Positions:** DRUG -28.82%, PRAX -28.81%, CMPS -24.56% (>20% loss from entry)
- **Catalyst Watch:** SYRE T+11 (near-term), 6 names at T+19-20 horizon

### Prior Report (2026-06-10) — Day 1 Baseline
- **Full Markdown Report:** [`PHASE2_DAY1_MONITORING_2026_06_10.md`](./PHASE2_DAY1_MONITORING_2026_06_10.md)
- **Machine-Readable JSON:** [`daily_2026_06_10_baseline.json`](./daily_2026_06_10_baseline.json)

### Key Findings (Day 1)
- **Portfolio Performance:** -14.73% (-$144.58) in 9 trading days
- **Equity Change:** $100.19 → $85.43
- **Governance Gates:** ✓ ALL HEALTHY (Drawdown 0.00pp, Jaccard 0.875)
- **Critical Positions:** 4 tickers with >15% loss (PRAX -26.35%, DRUG -23.86%, DNTH -20.80%, CMPS -20.73%)
- **Next Action:** Await Layer B signals (18:00–18:20 ET)

---

## Daily Monitoring Checklist

### Pre-Market (08:00 ET)
- [ ] Price data currency check
- [ ] yfinance recovery status
- [ ] Herald digest production
- [ ] Firecrawl research execution

### During Trading (08:00–16:00 ET)
- [ ] Path C governance gates (10:15 ET)
- [ ] Phase 2 daily tracking (10:20 ET)
- [ ] Data refresh completion (14:00 ET)
- [ ] Snapshot generation readiness

### Post-Trading (18:00–22:00 ET)
- [ ] Layer B signals (all 5 monitors)
  - Price Action Watch (18:00)
  - Catalyst Delta (18:05)
  - Options Watch (18:10)
  - IC Health Monitor (18:15)
  - Grok Biotech Watch (18:20)

### Gate Status (Daily)
| Gate | Current | Threshold | Status |
|------|---------|-----------|--------|
| Drawdown vs XBI | 0.00pp | ≤ -2.00pp hard exit | ✓ SAFE |
| 13F Jaccard | 0.875 | ≥ 0.70 | ✓ HEALTHY |
| IC Observable | NO_DATA | — | Expected ~2026-06-17 |

---

## Critical Positions (>15% Loss)

### High-Priority Monitoring
1. **PRAX** -26.35% | Tier B | Headwind | T+21 catalyst
2. **DRUG** -23.86% | Tier A | Headwind | T+144 catalyst
3. **DNTH** -20.80% | Tier A | Tailwind | T+20 catalyst
4. **CMPS** -20.73% | Tier C | Tailwind | T+20 catalyst

**Action:** Daily news check, catalyst verification, volume monitoring

---

## Governance Checkpoints

| Checkpoint | Date | Days | Action |
|------------|------|------|--------|
| Day 1 | 2026-06-10 | 0 | ✓ BASELINE CAPTURED |
| **Day 2** | **2026-06-11** | **1** | **⚠️ 2 gap alerts, drawdown gate check (you are here)** |
| Day 5 | 2026-06-14 | 5 | Weekly summary (collect Layer B outputs) |
| IC Print + Decision | ~2026-06-17 | ~10 | **CRITICAL:** IC first print; extend or revert? |
| Day 30 | ~2026-07-01 | 30 | Governance review: continue or exit? |
| Day 60 | ~2026-08-10 | 60 | Attribution review: mechanism clarity? |
| Day 90 | ~2026-09-09 | 90 | Final Phase 3 decision: promote or close? |

**Hard Exit (Real-Time):** If Drawdown ≤ -2.00pp → automatic phase end (no manual review)

---

## Portfolio Details

### Entry Prices (Execution: 2026-06-01)
```
COGT: $35.24  |  DNTH: $90.94  |  NRIX: $17.51  |  URGN: $26.43  |  ALMS: $20.30
SYRE: $70.48  |  RVMD: $161.26 |  CMPS: $14.62  |  SLDB: $7.26   |  DRUG: $86.48
STOK: $30.51  |  PRAX: $338.06 |  TRVI: $13.99  |  ERAS: $14.68  |  XENE: $53.66
Avg:  $65.43
```

### Current Prices (2026-06-10)
```
COGT: $32.17  |  DNTH: $72.02  |  NRIX: $15.72  |  URGN: $28.63  |  ALMS: $20.70
SYRE: $78.10  |  RVMD: $145.95 |  CMPS: $11.59  |  SLDB: $6.70   |  DRUG: $65.85
STOK: $29.85  |  PRAX: $248.99 |  TRVI: $13.70  |  ERAS: $13.56  |  XENE: $53.31
Avg:  $55.79
```

### Performance by Tier

| Tier | Holdings | Avg Change | Status |
|------|----------|-----------|--------|
| A | 7 (COGT, DNTH, NRIX, SLDB, DRUG, RCUS, PHVS) | -12.4% | Yellow |
| B | 6 (SYRE, RVMD, PRAX, XENE, MIRM, ORKA) | -15.2% | Red |
| C | 2 (CMPS, TRVI) | -11.4% | Yellow |

---

## Data References

### Snapshots
- **Baseline (Day 1):** `/mnt/c/Projects/biotech_screener/biotech-screener/data/snapshots_pit/2026-06-10/`
  - Portfolio positions: `portfolio_positions.json` (30 holdings)
  - Price data: `price_history.csv` (all tickers, daily)
  - Rankings: `rankings.csv` (decision engine output)

### Logs
- **Price data:** `logs/data_refresh.log`
- **Governance gates:** `/tmp/path_c_daily_*.log`
- **Layer B signals:** `logs/price_action_watch.log`, `logs/catalyst_delta.log`, etc.
- **Cron execution:** `logs/cron_evening_catchup.log`

### Memory Files (Background)
- `phase2_daily_monitoring_checklist_2026_06_05.md` — Full daily checklist template
- `phase2_day1_official_start_2026_06_01.md` — Phase 2 kickoff & baseline setup
- `PATH_C_WINDOW_CLOSE_DECISION_2026_06_03.md` — Governance framework & decision memo
- `layer_b_reactivation_2026_06_05.md` — Signal monitor status

---

## Commands for Daily Use

### Check Governance Gates (Quick)
```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 -c "import json; p=json.load(open('data/snapshots_pit/2026-06-10/portfolio_positions.json')); print(f'Drawdown: {p[\"drawdown_vs_xbi_pp\"]}pp | Status: {p[\"drawdown_vs_xbi_status\"]}')"
```

### Check Price Data Freshness
```bash
tail -1 production_data/price_history.csv | cut -d, -f2 | head -1
# Should show today's date (e.g., 2026-06-10)
```

### View Layer B Signals (Post-Trading)
```bash
echo "=== Price Action ===" && tail -3 logs/price_action_watch.log
echo "=== Catalyst Delta ===" && tail -3 logs/catalyst_delta.log
echo "=== IC Health ===" && tail -3 logs/ic_health_monitor.log
```

### Monitor Critical Positions (Daily)
```bash
python3 << 'EOF'
import pandas as pd
df = pd.read_csv('production_data/price_history.csv')
df['date'] = pd.to_datetime(df['date'])
latest = df[df['date'] == df['date'].max()]
critical = ['PRAX', 'DRUG', 'DNTH', 'CMPS']
print(latest[latest['ticker'].isin(critical)][['ticker', 'close']])
EOF
```

---

## Decision Framework

### If Gates Hold (Expected)
- Continue daily monitoring
- Observe Layer B signals (advisory only)
- Prepare for IC first print (~2026-06-17)

### If Drawdown Triggers Hard Exit (≤ -2.00pp)
- **Automatic:** Phase 2 window ends immediately
- **No manual review required**
- **Decision:** Abandon paper trading or investigate root cause
- **Escalation:** Immediate notification required

### If IC First Print (~2026-06-17)
- **Options:**
  - **A) Extend:** Continue Phase 2 through ~2026-07-01 (Day 30 checkpoint)
  - **B) Revert:** End paper trading, archive results, prepare Phase 3 design
- **Decision:** Operator + governance team

---

## Escalation Contacts

**Operator:** dschulz@brooks.us.com  
**Backup:** djschulz@gmail.com  
**Work Email:** dschulz@wakerobin.co  

---

## Document Metadata

- **Created:** 2026-06-10
- **Last Updated:** 2026-06-10
- **Status:** Active (daily updates through ~2026-06-17)
- **Next Review:** 2026-06-11
- **Archive:** Post-phase-end (2026-06-17 or upon hard exit)

---

**Phase 2 Monitoring — Ready for Daily Operations**
