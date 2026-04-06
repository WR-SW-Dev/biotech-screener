#!/usr/bin/env python3
"""
Manager-level 13F performance study.

Builds a PIT-safe panel of manager holdings, measures per-manager alpha,
computes overlap/redundancy, and compares coinvest model variants.

Usage:
    python scripts/research/manager_edge_study.py

Outputs:
    artifacts/manager_edge_study/manager_leaderboard.json
    artifacts/manager_edge_study/study_summary.md
"""

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "production_data" / "manager_registry.json"
PRICE_PATH = ROOT / "production_data" / "price_history.csv"
UNIVERSE_PATH = ROOT / "production_data" / "universe.json"
CUSIP_MAP_PATH = ROOT / "production_data" / "cusip_static_map.json"
PIT_CACHE_DIR = ROOT / "data" / "caches" / "sec_13f" / "PIT"
REGIME_PATH = ROOT / "artifacts" / "regime_shadow" / "history_summary.csv"
OUT_DIR = ROOT / "artifacts" / "manager_edge_study"

# Quarterly cache dates to use (filing-availability-based study)
QUARTERLY_DATES = [
    "2020-06-30",
    "2020-09-30",
    "2020-12-31",
    "2021-03-31",
    "2021-06-30",
    "2021-09-30",
    "2021-12-31",
    "2022-03-31",
    "2022-06-30",
    "2022-09-30",
    "2022-12-31",
    "2023-03-31",
    "2023-06-30",
    "2023-09-30",
    "2023-12-31",
    "2024-03-31",
    "2024-06-30",
    "2024-09-30",
    "2024-12-31",
    "2025-03-31",
    "2025-06-30",
    "2025-09-30",
    "2025-12-31",
]

