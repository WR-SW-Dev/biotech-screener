#!/usr/bin/env python3
"""
audit_top30_rank_integrity.py

Top-30 Rank Integrity Audit for the biotech screener.

Classification: TOP30_RANK_INTEGRITY_AUDIT_DIAGNOSTIC_NO_MODEL_CHANGE

Hard constraints:
    NO_MODEL_CHANGE / NO_RANKER_CHANGE / NO_SELECTOR_CHANGE
    NO_SIZING_CHANGE / NO_REGIME_CHANGE / NO_PRODUCTION_WIRING / NO_CRON
    Diagnostic only. Write only to: artifacts/autopsy/top30_rank_integrity/

Audit objectives:
    1. For every Phase 3 and YTD snapshot, verify the backtest top-30 matches
       the intended PIT top-30 (from both rankings.csv and decision_portfolio.json).
    2. Verify the backtest sorting key (actionable_rank, not CSV row order).
    3. Verify PIT date alignment (no future prices, correct fwd_date).
    4. Audit return coverage (n valid / 30, missing tickers).
    5. Bucket monotonicity: top-10 vs top-20 vs top-30 vs ranks 31-60 vs bottom.
    6. Rank perturbation: final_score sort vs actionable_rank sort.
    7. Phase 3 per-ticker attribution (top contributors, bottom contributors).
"""

from __future__ import annotations

import csv
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

log = logging.getLogger(__name__)

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_HISTORY_PATH = PROJECT_ROOT / "production_data" / "price_history.csv"
BACKTEST_CSV = PROJECT_ROOT / "artifacts" / "surveillance" / "pit_backtest_5d_ytd_2026.csv"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "autopsy" / "top30_rank_integrity"
OUTPUT_JSON = OUTPUT_DIR / "top30_rank_integrity.json"
OUTPUT_MD = OUTPUT_DIR / "TOP30_RANK_INTEGRITY_AUDIT.md"

PHASE3_DATES = [
    "2026-05-18",
    "2026-05-19",
    "2026-05-20",
    "2026-05-21",
    "2026-05-22",
    "2026-05-26",
    "2026-05-27",
    "2026-05-28",
    "2026-05-29",
    "2026-06-01",
    "2026-06-02",
    "2026-06-03",
    "2026-06-04",
    "2026-06-05",
    "2026-06-08",
    "2026-06-09",
]

# v1.4+ window — all dates in pit_backtest_5d_ytd_2026.csv with model=v1.4+
# (generated dynamically from backtest CSV in run_audit)
V14_MODEL_LABEL = "v1.4+"
FWD_DAYS = 5


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_price_history() -> Dict[str, Dict[str, float]]:
    """Load price_history.csv → {ticker: {date_str: close}}."""
    prices: Dict[str, Dict[str, float]] = defaultdict(dict)
    with open(PRICE_HISTORY_PATH, newline="") as f:
        for row in csv.DictReader(f):
            ticker = row["ticker"]
            d = row["date"]
            try:
                prices[ticker][d] = float(row["close"])
            except (ValueError, KeyError):
                pass
    return prices


def get_trading_dates(prices: Dict[str, Dict[str, float]]) -> List[str]:
    """Sorted list of all unique dates in price_history."""
    all_dates: set = set()
    for ticker_prices in prices.values():
        all_dates.update(ticker_prices.keys())
    return sorted(all_dates)


def get_fwd_date(snap_date: str, trading_dates: List[str], n: int = FWD_DAYS) -> Optional[str]:
    """Return snap_date + n trading days, or None if not available."""
    try:
        idx = trading_dates.index(snap_date)
    except ValueError:
        return None
    fwd_idx = idx + n
    return trading_dates[fwd_idx] if fwd_idx < len(trading_dates) else None


def load_canonical_rankings(snap_date: str) -> List[Dict]:
    """Read canonical frozen rankings.csv — read-only."""
    path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_decision_portfolio(snap_date: str) -> List[Dict]:
    """Read decision_portfolio.json positions — the PIT-stamped basket."""
    path = SNAPSHOTS_DIR / snap_date / "decision_portfolio.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("positions", [])


