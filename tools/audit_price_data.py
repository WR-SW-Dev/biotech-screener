"""
Full price data audit: accuracy, logic, and cross-source consistency.

Usage:
    python tools/audit_price_data.py [--snapshot YYYY-MM-DD]
"""

import argparse
import csv
import json
import math
import os
from collections import defaultdict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRICE_HISTORY_CSV = os.path.join(ROOT, "production_data", "price_history.csv")
MARKET_DATA_JSON = os.path.join(ROOT, "production_data", "market_data.json")
PIT_CACHE_ROOT = os.path.join(ROOT, "data", "caches", "price_pit", "PIT")
SNAPSHOTS_ROOT = os.path.join(ROOT, "data", "snapshots")

SPLIT_JUMP_THRESHOLD = 3.0  # +300% single day = likely un-adjusted split
SPLIT_DROP_THRESHOLD = -0.75  # -75% single day = likely reverse-split artifact
PRICE_MIN = 0.001
PRICE_MAX = 10_000.0
STALE_DAYS = 5  # flag tickers with no price update in N trading days
PRICE_CROSS_TOLERANCE = 0.10  # 10% tolerance for market_data price vs latest close


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _pct(n, d):
    return 0.0 if d == 0 else round(100.0 * n / d, 1)


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _trading_days_between(start: date, end: date) -> int:
    """Rough weekday count between two dates (ignores holidays)."""
    count = 0
    cur = start + timedelta(days=1)
    while cur <= end:
        if _is_weekday(cur):
            count += 1
        cur += timedelta(days=1)
    return count


def _fmt_val(v, digits=4):
    if v is None:
        return "None"
    if isinstance(v, float) and math.isnan(v):
        return "NaN"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


# ---------------------------------------------------------------------------
# Section 1 — Price History CSV
# ---------------------------------------------------------------------------


