#!/usr/bin/env python3
"""Prospective options diagnostics analysis scaffold.

Loads options_diagnostics.csv snapshots across dated snapshot directories,
joins to price_history.csv for forward returns, and produces a summary
report.  Designed for the prospective study: weekly snapshots accumulate
over time, and this script analyses the growing dataset.

Usage:
    python scripts/research/options_prospective_analysis.py \\
        --snapshots-dir data/snapshots \\
        --price-csv production_data/price_history.csv \\
        [--horizons 5,21,63] \\
        [--min-snapshots 4] \\
        [--output-dir output/options_research]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

# Minimum snapshots to attempt statistical analysis
DEFAULT_MIN_SNAPSHOTS = 4
DEFAULT_HORIZONS = [5, 21, 63]

# Schema version for the analysis output
ANALYSIS_SCHEMA = "options_prospective_analysis.v1"


# ---------------------------------------------------------------------------
# 1. Dataset loader
# ---------------------------------------------------------------------------


def load_options_snapshots(
    snapshots_dir: Path,
    min_date: str = "",
    max_date: str = "",
) -> List[Dict[str, Any]]:
    """Load options_diagnostics.csv from all dated snapshot directories.

    Returns a flat list of row dicts, each augmented with ``snap_date``
    (the parent directory name, YYYY-MM-DD).

    Parameters
    ----------
    snapshots_dir : base directory containing dated subdirectories
    min_date, max_date : optional ISO date filters (inclusive)
    """
    import re

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    rows: List[Dict[str, Any]] = []

    if not snapshots_dir.exists():
        return rows

    dirs = sorted(d.name for d in snapshots_dir.iterdir() if d.is_dir() and date_re.match(d.name))

    for dirname in dirs:
        if min_date and dirname < min_date:
            continue
        if max_date and dirname > max_date:
            continue

        csv_path = snapshots_dir / dirname / "options_diagnostics.csv"
        if not csv_path.exists():
            continue

        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["snap_date"] = dirname
                    rows.append(row)
        except (OSError, csv.Error) as exc:
            logger.warning("Skipping %s: %s", csv_path, exc)

    return rows


def load_price_series(csv_path: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv -> {ticker: {date_str: close}}.

    Mirrors the loader in eval_forward_returns.py for consistency.
    """
    prices: Dict[str, Dict[str, float]] = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = (row.get("ticker") or "").strip().upper()
            close_str = (row.get("close") or "").strip()
            date_str = (row.get("date") or "").strip()
            if not ticker or not close_str or not date_str:
                continue
            try:
                close = float(close_str)
            except (ValueError, TypeError):
                continue
            prices.setdefault(ticker, {})[date_str] = close
    return prices


# ---------------------------------------------------------------------------
# 2. Forward return helpers
# ---------------------------------------------------------------------------


def compute_forward_return(
    prices: Dict[str, float],
    sorted_dates: List[str],
    snap_date: str,
    horizon: int,
) -> Optional[float]:
    """Simple forward return = P(t+h)/P(t) - 1.

    Uses next-trading-day anchor (PIT-safe: trade after snapshot date).
    """
    # Find first trading day on or after snap_date
    trade_date = None
    for d in sorted_dates:
        if d >= snap_date:
            trade_date = d
            break
    if trade_date is None:
        return None

    p0 = prices.get(trade_date)
    if p0 is None or p0 <= 0:
        return None

    # Find trading day at horizon
    try:
        idx = sorted_dates.index(trade_date)
    except ValueError:
        return None
    target_idx = idx + horizon
    if target_idx >= len(sorted_dates):
        return None
    end_date = sorted_dates[target_idx]

    p1 = prices.get(end_date)
    if p1 is None or p1 <= 0:
        return None
    return p1 / p0 - 1.0