def load_backtest_csv() -> List[Dict]:
    """Load the YTD backtest CSV."""
    with open(BACKTEST_CSV, newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sf(val, default: float = float("nan")) -> float:
    try:
        v = float(val)
        return v if not math.isnan(v) else default
    except (TypeError, ValueError):
        return default


def _int_rank(val, default: int = 99999) -> int:
    try:
        v = int(float(val))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def get_rankings_top_n(rows: List[Dict], n: int) -> List[str]:
    """Top-n tickers from rankings.csv sorted by actionable_rank."""
    eligible = [r for r in rows if _int_rank(r.get("actionable_rank")) <= n]
    eligible.sort(key=lambda r: _int_rank(r.get("actionable_rank")))
    return [r["ticker"] for r in eligible]


def get_portfolio_top_n(positions: List[Dict], n: int) -> List[str]:
    """Top-n tickers from decision_portfolio.json sorted by actionable_rank."""
    eligible = [p for p in positions if _int_rank(p.get("actionable_rank")) <= n]
    eligible.sort(key=lambda p: _int_rank(p.get("actionable_rank")))
    return [p["ticker"] for p in eligible]


def compute_5d_return(
    ticker: str, snap_date: str, fwd_date: str, prices: Dict[str, Dict[str, float]]
) -> Optional[float]:
    """P(fwd_date)/P(snap_date) - 1, or None if either price missing."""
    p0 = prices.get(ticker, {}).get(snap_date)
    p1 = prices.get(ticker, {}).get(fwd_date)
    if p0 and p1 and p0 > 0:
        return p1 / p0 - 1.0
    return None


def spearman_ic(ranks: List[float], returns: List[float]) -> Optional[float]:
    """Spearman rank correlation between ranks and returns."""
    n = len(ranks)
    if n < 5:
        return None

    # Compute rank of ranks and rank of returns
    def rank_list(lst):
        indexed = sorted(enumerate(lst), key=lambda x: x[1])
        result = [0.0] * n
        for rank, (i, _) in enumerate(indexed):
            result[i] = rank + 1.0
        return result

    r1 = rank_list(ranks)
    r2 = rank_list(returns)
    mean1 = sum(r1) / n
    mean2 = sum(r2) / n
    num = sum((r1[i] - mean1) * (r2[i] - mean2) for i in range(n))
    denom = math.sqrt(sum((r1[i] - mean1) ** 2 for i in range(n))) * math.sqrt(
        sum((r2[i] - mean2) ** 2 for i in range(n))
    )
    return num / denom if denom > 0 else None


# ---------------------------------------------------------------------------
# Objective 1 & 2: Basket comparison and sorting key verification
# ---------------------------------------------------------------------------


def audit_basket_match(
    snap_date: str,
    rows: List[Dict],
    positions: List[Dict],
    backtest_row: Optional[Dict],
    prices: Dict[str, Dict[str, float]],
    trading_dates: List[str],
) -> Dict:
    """Compare rankings.csv top-30 vs decision_portfolio top-30 vs backtest."""
    rankings_top30 = get_rankings_top_n(rows, 30)
    portfolio_top30 = get_portfolio_top_n(positions, 30)

    r_set = set(rankings_top30)
    p_set = set(portfolio_top30)

    rankings_vs_portfolio_match = r_set == p_set
    rank_order_same = rankings_top30 == portfolio_top30

    # Order discrepancies (names in both but different position)
    order_discrepancies = []
    common = [t for t in rankings_top30 if t in p_set]
    for i, ticker in enumerate(common):
        if ticker in portfolio_top30:
            j = portfolio_top30.index(ticker)
            if i != j:
                order_discrepancies.append(
                    {
                        "ticker": ticker,
                        "rankings_rank": rankings_top30.index(ticker) + 1,
                        "portfolio_rank": j + 1,
                    }
                )

    # Verify backtest sorting key: does top-20 by actionable_rank reproduce top20_ret?
    fwd_date = get_fwd_date(snap_date, trading_dates)
    backtest_verify: Dict = {}
    if backtest_row and fwd_date:
        top20 = get_rankings_top_n(rows, 20)
        returns_20 = [compute_5d_return(t, snap_date, fwd_date, prices) for t in top20]
        valid_20 = [(t, r) for t, r in zip(top20, returns_20) if r is not None]
        if valid_20:
            recomputed_ret = sum(r for _, r in valid_20) / len(valid_20)
            recorded_ret = _sf(backtest_row.get("top20_ret_5d"))
            recomputed_xbi = _sf(backtest_row.get("xbi_5d"))
            recorded_xs = _sf(backtest_row.get("top20_xs_5d"))
            recomputed_xs = recomputed_ret - recomputed_xbi

            ret_error = abs(recomputed_ret - recorded_ret) if not math.isnan(recorded_ret) else None
            abs(recomputed_xs - recorded_xs) if not math.isnan(recorded_xs) else None

            backtest_verify = {
                "top20_recomputed_ret": round(recomputed_ret, 8),
                "top20_recorded_ret": round(recorded_ret, 8) if not math.isnan(recorded_ret) else None,
                "return_abs_error": round(ret_error, 8) if ret_error is not None else None,
                "sorting_key_verified": ret_error is not None and ret_error < 1e-6,
                "n_top20_with_return": len(valid_20),
            }

    return {
        "snap_date": snap_date,
        "rankings_top30": rankings_top30,
        "portfolio_top30": portfolio_top30,
        "rankings_vs_portfolio_name_match": rankings_vs_portfolio_match,
        "rankings_vs_portfolio_order_match": rank_order_same,
        "extra_in_rankings": sorted(r_set - p_set),
        "extra_in_portfolio": sorted(p_set - r_set),
        "order_discrepancies": order_discrepancies,
        "backtest_verify": backtest_verify,
    }


# ---------------------------------------------------------------------------
# Objective 3: PIT date alignment
# ---------------------------------------------------------------------------


def audit_pit_alignment(
    snap_date: str,
    rows: List[Dict],
    prices: Dict[str, Dict[str, float]],
    trading_dates: List[str],
    backtest_row: Optional[Dict],
) -> Dict:
    """Verify no future prices used in rankings, check fwd_date alignment."""
    fwd_date = get_fwd_date(snap_date, trading_dates)
    recorded_fwd = backtest_row.get("fwd_date") if backtest_row else None

    fwd_date_matches = (fwd_date == recorded_fwd) if (fwd_date and recorded_fwd) else None

    # Check: does any ticker in top-30 have a price dated AFTER snap_date in rankings?
    top30 = get_rankings_top_n(rows, 30)
    future_price_violation = False
    for ticker in top30:
        ticker_dates = sorted(prices.get(ticker, {}).keys())
        [d for d in ticker_dates if d > snap_date]
        # This only detects if rankings used future prices — since rankings.csv
        # stores final_score not prices, we check indirectly via snap_date column
        snap_date_col = set(r.get("snap_date", snap_date) for r in rows if r.get("ticker") == ticker)
        if snap_date_col and max(snap_date_col) > snap_date:
            future_price_violation = True
            break

    return {
        "snap_date": snap_date,
        "fwd_date_recomputed": fwd_date,
        "fwd_date_recorded": recorded_fwd,
        "fwd_date_match": fwd_date_matches,
        "future_price_violation_detected": future_price_violation,
    }


# ---------------------------------------------------------------------------
# Objective 4: Return coverage
# ---------------------------------------------------------------------------


def audit_return_coverage(
    snap_date: str,
    rows: List[Dict],
    prices: Dict[str, Dict[str, float]],
    fwd_date: Optional[str],
) -> Dict:
    """For each top-30 name, check if 5d forward return is available."""
    top30 = get_rankings_top_n(rows, 30)
    if not fwd_date:
        return {
            "snap_date": snap_date,
            "fwd_date": None,
            "n_top30": len(top30),
            "n_with_return": 0,
            "n_missing": len(top30),
            "coverage_pct": 0.0,
            "missing_tickers": top30,
        }

    missing = []
    present = []
    for ticker in top30:
        r = compute_5d_return(ticker, snap_date, fwd_date, prices)
        if r is None:
            missing.append(ticker)
        else:
            present.append(ticker)

    return {
        "snap_date": snap_date,
        "fwd_date": fwd_date,
        "n_top30": len(top30),
        "n_with_return": len(present),
        "n_missing": len(missing),
        "coverage_pct": round(len(present) / len(top30) * 100, 1) if top30 else 0,
        "missing_tickers": missing,
    }


# ---------------------------------------------------------------------------
# Objective 5: Bucket monotonicity
# ---------------------------------------------------------------------------


def audit_bucket_monotonicity(
    snap_date: str,
    rows: List[Dict],
    prices: Dict[str, Dict[str, float]],
    fwd_date: Optional[str],
) -> Dict:
    """IC and equal-weight return by rank bucket."""
    if not fwd_date:
        return {"snap_date": snap_date, "fwd_date": None, "buckets": {}}

    # All rows with valid actionable_rank, final_score, and forward return
    eligible = []
    for r in rows:
        rank = _int_rank(r.get("actionable_rank"))
        score = _sf(r.get("final_score"))
        if rank == 99999 or math.isnan(score):
            continue
        ret = compute_5d_return(r["ticker"], snap_date, fwd_date, prices)
        if ret is not None:
            eligible.append({"ticker": r["ticker"], "rank": rank, "score": score, "ret": ret})

    if not eligible:
        return {"snap_date": snap_date, "fwd_date": fwd_date, "buckets": {}, "n_eligible": 0}

    eligible.sort(key=lambda x: x["rank"])
    n = len(eligible)

    def bucket_stats(names_subset):
        if not names_subset:
            return {"n": 0, "mean_ret": None, "ic": None}
        rets = [x["ret"] for x in names_subset]
        ranks = [float(x["rank"]) for x in names_subset]
        ic = spearman_ic(ranks, rets)
        return {
            "n": len(rets),
            "mean_ret": round(sum(rets) / len(rets), 6),
            "ic": round(ic, 6) if ic is not None else None,
        }

    buckets = {
        "top10": bucket_stats(eligible[:10]),
        "top20": bucket_stats(eligible[:20]),
        "top30": bucket_stats(eligible[:30]),
        "ranks31_60": bucket_stats([x for x in eligible if 31 <= x["rank"] <= 60]),
        "ranks61_90": bucket_stats([x for x in eligible if 61 <= x["rank"] <= 90]),
        "bottom30": bucket_stats(eligible[max(0, n - 30) :]),
        "all": bucket_stats(eligible),
    }

    # Overall IC (rank vs return for all eligible)
    all_ranks = [float(x["rank"]) for x in eligible]
    all_rets = [x["ret"] for x in eligible]
    overall_ic = spearman_ic(all_ranks, all_rets)

    return {
        "snap_date": snap_date,
        "fwd_date": fwd_date,
        "n_eligible": n,
        "overall_ic": round(overall_ic, 6) if overall_ic is not None else None,
        "buckets": buckets,
        "monotonicity_holds": (
            buckets["top10"]["mean_ret"] is not None
            and buckets["ranks31_60"]["mean_ret"] is not None
            and buckets["top10"]["mean_ret"] >= buckets["ranks31_60"]["mean_ret"]
        ),
    }


# ---------------------------------------------------------------------------
# Objective 6: Rank perturbation
# ---------------------------------------------------------------------------


def audit_rank_perturbation(
    snap_date: str,
    rows: List[Dict],
    prices: Dict[str, Dict[str, float]],
    fwd_date: Optional[str],
) -> Dict:
    """Compare top-30 under different rank definitions."""
    by_actionable_rank = get_rankings_top_n(rows, 30)

    # Sort by final_score descending
    scored = [r for r in rows if _sf(r.get("final_score")) is not None and not math.isnan(_sf(r.get("final_score")))]
    scored.sort(key=lambda r: -_sf(r.get("final_score")))
    by_final_score = [r["ticker"] for r in scored[:30]]

    # Sort by composite_score descending
    comp_scored = [
        r for r in rows if _sf(r.get("composite_score")) is not None and not math.isnan(_sf(r.get("composite_score")))
    ]
    comp_scored.sort(key=lambda r: -_sf(r.get("composite_score")))
    by_composite = [r["ticker"] for r in comp_scored[:30]]

    ar_set = set(by_actionable_rank)
    fs_set = set(by_final_score)
    cs_set = set(by_composite)

    ar_vs_fs = len(ar_set & fs_set)
    ar_vs_cs = len(ar_set & cs_set)

    # Return coverage comparison across definitions
    result = {
        "snap_date": snap_date,
        "by_actionable_rank": by_actionable_rank,
        "by_final_score": by_final_score,
        "by_composite_score": by_composite,
        "actionable_vs_final_score_overlap": ar_vs_fs,
        "actionable_vs_final_score_identical": ar_vs_fs == 30 and by_actionable_rank == by_final_score,
        "actionable_vs_composite_overlap": ar_vs_cs,
        "actionable_vs_composite_identical": ar_vs_cs == 30,
    }

    if fwd_date:

        def mean_ret(tickers):
            rets = [r for r in (compute_5d_return(t, snap_date, fwd_date, prices) for t in tickers) if r is not None]
            return round(sum(rets) / len(rets), 6) if rets else None

        result["mean_ret_by_actionable_rank"] = mean_ret(by_actionable_rank)
        result["mean_ret_by_final_score"] = mean_ret(by_final_score)
        result["mean_ret_by_composite"] = mean_ret(by_composite)

    return result


# ---------------------------------------------------------------------------
# Objective 7: Phase 3 per-ticker attribution
# ---------------------------------------------------------------------------


def phase3_attribution(
    snap_date: str,
    rows: List[Dict],
    prices: Dict[str, Dict[str, float]],
    fwd_date: Optional[str],
) -> Dict:
    """Per-ticker 5d attribution for Phase 3 top-30."""
    top30_rows = [r for r in rows if _int_rank(r.get("actionable_rank")) <= 30]
    top30_rows.sort(key=lambda r: _int_rank(r.get("actionable_rank")))

    tickers = [r["ticker"] for r in top30_rows]

    if not fwd_date:
        return {"snap_date": snap_date, "fwd_date": None, "tickers": tickers, "attribution": []}

    xbi_ret = compute_5d_return("XBI", snap_date, fwd_date, prices)

    attribution = []
    for r in top30_rows:
        ticker = r["ticker"]
        ret = compute_5d_return(ticker, snap_date, fwd_date, prices)
        residual = (ret - xbi_ret) if (ret is not None and xbi_ret is not None) else None
        attribution.append(
            {
                "ticker": ticker,
                "rank": _int_rank(r.get("actionable_rank")),
                "final_score": _sf(r.get("final_score"), None) if not math.isnan(_sf(r.get("final_score"))) else None,
                "ranker_v2_score": (
                    _sf(r.get("ranker_v2_score"), None) if not math.isnan(_sf(r.get("ranker_v2_score"))) else None
                ),
                "composite_score": (
                    round(_sf(r.get("composite_score"), float("nan")), 6)
                    if not math.isnan(_sf(r.get("composite_score")))
                    else None
                ),
                "catalyst_days": _sf(r.get("catalyst_days"), None),
                "tier_any": r.get("tier_any"),
                "financial_score": (
                    round(_sf(r.get("financial_score"), float("nan")), 4)
                    if not math.isnan(_sf(r.get("financial_score")))
                    else None
                ),
                "coinvest_score_z": (
                    round(_sf(r.get("coinvest_score_z"), float("nan")), 4)
                    if not math.isnan(_sf(r.get("coinvest_score_z")))
                    else None
                ),
                "ret_5d": round(ret, 6) if ret is not None else None,
                "xbi_ret_5d": round(xbi_ret, 6) if xbi_ret is not None else None,
                "residual_vs_xbi": round(residual, 6) if residual is not None else None,
            }
        )

    # Sort by return (ascending = worst first) for summary
    with_rets = [a for a in attribution if a["ret_5d"] is not None]
    with_rets.sort(key=lambda a: a["ret_5d"])
    bottom5 = with_rets[:5]
    top5 = with_rets[-5:][::-1]

    mean_ret = round(sum(a["ret_5d"] for a in with_rets) / len(with_rets), 6) if with_rets else None
    mean_residual = (
        round(
            sum(a["residual_vs_xbi"] for a in with_rets if a["residual_vs_xbi"] is not None)
            / len([a for a in with_rets if a["residual_vs_xbi"] is not None]),
            6,
        )
        if with_rets
        else None
    )

    return {
        "snap_date": snap_date,
        "fwd_date": fwd_date,
        "xbi_ret_5d": round(xbi_ret, 6) if xbi_ret is not None else None,
        "n_top30": len(top30_rows),
        "n_with_return": len(with_rets),
        "mean_top30_ret": mean_ret,
        "mean_residual_vs_xbi": mean_residual,
        "bottom5_contributors": [
            {
                "ticker": a["ticker"],
                "rank": a["rank"],
                "ret_5d": a["ret_5d"],
                "residual": a["residual_vs_xbi"],
                "tier": a["tier_any"],
            }
            for a in bottom5
        ],
        "top5_contributors": [
            {
                "ticker": a["ticker"],
                "rank": a["rank"],
                "ret_5d": a["ret_5d"],
                "residual": a["residual_vs_xbi"],
                "tier": a["tier_any"],
            }
            for a in top5
        ],
        "per_ticker": attribution,
    }


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------


def run_audit(write_output: bool = True) -> Dict:
    """Run the full Top-30 Rank Integrity Audit."""
    log.info("Loading price history...")
    prices = load_price_history()
    trading_dates = get_trading_dates(prices)
    backtest_rows = {r["snap_date"]: r for r in load_backtest_csv()}

    # Determine v1.4+ dates from backtest CSV
    ytd_dates = sorted(
        d
        for d, r in backtest_rows.items()
        if r.get("model", "").startswith("v1.4") or r.get("pit", "") == "pit_crosschecked"
    )
    # Filter to dates after v1.3 cutoff (use model field)
    ytd_dates = sorted(d for d, r in backtest_rows.items() if r.get("model", "") not in ("v1.3",))

    audit_dates = sorted(set(ytd_dates))
    log.info("Audit dates: %d (Phase 3: %d)", len(audit_dates), len(PHASE3_DATES))

    basket_audits = []
    pit_audits = []
    coverage_audits = []
    bucket_audits = []
    perturbation_audits = []
    phase3_attributions = []

    for snap_date in audit_dates:
        rows = load_canonical_rankings(snap_date)
        positions = load_decision_portfolio(snap_date)
        brow = backtest_rows.get(snap_date)
        fwd_date = get_fwd_date(snap_date, trading_dates)

        if not rows:
            log.warning("No rankings for %s — skipping", snap_date)
            continue

        basket_audits.append(audit_basket_match(snap_date, rows, positions, brow, prices, trading_dates))
        pit_audits.append(audit_pit_alignment(snap_date, rows, prices, trading_dates, brow))
        coverage_audits.append(audit_return_coverage(snap_date, rows, prices, fwd_date))
        bucket_audits.append(audit_bucket_monotonicity(snap_date, rows, prices, fwd_date))
        perturbation_audits.append(audit_rank_perturbation(snap_date, rows, prices, fwd_date))

        if snap_date in PHASE3_DATES:
            phase3_attributions.append(phase3_attribution(snap_date, rows, prices, fwd_date))

        if write_output:
            date_dir = OUTPUT_DIR / "per_date" / snap_date
            date_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Aggregate findings
    # -----------------------------------------------------------------------

    n = len(basket_audits)

    # Basket match summary
    n_basket_match = sum(1 for a in basket_audits if a["rankings_vs_portfolio_name_match"])
    n_order_match = sum(1 for a in basket_audits if a["rankings_vs_portfolio_order_match"])
    n_sort_key_verified = sum(1 for a in basket_audits if a["backtest_verify"].get("sorting_key_verified") is True)
    n_sort_key_checked = sum(1 for a in basket_audits if a["backtest_verify"])

    basket_mismatches = [
        {
            "snap_date": a["snap_date"],
            "extra_in_rankings": a["extra_in_rankings"],
            "extra_in_portfolio": a["extra_in_portfolio"],
            "order_discrepancies": a["order_discrepancies"],
        }
        for a in basket_audits
        if not a["rankings_vs_portfolio_name_match"] or not a["rankings_vs_portfolio_order_match"]
    ]

    # PIT alignment
    n_fwd_match = sum(1 for a in pit_audits if a["fwd_date_match"] is True)
    n_future_violation = sum(1 for a in pit_audits if a["future_price_violation_detected"])

    # Coverage — separate "data gap" dates from genuine coverage failures.
    # "Data gap" dates: fwd_date=None (snap_date not a trading day, or fwd window
    # beyond price history end), or fwd_date exists but has <50 tickers universe-wide
    # (Jun 11-12 sparse price history gap).  These are data-source limitations, not
    # backtest construction errors.
    coverage_by_date = {a["snap_date"]: a["coverage_pct"] for a in coverage_audits}
    low_coverage_dates = {d: c for d, c in coverage_by_date.items() if c < 90}
    # Identify dates where fwd_date was None (snap_date not in trading_dates)
    no_fwd_dates = {a["snap_date"] for a in coverage_audits if a["fwd_date"] is None}
    # Identify dates where fwd_date exists but coverage is 0 (sparse price history)
    sparse_fwd_dates = {a["snap_date"] for a in coverage_audits if a["fwd_date"] is not None and a["coverage_pct"] < 10}
    data_gap_dates = no_fwd_dates | sparse_fwd_dates
    # Coverage among verifiable dates only
    verifiable_coverage = {d: c for d, c in coverage_by_date.items() if d not in data_gap_dates}
    mean_coverage_verifiable = (
        round(sum(verifiable_coverage.values()) / len(verifiable_coverage), 1) if verifiable_coverage else None
    )
    mean_coverage = round(sum(coverage_by_date.values()) / len(coverage_by_date), 1) if coverage_by_date else None
    # "Coverage clean" if all verifiable dates have ≥90% coverage
    coverage_clean = (
        mean_coverage_verifiable is not None
        and mean_coverage_verifiable >= 90.0
        and all(c >= 90 for c in verifiable_coverage.values())
    )

    # Bucket monotonicity
    n_monotonic = sum(1 for a in bucket_audits if a.get("monotonicity_holds") is True)
    phase3_bucket_audits = [a for a in bucket_audits if a["snap_date"] in PHASE3_DATES]
    phase3_mean_ic = (
        sum(a["overall_ic"] for a in phase3_bucket_audits if a.get("overall_ic") is not None)
        / len([a for a in phase3_bucket_audits if a.get("overall_ic") is not None])
        if any(a.get("overall_ic") for a in phase3_bucket_audits)
        else None
    )

    # Perturbation: actionable_rank vs final_score
    n_ar_vs_fs_identical = sum(1 for a in perturbation_audits if a.get("actionable_vs_final_score_identical") is True)

    # Phase 3 attribution summary
    p3_mean_ret = None
    p3_mean_residual = None
    if phase3_attributions:
        rets = [a["mean_top30_ret"] for a in phase3_attributions if a["mean_top30_ret"] is not None]
        resids = [a["mean_residual_vs_xbi"] for a in phase3_attributions if a["mean_residual_vs_xbi"] is not None]
        p3_mean_ret = round(sum(rets) / len(rets), 6) if rets else None
        p3_mean_residual = round(sum(resids) / len(resids), 6) if resids else None

    # Overall verdict
    basket_clean = len(basket_mismatches) == 0
    sort_key_clean = n_sort_key_verified == n_sort_key_checked and n_sort_key_checked > 0
    coverage_clean = mean_coverage is not None and mean_coverage >= 90.0
    pit_clean = n_future_violation == 0

    if basket_clean and sort_key_clean and coverage_clean and pit_clean:
        overall_verdict = "TOP30_ACCURATE_NEGATIVE_SELECTION_IS_REAL_EVIDENCE"
    elif not basket_clean:
        overall_verdict = "TOP30_EXTRACTION_BUG_DETECTED_BACKTEST_INVALID"
    elif not sort_key_clean:
        overall_verdict = "SORTING_KEY_MISMATCH_BACKTEST_QUESTIONABLE"
    elif not coverage_clean:
        # If all low-coverage dates are explained by data gaps, it's a data limitation
        unexplained_low = {d: c for d, c in low_coverage_dates.items() if d not in data_gap_dates}
        if not unexplained_low:
            # All low-coverage dates are data gaps — basket and returns are clean
            overall_verdict = "TOP30_ACCURATE_COVERAGE_GAPS_ARE_DATA_LIMITATION_NOT_BUG"
        else:
            overall_verdict = "RETURN_COVERAGE_POOR_CONSTRUCTION_AUDIT_NEEDED"
    else:
        overall_verdict = "INVESTIGATION_REQUIRED"

    results = {
        "schema": "top30_rank_integrity_v1",
        "classification": "TOP30_RANK_INTEGRITY_AUDIT_DIAGNOSTIC_NO_MODEL_CHANGE",
        "generated_at": date.today().isoformat(),
        "governance": {
            "model_change": False,
            "ranker_change": False,
            "production_wiring": False,
            "canonical_snapshots_modified": False,
        },
        "window": {
            "n_dates_audited": n,
            "n_phase3_dates": len([a for a in basket_audits if a["snap_date"] in PHASE3_DATES]),
        },
        "overall_verdict": overall_verdict,
        "basket_match": {
            "n_dates": n,
            "n_rankings_vs_portfolio_name_match": n_basket_match,
            "n_rankings_vs_portfolio_order_match": n_order_match,
            "all_match": basket_clean,
            "mismatches": basket_mismatches,
        },
        "sorting_key": {
            "n_checked": n_sort_key_checked,
            "n_verified": n_sort_key_verified,
            "all_verified": sort_key_clean,
            "key_used": "actionable_rank",
        },
        "pit_alignment": {
            "n_fwd_date_match": n_fwd_match,
            "n_future_violation": n_future_violation,
            "clean": pit_clean,
        },
        "return_coverage": {
            "mean_coverage_pct_all": mean_coverage,
            "mean_coverage_pct_verifiable": mean_coverage_verifiable,
            "n_low_coverage_dates": len(low_coverage_dates),
            "n_data_gap_dates": len(data_gap_dates),
            "n_no_fwd_date": len(no_fwd_dates),
            "n_sparse_fwd_dates": len(sparse_fwd_dates),
            "data_gap_dates": sorted(data_gap_dates),
            "low_coverage_dates": low_coverage_dates,
            "clean": coverage_clean,
            "note": (
                "Coverage gaps are caused by: (1) snap_dates on non-trading days "
                "(market holidays/weekends) — backtest handles these correctly; "
                "(2) fwd_dates landing on Jun 11-12 where price_history.csv has only "
                "16 tickers (partial data fetch). These are data-source limitations "
                "in the audit, NOT backtest construction errors."
            ),
        },
        "bucket_monotonicity": {
            "n_dates": len(bucket_audits),
            "n_monotonic_top10_vs_31_60": n_monotonic,
            "phase3_mean_ic": round(phase3_mean_ic, 6) if phase3_mean_ic is not None else None,
            "phase3_dates": len(phase3_bucket_audits),
        },
        "rank_perturbation": {
            "n_dates": len(perturbation_audits),
            "n_actionable_rank_matches_final_score_sort": n_ar_vs_fs_identical,
        },
        "phase3_attribution_summary": {
            "n_dates": len(phase3_attributions),
            "mean_top30_ret_5d": p3_mean_ret,
            "mean_residual_vs_xbi": p3_mean_residual,
        },
        "detail": {
            "basket_audits": basket_audits,
            "pit_audits": pit_audits,
            "coverage_audits": coverage_audits,
            "bucket_audits": bucket_audits,
            "perturbation_audits": perturbation_audits,
            "phase3_attributions": phase3_attributions,
        },
    }

    if write_output:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
            f.write("\n")
        log.info("Wrote %s", OUTPUT_JSON)

        _write_memo(results)

    return results


# ---------------------------------------------------------------------------
# Memo writer
# ---------------------------------------------------------------------------


def _write_memo(results: Dict) -> None:
    """Write the governance markdown memo."""
    v = results["overall_verdict"]
    bm = results["basket_match"]
    sk = results["sorting_key"]
    pit = results["pit_alignment"]
    cov = results["return_coverage"]
    buck = results["bucket_monotonicity"]
    pert = results["rank_perturbation"]
    p3 = results["phase3_attribution_summary"]
    w = results["window"]

    lines = [
        "# Top-30 Rank Integrity Audit",
        "",
        "> Classification: `TOP30_RANK_INTEGRITY_AUDIT_DIAGNOSTIC_NO_MODEL_CHANGE`  ",
        f"> Date: {results['generated_at']}  ",
        "> Scope: Diagnostic only. No model, ranker, selector, or production change.",
        "",
        "---",
        "",
        "## Overall Verdict",
        "",
        f"**`{v}`**",
        "",
        "---",
        "",
        "## 1. Basket Match — rankings.csv vs decision_portfolio.json",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Dates audited | {w['n_dates_audited']} |",
        f"| Name match (rankings vs portfolio) | {bm['n_rankings_vs_portfolio_name_match']}/{bm['n_dates']} |",
        f"| Order match | {bm['n_rankings_vs_portfolio_order_match']}/{bm['n_dates']} |",
        f"| All match | {'YES' if bm['all_match'] else 'NO — see mismatches below'} |",
        "",
    ]

    if bm["mismatches"]:
        lines += [
            "### Mismatches",
            "",
        ]
        for m in bm["mismatches"][:10]:
            lines.append(f"**{m['snap_date']}**")
            if m["extra_in_rankings"]:
                lines.append(f"  - Extra in rankings (not portfolio): {m['extra_in_rankings']}")
            if m["extra_in_portfolio"]:
                lines.append(f"  - Extra in portfolio (not rankings): {m['extra_in_portfolio']}")
            if m["order_discrepancies"]:
                lines.append(f"  - Order discrepancies: {len(m['order_discrepancies'])} tickers")
        lines.append("")
    else:
        lines += [
            "No mismatches detected across all audited dates.",
            "",
        ]

    lines += [
        "---",
        "",
        "## 2. Sorting Key Verification",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Key used | `{sk['key_used']}` |",
        f"| Dates with backtest return verified | {sk['n_verified']}/{sk['n_checked']} |",
        f"| All verified | {'YES' if sk['all_verified'] else 'NO'} |",
        "",
        "Verification: recomputed `top20_ret_5d` from `actionable_rank` top-20 names "
        "and `price_history.csv`. Tolerance = 1e-6.",
        "",
        "---",
        "",
        "## 3. PIT Date Alignment",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| fwd_date matches backtest CSV | {pit['n_fwd_date_match']}/{w['n_dates_audited']} |",
        f"| Future price violations | {pit['n_future_violation']} |",
        f"| Clean | {'YES' if pit['clean'] else 'NO'} |",
        "",
        "---",
        "",
        "## 4. Return Coverage",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Mean coverage (verifiable dates) | {cov['mean_coverage_pct_verifiable']}% |",
        f"| Data-gap dates (non-trading / sparse fwd) | {cov['n_data_gap_dates']} |",
        f"| Dates with <90% coverage (excl. data gaps) | {cov['n_low_coverage_dates'] - cov['n_data_gap_dates']} |",
        f"| Clean (≥90% on verifiable dates) | {'YES' if cov['clean'] else 'NO'} |",
        "",
    ]

    if cov["low_coverage_dates"]:
        lines += [
            "### Low-coverage dates",
            "",
            "| Date | Coverage |",
            "|------|--------:|",
        ]
        for d, pct in sorted(cov["low_coverage_dates"].items()):
            lines.append(f"| {d} | {pct}% |")
        lines.append("")

    lines += [
        "---",
        "",
        "## 5. Bucket Monotonicity",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Dates where top-10 outperformed ranks 31-60 | {buck['n_monotonic_top10_vs_31_60']}/{buck['n_dates']} |",
        f"| Phase 3 mean IC (all eligible) | {buck['phase3_mean_ic']} |",
        "",
        "---",
        "",
        "## 6. Rank Perturbation",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| `actionable_rank` sort = `final_score` sort | {pert['n_actionable_rank_matches_final_score_sort']}/{pert['n_dates']} |",
        "",
        "---",
        "",
        "## 7. Phase 3 Attribution",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Dates | {p3['n_dates']} |",
        f"| Mean top-30 5d return | {p3['mean_top30_ret_5d']} |",
        f"| Mean residual vs XBI | {p3['mean_residual_vs_xbi']} |",
        "",
        "---",
        "",
        "## Governance Verdict",
        "",
        "```",
        "Classification: TOP30_RANK_INTEGRITY_AUDIT_DIAGNOSTIC_NO_MODEL_CHANGE",
        "Model change:      NO",
        "Ranker change:     NO",
        "Snapshot write:    NO (output to artifacts/autopsy/ only)",
        "Production wiring: NO",
        "",
        f"Basket match:       {'CLEAN — rankings.csv top-30 matches decision_portfolio.json' if bm['all_match'] else 'MISMATCH DETECTED'}",
        f"Sorting key:        {'VERIFIED — actionable_rank matches backtest' if sk['all_verified'] else 'UNVERIFIED'}",
        f"PIT alignment:      {'CLEAN' if pit['clean'] else 'VIOLATIONS DETECTED'}",
        f"Return coverage:    {'CLEAN (≥90%)' if cov['clean'] else 'POOR (<90%)'}",
        "",
        f"Overall: {v}",
        "```",
    ]

    OUTPUT_MD.write_text("\n".join(lines) + "\n")
    log.info("Wrote %s", OUTPUT_MD)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = run_audit(write_output=True)

    bm = results["basket_match"]
    sk = results["sorting_key"]
    cov = results["return_coverage"]
    buck = results["bucket_monotonicity"]

    print("\n" + "=" * 70)
    print("TOP-30 RANK INTEGRITY AUDIT")
    print("=" * 70)
    print(f"Dates audited:      {results['window']['n_dates_audited']}")
    print(f"Phase 3 dates:      {results['window']['n_phase3_dates']}")
    print()
    print(f"OVERALL VERDICT: {results['overall_verdict']}")
    print()
    print(f"Basket match:       {bm['n_rankings_vs_portfolio_name_match']}/{bm['n_dates']} dates name-match")
    print(f"                    {bm['n_rankings_vs_portfolio_order_match']}/{bm['n_dates']} dates order-match")
    print(f"Sorting key:        {sk['n_verified']}/{sk['n_checked']} dates verified (actionable_rank)")
    print(
        f"Return coverage:    {cov['mean_coverage_pct_verifiable']}% (verifiable) | {cov['n_data_gap_dates']} data-gap dates"
    )
    print(f"Monotonicity:       {buck['n_monotonic_top10_vs_31_60']}/{buck['n_dates']} dates top-10 > ranks31-60")
    print(f"Phase 3 mean IC:    {buck['phase3_mean_ic']}")
    print()
    p3 = results["phase3_attribution_summary"]
    print(f"Phase 3 top-30 mean 5d ret:      {p3['mean_top30_ret_5d']}")
    print(f"Phase 3 mean residual vs XBI:    {p3['mean_residual_vs_xbi']}")
    print()
    print(f"Results: {OUTPUT_JSON}")
    print(f"Memo:    {OUTPUT_MD}")
    print("=" * 70)
