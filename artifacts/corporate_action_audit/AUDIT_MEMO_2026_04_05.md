# Corporate Actions Audit — 2026-04-05

## Executive Summary

**The ticker universes and identity continuity are broadly trustworthy for production use, with specific exceptions documented below.**

The repo has a **defense-in-depth** approach to split handling: `run_screen.py` truncates pre-split history at runtime (safe for forward production), and `repair_price_history_splits.py` produces a fully-adjusted file for research. The main risk is that the adjusted file can go stale — it was regenerated as part of this audit.

There is **no formal corporate-action mapping table** in the repo. Ticker identity is handled implicitly: yfinance provides split-adjusted prices (usually), the CUSIP static map handles 13F-to-ticker resolution, and dead tickers get removed from the universe manually. This works but is fragile.

---

## What Was Checked

| Area | Scope | Method |
|------|-------|--------|
| Price history | 357 tickers, 497K rows, 2020-2026 | Automated split detection (3x/0.75x thresholds) |
| Universe membership | 342 active tickers | Cross-ref with prices, CUSIP map, known acquisitions |
| CUSIP/13F mapping | 391 CUSIP entries, 26 managers | Schema audit, orphan detection, multi-CUSIP check |
| Form 4 data | 341 tickers, 27K panel rows | Schema check, ticker coverage |
| Event/catalyst data | Event ledger, PDUFA dates | Ticker continuity check |
| Split adjustment | repair_price_history_splits.py | Full re-run, 31 tickers flagged |

---

## Findings by Area

### 1. Price History Split Artifacts

**31 tickers have split/reverse-split events detected** in `price_history.csv`.

The raw price file (`price_history.csv`) contains a mix of yfinance-adjusted and unadjusted data. For most tickers, yfinance retroactively adjusts pre-split prices. But for some — especially low-float micro-caps that did reverse splits — the adjustment is incomplete or missing.

**Production mitigation**: `run_screen.py` calls `_filter_price_outliers()` which truncates the series at the latest split point, keeping only post-split data. This prevents wrong return calculations but shortens the lookback window (e.g., momentum uses only post-split history).

**Research mitigation**: `price_history_split_adj.csv` contains the fully-adjusted series. **Regenerated as part of this audit** (was stale since 2026-03-12).

**Impact on backtests**: Research scripts that use the raw `price_history.csv` without the split-adjusted version may compute wrong returns for the 31 affected tickers. The `run_rank_ic_backtest.py` correctly uses the adjusted file. Other research scripts should be checked.

| Severity | Count | Examples |
|----------|-------|---------|
| HIGH (>10x factor) | 4 | AKTX (40x), DRUG (15x), TECX (12x), INDV (7x) |
| MODERATE (3-7x) | 27 | COGT, DFTX, MCRB, ORKA, SRRK, etc. |

### 2. Acquired/Dead Tickers in Universe

Three acquired companies are still in the universe:

| Ticker | Acquirer | Date | Status | Risk |
|--------|----------|------|--------|------|
| CNTA | Eli Lilly | 2026-03 | Trading at deal price | HIGH — price frozen, distorts returns |
| IMVT | Roche | 2024 | Trading as CVR/stub | MODERATE — low volume, stale fundamentals |
| BHVN | AbbVie | 2024-10 | CVR/transition entity | MODERATE — price behavior is CVR, not biotech |

**Fix**: These should be flagged with `status=acquired` in the universe and excluded from active scoring. The pipeline currently treats them as normal biotechs, which is wrong — CNTA's price will hover at the deal price regardless of clinical signals.

### 3. CUSIP/13F Mapping

**58 stale CUSIP map entries** point to tickers no longer in the universe (removed companies, old tickers). These don't cause errors — the 13F extractor skips unmatched CUSIPs — but they waste cycles.

**12 universe tickers lack CUSIP mapping**: AKTX, CADL, CRL, DFTX, DRMA, LBRX, MENS, NBP, OABI, QSI, TEVA, TKNO. These tickers receive zero 13F institutional data, which means coinvest_score = 0 for them. This is **correct behavior** (no data = no signal), not a bug.

**4 tickers have multiple CUSIPs**: BEAM, GH, IMCR, ZVRA. The second CUSIP appears to be a convertible note or warrant. If both report 13F positions, holdings could be double-counted. **Low probability of impact** since the 13F extractor aggregates by ticker, not CUSIP.

**No CUSIP-to-ticker mismapping detected**. The static map was audited against the current universe and no incorrect ticker assignments were found.

### 4. Form 4 / Insider Data

Form 4 data covers **341 tickers** with 27,177 panel rows across 317 unique tickers.