def resolve_event_outcome(
    ticker_prices: Dict[str, float],
    sorted_dates: List[str],
    snap_date: str,
    catalyst_days: int,
) -> Dict[str, Any]:
    """Compute event-window returns for a ticker near a catalyst.

    Returns dict with:
        event_1d_move  — 1-day return around estimated event date
        event_5d_move  — 5-day return around estimated event date
        abs_gap        — absolute 1d move
        signed_gap     — signed 1d move (same as event_1d_move)
    """
    empty: Dict[str, Any] = {
        "event_1d_move": None,
        "event_5d_move": None,
        "abs_gap": None,
        "signed_gap": None,
    }

    if not ticker_prices or catalyst_days is None:
        return empty

    # Estimate event date from snap_date + catalyst_days
    try:
        snap = _date.fromisoformat(snap_date)
    except (ValueError, TypeError):
        return empty

    from datetime import timedelta

    event_date = snap + timedelta(days=catalyst_days)
    event_str = event_date.isoformat()

    # Find nearest trading day on or after event date
    event_td = None
    for d in sorted_dates:
        if d >= event_str:
            event_td = d
            break
    if event_td is None:
        return empty

    try:
        ev_idx = sorted_dates.index(event_td)
    except ValueError:
        return empty

    # 1-day move: close[event] / close[event-1] - 1
    if ev_idx < 1:
        return empty
    p_pre = ticker_prices.get(sorted_dates[ev_idx - 1])
    p_event = ticker_prices.get(event_td)
    if p_pre and p_pre > 0 and p_event and p_event > 0:
        move_1d = p_event / p_pre - 1.0
    else:
        move_1d = None

    # 5-day move: close[event+2] / close[event-2] - 1
    move_5d = None
    if ev_idx >= 2 and ev_idx + 2 < len(sorted_dates):
        p_pre5 = ticker_prices.get(sorted_dates[ev_idx - 2])
        p_post5 = ticker_prices.get(sorted_dates[ev_idx + 2])
        if p_pre5 and p_pre5 > 0 and p_post5 and p_post5 > 0:
            move_5d = p_post5 / p_pre5 - 1.0

    return {
        "event_1d_move": move_1d,
        "event_5d_move": move_5d,
        "abs_gap": abs(move_1d) if move_1d is not None else None,
        "signed_gap": move_1d,
    }


# ---------------------------------------------------------------------------
# 3. Analysis dataset builder
# ---------------------------------------------------------------------------


def build_analysis_dataset(
    opt_rows: List[Dict[str, Any]],
    prices: Dict[str, Dict[str, float]],
    horizons: List[int],
) -> List[Dict[str, Any]]:
    """Join snapshot rows to price data, computing forward returns.

    Each output row has the original options columns plus:
        fwd_ret_{h}d  — forward return at each horizon h
        event_1d_move, event_5d_move, abs_gap, signed_gap  — if catalyst_days present
    """
    # Build sorted dates from all prices
    all_dates_set: set = set()
    for td in prices.values():
        all_dates_set.update(td.keys())
    sorted_dates = sorted(all_dates_set)

    result: List[Dict[str, Any]] = []

    for row in opt_rows:
        ticker = (row.get("ticker") or "").upper()
        snap_date = row.get("snap_date", "")
        if not ticker or not snap_date:
            continue

        ticker_prices = prices.get(ticker, {})
        out = dict(row)

        # Forward returns
        for h in horizons:
            ret = compute_forward_return(ticker_prices, sorted_dates, snap_date, h)
            out[f"fwd_ret_{h}d"] = ret

        # Event outcome (if catalyst_days available)
        cat_days_str = row.get("catalyst_days", "")
        try:
            cat_days = int(float(cat_days_str))
        except (ValueError, TypeError):
            cat_days = None

        if cat_days is not None and cat_days >= 0:
            event = resolve_event_outcome(ticker_prices, sorted_dates, snap_date, cat_days)
            out.update(event)
        else:
            out.update(
                {
                    "event_1d_move": None,
                    "event_5d_move": None,
                    "abs_gap": None,
                    "signed_gap": None,
                }
            )

        result.append(out)

    return result


# ---------------------------------------------------------------------------
# 4. Report generator
# ---------------------------------------------------------------------------


