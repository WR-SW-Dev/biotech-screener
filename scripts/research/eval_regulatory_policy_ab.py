#!/usr/bin/env python3
"""Regulatory Sleeve Policy A/B Evaluation.

Compares two portfolio construction policies on snapshot dates where
regulatory names are present:

  A) Baseline — flat equal-weight (no ladder, no quality tilt, no resolution)
  B) Current  — family targets + ladder + quality tilt + resolution

For each qualifying snapshot date:
  1. Load rankings.csv
  2. Enrich with regulatory data from pdufa_dates.json
  3. Run build_positions() under each policy
  4. Compute forward returns from price_history.csv
  5. Aggregate: per-bucket and per-sub-bucket metrics

Output: VERDICT.md + VERDICT.json in --out-dir.

Usage:
    python3 scripts/research/eval_regulatory_policy_ab.py \\
        --snapshot-root data/snapshots_reranked_baseline \\
        --price-csv production_data/price_history.csv \\
        --out-dir output/reg_policy_ab \\
        --horizons 63,84 \\
        --min-reg-pct 3
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date as _date
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import build_positions, load_rankings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
PDUFA_JSON = PROJECT_ROOT / "production_data" / "pdufa_dates.json"

BASELINE_POLICY = {
    "account_usd": 500_000,
    "bucket_targets": {
        "binary_91_180": 0.55,
        "binary_31_90": 0.25,
        "binary_0_30": 0.10,
        "less_binary": 0.10,
    },
    "bucket_top_k": {
        "binary_91_180": 20,
        "binary_31_90": 15,
        "binary_0_30": 10,
        "less_binary": 15,
    },
    "bucket_name_caps": {
        "binary_91_180": 3.0,
        "binary_31_90": 2.0,
        "binary_0_30": 1.0,
        "less_binary": 2.0,
    },
    "family_overrides": {},
    "family_targets": {},
    "family_filter_mode": "secondary",
    "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
    "regulatory_ladder_enabled": False,
    "regulatory_bucket_caps_pct": {},
    "regulatory_bucket_weights": {},
    "regulatory_quality_tilt_enabled": False,
    "regulatory_quality_clip_lo": 0.30,
    "regulatory_quality_clip_hi": 1.00,
    "regulatory_resolution_enabled": False,
    "rebalance_buffer_ranks": 30,
    "bucket_hysteresis_days": 7,
}

CURRENT_POLICY = {
    "account_usd": 500_000,
    "bucket_targets": {
        "binary_91_180": 0.55,
        "binary_31_90": 0.25,
        "binary_0_30": 0.10,
        "less_binary": 0.10,
    },
    "bucket_top_k": {
        "binary_91_180": 20,
        "binary_31_90": 15,
        "binary_0_30": 10,
        "less_binary": 15,
    },
    "bucket_name_caps": {
        "binary_91_180": 3.0,
        "binary_31_90": 2.0,
        "binary_0_30": 1.0,
        "less_binary": 2.0,
    },
    "family_overrides": {
        "binary_91_180": {
            "REGULATORY": {"max_k": 8, "name_cap_pct": 3.5},
            "CLINICAL": {"max_k": 12, "name_cap_pct": 3.0},
        },
        "binary_31_90": {
            "REGULATORY": {"max_k": 8, "name_cap_pct": 2.5},
            "CLINICAL": {"max_k": 7, "name_cap_pct": 2.0},
        },
    },
    "family_targets": {
        "binary_31_90": {"REGULATORY": 0.70, "CLINICAL": 0.30},
        "binary_0_30": {"REGULATORY": 0.30, "CLINICAL": 0.70},
    },
    "family_filter_mode": "secondary",
    "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
    "regulatory_ladder_enabled": True,
    "regulatory_day_buckets": [14, 45, 90, 180],
    "regulatory_bucket_caps_pct": {
        "reg_0_14": 0.35,
        "reg_15_45": 1.25,
        "reg_46_90": 1.00,
        "reg_91_180": 0.75,
    },
    "regulatory_bucket_weights": {
        "binary_0_30": {
            "reg_0_14": 0.30,
            "reg_15_45": 0.40,
            "reg_46_90": 0.20,
            "reg_91_180": 0.10,
        },
        "binary_31_90": {
            "reg_0_14": 0.05,
            "reg_15_45": 0.40,
            "reg_46_90": 0.40,
            "reg_91_180": 0.15,
        },
    },
    "regulatory_quality_tilt_enabled": True,
    "regulatory_quality_clip_lo": 0.30,
    "regulatory_quality_clip_hi": 1.00,
    "regulatory_resolution_enabled": True,
    "rebalance_buffer_ranks": 30,
    "bucket_hysteresis_days": 7,
}


# ---------------------------------------------------------------------------
# PDUFA enrichment
# ---------------------------------------------------------------------------


def load_pdufa_manual(path: Path = PDUFA_JSON) -> List[Dict[str, str]]:
    """Load PDUFA manual entries."""
    if not path.is_file():
        return []
    with open(path) as f:
        return json.load(f)


def enrich_with_regulatory(
    rankings: List[Dict[str, str]],
    as_of_date: str,
    pdufa_entries: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], int]:
    """Enrich ranking rows with regulatory fields from PDUFA manual.

    For each ticker in rankings, if there is a PDUFA entry with
    1 <= days_to_pdufa <= 180, set:
      - has_regulatory_upcoming_180d = "1"
      - regulatory_days = str(days)
      - regulatory_event_type = "PDUFA"
      - regulatory_quality = binary_quality_score (or "0.50" default)

    Returns (enriched_rankings, n_regulatory_flagged).
    """
    try:
        ref = _date.fromisoformat(as_of_date)
    except ValueError:
        return rankings, 0

    # Build ticker → nearest PDUFA days map
    pdufa_map: Dict[str, Tuple[int, str]] = {}
    for entry in pdufa_entries:
        ticker = entry.get("ticker", "").upper()
        pdufa_date_str = entry.get("pdufa_date", "")
        if not ticker or not pdufa_date_str:
            continue
        try:
            pd = _date.fromisoformat(pdufa_date_str)
        except ValueError:
            continue
        days = (pd - ref).days
        if 1 <= days <= 180:
            if ticker not in pdufa_map or days < pdufa_map[ticker][0]:
                pdufa_map[ticker] = (days, entry.get("submission_type", "NDA"))

    n_flagged = 0
    for row in rankings:
        ticker = row.get("ticker", "").upper()
        if ticker in pdufa_map:
            days, sub_type = pdufa_map[ticker]
            row["has_regulatory_upcoming_180d"] = "1"
            row["regulatory_days"] = str(days)
            row["regulatory_event_type"] = "PDUFA"
            # Use binary_quality_score if available, else 0.50
            bqs = row.get("binary_quality_score", "")
            row["regulatory_quality"] = bqs if bqs else "0.50"
            n_flagged += 1
        else:
            row.setdefault("has_regulatory_upcoming_180d", "0")
            row.setdefault("regulatory_days", "")
            row.setdefault("regulatory_event_type", "")
            row.setdefault("regulatory_quality", "0")
    return rankings, n_flagged


# ---------------------------------------------------------------------------
# Price loading + forward returns
# ---------------------------------------------------------------------------


def load_price_index(price_csv: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv → {ticker: {date: close}}."""
    index: Dict[str, Dict[str, float]] = defaultdict(dict)
    with open(price_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "")
            dt = row.get("date", "")
            close_str = row.get("close", "")
            if ticker and dt and close_str:
                try:
                    index[ticker][dt] = float(close_str)
                except ValueError:
                    pass
    return dict(index)