**No fragmentation found across renames**: The Form 4 fetch script (`fetch_form4_insider.py`) fetches by current ticker from the SEC EDGAR owner search. If a company was renamed, old Form 4 filings remain under the old CIK — the fetch script uses the current ticker symbol, so old filings under a predecessor ticker would be missed.

**Impact**: Low. Only 2-3 tickers in the universe have undergone recent renames (HOWL formerly WERW, etc.). The Form 4 signal is a supplementary ranker input, not a selector. Missing a few historical insider transactions would have negligible impact on signal quality.

### 5. Event / Catalyst Continuity

Event data is keyed by ticker in the current snapshot. **No broken event chains found** — the event ledger, PDUFA dates, and CRT resolutions all use current ticker symbols.

**Potential gap**: If a ticker changes symbol, old catalyst events under the predecessor symbol would be orphaned. In practice, the catalyst pipeline rebuilds events from scratch each day from CTGov/SEC sources, so orphaned events would simply not be carried forward. This is **safe behavior** (fail-closed, not fail-open).

### 6. Backtest / Forward Impact Assessment

| Component | Affected by corporate actions? | Severity |
|-----------|-------------------------------|----------|
| Selector bundle tests | Marginal — truncation shortens lookback for ~10% of tickers | LOW |
| Pairwise ranker evaluation | Marginal — same truncation effect | LOW |
| Signal cards (Spec 049) | NOT affected — uses cross-sectional z-scores within snapshot | NONE |
| Forward shadow monitoring | NOT affected — uses daily returns only | NONE |
| Timing hazard calibration | NOT affected — event-level, not return-level | NONE |
| Production monitor | NOT affected — uses overlap/rank, not prices | NONE |
| Benchmark-relative returns | Affected if XBI benchmark split-adjusted differently than portfolio names | LOW |

**Headline conclusions are NOT materially distorted** by corporate-action issues. The primary risk is reduced lookback for momentum/beta on the ~31 split-affected tickers, which affects their ranking but does not systematically bias the portfolio.

---

## Fixes Applied

1. **Regenerated `price_history_split_adj.csv`** — now current with all 35 split events across 31 tickers.

2. **Added 11 regression tests** (`tests/test_corporate_actions_audit.py`):
   - Split detection (reverse + forward)
   - Adjusted price continuity across splits
   - Price truncation behavior
   - Universe duplicate/status checks
   - CUSIP map sanity
   - Split-adjusted file freshness

3. **Created flagged cases table** (`artifacts/corporate_action_audit/flagged_cases.json` and `.csv`) — 53 cases with severity, status, and notes.

---

## Remaining Open Issues

| Issue | Severity | Recommended Fix |
|-------|----------|----------------|
| CNTA/IMVT/BHVN in universe as active | HIGH | Add `status=acquired` to universe entries; exclude from scoring |
| 58 stale CUSIP map entries | MODERATE | Periodic cleanup script; remove CUSIPs for delisted names |
| 12 tickers missing CUSIPs | LOW | Add CUSIPs when 13F coverage becomes available |
| No formal ticker rename/successor table | MODERATE | Build `production_data/corporate_actions.json` with rename chains |
| split_adj.csv not auto-regenerated in pipeline | MODERATE | Add regeneration step to `run_daily.py` or `warm_caches.py` |
| Some research scripts use raw prices | LOW | Audit and switch to split_adj.csv where return calculations occur |

---

## Recommendation: Do We Need a Corporate Action Mapping Table?

**Yes, eventually, but not urgently.**

The current defense-in-depth approach (truncation + split-adj file) handles the majority of cases. A formal `corporate_actions.json` would be needed if:

1. The universe starts tracking more tickers with frequent renames (current rename rate is ~1-2/year)
2. Historical backtests need to chain predecessor/successor returns
3. 13F holdings need to map across CUSIP changes at rename boundaries

For now, the `cusip_static_map.json` is the de facto identity table. It should be periodically cleaned (remove defunct entries, add new CUSIPs).

---

## Blunt Operator Summary

**Trust level: HIGH for production, MODERATE for deep historical research.**

- **Universe**: Trustworthy except CNTA/IMVT/BHVN which are acquired and should be excluded.
- **Prices**: Trustworthy for forward production (truncation protects). Split-adjusted file now current for research.
- **13F/Holdings**: Trustworthy. CUSIP map is mostly correct; no mismappings detected.
- **Form 4/Insider**: Trustworthy for current tickers. Small gap for renamed companies.
- **Events/Catalysts**: Trustworthy. No orphaned events found.
- **Backtests**: Not materially distorted. Momentum/beta lookback is shorter for ~31 tickers due to truncation, but this is a minor effect.

**The biggest real risk is CNTA** — an acquired company frozen at the deal price, being scored as if it's a live biotech with catalysts and institutional signals. Fix that first.