def audit_price_history(snapshot_date: date):
    print("\n" + "=" * 70)
    print("SECTION 1 — PRICE HISTORY CSV")
    print("=" * 70)

    if not os.path.exists(PRICE_HISTORY_CSV):
        print("  ERROR: price_history.csv not found")
        return {}

    rows_by_ticker = defaultdict(list)
    total_rows = 0
    parse_errors = []

    with open(PRICE_HISTORY_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            try:
                d = date.fromisoformat(row["date"])
                close = float(row["close"])

                # open/high/low are absent in older historical rows (close+volume only)
                def _opt(v):
                    return float(v) if v else None

                open_ = _opt(row.get("open", ""))
                high = _opt(row.get("high", ""))
                low = _opt(row.get("low", ""))
                volume = float(row.get("volume") or 0)
                rows_by_ticker[row["ticker"]].append((d, close, open_, high, low, volume))
                total_rows += 1
            except Exception as e:
                parse_errors.append((i, str(e), row))

    print(f"\n  Rows loaded   : {total_rows:,}")
    print(f"  Tickers       : {len(rows_by_ticker)}")
    if parse_errors:
        print(f"  Parse errors  : {len(parse_errors)}")
        for ln, err, row in parse_errors[:5]:
            print(f"    Line {ln}: {err} | {row}")

    # Sort each ticker's series chronologically
    for t in rows_by_ticker:
        rows_by_ticker[t].sort(key=lambda x: x[0])

    # 1a. Staleness
    print(f"\n  [1a] Staleness (snapshot_date={snapshot_date})")
    stale = []
    for ticker, series in rows_by_ticker.items():
        latest = series[-1][0]
        gap = _trading_days_between(latest, snapshot_date)
        if gap > STALE_DAYS:
            stale.append((ticker, latest, gap))
    stale.sort(key=lambda x: -x[2])
    print(f"       Tickers with no update in >{STALE_DAYS} trading days: {len(stale)}")
    for ticker, latest, gap in stale[:15]:
        print(f"       {ticker:8s} last={latest}  gap={gap}d")
    if len(stale) > 15:
        print(f"       ... and {len(stale) - 15} more")

    rows_with_ohlc = sum(1 for series in rows_by_ticker.values() for (_, _, o, h, l, _) in series if o is not None)
    rows_total_all = sum(len(s) for s in rows_by_ticker.values())
    print(f"  Rows with full OHLC  : {rows_with_ohlc:,}  (close-only: {rows_total_all - rows_with_ohlc:,})")

    # 1b. Zero/negative prices
    print("\n  [1b] Zero or Negative Prices (close; OHLC where present)")
    zero_neg = []
    for ticker, series in rows_by_ticker.items():
        for d, close, open_, high, low, vol in series:
            bad = close <= 0
            bad = bad or (open_ is not None and open_ <= 0)
            bad = bad or (high is not None and high <= 0)
            bad = bad or (low is not None and low <= 0)
            if bad:
                zero_neg.append((ticker, d, close, open_, high, low))
    print(f"       Rows with zero/negative OHLC: {len(zero_neg)}")
    for ticker, d, c, o, h, l in zero_neg[:10]:
        print(f"       {ticker:8s} {d}  close={c}  open={o}  high={h}  low={l}")

    # 1c. OHLC logic violations (close-only rows skipped)
    print("\n  [1c] OHLC Logic Violations (low>high, close∉[low,high], open∉[low,high]; OHLC rows only)")
    ohlc_violations = []
    for ticker, series in rows_by_ticker.items():
        for d, close, open_, high, low, vol in series:
            if open_ is None or high is None or low is None:
                continue
            reasons = []
            if low > high:
                reasons.append(f"low({low:.4f})>high({high:.4f})")
            tol = high * 0.005 if high > 0 else 0.001
            if close < low - tol or close > high + tol:
                reasons.append(f"close({close:.4f})not_in[{low:.4f},{high:.4f}]")
            if open_ < low - tol or open_ > high + tol:
                reasons.append(f"open({open_:.4f})not_in[{low:.4f},{high:.4f}]")
            if reasons:
                ohlc_violations.append((ticker, d, "; ".join(reasons)))
    print(f"       Violations: {len(ohlc_violations)}")
    for ticker, d, reason in ohlc_violations[:15]:
        print(f"       {ticker:8s} {d}  {reason}")
    if len(ohlc_violations) > 15:
        print(f"       ... and {len(ohlc_violations) - 15} more")

    # 1d. Split / extreme move artifacts
    print(
        f"\n  [1d] Split Artifacts (single-day >{SPLIT_JUMP_THRESHOLD*100:.0f}% up or >{abs(SPLIT_DROP_THRESHOLD)*100:.0f}% down)"
    )
    split_artifacts = []
    for ticker, series in rows_by_ticker.items():
        for i in range(1, len(series)):
            prev_d, prev_c = series[i - 1][0], series[i - 1][1]
            cur_d, cur_c = series[i][0], series[i][1]
            if prev_c <= 0:
                continue
            chg = (cur_c - prev_c) / prev_c
            if chg > SPLIT_JUMP_THRESHOLD or chg < SPLIT_DROP_THRESHOLD:
                split_artifacts.append((ticker, prev_d, cur_d, prev_c, cur_c, chg))
    split_artifacts.sort(key=lambda x: abs(x[5]), reverse=True)
    print(f"       Candidate artifacts: {len(split_artifacts)}")
    for ticker, d1, d2, c1, c2, chg in split_artifacts[:20]:
        print(f"       {ticker:8s} {d1}→{d2}  {c1:.4f}→{c2:.4f}  ({chg*100:+.1f}%)")
    if len(split_artifacts) > 20:
        print(f"       ... and {len(split_artifacts) - 20} more")

    # 1e. Extreme price outliers (not split-related)
    print(f"\n  [1e] Extreme Price Outliers (close<{PRICE_MIN} or close>{PRICE_MAX})")
    outliers = []
    for ticker, series in rows_by_ticker.items():
        for d, close, open_, high, low, vol in series:
            if close < PRICE_MIN or close > PRICE_MAX:
                outliers.append((ticker, d, close))
    print(f"       Rows with outlier close: {len(outliers)}")
    for ticker, d, c in outliers[:10]:
        print(f"       {ticker:8s} {d}  close={c}")

    # 1f. Duplicate rows
    print("\n  [1f] Duplicate (ticker, date) rows")
    seen = defaultdict(int)
    with open(PRICE_HISTORY_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            seen[(row["ticker"], row["date"])] += 1
    dupes = {k: v for k, v in seen.items() if v > 1}
    print(f"       Duplicate (ticker,date) pairs: {len(dupes)}")
    for (ticker, d), cnt in list(sorted(dupes.items(), key=lambda x: -x[1]))[:10]:
        print(f"       {ticker:8s} {d}  count={cnt}")

    # 1g. Weekday gaps (>1 consecutive weekday missing)
    print("\n  [1g] Unexplained Date Gaps (>3 consecutive weekday missing, last 90 days)")
    cutoff = snapshot_date - timedelta(days=90)
    gap_tickers = []
    for ticker, series in rows_by_ticker.items():
        recent = [row for row in series if row[0] >= cutoff]
        if len(recent) < 2:
            continue
        for i in range(1, len(recent)):
            prev_d = recent[i - 1][0]
            cur_d = recent[i][0]
            gap = _trading_days_between(prev_d, cur_d)
            if gap > 3:  # >3 weekdays missing — likely suspended/halted or data hole
                gap_tickers.append((ticker, prev_d, cur_d, gap))
    gap_tickers.sort(key=lambda x: -x[3])
    print(f"       Tickers with >3 weekday gap in last 90d: {len(gap_tickers)}")
    for ticker, d1, d2, gap in gap_tickers[:15]:
        print(f"       {ticker:8s} {d1}→{d2}  gap={gap} weekdays")

    # 1h. Zero volume on non-OTC trading days
    print("\n  [1h] Zero Volume (recent 30 days only)")
    cutoff30 = snapshot_date - timedelta(days=30)
    zero_vol = []
    for ticker, series in rows_by_ticker.items():
        for d, close, open_, high, low, vol in series:
            if d >= cutoff30 and _is_weekday(d) and vol == 0:
                zero_vol.append((ticker, d, close, vol))
    print(f"       Zero-volume rows in last 30d: {len(zero_vol)}")
    for ticker, d, c, v in zero_vol[:10]:
        print(f"       {ticker:8s} {d}  close={c:.4f}  vol={v}")

    # 1i. Coverage summary
    tickers_with_recent_data = sum(
        1
        for t, series in rows_by_ticker.items()
        if series and series[-1][0] >= snapshot_date - timedelta(days=STALE_DAYS)
    )
    print("\n  [1i] Coverage Summary")
    print(f"       Tickers with recent data (<={STALE_DAYS}d old): {tickers_with_recent_data}/{len(rows_by_ticker)}")
    latest_dates = sorted({series[-1][0] for series in rows_by_ticker.values()}, reverse=True)
    print(f"       Most recent dates in file: {latest_dates[:5]}")

    return rows_by_ticker


# ---------------------------------------------------------------------------
# Section 2 — Market Data JSON
# ---------------------------------------------------------------------------


def audit_market_data(rows_by_ticker: dict, snapshot_date: date):
    print("\n" + "=" * 70)
    print("SECTION 2 — MARKET DATA JSON")
    print("=" * 70)

    if not os.path.exists(MARKET_DATA_JSON):
        print("  ERROR: market_data.json not found")
        return []

    with open(MARKET_DATA_JSON) as f:
        records = json.load(f)

    if not isinstance(records, list):
        records = list(records.values())

    print(f"\n  Records: {len(records)}")

    # 2a. Staleness
    print("\n  [2a] Staleness")
    from collections import Counter

    dates = [r.get("collected_at", "MISSING") for r in records]
    for d, cnt in sorted(Counter(dates).items(), reverse=True)[:5]:
        age = (snapshot_date - date.fromisoformat(d)).days if d != "MISSING" else "?"
        print(f"       collected_at={d}  count={cnt}  age={age}d")

    # 2b. Null/missing field rates
    print("\n  [2b] Field Null Rates (sorted by % null, fields >0% null)")
    all_fields = set()
    for r in records:
        all_fields.update(r.keys())
    null_rates = {}
    for field in sorted(all_fields):
        nulls = sum(1 for r in records if r.get(field) is None)
        if nulls > 0:
            null_rates[field] = nulls
    for field, n in sorted(null_rates.items(), key=lambda x: -x[1]):
        print(f"       {field:30s}  null={n}/{len(records)} ({_pct(n, len(records)):.1f}%)")

    # 2c. Unit consistency checks
    print("\n  [2c] Unit Consistency Checks")

    # volatility_90d: expect decimal (0.01 to 5.0 = 1% to 500% ann.)
    vols = [(r["ticker"], r["volatility_90d"]) for r in records if r.get("volatility_90d") is not None]
    high_vols = [(t, v) for t, v in vols if v > 5.0]
    print(f"       volatility_90d > 5.0 (>500% ann., suspect %/100 confusion): {len(high_vols)}")
    for t, v in sorted(high_vols, key=lambda x: -x[1])[:5]:
        print(f"         {t}: {v:.4f}")
    negative_vols = [(t, v) for t, v in vols if v < 0]
    print(f"       volatility_90d < 0 (impossible): {len(negative_vols)}")

    # returns_1m / returns_3m: expect decimal (-5.0 to +10.0)
    for rfield in ["returns_1m", "returns_3m"]:
        rets = [(r["ticker"], r[rfield]) for r in records if r.get(rfield) is not None]
        bad = [(t, v) for t, v in rets if abs(v) > 10.0]
        print(f"       {rfield} |value|>10.0 (suspect % not decimal): {len(bad)}")
        for t, v in sorted(bad, key=lambda x: -abs(x[1]))[:3]:
            print(f"         {t}: {v:.4f}")

    # short_percent: expect decimal (0.0 to 1.0)
    shorts = [(r["ticker"], r["short_percent"]) for r in records if r.get("short_percent") is not None]
    bad_shorts = [(t, v) for t, v in shorts if v > 1.0]
    print(f"       short_percent > 1.0 (suspect % not decimal): {len(bad_shorts)}")
    for t, v in sorted(bad_shorts, key=lambda x: -x[1])[:5]:
        print(f"         {t}: {v:.4f}")

    # 2d. Price sanity (cross-check vs price_history)
    print("\n  [2d] Price Cross-Check: market_data.price vs price_history latest close")
    cross_issues = []
    missing_in_history = []
    for r in records:
        ticker = r["ticker"]
        md_price = r.get("price")
        if md_price is None or md_price <= 0:
            continue
        if ticker not in rows_by_ticker:
            missing_in_history.append(ticker)
            continue
        series = rows_by_ticker[ticker]
        if not series:
            continue
        latest_close = series[-1][1]
        if latest_close <= 0:
            continue
        pct_diff = abs(md_price - latest_close) / latest_close
        if pct_diff > PRICE_CROSS_TOLERANCE:
            cross_issues.append((ticker, md_price, latest_close, pct_diff, series[-1][0]))
    cross_issues.sort(key=lambda x: -x[3])
    print(f"       market_data tickers missing from price_history: {len(missing_in_history)}")
    if missing_in_history:
        print(f"         {missing_in_history[:10]}")
    print(f"       Price discrepancy >{PRICE_CROSS_TOLERANCE*100:.0f}% vs latest close: {len(cross_issues)}")
    for ticker, mdp, hc, diff, hdate in cross_issues[:20]:
        print(f"       {ticker:8s}  md_price={mdp:.4f}  hist_close={hc:.4f} ({hdate})  diff={diff*100:.1f}%")
    if len(cross_issues) > 20:
        print(f"       ... and {len(cross_issues) - 20} more")

    # 2e. Market cap vs price * shares consistency
    print("\n  [2e] Market Cap Sanity (market_cap vs price*shares_outstanding, tolerance 25%)")
    cap_issues = []
    for r in records:
        price = r.get("price")
        shares = r.get("shares_outstanding")
        mcap = r.get("market_cap")
        ticker = r.get("ticker", "?")
        if not all(isinstance(v, (int, float)) and v is not None for v in [price, shares, mcap]):
            continue
        if price <= 0 or shares <= 0 or mcap <= 0:
            continue
        implied = price * shares
        if implied == 0:
            continue
        diff = abs(mcap - implied) / implied
        if diff > 0.25:
            cap_issues.append((ticker, price, shares, mcap, implied, diff))
    cap_issues.sort(key=lambda x: -x[5])
    print(f"       Discrepancies >25%: {len(cap_issues)}")
    for ticker, p, s, mc, imp, diff in cap_issues[:10]:
        print(
            f"       {ticker:8s}  price={p:.2f}  shares={s/1e6:.1f}M  "
            f"market_cap=${mc/1e6:.1f}M  implied=${imp/1e6:.1f}M  diff={diff*100:.0f}%"
        )

    # 2f. Extreme price outliers in market_data
    print("\n  [2f] Extreme Prices in market_data.json")
    low_prices = [(r["ticker"], r["price"]) for r in records if r.get("price") and r["price"] < 0.10]
    high_prices = [(r["ticker"], r["price"]) for r in records if r.get("price") and r["price"] > 1000]
    neg_prices = [(r["ticker"], r["price"]) for r in records if r.get("price") and r["price"] <= 0]
    print(f"       price < $0.10    : {len(low_prices)}")
    for t, v in sorted(low_prices, key=lambda x: x[1])[:5]:
        print(f"         {t}: ${v:.4f}")
    print(f"       price > $1,000   : {len(high_prices)}")
    for t, v in sorted(high_prices, key=lambda x: -x[1])[:5]:
        print(f"         {t}: ${v:.2f}")
    print(f"       price <= 0       : {len(neg_prices)}")

    return records


# ---------------------------------------------------------------------------
# Section 3 — PIT Cache
# ---------------------------------------------------------------------------


def audit_pit_cache(snapshot_date: date):
    print("\n" + "=" * 70)
    print("SECTION 3 — PIT PRICE CACHE")
    print("=" * 70)

    if not os.path.exists(PIT_CACHE_ROOT):
        print("  PIT cache directory not found")
        return

    cache_dates = sorted(d for d in os.listdir(PIT_CACHE_ROOT) if os.path.isdir(os.path.join(PIT_CACHE_ROOT, d)))
    print(f"\n  Cache dates available: {len(cache_dates)}")
    print(f"  Date range: {cache_dates[0] if cache_dates else 'none'} → {cache_dates[-1] if cache_dates else 'none'}")

    # Audit latest cache
    if not cache_dates:
        print("  No cache entries found.")
        return

    latest = cache_dates[-1]
    index_path = os.path.join(PIT_CACHE_ROOT, latest, "index.json")
    prices_path = os.path.join(PIT_CACHE_ROOT, latest, "prices.csv")

    print(f"\n  [3a] Latest cache: {latest}")
    if not os.path.exists(index_path):
        print(f"  ERROR: index.json missing for {latest}")
        return

    with open(index_path) as f:
        idx = json.load(f)

    print(f"       schema_version    : {idx.get('schema_version')}")
    print(f"       cache_type        : {idx.get('cache_type')}")
    print(f"       as_of_date        : {idx.get('as_of_date')}")
    print(f"       anchor_date       : {idx.get('anchor_date')}")
    print(f"       ticker_count      : {idx.get('ticker_count')}")
    print(f"       coverage_pct      : {idx.get('coverage_pct')}")
    print(f"       horizons_filled   : {idx.get('horizons_filled')}")
    print(f"       horizons_pending  : {idx.get('horizons_pending')}")
    missing_anchors = idx.get("tickers_missing_anchor", [])
    print(f"       tickers_missing_anchor: {len(missing_anchors)}")
    if missing_anchors:
        print(f"         {missing_anchors[:10]}")
    split_warns = idx.get("split_warnings", [])
    print(f"       split_warnings    : {len(split_warns)}")
    for w in split_warns[:5]:
        print(f"         {w}")

    # 3b. Prices CSV spot check
    print("\n  [3b] PIT prices.csv spot check")
    if not os.path.exists(prices_path):
        print(f"  ERROR: prices.csv missing for {latest}")
        return

    pit_rows = []
    with open(prices_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pit_rows.append(row)
    print(f"       Rows: {len(pit_rows)}")
    if pit_rows:
        print(f"       Columns: {list(pit_rows[0].keys())}")

    # Check for zero or negative anchor_close
    bad_anchors = []
    null_anchors = []
    for row in pit_rows:
        ac = row.get("anchor_close", "")
        if ac == "" or ac is None:
            null_anchors.append(row["ticker"])
        else:
            try:
                ac_f = float(ac)
                if ac_f <= 0:
                    bad_anchors.append((row["ticker"], ac_f))
            except ValueError:
                null_anchors.append(row["ticker"])
    print(f"       Null/empty anchor_close: {len(null_anchors)}")
    print(f"       Zero/negative anchor_close: {len(bad_anchors)}")
    for t, v in bad_anchors[:5]:
        print(f"         {t}: {v}")

    # Check forward return magnitudes
    horizons = ["h5", "h20", "h63"]
    for hz in horizons:
        close_col = f"{hz}_close"
        if not pit_rows or close_col not in pit_rows[0]:
            continue
        extreme_fwd = []
        for row in pit_rows:
            ac = row.get("anchor_close", "")
            fc = row.get(close_col, "")
            if ac == "" or fc == "":
                continue
            try:
                ac_f, fc_f = float(ac), float(fc)
                if ac_f <= 0 or fc_f <= 0:
                    continue
                ret = (fc_f - ac_f) / ac_f
                if abs(ret) > 1.5:  # >150% or <-75% — flag
                    extreme_fwd.append((row["ticker"], ac_f, fc_f, ret))
            except ValueError:
                pass
        if extreme_fwd:
            print(f"\n  [3c] PIT {hz} extreme forward returns (>±150%):")
            for t, ac, fc, ret in sorted(extreme_fwd, key=lambda x: -abs(x[3]))[:10]:
                print(f"         {t:8s}  anchor={ac:.4f}  {hz}_close={fc:.4f}  ret={ret*100:+.1f}%")


# ---------------------------------------------------------------------------
# Section 4 — Pipeline Field Audit (from latest rankings.csv)
# ---------------------------------------------------------------------------


def audit_pipeline_fields(snapshot_date: date):
    print("\n" + "=" * 70)
    print("SECTION 4 — PIPELINE FIELD AUDIT (latest rankings.csv)")
    print("=" * 70)

    snapshot_str = snapshot_date.isoformat()
    rankings_path = os.path.join(SNAPSHOTS_ROOT, snapshot_str, "rankings.csv")

    # Fall back to most recent snapshot
    if not os.path.exists(rankings_path):
        dirs = sorted(
            d for d in os.listdir(SNAPSHOTS_ROOT) if os.path.isdir(os.path.join(SNAPSHOTS_ROOT, d)) and d[:4].isdigit()
        )
        if dirs:
            snapshot_str = dirs[-1]
            rankings_path = os.path.join(SNAPSHOTS_ROOT, snapshot_str, "rankings.csv")
        if not os.path.exists(rankings_path):
            print("  No rankings.csv found.")
            return

    print(f"\n  Snapshot: {snapshot_str}")

    rows = []
    with open(rankings_path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"  Rows: {len(rows)}")

    def _floats(field):
        vals = []
        for r in rows:
            v = r.get(field, "")
            if v and v not in ("", "None", "nan", "NaN"):
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
        return vals

    # 4a. priced_move_pct units
    print("\n  [4a] priced_move_pct units (expect percentage-points 1–500, not raw decimal)")
    pmv = _floats("priced_move_pct")
    if pmv:
        below_1 = [v for v in pmv if v < 1.0]
        above_500 = [v for v in pmv if v > 500.0]
        print(
            f"       Non-null: {len(pmv)}  min={min(pmv):.4f}  max={max(pmv):.4f}  "
            f"median={sorted(pmv)[len(pmv)//2]:.2f}"
        )
        print(f"       Values <1.0 (raw decimal — unit conversion missed?): {len(below_1)}")
        print(f"       Values >500 (implausibly large): {len(above_500)}")
        if below_1:
            bad_tickers = [
                (r["ticker"], float(r["priced_move_pct"]))
                for r in rows
                if r.get("priced_move_pct", "") not in ("", "None", "nan", "NaN") and float(r["priced_move_pct"]) < 1.0
            ]
            for t, v in sorted(bad_tickers, key=lambda x: x[1])[:10]:
                print(f"         {t}: {v:.6f}")
    else:
        print("       No non-null priced_move_pct values found")

    # 4b. straddle_price vs priced_move_pct relationship
    print("\n  [4b] straddle_price vs priced_move_pct consistency (expect pmp ≈ straddle*100)")
    mismatches = []
    for r in rows:
        sp = r.get("straddle_price", "")
        pmp = r.get("priced_move_pct", "")
        if sp not in ("", "None", "nan") and pmp not in ("", "None", "nan"):
            try:
                sp_f = float(sp)
                pmp_f = float(pmp)
                if sp_f > 0 and pmp_f > 0:
                    ratio = pmp_f / sp_f
                    if ratio < 50 or ratio > 200:  # expect ~100
                        mismatches.append((r["ticker"], sp_f, pmp_f, ratio))
            except ValueError:
                pass
    print(f"       Rows where pmp/straddle ratio ∉[50,200]: {len(mismatches)}")
    for t, sp, pmp, ratio in sorted(mismatches, key=lambda x: abs(x[3] - 100))[:10]:
        print(f"         {t:8s}  straddle={sp:.4f}  priced_move={pmp:.2f}  ratio={ratio:.1f}")

    # 4c. close_price outliers
    print("\n  [4c] close_price outliers in rankings")
    cp = _floats("close_price")
    if cp:
        print(f"       Non-null: {len(cp)}  min={min(cp):.4f}  max={max(cp):.4f}")
        pct1 = sorted(cp)[len(cp) // 100] if len(cp) >= 100 else min(cp)
        pct99 = sorted(cp)[len(cp) * 99 // 100] if len(cp) >= 100 else max(cp)
        print(f"       P1={pct1:.4f}  P99={pct99:.4f}")
        low_prices = [
            (r["ticker"], float(r["close_price"]))
            for r in rows
            if r.get("close_price", "") not in ("", "None", "nan", "NaN") and float(r["close_price"]) < 0.10
        ]
        print(f"       close_price < $0.10: {len(low_prices)}")
        for t, v in sorted(low_prices, key=lambda x: x[1])[:5]:
            print(f"         {t}: ${v:.4f}")

    # 4d. drawdown sign check
    print("\n  [4d] de_drawdown sign check (expect ≤0)")
    dd = _floats("de_drawdown")
    if dd:
        pos_dd = [v for v in dd if v > 0]
        print(f"       Non-null: {len(dd)}  min={min(dd):.4f}  max={max(dd):.4f}")
        print(f"       Positive drawdown values (should be ≤0): {len(pos_dd)}")
        if pos_dd:
            bad = [
                (r["ticker"], float(r["de_drawdown"]))
                for r in rows
                if r.get("de_drawdown", "") not in ("", "None", "nan", "NaN") and float(r["de_drawdown"]) > 0
            ]
            for t, v in sorted(bad, key=lambda x: -x[1])[:5]:
                print(f"         {t}: {v:.4f}")

    # 4e. momentum return units (de_alpha_60d — expect decimal like ±2.0 = ±200%)
    print("\n  [4e] de_alpha_60d units (expect decimal ±2.0, not percentage)")
    alpha = _floats("de_alpha_60d")
    if alpha:
        extreme = [v for v in alpha if abs(v) > 5.0]
        print(f"       Non-null: {len(alpha)}  min={min(alpha):.4f}  max={max(alpha):.4f}")
        print(f"       |value|>5.0 (suspect percentage not decimal): {len(extreme)}")
        if extreme:
            bad = [
                (r["ticker"], float(r["de_alpha_60d"]))
                for r in rows
                if r.get("de_alpha_60d", "") not in ("", "None", "nan", "NaN") and abs(float(r["de_alpha_60d"])) > 5.0
            ]
            for t, v in sorted(bad, key=lambda x: -abs(x[1]))[:5]:
                print(f"         {t}: {v:.4f}")

    # 4f. vol_60d units
    print("\n  [4f] de_vol_60d units (expect annualized decimal, e.g. 0.5 = 50% vol)")
    vol60 = _floats("de_vol_60d")
    if vol60:
        extreme_vols = [v for v in vol60 if v > 5.0]
        print(f"       Non-null: {len(vol60)}  min={min(vol60):.4f}  max={max(vol60):.4f}")
        print(f"       Values >5.0 (>500% ann. vol, suspect % confusion): {len(extreme_vols)}")
        if extreme_vols:
            bad = [
                (r["ticker"], float(r["de_vol_60d"]))
                for r in rows
                if r.get("de_vol_60d", "") not in ("", "None", "nan", "NaN") and float(r["de_vol_60d"]) > 5.0
            ]
            for t, v in sorted(bad, key=lambda x: -x[1])[:5]:
                print(f"         {t}: {v:.4f}")

    # 4g. market_cap_mm sanity
    print("\n  [4g] market_cap_mm sanity (expect $50M–$50,000M range for screened universe)")
    mcm = _floats("market_cap_mm")
    if mcm:
        below_50 = [v for v in mcm if v < 50]
        above_50k = [v for v in mcm if v > 50_000]
        print(f"       Non-null: {len(mcm)}  min={min(mcm):.1f}  max={max(mcm):.1f}")
        print(f"       <$50M (below typical small-cap threshold): {len(below_50)}")
        for t in [
            r["ticker"]
            for r in rows
            if r.get("market_cap_mm", "") not in ("", "None", "nan", "NaN") and float(r["market_cap_mm"]) < 50
        ][:5]:
            print(f"         {t}: {next(float(r['market_cap_mm']) for r in rows if r['ticker'] == t):.1f}M")
        print(f"       >$50,000M (very large cap, unusual for biotech screener): {len(above_50k)}")

    # 4h. short_interest_pct units (expect decimal 0–1)
    print("\n  [4h] short_interest_pct units (expect decimal 0–1)")
    si = _floats("short_interest_pct")
    if si:
        bad_si = [v for v in si if v > 1.0]
        print(f"       Non-null: {len(si)}  min={min(si):.4f}  max={max(si):.4f}")
        print(f"       Values >1.0 (suspect %/100 not applied): {len(bad_si)}")
        if bad_si:
            bad = [
                (r["ticker"], float(r["short_interest_pct"]))
                for r in rows
                if r.get("short_interest_pct", "") not in ("", "None", "nan", "NaN")
                and float(r["short_interest_pct"]) > 1.0
            ]
            for t, v in sorted(bad, key=lambda x: -x[1])[:5]:
                print(f"         {t}: {v:.4f}")

    # 4i. implied_event_move (raw, pre-*100) vs priced_move_pct alignment
    print("\n  [4i] implied_event_move vs priced_move_pct (expect pmp ≈ iem*100)")
    iem_pmv = []
    for r in rows:
        iem = r.get("implied_event_move", "")
        pmp = r.get("priced_move_pct", "")
        if iem not in ("", "None", "nan", "NaN") and pmp not in ("", "None", "nan", "NaN"):
            try:
                iem_f = float(iem)
                pmp_f = float(pmp)
                if iem_f > 0 and pmp_f > 0:
                    iem_pmv.append((r["ticker"], iem_f, pmp_f))
            except ValueError:
                pass
    if iem_pmv:
        ratios = [pmp / iem for _, iem, pmp in iem_pmv]
        bad_ratio = [(t, iem, pmp, pmp / iem) for t, iem, pmp in iem_pmv if pmp / iem < 50 or pmp / iem > 200]
        print(
            f"       Pairs: {len(iem_pmv)}  ratio p25={sorted(ratios)[len(ratios)//4]:.1f}  "
            f"median={sorted(ratios)[len(ratios)//2]:.1f}  p75={sorted(ratios)[len(ratios)*3//4]:.1f}"
        )
        print(f"       Ratio ∉[50,200]: {len(bad_ratio)}")
        for t, iem, pmp, ratio in sorted(bad_ratio, key=lambda x: abs(x[3] - 100))[:5]:
            print(f"         {t:8s}  iem={iem:.4f}  pmp={pmp:.2f}  ratio={ratio:.1f}")

    # 4j. Missing priced_move_pct for options-covered tickers
    print("\n  [4j] opt_has_data=1 but priced_move_pct missing")
    opt_no_pmv = [
        r["ticker"]
        for r in rows
        if r.get("opt_has_data", "") == "1" and r.get("priced_move_pct", "") in ("", "None", "nan", "NaN", "0", "0.0")
    ]
    print(f"       Count: {len(opt_no_pmv)}")
    if opt_no_pmv:
        print(f"         {opt_no_pmv[:10]}")


# ---------------------------------------------------------------------------
# Section 5 — Cross-Source Universe Consistency
# ---------------------------------------------------------------------------


def audit_universe_consistency(rows_by_ticker: dict, market_records: list, snapshot_date: date):
    print("\n" + "=" * 70)
    print("SECTION 5 — UNIVERSE CONSISTENCY (cross-source coverage)")
    print("=" * 70)

    md_tickers = {r["ticker"] for r in market_records}
    ph_tickers = set(rows_by_ticker.keys())

    snapshot_str = snapshot_date.isoformat()
    rankings_path = os.path.join(SNAPSHOTS_ROOT, snapshot_str, "rankings.csv")
    if not os.path.exists(rankings_path):
        dirs = sorted(
            d for d in os.listdir(SNAPSHOTS_ROOT) if os.path.isdir(os.path.join(SNAPSHOTS_ROOT, d)) and d[:4].isdigit()
        )
        if dirs:
            snapshot_str = dirs[-1]
            rankings_path = os.path.join(SNAPSHOTS_ROOT, snapshot_str, "rankings.csv")

    rank_tickers = set()
    if os.path.exists(rankings_path):
        with open(rankings_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rank_tickers.add(row["ticker"])

    print(f"\n  market_data.json   : {len(md_tickers)} tickers")
    print(f"  price_history.csv  : {len(ph_tickers)} tickers")
    print(f"  rankings.csv       : {len(rank_tickers)} tickers (snapshot {snapshot_str})")

    in_md_not_ph = md_tickers - ph_tickers
    in_ph_not_md = ph_tickers - md_tickers
    in_rank_not_ph = rank_tickers - ph_tickers
    in_rank_not_md = rank_tickers - md_tickers

    print(f"\n  [5a] In market_data but NOT price_history: {len(in_md_not_ph)}")
    if in_md_not_ph:
        print(f"       {sorted(in_md_not_ph)[:15]}")

    print(f"\n  [5b] In price_history but NOT market_data: {len(in_ph_not_md)}")
    if in_ph_not_md:
        print(f"       {sorted(in_ph_not_md)[:15]}")
        if len(in_ph_not_md) > 15:
            print(f"       ... and {len(in_ph_not_md) - 15} more")

    print(f"\n  [5c] In rankings but NOT price_history: {len(in_rank_not_ph)}")
    if in_rank_not_ph:
        print(f"       {sorted(in_rank_not_ph)}")

    print(f"\n  [5d] In rankings but NOT market_data: {len(in_rank_not_md)}")
    if in_rank_not_md:
        print(f"       {sorted(in_rank_not_md)}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Full price data audit")
    parser.add_argument("--snapshot", default=None, help="Snapshot date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    if args.snapshot:
        snapshot_date = date.fromisoformat(args.snapshot)
    else:
        snapshot_date = date.today()

    print(f"\n{'#'*70}")
    print("  BIOTECH SCREENER — FULL PRICE DATA AUDIT")
    print(f"  Run date: {date.today()}   Snapshot: {snapshot_date}")
    print(f"{'#'*70}")

    rows_by_ticker = audit_price_history(snapshot_date)
    market_records = audit_market_data(rows_by_ticker, snapshot_date)
    audit_pit_cache(snapshot_date)
    audit_pipeline_fields(snapshot_date)
    audit_universe_consistency(rows_by_ticker, market_records, snapshot_date)

    print("\n" + "=" * 70)
    print("AUDIT COMPLETE")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