def _find_closest_price(ticker_prices: Dict[str, float], target_date: str, max_gap: int = 5) -> Optional[float]:
    """Find closest price to target_date within max_gap trading days."""
    try:
        ref = _date.fromisoformat(target_date)
    except ValueError:
        return None
    # Try exact, then search forward/backward
    for offset in range(max_gap + 1):
        for sign in [0, 1, -1]:
            d = (ref + timedelta(days=offset * (sign if sign else 1))).isoformat()
            if d in ticker_prices:
                return ticker_prices[d]
            if offset == 0:
                break  # Only try exact date once
    return None


def compute_portfolio_return(
    positions: List[Dict[str, Any]],
    entry_date: str,
    horizon_days: int,
    price_index: Dict[str, Dict[str, float]],
) -> Optional[float]:
    """Compute dollar-weighted portfolio return over horizon.

    Uses target_dollars as weight, entry at entry_date close,
    exit at entry_date + horizon_days close.
    """
    try:
        ref = _date.fromisoformat(entry_date)
    except ValueError:
        return None

    exit_date = (ref + timedelta(days=horizon_days)).isoformat()
    total_weight = 0.0
    weighted_return = 0.0

    for pos in positions:
        ticker = pos["ticker"]
        dollars = pos["target_dollars"]
        if dollars <= 0:
            continue
        tp = price_index.get(ticker)
        if not tp:
            continue
        entry_price = _find_closest_price(tp, entry_date)
        exit_price = _find_closest_price(tp, exit_date)
        if entry_price and exit_price and entry_price > 0:
            ret = (exit_price - entry_price) / entry_price
            weighted_return += dollars * ret
            total_weight += dollars

    if total_weight <= 0:
        return None
    return weighted_return / total_weight