def generate_report(
    dataset: List[Dict[str, Any]],
    horizons: List[int],
    min_snapshots: int,
) -> Dict[str, Any]:
    """Generate an analysis report from the enriched dataset.

    Returns a structured dict suitable for JSON serialization.
    Handles "insufficient sample" gracefully.
    """
    # Count unique snap_dates
    snap_dates = sorted(set(r.get("snap_date", "") for r in dataset if r.get("snap_date")))
    n_snapshots = len(snap_dates)
    n_observations = len(dataset)

    report: Dict[str, Any] = {
        "schema": ANALYSIS_SCHEMA,
        "n_snapshots": n_snapshots,
        "n_observations": n_observations,
        "snap_dates": snap_dates,
        "status": "ok",
    }

    if n_snapshots < min_snapshots:
        report["status"] = "insufficient_sample"
        report["message"] = (
            f"Need {min_snapshots} snapshots for analysis, have {n_snapshots}. "
            f"Continue accumulating weekly snapshots."
        )
        report["summary_stats"] = {}
        report["flag_splits"] = {}
        return report

    # --- Summary statistics per horizon ---
    summary_stats: Dict[str, Any] = {}
    for h in horizons:
        col = f"fwd_ret_{h}d"
        values = [r[col] for r in dataset if r.get(col) is not None]
        if values:
            summary_stats[col] = {
                "n": len(values),
                "mean": round(_mean(values), 6),
                "median": round(_median(values), 6),
                "std": round(_std(values), 6),
                "pct_positive": round(sum(1 for v in values if v > 0) / len(values) * 100, 1),
            }
    report["summary_stats"] = summary_stats

    # --- Flag-based splits ---
    flag_splits: Dict[str, Any] = {}
    for flag_col in ["opt_event_premium", "opt_iv_regime", "opt_use_for_judgment"]:
        splits: Dict[str, Any] = {}
        groups: Dict[str, List[Dict]] = {}
        for r in dataset:
            val = r.get(flag_col, "")
            groups.setdefault(val, []).append(r)

        for val, group in sorted(groups.items()):
            group_stats: Dict[str, Any] = {"n": len(group)}
            for h in horizons:
                col = f"fwd_ret_{h}d"
                values = [r[col] for r in group if r.get(col) is not None]
                if values:
                    group_stats[col] = {
                        "n": len(values),
                        "mean": round(_mean(values), 6),
                        "median": round(_median(values), 6),
                    }
            splits[val] = group_stats
        flag_splits[flag_col] = splits
    report["flag_splits"] = flag_splits

    # --- Event outcome analysis (backwardation vs non) ---
    event_analysis: Dict[str, Any] = {}
    backwardation = [r for r in dataset if r.get("opt_event_premium") == "YES"]
    non_backwardation = [r for r in dataset if r.get("opt_event_premium") == "NO" and r.get("opt_has_data") == "1"]

    for label, group in [("backwardation", backwardation), ("non_backwardation", non_backwardation)]:
        moves = [r["abs_gap"] for r in group if r.get("abs_gap") is not None]
        signed = [r["signed_gap"] for r in group if r.get("signed_gap") is not None]
        event_analysis[label] = {
            "n_total": len(group),
            "n_with_event_outcome": len(moves),
        }
        if moves:
            event_analysis[label].update(
                {
                    "mean_abs_gap": round(_mean(moves), 6),
                    "mean_signed_gap": round(_mean(signed), 6) if signed else None,
                    "median_abs_gap": round(_median(moves), 6),
                }
            )
    report["event_analysis"] = event_analysis

    return report