PRIMARY_HORIZON = 20
HORIZONS = [20, 60]


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_price_history():
    """Load price history into {ticker: {date_str: close}}."""
    prices = defaultdict(dict)
    with open(PRICE_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                close = float(row["close"])
            except (ValueError, TypeError):
                continue
            prices[row["ticker"]][row["date"]] = close
    return dict(prices)


def load_universe_tickers():
    """Return set of current universe tickers."""
    with open(UNIVERSE_PATH) as f:
        data = json.load(f)
    return {item["ticker"] for item in data if item.get("ticker")}


def load_cusip_map():
    with open(CUSIP_MAP_PATH) as f:
        return json.load(f)


def load_manager_registry():
    with open(REGISTRY_PATH) as f:
        data = json.load(f)
    managers = {}
    for m in data.get("elite_core", []):
        managers[m["cik"]] = m
    return managers


def load_regime_data():
    """Return {date_str: regime_str}."""
    regimes = {}
    with open(REGIME_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            regimes[row["date"]] = row["simple"]
    return regimes


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------


def get_trading_dates(prices_xbi):
    """Return sorted list of all trading dates from XBI."""
    return sorted(prices_xbi.keys())


def _bisect_left(sorted_list, target):
    """Binary search for insertion point."""
    lo, hi = 0, len(sorted_list)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_list[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def find_nearest_trading_date(target, trading_dates, direction="forward"):
    """Find the nearest trading date on or after (forward) or on/before (backward)."""
    idx = _bisect_left(trading_dates, target)
    if direction == "forward":
        if idx < len(trading_dates):
            return trading_dates[idx]
        return None
    else:  # backward
        if idx < len(trading_dates) and trading_dates[idx] == target:
            return target
        if idx > 0:
            return trading_dates[idx - 1]
        return None


def compute_forward_return(ticker, start_date, horizon, prices, trading_dates, _td_index={}):
    """
    Compute forward return from start_date over horizon trading days.
    Returns float or None if data missing.
    """
    ticker_prices = prices.get(ticker)
    if not ticker_prices:
        return None

    # Build index once for fast lookup
    if not _td_index:
        for i, d in enumerate(trading_dates):
            _td_index[d] = i

    # Find start: nearest trading date on or after start_date
    start = find_nearest_trading_date(start_date, trading_dates, "forward")
    if not start or start not in ticker_prices:
        return None

    start_idx = _td_index.get(start)
    if start_idx is None:
        return None
    end_idx = start_idx + horizon
    if end_idx >= len(trading_dates):
        return None
    end_date = trading_dates[end_idx]
    end_price = ticker_prices.get(end_date)
    if end_price is None:
        return None
    start_price = ticker_prices[start]
    if start_price <= 0:
        return None
    return (end_price - start_price) / start_price


# ---------------------------------------------------------------------------
# Phase A: Build PIT panel
# ---------------------------------------------------------------------------


def build_pit_panel(managers, prices, universe_tickers, cusip_map, trading_dates):
    """
    Build list of dicts: one per (quarter, manager, ticker) holding observation.
    Each has forward returns and metadata.
    """
    panel = []
    quarter_stats = {}  # {qdate: {ticker: [manager_ciks]}}

    for qdate in QUARTERLY_DATES:
        cache_dir = PIT_CACHE_DIR / qdate
        index_path = cache_dir / "index.json"
        if not index_path.exists():
            print(f"  SKIP {qdate}: no index.json")
            continue

        with open(index_path) as f:
            index = json.load(f)

        # Build CIK -> index entry for filed_at lookup
        cik_index = {}
        for entry in index.get("managers", []):
            if entry.get("selected"):
                cik_index[entry["manager_cik"]] = entry

        quarter_ticker_managers = defaultdict(list)

        for cik, mgr_info in managers.items():
            if cik not in cik_index:
                continue
            idx_entry = cik_index[cik]
            filed_at = idx_entry.get("filed_at")
            if not filed_at:
                continue

            # Load holdings
            mgr_path = cache_dir / "managers" / f"{cik}.json"
            if not mgr_path.exists():
                continue
            with open(mgr_path) as f:
                mgr_data = json.load(f)

            holdings = mgr_data.get("holdings", [])
            universe_holdings = []
            for h in holdings:
                ticker = h.get("ticker", "").strip()
                cusip_val = h.get("cusip", "").strip()
                # Resolve blank ticker via CUSIP map
                if not ticker and cusip_val:
                    ticker = cusip_map.get(cusip_val, "")
                if not ticker:
                    continue
                ticker = ticker.upper()
                if ticker not in universe_tickers:
                    continue
                # Deduplicate (same ticker can appear with put/call variants)
                if ticker not in universe_holdings:
                    universe_holdings.append(ticker)
                quarter_ticker_managers[ticker].append(cik)

            if not universe_holdings:
                continue

            # Compute forward returns from filing date
            for ticker in universe_holdings:
                obs = {
                    "quarter": qdate,
                    "cik": cik,
                    "manager_name": mgr_info["name"],
                    "ticker": ticker,
                    "filed_at": filed_at,
                }
                for hz in HORIZONS:
                    ret = compute_forward_return(ticker, filed_at, hz, prices, trading_dates)
                    obs[f"fwd_{hz}d"] = ret
                panel.append(obs)

        quarter_stats[qdate] = dict(quarter_ticker_managers)

    return panel, quarter_stats


def compute_benchmarks(quarter_stats, prices, trading_dates, managers):
    """
    For each quarter, compute XBI and EW-all-eligible benchmark returns.
    Uses the most common filing date among elite managers as the benchmark start.
    Returns {qdate: {horizon: {"xbi": float, "ew_all": float, "filed_at": str}}}
    """
    benchmarks = {}
    for qdate in QUARTERLY_DATES:
        cache_dir = PIT_CACHE_DIR / qdate
        index_path = cache_dir / "index.json"
        if not index_path.exists():
            continue
        with open(index_path) as f:
            index = json.load(f)

        # Get representative filing date (most common among elite managers)
        filed_dates = []
        for entry in index.get("managers", []):
            if entry.get("selected") and entry.get("filed_at"):
                if entry["manager_cik"] in managers:
                    filed_dates.append(entry["filed_at"])
        if not filed_dates:
            continue
        filed_at = Counter(filed_dates).most_common(1)[0][0]

        bm = {}
        for hz in HORIZONS:
            xbi_ret = compute_forward_return("XBI", filed_at, hz, prices, trading_dates)

            # EW-all-eligible: average return of all tickers held by any manager
            tickers_in_quarter = list(quarter_stats.get(qdate, {}).keys())
            ew_rets = []
            for t in tickers_in_quarter:
                r = compute_forward_return(t, filed_at, hz, prices, trading_dates)
                if r is not None:
                    ew_rets.append(r)
            ew_all = sum(ew_rets) / len(ew_rets) if ew_rets else None

            bm[hz] = {"xbi": xbi_ret, "ew_all": ew_all, "filed_at": filed_at}
        benchmarks[qdate] = bm

    return benchmarks


# ---------------------------------------------------------------------------
# Phase B: Score each manager
# ---------------------------------------------------------------------------


def score_managers(panel, benchmarks):
    """
    Compute per-manager statistics across all horizons.
    Returns dict of {cik: stats_dict}.
    """
    by_manager = defaultdict(list)
    for obs in panel:
        by_manager[obs["cik"]].append(obs)

    results = {}
    for cik, obs_list in by_manager.items():
        name = obs_list[0]["manager_name"]
        quarters_seen = set()
        holdings_per_quarter = defaultdict(set)

        stats = {
            "cik": cik,
            "name": name,
            "n_obs": 0,
            "n_quarters": 0,
            "avg_holdings_per_q": 0,
        }

        for hz in HORIZONS:
            rets = []
            excess_xbi = []
            excess_ew = []
            year_excess = defaultdict(list)

            for obs in obs_list:
                r = obs.get(f"fwd_{hz}d")
                if r is None:
                    continue
                quarters_seen.add(obs["quarter"])
                holdings_per_quarter[obs["quarter"]].add(obs["ticker"])
                rets.append(r)

                bm = benchmarks.get(obs["quarter"], {}).get(hz, {})
                xbi_r = bm.get("xbi")
                ew_r = bm.get("ew_all")
                if xbi_r is not None:
                    excess_xbi.append(r - xbi_r)
                if ew_r is not None:
                    excess_ew.append(r - ew_r)
                    year = obs["quarter"][:4]
                    year_excess[year].append(r - ew_r)

            n = len(rets)
            stats[f"n_obs_{hz}d"] = n
            stats[f"avg_ret_{hz}d"] = _mean(rets)
            stats[f"avg_excess_xbi_{hz}d"] = _mean(excess_xbi)
            stats[f"avg_excess_ew_{hz}d"] = _mean(excess_ew)
            stats[f"hit_rate_xbi_{hz}d"] = _hit_rate(excess_xbi)
            stats[f"hit_rate_ew_{hz}d"] = _hit_rate(excess_ew)

            # T-stat for excess vs EW (simple: mean / (std / sqrt(n)))
            if len(excess_ew) >= 5:
                mean_exc = sum(excess_ew) / len(excess_ew)
                var = sum((x - mean_exc) ** 2 for x in excess_ew) / (len(excess_ew) - 1)
                std = var**0.5
                if std > 0:
                    stats[f"tstat_ew_{hz}d"] = mean_exc / (std / len(excess_ew) ** 0.5)
                else:
                    stats[f"tstat_ew_{hz}d"] = None
            else:
                stats[f"tstat_ew_{hz}d"] = None

            # Year-by-year excess vs EW
            year_summary = {}
            for yr, vals in sorted(year_excess.items()):
                year_summary[yr] = {"mean": _mean(vals), "n": len(vals)}
            stats[f"year_excess_ew_{hz}d"] = year_summary

        stats["n_obs"] = stats.get(f"n_obs_{PRIMARY_HORIZON}d", 0)
        stats["n_quarters"] = len(quarters_seen)
        if holdings_per_quarter:
            stats["avg_holdings_per_q"] = round(
                sum(len(v) for v in holdings_per_quarter.values()) / len(holdings_per_quarter), 1
            )
        results[cik] = stats

    return results


def _mean(lst):
    if not lst:
        return None
    return sum(lst) / len(lst)


def _hit_rate(lst):
    if not lst:
        return None
    return sum(1 for x in lst if x > 0) / len(lst)


# ---------------------------------------------------------------------------
# Phase C: Overlap / Redundancy
# ---------------------------------------------------------------------------


def compute_overlap(panel):
    """
    Compute pairwise Jaccard overlap and per-manager unique/crowded holdings.
    """
    # Build {(cik, quarter): set(tickers)}
    holdings_by_mq = defaultdict(set)
    for obs in panel:
        holdings_by_mq[(obs["cik"], obs["quarter"])].add(obs["ticker"])

    all_ciks = sorted(set(obs["cik"] for obs in panel))
    all_quarters = sorted(set(obs["quarter"] for obs in panel))
    cik_names = {}
    for obs in panel:
        cik_names[obs["cik"]] = obs["manager_name"]

    # Pairwise Jaccard (average across quarters where both have data)
    pairwise = {}
    for c1, c2 in combinations(all_ciks, 2):
        jaccards = []
        for q in all_quarters:
            s1 = holdings_by_mq.get((c1, q), set())
            s2 = holdings_by_mq.get((c2, q), set())
            if not s1 or not s2:
                continue
            inter = len(s1 & s2)
            union = len(s1 | s2)
            if union > 0:
                jaccards.append(inter / union)
        if jaccards:
            pairwise[(c1, c2)] = sum(jaccards) / len(jaccards)

    # Per-manager: unique (held by this manager only) and crowded (5+ holders)
    ticker_holder_counts = defaultdict(lambda: defaultdict(int))
    for (cik, q), tickers in holdings_by_mq.items():
        for t in tickers:
            ticker_holder_counts[q][t] += 1

    unique_counts = defaultdict(int)
    crowded_counts = defaultdict(int)
    total_counts = defaultdict(int)

    for (cik, q), tickers in holdings_by_mq.items():
        for t in tickers:
            total_counts[cik] += 1
            c = ticker_holder_counts[q][t]
            if c == 1:
                unique_counts[cik] += 1
            if c >= 5:
                crowded_counts[cik] += 1

    manager_overlap_stats = {}
    for cik in all_ciks:
        tot = total_counts[cik]
        manager_overlap_stats[cik] = {
            "name": cik_names.get(cik, cik),
            "unique_pct": round(unique_counts[cik] / tot * 100, 1) if tot else 0,
            "crowded_pct": round(crowded_counts[cik] / tot * 100, 1) if tot else 0,
            "total_holding_obs": tot,
        }

    return pairwise, manager_overlap_stats, cik_names


# ---------------------------------------------------------------------------
# Phase D: Model comparison
# ---------------------------------------------------------------------------


def model_comparison(panel, quarter_stats, benchmarks, manager_scores, prices, trading_dates):
    """
    Compare coinvest model variants with temporal separation:
    - First half of quarters: measure manager edge (train)
    - Second half: apply models (test)
    """
    sorted_quarters = sorted(set(obs["quarter"] for obs in panel))
    mid = len(sorted_quarters) // 2
    train_quarters = set(sorted_quarters[:mid])
    test_quarters = set(sorted_quarters[mid:])

    print(f"  Train quarters: {sorted(train_quarters)[0]} to {sorted(train_quarters)[-1]} ({len(train_quarters)})")
    print(f"  Test quarters:  {sorted(test_quarters)[0]} to {sorted(test_quarters)[-1]} ({len(test_quarters)})")

    # --- Measure manager edge on TRAIN period ---
    train_excess = defaultdict(list)
    for obs in panel:
        if obs["quarter"] not in train_quarters:
            continue
        r = obs.get(f"fwd_{PRIMARY_HORIZON}d")
        if r is None:
            continue
        bm = benchmarks.get(obs["quarter"], {}).get(PRIMARY_HORIZON, {})
        ew_r = bm.get("ew_all")
        if ew_r is not None:
            train_excess[obs["cik"]].append(r - ew_r)

    manager_train_alpha = {}
    for cik, vals in train_excess.items():
        manager_train_alpha[cik] = sum(vals) / len(vals) if vals else 0

    # Top-10 managers by train alpha
    sorted_mgrs = sorted(manager_train_alpha.items(), key=lambda x: x[1], reverse=True)
    top10_ciks = set(cik for cik, _ in sorted_mgrs[:10])
    print(f"  Top-10 train managers: {[manager_scores[c]['name'][:15] for c in top10_ciks if c in manager_scores]}")

    # --- Evaluate models on TEST period ---
    model_results = {m: [] for m in ["ew_all_mgr", "top10_only", "edge_weighted"]}
    xbi_results = []
    ew_all_results = []

    for qdate in sorted(test_quarters):
        bm = benchmarks.get(qdate, {}).get(PRIMARY_HORIZON, {})
        xbi_r = bm.get("xbi")
        ew_all_r = bm.get("ew_all")
        filed_at = bm.get("filed_at")
        if xbi_r is None or filed_at is None:
            continue
        xbi_results.append(xbi_r)
        if ew_all_r is not None:
            ew_all_results.append(ew_all_r)

        # Build per-ticker vote counts from panel observations in this quarter
        ticker_votes_all = defaultdict(int)
        ticker_votes_top10 = defaultdict(int)
        ticker_votes_weighted = defaultdict(float)

        for obs in panel:
            if obs["quarter"] != qdate:
                continue
            t = obs["ticker"]
            cik = obs["cik"]
            ticker_votes_all[t] += 1
            if cik in top10_ciks:
                ticker_votes_top10[t] += 1
            alpha = manager_train_alpha.get(cik, 0)
            ticker_votes_weighted[t] += max(alpha, 0)  # zero-floor negative alpha

        # For each model, pick top-30 by votes, compute EW return
        for model_name, votes in [
            ("ew_all_mgr", ticker_votes_all),
            ("top10_only", ticker_votes_top10),
            ("edge_weighted", ticker_votes_weighted),
        ]:
            if not votes:
                continue
            ranked = sorted(votes.items(), key=lambda x: -x[1])[:30]
            rets = []
            for t, _ in ranked:
                r = compute_forward_return(t, filed_at, PRIMARY_HORIZON, prices, trading_dates)
                if r is not None:
                    rets.append(r)
            if rets:
                model_results[model_name].append(sum(rets) / len(rets))

    # Summarize
    summary = {}
    for model_name, rets in model_results.items():
        if not rets:
            summary[model_name] = {"avg_ret_per_q": None, "n_quarters": 0}
            continue
        avg = sum(rets) / len(rets)
        xbi_avg = sum(xbi_results[: len(rets)]) / len(xbi_results[: len(rets)]) if xbi_results else 0
        ew_avg = sum(ew_all_results[: len(rets)]) / len(ew_all_results[: len(rets)]) if ew_all_results else 0
        summary[model_name] = {
            "avg_ret_per_q": round(avg * 100, 2),
            "avg_excess_xbi_per_q": round((avg - xbi_avg) * 100, 2),
            "avg_excess_ew_all_per_q": round((avg - ew_avg) * 100, 2),
            "n_quarters": len(rets),
        }

    return summary, top10_ciks, manager_train_alpha


# ---------------------------------------------------------------------------
# Regime splits
# ---------------------------------------------------------------------------


def compute_regime_splits(panel, benchmarks, regimes):
    """Compute per-manager excess in BULL vs BEAR regimes."""
    regime_dates = sorted(regimes.keys())

    def _find_regime(filing_date):
        idx = _bisect_left(regime_dates, filing_date)
        if idx < len(regime_dates) and regime_dates[idx] == filing_date:
            return regimes[filing_date]
        if idx > 0:
            return regimes[regime_dates[idx - 1]]
        return None

    splits = defaultdict(lambda: defaultdict(list))
    for obs in panel:
        r = obs.get(f"fwd_{PRIMARY_HORIZON}d")
        if r is None:
            continue
        bm = benchmarks.get(obs["quarter"], {}).get(PRIMARY_HORIZON, {})
        ew_r = bm.get("ew_all")
        if ew_r is None:
            continue
        excess = r - ew_r
        regime = _find_regime(obs["filed_at"])
        if regime:
            splits[obs["cik"]][regime].append(excess)

    result = {}
    for cik, regime_data in splits.items():
        result[cik] = {}
        for regime, vals in regime_data.items():
            result[cik][regime] = {
                "mean": sum(vals) / len(vals) if vals else None,
                "n": len(vals),
            }
    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_leaderboard(manager_scores, out_path):
    """Write JSON leaderboard sorted by primary excess."""
    key = f"avg_excess_ew_{PRIMARY_HORIZON}d"
    leaderboard = sorted(
        manager_scores.values(),
        key=lambda x: x.get(key) or -999,
        reverse=True,
    )
    # Clean for JSON serialization
    clean = []
    for s in leaderboard:
        c = {}
        for k, v in s.items():
            if isinstance(v, float):
                c[k] = round(v, 6)
            elif isinstance(v, dict):
                nested = {}
                for yk, yv in v.items():
                    if isinstance(yv, dict):
                        nested[yk] = {kk: round(vv, 6) if isinstance(vv, float) else vv for kk, vv in yv.items()}
                    else:
                        nested[yk] = yv
                c[k] = nested
            else:
                c[k] = v
        clean.append(c)

    with open(out_path, "w") as f:
        json.dump(clean, f, indent=2)
    return leaderboard


def write_summary_md(leaderboard, pairwise, mgr_overlap, model_summary, top10_ciks, cik_names, regime_splits, out_path):
    """Write human-readable summary."""
    lines = [
        "# Manager 13F Edge Study",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Quarterly caches: {QUARTERLY_DATES[0]} to {QUARTERLY_DATES[-1]}",
        f"Primary horizon: {PRIMARY_HORIZON} trading days",
        "PIT-safe: forward returns measured from filed_at date, not quarter-end.",
        "",
    ]

    # ------------------------------------------------------------------
    # Section 1: Leaderboard
    # ------------------------------------------------------------------
    lines += [
        "## Manager Leaderboard (sorted by excess vs EW-all-eligible, 20d)",
        "",
        "| Rank | Manager | Excess EW | Excess XBI | Hit%(EW) | t-stat | Obs | Qtrs | Hold/Q |",
        "|-----:|---------|----------:|-----------:|---------:|-------:|----:|-----:|-------:|",
    ]
    for i, s in enumerate(leaderboard, 1):
        exc_ew = s.get(f"avg_excess_ew_{PRIMARY_HORIZON}d")
        exc_xbi = s.get(f"avg_excess_xbi_{PRIMARY_HORIZON}d")
        hit = s.get(f"hit_rate_ew_{PRIMARY_HORIZON}d")
        tstat = s.get(f"tstat_ew_{PRIMARY_HORIZON}d")
        exc_ew_s = f"{exc_ew*100:+.2f}%" if exc_ew is not None else "N/A"
        exc_xbi_s = f"{exc_xbi*100:+.2f}%" if exc_xbi is not None else "N/A"
        hit_s = f"{hit*100:.0f}%" if hit is not None else "N/A"
        tstat_s = f"{tstat:.2f}" if tstat is not None else "N/A"
        lines.append(
            f"| {i:4d} | {s['name'][:28]:28s} | {exc_ew_s:>9s} | {exc_xbi_s:>10s} | "
            f"{hit_s:>8s} | {tstat_s:>6s} | {s.get('n_obs', 0):3d} | "
            f"{s.get('n_quarters', 0):4d} | {s.get('avg_holdings_per_q', 0):6.1f} |"
        )

    # ------------------------------------------------------------------
    # Section 2: Year-by-year for top 10
    # ------------------------------------------------------------------
    lines += ["", "## Year-by-Year Excess vs EW (20d) -- Top 10 Managers", ""]
    years = sorted(set(yr for s in leaderboard[:10] for yr in s.get(f"year_excess_ew_{PRIMARY_HORIZON}d", {}).keys()))
    if years:
        header = "| Manager | " + " | ".join(years) + " |"
        sep = "|---------|" + "|".join(["--------:"] * len(years)) + "|"
        lines.append(header)
        lines.append(sep)
        for s in leaderboard[:10]:
            yr_data = s.get(f"year_excess_ew_{PRIMARY_HORIZON}d", {})
            cells = []
            for yr in years:
                d = yr_data.get(yr)
                if d and d.get("mean") is not None:
                    cells.append(f"{d['mean']*100:+.1f}%")
                else:
                    cells.append("--")
            lines.append(f"| {s['name'][:25]:25s} | " + " | ".join(f"{c:>7s}" for c in cells) + " |")

    # ------------------------------------------------------------------
    # Section 3: Overlap matrix (top 10)
    # ------------------------------------------------------------------
    lines += ["", "## Overlap Matrix -- Top 10 Managers (avg Jaccard)", ""]
    top10_lb = leaderboard[:10]
    _ = [s["cik"] for s in top10_lb]
    short_names = [s["name"][:10] for s in top10_lb]
    header = "| Manager | " + " | ".join(short_names) + " |"
    lines.append(header)
    lines.append("|---------|" + "|".join(["------:"] * len(top10_lb)) + "|")
    for s1 in top10_lb:
        cells = []
        for s2 in top10_lb:
            if s1["cik"] == s2["cik"]:
                cells.append("  --")
            else:
                key = tuple(sorted([s1["cik"], s2["cik"]]))
                j = pairwise.get(key)
                cells.append(f"{j:.2f}" if j is not None else " N/A")
        lines.append(f"| {s1['name'][:10]:10s} | " + " | ".join(f"{c:>6s}" for c in cells) + " |")

    # ------------------------------------------------------------------
    # Section 4: Unique vs crowded
    # ------------------------------------------------------------------
    lines += ["", "## Unique vs Crowded Holdings (Top 15)", ""]
    lines.append("| Manager | Unique% | Crowded% | Total Obs |")
    lines.append("|---------|--------:|---------:|----------:|")
    for s in leaderboard[:15]:
        ov = mgr_overlap.get(s["cik"], {})
        lines.append(
            f"| {s['name'][:30]:30s} | {ov.get('unique_pct', 0):6.1f}% | "
            f"{ov.get('crowded_pct', 0):7.1f}% | {ov.get('total_holding_obs', 0):9d} |"
        )

    # ------------------------------------------------------------------
    # Section 5: Model comparison
    # ------------------------------------------------------------------
    lines += ["", "## Model Comparison (Test Period, 20d horizon)", ""]
    lines.append("| Model | Avg Ret/Q (%) | Excess XBI/Q (%) | Excess EW-all/Q (%) | Quarters |")
    lines.append("|-------|-------------:|-----------------:|--------------------:|---------:|")
    for model_name in ["ew_all_mgr", "top10_only", "edge_weighted"]:
        ms = model_summary.get(model_name, {})
        avg = ms.get("avg_ret_per_q")
        exc_xbi = ms.get("avg_excess_xbi_per_q")
        exc_ew = ms.get("avg_excess_ew_all_per_q")
        nq = ms.get("n_quarters", 0)
        avg_s = f"{avg:.2f}" if avg is not None else "N/A"
        exc_xbi_s = f"{exc_xbi:+.2f}" if exc_xbi is not None else "N/A"
        exc_ew_s = f"{exc_ew:+.2f}" if exc_ew is not None else "N/A"
        lines.append(f"| {model_name:15s} | {avg_s:>13s} | {exc_xbi_s:>16s} | {exc_ew_s:>19s} | {nq:8d} |")

    # Top-10 managers used
    lines += ["", "### Top-10 Managers (trained on first half)", ""]
    for cik in sorted(top10_ciks):
        n = cik_names.get(cik, cik)
        lines.append(f"- {n}")

    # ------------------------------------------------------------------
    # Section 6: Regime splits
    # ------------------------------------------------------------------
    if regime_splits:
        lines += ["", "## Regime Splits (20d excess vs EW-all, Top 15)", ""]
        lines.append("| Manager | BULL excess | BEAR excess | BULL n | BEAR n |")
        lines.append("|---------|------------:|------------:|-------:|-------:|")
        for s in leaderboard[:15]:
            rs = regime_splits.get(s["cik"], {})
            bull = rs.get("BULL", {})
            bear = rs.get("BEAR", {})
            bull_s = f"{bull['mean']*100:+.2f}%" if bull.get("mean") is not None else "N/A"
            bear_s = f"{bear['mean']*100:+.2f}%" if bear.get("mean") is not None else "N/A"
            lines.append(
                f"| {s['name'][:30]:30s} | {bull_s:>10s} | {bear_s:>10s} | "
                f"{bull.get('n', 0):6d} | {bear.get('n', 0):6d} |"
            )

    # ------------------------------------------------------------------
    # Section 7: 60d horizon check
    # ------------------------------------------------------------------
    # hz60_key removed (unused)
    lines += ["", "## 60-day Horizon Check (Top 10 by 20d ranking)", ""]
    lines.append("| Manager | Excess EW 20d | Excess EW 60d | t-stat 60d |")
    lines.append("|---------|-------------:|-------------:|-----------:|")
    for s in leaderboard[:10]:
        e20 = s.get(f"avg_excess_ew_{PRIMARY_HORIZON}d")
        e60 = s.get("avg_excess_ew_60d")
        t60 = s.get("tstat_ew_60d")
        e20_s = f"{e20*100:+.2f}%" if e20 is not None else "N/A"
        e60_s = f"{e60*100:+.2f}%" if e60 is not None else "N/A"
        t60_s = f"{t60:.2f}" if t60 is not None else "N/A"
        lines.append(f"| {s['name'][:30]:30s} | {e20_s:>12s} | {e60_s:>12s} | {t60_s:>10s} |")

    lines += [
        "",
        "---",
        "",
        "### Methodology Notes",
        "- **PIT-safe**: Forward returns start from `filed_at` date (SEC filing availability), not quarter-end.",
        "- **Excess vs EW-all**: Excess over equal-weight average of ALL tickers held by ANY elite manager that quarter. This is the TRUE alpha measure.",
        "- **Excess vs XBI**: Excess over SPDR S&P Biotech ETF. Includes sector beta.",
        "- **Hit rate**: % of individual holding observations that beat the EW-all benchmark.",
        "- **Model comparison**: Train/test split at temporal midpoint. Top-10 and edge-weighted models use ONLY train-period alpha to select/weight managers.",
        "- **Regime**: Joined from regime shadow history (BULL/BEAR simple classification) at filing date.",
        "",
    ]

    with open(out_path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 60)
    print("Manager 13F Edge Study")
    print("=" * 60)

    print("\n[1/7] Loading data...")
    managers = load_manager_registry()
    print(f"  {len(managers)} elite_core managers")
    prices = load_price_history()
    print(f"  {len(prices)} tickers in price history")
    universe_tickers = load_universe_tickers()
    print(f"  {len(universe_tickers)} universe tickers")
    cusip_map = load_cusip_map()
    print(f"  {len(cusip_map)} CUSIP mappings")
    regimes = load_regime_data()
    print(f"  {len(regimes)} regime dates")

    trading_dates = get_trading_dates(prices.get("XBI", {}))
    print(f"  {len(trading_dates)} XBI trading dates")

    # Clear the memoization dict for forward return index
    compute_forward_return.__defaults__  # ensure default exists
    # Reset the mutable default
    compute_forward_return.__defaults__ = (compute_forward_return.__defaults__[0].__class__(),)

    print(f"\n[2/7] Building PIT panel ({len(QUARTERLY_DATES)} quarters)...")
    panel, quarter_stats = build_pit_panel(managers, prices, universe_tickers, cusip_map, trading_dates)
    print(f"  {len(panel)} holding observations")
    n_mgrs = len(set(obs["cik"] for obs in panel))
    n_qtrs = len(set(obs["quarter"] for obs in panel))
    print(f"  {n_mgrs} managers, {n_qtrs} quarters with data")

    # Quick data quality check
    missing_20d = sum(1 for obs in panel if obs.get("fwd_20d") is None)
    missing_60d = sum(1 for obs in panel if obs.get("fwd_60d") is None)
    print(f"  Missing 20d returns: {missing_20d}/{len(panel)} ({missing_20d/len(panel)*100:.1f}%)")
    print(f"  Missing 60d returns: {missing_60d}/{len(panel)} ({missing_60d/len(panel)*100:.1f}%)")

    print("\n[3/7] Computing benchmarks...")
    benchmarks = compute_benchmarks(quarter_stats, prices, trading_dates, managers)
    for hz in HORIZONS:
        bm_rets = [b[hz]["xbi"] for b in benchmarks.values() if b.get(hz, {}).get("xbi") is not None]
        ew_rets = [b[hz]["ew_all"] for b in benchmarks.values() if b.get(hz, {}).get("ew_all") is not None]
        if bm_rets:
            print(f"  XBI avg {hz}d: {sum(bm_rets)/len(bm_rets)*100:.2f}% ({len(bm_rets)} qtrs)")
        if ew_rets:
            print(f"  EW-all avg {hz}d: {sum(ew_rets)/len(ew_rets)*100:.2f}% ({len(ew_rets)} qtrs)")

    print("\n[4/7] Scoring managers...")
    manager_scores = score_managers(panel, benchmarks)
    key = f"avg_excess_ew_{PRIMARY_HORIZON}d"
    scored = [(s["name"], s.get(key, 0) or 0, s.get(f"tstat_ew_{PRIMARY_HORIZON}d")) for s in manager_scores.values()]
    scored.sort(key=lambda x: x[1], reverse=True)
    print(f"  Top 5 by excess vs EW ({PRIMARY_HORIZON}d):")
    for name, exc, tstat in scored[:5]:
        ts = f"t={tstat:.2f}" if tstat is not None else "t=N/A"
        print(f"    {name:35s}  {exc*100:+.2f}%  ({ts})")
    print("  Bottom 3:")
    for name, exc, tstat in scored[-3:]:
        ts = f"t={tstat:.2f}" if tstat is not None else "t=N/A"
        print(f"    {name:35s}  {exc*100:+.2f}%  ({ts})")

    print("\n[5/7] Computing overlap/redundancy...")
    pairwise, mgr_overlap, cik_names = compute_overlap(panel)
    print(f"  {len(pairwise)} manager pairs measured")
    if pairwise:
        sorted_pairs = sorted(pairwise.items(), key=lambda x: x[1], reverse=True)
        print("  Most overlap:")
        for (c1, c2), j in sorted_pairs[:3]:
            print(f"    {cik_names.get(c1, c1)[:25]} <-> {cik_names.get(c2, c2)[:25]}  J={j:.3f}")
        print("  Least overlap:")
        for (c1, c2), j in sorted_pairs[-3:]:
            print(f"    {cik_names.get(c1, c1)[:25]} <-> {cik_names.get(c2, c2)[:25]}  J={j:.3f}")

    print("\n[6/7] Model comparison (temporal split)...")
    model_summary, top10_ciks, manager_train_alpha = model_comparison(
        panel, quarter_stats, benchmarks, manager_scores, prices, trading_dates
    )
    for model_name, ms in model_summary.items():
        avg = ms.get("avg_ret_per_q")
        exc_xbi = ms.get("avg_excess_xbi_per_q")
        exc_ew = ms.get("avg_excess_ew_all_per_q")
        avg_s = f"{avg:.2f}%" if avg is not None else "N/A"
        exc_xbi_s = f"{exc_xbi:+.2f}%" if exc_xbi is not None else "N/A"
        exc_ew_s = f"{exc_ew:+.2f}%" if exc_ew is not None else "N/A"
        print(
            f"  {model_name:15s}: ret={avg_s:>8s}/q  vs_XBI={exc_xbi_s:>8s}/q  vs_EW={exc_ew_s:>8s}/q  n={ms.get('n_quarters', 0)}"
        )

    print("\n[6b/7] Regime splits...")
    regime_splits = compute_regime_splits(panel, benchmarks, regimes)
    # Print aggregate regime summary
    for regime_label in ["BULL", "BEAR"]:
        all_exc = []
        for cik, rd in regime_splits.items():
            if regime_label in rd and rd[regime_label].get("mean") is not None:
                all_exc.append(rd[regime_label]["mean"])
        if all_exc:
            print(
                f"  {regime_label}: avg manager excess = {sum(all_exc)/len(all_exc)*100:+.2f}% ({len(all_exc)} managers)"
            )

    print("\n[7/7] Writing output...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    leaderboard = write_leaderboard(manager_scores, OUT_DIR / "manager_leaderboard.json")

    write_summary_md(
        leaderboard,
        pairwise,
        mgr_overlap,
        model_summary,
        top10_ciks,
        cik_names,
        regime_splits,
        OUT_DIR / "study_summary.md",
    )
    print(f"  -> {OUT_DIR / 'manager_leaderboard.json'}")
    print(f"  -> {OUT_DIR / 'study_summary.md'}")

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