def compute_xbi_return(
    entry_date: str,
    horizon_days: int,
    price_index: Dict[str, Dict[str, float]],
) -> Optional[float]:
    """Compute XBI benchmark return over horizon."""
    xbi = price_index.get("XBI")
    if not xbi:
        return None
    try:
        ref = _date.fromisoformat(entry_date)
    except ValueError:
        return None
    exit_date = (ref + timedelta(days=horizon_days)).isoformat()
    entry = _find_closest_price(xbi, entry_date)
    exit_ = _find_closest_price(xbi, exit_date)
    if entry and exit_ and entry > 0:
        return (exit_ - entry) / entry
    return None


# ---------------------------------------------------------------------------
# Concentration / turnover metrics
# ---------------------------------------------------------------------------


def max_weight_pct(positions: List[Dict[str, Any]]) -> float:
    """Max single-name weight %."""
    if not positions:
        return 0.0
    return max(p.get("weight_pct", 0.0) for p in positions)


def hhi(positions: List[Dict[str, Any]]) -> float:
    """Herfindahl-Hirschman Index from weight_pct."""
    if not positions:
        return 0.0
    return sum(p.get("weight_pct", 0.0) ** 2 for p in positions)


def reg_bucket_breakdown(
    positions: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Group positions by reg_sub_bucket, return counts and total $."""
    breakdown: Dict[str, Dict[str, Any]] = {}
    for p in positions:
        sb = p.get("reg_sub_bucket", "")
        if not sb:
            continue
        if sb not in breakdown:
            breakdown[sb] = {"count": 0, "total_dollars": 0.0, "tickers": []}
        breakdown[sb]["count"] += 1
        breakdown[sb]["total_dollars"] += p.get("target_dollars", 0.0)
        breakdown[sb]["tickers"].append(p["ticker"])
    return breakdown


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------


def run_policy_ab(
    snapshot_root: Path,
    price_csv: Path,
    out_dir: Path,
    horizons: List[int],
    min_reg_pct: float = 3.0,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    pdufa_path: Path = PDUFA_JSON,
) -> Dict[str, Any]:
    """Run A/B comparison of baseline vs current policy."""

    pdufa_entries = load_pdufa_manual(pdufa_path)
    price_index = load_price_index(price_csv)

    # Discover snapshot dates
    snap_dates = sorted(
        d.name for d in snapshot_root.iterdir() if d.is_dir() and len(d.name) == 10 and (d / "rankings.csv").is_file()
    )
    if date_from:
        snap_dates = [d for d in snap_dates if d >= date_from]
    if date_to:
        snap_dates = [d for d in snap_dates if d <= date_to]

    print(f"Found {len(snap_dates)} snapshot dates in {snapshot_root}")

    # Per-date results
    date_results: List[Dict[str, Any]] = []
    skipped = 0

    for snap_date in snap_dates:
        snap_dir = snapshot_root / snap_date
        try:
            rankings = load_rankings(snap_dir)
        except Exception:
            skipped += 1
            continue

        # Enrich with regulatory data
        rankings, n_reg = enrich_with_regulatory(rankings, snap_date, pdufa_entries)
        n_eligible = len(rankings)
        reg_pct = (n_reg / n_eligible * 100) if n_eligible > 0 else 0.0

        # Filter: skip dates below coverage threshold
        if reg_pct < min_reg_pct:
            skipped += 1
            continue

        # Run both policies
        result_a = build_positions(rankings, BASELINE_POLICY)
        result_b = build_positions(rankings, CURRENT_POLICY)

        pos_a = result_a["positions"]
        pos_b = result_b["positions"]

        # Compute forward returns for each horizon
        horizon_metrics: Dict[int, Dict[str, Any]] = {}
        for h in horizons:
            ret_a = compute_portfolio_return(pos_a, snap_date, h, price_index)
            ret_b = compute_portfolio_return(pos_b, snap_date, h, price_index)
            xbi_ret = compute_xbi_return(snap_date, h, price_index)

            delta_ret = (ret_b - ret_a) if ret_a is not None and ret_b is not None else None
            horizon_metrics[h] = {
                "return_a": ret_a,
                "return_b": ret_b,
                "delta_return": delta_ret,
                "xbi_return": xbi_ret,
                "excess_a": (ret_a - xbi_ret) if ret_a is not None and xbi_ret is not None else None,
                "excess_b": (ret_b - xbi_ret) if ret_b is not None and xbi_ret is not None else None,
            }

        date_results.append(
            {
                "date": snap_date,
                "n_eligible": n_eligible,
                "n_regulatory": n_reg,
                "reg_pct": reg_pct,
                "n_positions_a": len(pos_a),
                "n_positions_b": len(pos_b),
                "max_weight_a": max_weight_pct(pos_a),
                "max_weight_b": max_weight_pct(pos_b),
                "hhi_a": hhi(pos_a),
                "hhi_b": hhi(pos_b),
                "reg_breakdown_b": reg_bucket_breakdown(pos_b),
                "horizon_metrics": horizon_metrics,
                "resolved_b": result_b["summary"].get("resolved_regulatory", []),
            }
        )

    print(f"Evaluated {len(date_results)} dates (skipped {skipped} " f"below {min_reg_pct}% reg coverage)")

    # Aggregate
    agg = _aggregate_results(date_results, horizons)

    # Write outputs
    out_dir.mkdir(parents=True, exist_ok=True)
    verdict = _build_verdict(agg, date_results, horizons, min_reg_pct, snapshot_root)

    verdict_md = out_dir / "VERDICT.md"
    verdict_json = out_dir / "VERDICT.json"

    with open(verdict_md, "w") as f:
        f.write(verdict["markdown"])
    with open(verdict_json, "w") as f:
        json.dump(verdict["data"], f, indent=2, default=str)

    print(f"\nWrote {verdict_md}")
    print(f"Wrote {verdict_json}")
    return verdict["data"]


def _aggregate_results(date_results: List[Dict[str, Any]], horizons: List[int]) -> Dict[str, Any]:
    """Aggregate per-date results into summary statistics."""
    n = len(date_results)
    if n == 0:
        return {"n_dates": 0}

    agg: Dict[str, Any] = {"n_dates": n}

    # Per-horizon aggregation
    for h in horizons:
        returns_a = []
        returns_b = []
        excess_a = []
        excess_b = []
        for dr in date_results:
            hm = dr["horizon_metrics"].get(h, {})
            if hm.get("return_a") is not None:
                returns_a.append(hm["return_a"])
            if hm.get("return_b") is not None:
                returns_b.append(hm["return_b"])
            if hm.get("excess_a") is not None:
                excess_a.append(hm["excess_a"])
            if hm.get("excess_b") is not None:
                excess_b.append(hm["excess_b"])

        agg[f"h{h}"] = {
            "n_dates_with_returns": len(returns_a),
            "mean_return_a": _mean(returns_a),
            "mean_return_b": _mean(returns_b),
            "mean_excess_a": _mean(excess_a),
            "mean_excess_b": _mean(excess_b),
            "delta_return": _mean(returns_b) - _mean(returns_a) if returns_a and returns_b else None,
            "delta_excess": _mean(excess_b) - _mean(excess_a) if excess_a and excess_b else None,
        }

    # Concentration
    agg["mean_max_weight_a"] = _mean([d["max_weight_a"] for d in date_results])
    agg["mean_max_weight_b"] = _mean([d["max_weight_b"] for d in date_results])
    agg["mean_hhi_a"] = _mean([d["hhi_a"] for d in date_results])
    agg["mean_hhi_b"] = _mean([d["hhi_b"] for d in date_results])
    agg["mean_n_positions_a"] = _mean([d["n_positions_a"] for d in date_results])
    agg["mean_n_positions_b"] = _mean([d["n_positions_b"] for d in date_results])
    agg["mean_reg_pct"] = _mean([d["reg_pct"] for d in date_results])

    # Sub-bucket attribution (policy B only)
    sub_bucket_totals: Dict[str, List[float]] = defaultdict(list)
    for dr in date_results:
        for sb, info in dr.get("reg_breakdown_b", {}).items():
            sub_bucket_totals[sb].append(info["total_dollars"])
    agg["sub_bucket_avg_dollars"] = {sb: _mean(vals) for sb, vals in sorted(sub_bucket_totals.items())}

    return agg


def _mean(vals: List[float]) -> float:
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def _pct(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:+.2f}%"


def _build_verdict(
    agg: Dict[str, Any],
    date_results: List[Dict[str, Any]],
    horizons: List[int],
    min_reg_pct: float,
    snapshot_root: Path,
) -> Dict[str, Any]:
    """Build VERDICT markdown and structured data."""

    n = agg.get("n_dates", 0)

    lines = [
        "# Regulatory Sleeve Policy A/B Verdict",
        "",
        f"**Snapshot root**: `{snapshot_root}`",
        f"**Coverage filter**: regulatory_pct >= {min_reg_pct}%",
        f"**Dates evaluated**: {n}",
        f"**Avg regulatory coverage**: {agg.get('mean_reg_pct', 0):.1f}%",
        "",
        "## Policies",
        "",
        "| Feature | A (Baseline) | B (Current) |",
        "|---------|-------------|-------------|",
        "| Family targets | OFF | 70/30 REG/CLIN (31-90), 30/70 (0-30) |",
        "| Regulatory ladder | OFF | ON (4 sub-buckets) |",
        "| Quality tilt | OFF | ON (clip 0.30-1.00) |",
        "| Event resolution | OFF | ON (days<=0 → 0%) |",
        "| Family overrides | OFF | ON (per-bucket max_k + caps) |",
        "",
    ]

    # Return deltas
    lines.append("## Forward Returns")
    lines.append("")
    lines.append("| Horizon | Return A | Return B | Delta | Excess A | Excess B | Excess Delta |")
    lines.append("|---------|----------|----------|-------|----------|----------|-------------|")

    for h in horizons:
        hm = agg.get(f"h{h}", {})
        lines.append(
            f"| {h}d "
            f"| {_pct(hm.get('mean_return_a'))} "
            f"| {_pct(hm.get('mean_return_b'))} "
            f"| {_pct(hm.get('delta_return'))} "
            f"| {_pct(hm.get('mean_excess_a'))} "
            f"| {_pct(hm.get('mean_excess_b'))} "
            f"| {_pct(hm.get('delta_excess'))} |"
        )

    lines.append("")

    # Concentration
    lines.append("## Concentration")
    lines.append("")
    lines.append("| Metric | A (Baseline) | B (Current) |")
    lines.append("|--------|-------------|-------------|")
    lines.append(
        f"| Avg positions | {agg.get('mean_n_positions_a', 0):.1f} " f"| {agg.get('mean_n_positions_b', 0):.1f} |"
    )
    lines.append(
        f"| Max weight (avg) | {agg.get('mean_max_weight_a', 0):.2f}% " f"| {agg.get('mean_max_weight_b', 0):.2f}% |"
    )
    lines.append(f"| HHI (avg) | {agg.get('mean_hhi_a', 0):.2f} " f"| {agg.get('mean_hhi_b', 0):.2f} |")
    lines.append("")

    # Sub-bucket attribution (policy B)
    sb_dollars = agg.get("sub_bucket_avg_dollars", {})
    if sb_dollars:
        lines.append("## Regulatory Sub-Bucket Attribution (Policy B)")
        lines.append("")
        lines.append("| Sub-Bucket | Avg $ Allocated |")
        lines.append("|------------|----------------|")
        for sb, avg_d in sorted(sb_dollars.items()):
            lines.append(f"| {sb} | ${avg_d:,.0f} |")
        lines.append("")

    # Per-date detail (first 10)
    if date_results:
        lines.append("## Per-Date Detail (first 10)")
        lines.append("")
        hdr = "| Date | N Reg | Reg% | Pos A | Pos B |"
        for h in horizons:
            hdr += f" Ret A {h}d | Ret B {h}d | Delta {h}d |"
        hdr += ""
        lines.append(hdr)
        sep = "|------|-------|------|-------|-------|"
        for h in horizons:
            sep += "-----------|-----------|----------|"
        lines.append(sep)
        for dr in date_results[:10]:
            row = f"| {dr['date']} | {dr['n_regulatory']} | {dr['reg_pct']:.1f}% | {dr['n_positions_a']} | {dr['n_positions_b']} |"
            for h in horizons:
                hm = dr["horizon_metrics"].get(h, {})
                row += f" {_pct(hm.get('return_a'))} | {_pct(hm.get('return_b'))} | {_pct(hm.get('delta_return'))} |"
            lines.append(row)
        lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")

    if n == 0:
        verdict_label = "INSUFFICIENT_DATA"
        lines.append(
            f"**{verdict_label}**: No snapshot dates met the {min_reg_pct}% "
            "regulatory coverage threshold. The PDUFA manual has limited "
            "historical depth — consider enriching with event ledger data."
        )
    else:
        # Check if B outperforms A on primary horizon
        primary_h = max(horizons)
        hm = agg.get(f"h{primary_h}", {})
        delta = hm.get("delta_excess")
        if delta is not None and delta > 0.001:  # >0.1pp
            verdict_label = "POSITIVE"
            lines.append(
                f"**{verdict_label}**: Policy B outperforms A by "
                f"{_pct(delta)} excess return at {primary_h}d "
                f"across {n} dates."
            )
        elif delta is not None and delta < -0.001:
            verdict_label = "NEGATIVE"
            lines.append(
                f"**{verdict_label}**: Policy B underperforms A by "
                f"{_pct(delta)} excess return at {primary_h}d. "
                "Consider reverting to baseline policy."
            )
        else:
            verdict_label = "NEUTRAL"
            lines.append(
                f"**{verdict_label}**: No meaningful difference between policies "
                f"at {primary_h}d ({_pct(delta)} excess delta). "
                "Need more regulatory-rich dates to distinguish."
            )

    lines.append("")
    lines.append("---")
    lines.append("*Generated by eval_regulatory_policy_ab.py*")

    data = {
        "schema": "reg_policy_ab.v1",
        "verdict": verdict_label,
        "n_dates": n,
        "min_reg_pct": min_reg_pct,
        "snapshot_root": str(snapshot_root),
        "horizons": horizons,
        "aggregate": agg,
        "date_results": date_results,
    }

    return {"markdown": "\n".join(lines), "data": data}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Regulatory sleeve policy A/B")
    parser.add_argument(
        "--snapshot-root",
        type=str,
        default=str(PROJECT_ROOT / "data" / "snapshots_reranked_baseline"),
    )
    parser.add_argument(
        "--price-csv",
        type=str,
        default=str(PRICE_CSV),
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=str(PROJECT_ROOT / "output" / "reg_policy_ab"),
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default="63,84",
        help="Comma-separated forward-return horizons in days",
    )
    parser.add_argument(
        "--min-reg-pct",
        type=float,
        default=3.0,
        help="Min regulatory coverage %% to include a date",
    )
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument(
        "--pdufa-path",
        type=str,
        default=str(PDUFA_JSON),
    )
    args = parser.parse_args()

    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    run_policy_ab(
        snapshot_root=Path(args.snapshot_root),
        price_csv=Path(args.price_csv),
        out_dir=Path(args.out_dir),
        horizons=horizons,
        min_reg_pct=args.min_reg_pct,
        date_from=args.date_from,
        date_to=args.date_to,
        pdufa_path=Path(args.pdufa_path),
    )


if __name__ == "__main__":
    main()