def format_report_md(report: Dict[str, Any]) -> str:
    """Render analysis report as markdown."""
    lines = [
        "# Options Diagnostics — Prospective Analysis",
        "",
        f"**Snapshots**: {report.get('n_snapshots', 0)}  ",
        f"**Observations**: {report.get('n_observations', 0)}  ",
        f"**Status**: {report.get('status', '?')}",
        "",
    ]

    if report.get("status") == "insufficient_sample":
        lines.append(f"> {report.get('message', '')}")
        lines.append("")
        return "\n".join(lines) + "\n"

    # Summary stats
    stats = report.get("summary_stats", {})
    if stats:
        lines.append("## Forward Returns")
        lines.append("")
        lines.append("| Horizon | N | Mean | Median | Std | % Positive |")
        lines.append("|---------|---|------|--------|-----|------------|")
        for col, s in stats.items():
            lines.append(
                f"| {col} | {s['n']} | {s['mean']:.4f} | {s['median']:.4f} "
                f"| {s['std']:.4f} | {s['pct_positive']}% |"
            )
        lines.append("")

    # Flag splits
    flag_splits = report.get("flag_splits", {})
    for flag_name, splits in flag_splits.items():
        lines.append(f"## Split: {flag_name}")
        lines.append("")
        header = "| Value | N |"
        sep = "|-------|---|"
        for col in stats:
            header += f" {col} mean |"
            sep += "------|"
        lines.append(header)
        lines.append(sep)
        for val, gs in splits.items():
            row_str = f"| {val} | {gs['n']} |"
            for col in stats:
                if col in gs:
                    row_str += f" {gs[col]['mean']:.4f} |"
                else:
                    row_str += " — |"
            lines.append(row_str)
        lines.append("")

    # Event analysis
    ea = report.get("event_analysis", {})
    if ea:
        lines.append("## Event Outcome Analysis")
        lines.append("")
        lines.append("| Group | N | N w/ outcome | Mean |abs gap| | Mean signed |")
        lines.append("|-------|---|-------------|----------------|------------|")
        for label, data in ea.items():
            n = data.get("n_total", 0)
            n_out = data.get("n_with_event_outcome", 0)
            mag = data.get("mean_abs_gap", "—")
            sig = data.get("mean_signed_gap", "—")
            if isinstance(mag, float):
                mag = f"{mag:.4f}"
            if isinstance(sig, float):
                sig = f"{sig:.4f}"
            lines.append(f"| {label} | {n} | {n_out} | {mag} | {sig} |")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Stat helpers (no numpy/scipy dependency)
# ---------------------------------------------------------------------------


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: List[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    var = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return var**0.5


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Prospective options diagnostics analysis")
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=Path("data/snapshots"),
        help="Base snapshot directory",
    )
    parser.add_argument(
        "--price-csv",
        type=Path,
        default=Path("production_data/price_history.csv"),
        help="Price history CSV",
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default="5,21,63",
        help="Comma-separated forward return horizons (trading days)",
    )
    parser.add_argument(
        "--min-snapshots",
        type=int,
        default=DEFAULT_MIN_SNAPSHOTS,
        help="Minimum snapshots required for statistical analysis",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: stdout)",
    )
    parser.add_argument("--min-date", type=str, default="")
    parser.add_argument("--max-date", type=str, default="")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    # Load data
    logger.info("Loading options snapshots from %s ...", args.snapshots_dir)
    opt_rows = load_options_snapshots(args.snapshots_dir, args.min_date, args.max_date)
    logger.info("Loaded %d rows across snapshots", len(opt_rows))

    if not opt_rows:
        logger.info("No options snapshot data found. Nothing to analyse.")
        return

    logger.info("Loading price history from %s ...", args.price_csv)
    prices = load_price_series(args.price_csv)
    logger.info("Loaded prices for %d tickers", len(prices))

    # Build dataset
    dataset = build_analysis_dataset(opt_rows, prices, horizons)
    logger.info("Analysis dataset: %d rows", len(dataset))

    # Generate report
    report = generate_report(dataset, horizons, args.min_snapshots)

    # Output
    report_json = json.dumps(report, indent=2, default=str)
    report_md = format_report_md(report)

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with open(args.output_dir / "options_prospective_report.json", "w") as f:
            f.write(report_json + "\n")
        with open(args.output_dir / "options_prospective_report.md", "w") as f:
            f.write(report_md)
        logger.info("Report written to %s", args.output_dir)
    else:
        print(report_md)
        print("---")
        print(report_json)


if __name__ == "__main__":
    main()
