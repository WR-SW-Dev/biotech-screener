#!/usr/bin/env python3
"""Build Portfolio Report — aggregate performance.csv into cumulative metrics + markdown report.

Usage:
    python3 tools/build_portfolio_report.py
    python3 tools/build_portfolio_report.py --out-dir /tmp/report
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SHADOW_ROOT = PROJECT_ROOT / "artifacts" / "live_shadow"
PERFORMANCE_CSV = SHADOW_ROOT / "performance.csv"
TRADES_ROOT = SHADOW_ROOT / "trades"

SCHEMA_VERSION = "portfolio_metrics.v1"

BUCKET_NAMES = ["binary_0_30", "binary_31_90", "binary_91_180", "less_binary"]
BUCKET_DISPLAY = {
    "binary_0_30": "Binary 0-30d",
    "binary_31_90": "Binary 31-90d",
    "binary_91_180": "Binary 91-180d",
    "less_binary": "Less Binary",
}


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def load_performance_history(perf_csv: Path) -> List[Dict[str, Any]]:
    """Read performance.csv and parse numeric fields."""
    if not perf_csv.is_file():
        return []
    with open(perf_csv, encoding="utf-8") as f:
        raw = list(csv.DictReader(f))
    rows = []
    for r in raw:
        rows.append(
            {
                "date": r.get("date", ""),
                "prior_date": r.get("prior_date", ""),
                "total_pnl": _safe_float(r.get("total_pnl")),
                "pnl_pct": _safe_float(r.get("pnl_pct")),
                "xbi_return_pct": _safe_float(r.get("xbi_return_pct")),
                "excess_vs_xbi_pct": _safe_float(r.get("excess_vs_xbi_pct")),
                "n_held": int(_safe_float(r.get("n_held"))),
                "turnover": _safe_float(r.get("turnover")),
                "gap_risk_high_count": int(_safe_float(r.get("gap_risk_high_count"))),
                "n_missing_price": int(_safe_float(r.get("n_missing_price"))),
                "sleeve_binary_0_30_pnl": _safe_float(r.get("sleeve_binary_0_30_pnl")),
                "sleeve_binary_31_90_pnl": _safe_float(r.get("sleeve_binary_31_90_pnl")),
                "sleeve_binary_91_180_pnl": _safe_float(r.get("sleeve_binary_91_180_pnl")),
                "sleeve_less_binary_pnl": _safe_float(r.get("sleeve_less_binary_pnl")),
                "ruleset_id": r.get("ruleset_id", ""),
            }
        )
    return rows


def compute_portfolio_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute cumulative analytics from performance history."""
    if not rows:
        return {
            "n_periods": 0,
            "cumulative_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "avg_turnover": 0.0,
            "best_period": None,
            "worst_period": None,
            "win_rate": 0.0,
            "total_pnl_usd": 0.0,
            "sleeve_attribution": {b: 0.0 for b in BUCKET_NAMES},
            "cumulative_excess_pct": 0.0,
        }

    # Cumulative return (compound)
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    equity_curve = []

    for r in rows:
        ret = r["pnl_pct"] / 100.0
        cum *= 1.0 + ret
        equity_curve.append(cum)
        if cum > peak:
            peak = cum
        dd = (peak - cum) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    cumulative_return_pct = round((cum - 1.0) * 100, 4)
    max_drawdown_pct = round(max_dd * 100, 4)

    # Sharpe (annualized, weekly periods → sqrt(52))
    excess_returns = [r["pnl_pct"] / 100.0 - r["xbi_return_pct"] / 100.0 for r in rows]
    n = len(excess_returns)
    if n > 1:
        mean_ex = sum(excess_returns) / n
        var_ex = sum((x - mean_ex) ** 2 for x in excess_returns) / (n - 1)
        std_ex = math.sqrt(var_ex) if var_ex > 0 else 0.0
        sharpe = (mean_ex / std_ex * math.sqrt(52)) if std_ex > 0 else 0.0
    else:
        sharpe = 0.0

    # Win rate
    wins = sum(1 for r in rows if r["pnl_pct"] > 0)
    win_rate = wins / n if n > 0 else 0.0

    # Best / worst period
    best = max(rows, key=lambda r: r["pnl_pct"])
    worst = min(rows, key=lambda r: r["pnl_pct"])

    # Turnover
    avg_turnover = sum(r["turnover"] for r in rows) / n if n > 0 else 0.0

    # Total P&L
    total_pnl = sum(r["total_pnl"] for r in rows)

    # Sleeve attribution (cumulative)
    sleeve_attr = {}
    for b in BUCKET_NAMES:
        col = f"sleeve_{b}_pnl"
        sleeve_attr[b] = round(sum(r.get(col, 0.0) for r in rows), 2)

    # Cumulative excess
    cum_excess = sum(r["excess_vs_xbi_pct"] for r in rows)

    return {
        "n_periods": n,
        "cumulative_return_pct": cumulative_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe_ratio": round(sharpe, 4),
        "avg_turnover": round(avg_turnover, 4),
        "best_period": {"date": best["date"], "pnl_pct": best["pnl_pct"]},
        "worst_period": {"date": worst["date"], "pnl_pct": worst["pnl_pct"]},
        "win_rate": round(win_rate, 4),
        "total_pnl_usd": round(total_pnl, 2),
        "sleeve_attribution": sleeve_attr,
        "cumulative_excess_pct": round(cum_excess, 4),
    }


def load_fill_quality(trades_root: Path) -> Optional[Dict[str, Any]]:
    """Scan trades/*/fills.csv and compute aggregate fill metrics."""
    if not trades_root.is_dir():
        return None

    all_fills: List[Dict[str, str]] = []
    for date_dir in sorted(trades_root.iterdir()):
        fills_path = date_dir / "fills.csv"
        if fills_path.is_file():
            with open(fills_path, encoding="utf-8") as f:
                all_fills.extend(csv.DictReader(f))

    if not all_fills:
        return None

    total = len(all_fills)
    filled = [f for f in all_fills if f.get("status") in ("FILLED", "PARTIAL")]
    fill_rate = len(filled) / total if total > 0 else 0.0

    slippages = []
    for f in filled:
        try:
            slip = float(f.get("slippage_bps", "0") or "0")
            slippages.append(slip)
        except (ValueError, TypeError):
            pass

    mean_slip = sum(slippages) / len(slippages) if slippages else 0.0
    sorted_s = sorted(slippages)
    median_slip = sorted_s[len(sorted_s) // 2] if sorted_s else 0.0

    return {
        "total_fills": total,
        "n_filled": len(filled),
        "fill_rate": round(fill_rate, 4),
        "mean_slippage_bps": round(mean_slip, 2),
        "median_slippage_bps": round(median_slip, 2),
        "n_dates": sum(1 for d in trades_root.iterdir() if (d / "fills.csv").is_file()),
    }


def write_portfolio_report(
    metrics: Dict[str, Any],
    fills: Optional[Dict[str, Any]],
    out_path: Path,
) -> Path:
    """Write portfolio_report.md."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Shadow Portfolio Report",
        "",
        f"**Generated**: {ts}",
        f"**Periods**: {metrics['n_periods']}",
        "",
    ]

    if metrics["n_periods"] == 0:
        lines.append("*Insufficient data — no performance history yet.*")
        lines.append("")
        with open(out_path, "w") as f:
            f.write("\n".join(lines))
        return out_path

    # Cumulative performance
    lines.append("## Cumulative Performance")
    lines.append("")
    lines.append(f"- **Cumulative return**: {metrics['cumulative_return_pct']:+.2f}%")
    lines.append(f"- **Total P&L**: ${metrics['total_pnl_usd']:,.2f}")
    lines.append(f"- **Max drawdown**: {metrics['max_drawdown_pct']:.2f}%")
    lines.append(f"- **Sharpe ratio**: {metrics['sharpe_ratio']:.2f}")
    lines.append(f"- **Win rate**: {metrics['win_rate']:.0%}")
    lines.append(f"- **Avg turnover**: {metrics['avg_turnover']:.1%}")
    lines.append(f"- **Cumulative excess vs XBI**: {metrics['cumulative_excess_pct']:+.2f}%")
    lines.append("")

    best = metrics.get("best_period")
    worst = metrics.get("worst_period")
    if best:
        lines.append(f"- **Best period**: {best['date']} ({best['pnl_pct']:+.2f}%)")
    if worst:
        lines.append(f"- **Worst period**: {worst['date']} ({worst['pnl_pct']:+.2f}%)")
    lines.append("")

    # Sleeve attribution
    sleeve = metrics.get("sleeve_attribution", {})
    lines.append("## Sleeve Attribution")
    lines.append("")
    lines.append("| Bucket | Cumulative P&L |")
    lines.append("|--------|---------------|")
    for b in BUCKET_NAMES:
        pnl = sleeve.get(b, 0.0)
        lines.append(f"| {BUCKET_DISPLAY.get(b, b)} | ${pnl:,.2f} |")
    lines.append("")

    # Execution quality
    if fills:
        lines.append("## Execution Quality")
        lines.append("")
        lines.append(f"- **Fill rate**: {fills['fill_rate']:.0%} ({fills['n_filled']}/{fills['total_fills']})")
        lines.append(f"- **Mean slippage**: {fills['mean_slippage_bps']:.1f} bps")
        lines.append(f"- **Median slippage**: {fills['median_slippage_bps']:.1f} bps")
        lines.append(f"- **Trade dates with fills**: {fills['n_dates']}")
        lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    return out_path


def write_portfolio_metrics_json(
    metrics: Dict[str, Any],
    fills: Optional[Dict[str, Any]],
    out_path: Path,
) -> Path:
    """Write portfolio_metrics.json sidecar."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **metrics,
    }
    if fills:
        doc["execution_quality"] = fills
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=2)
    return out_path


def build_portfolio_report(
    shadow_root: Path = SHADOW_ROOT,
) -> Dict[str, Any]:
    """Main entry: load history, compute metrics, write report + JSON."""
    perf_csv = shadow_root / "performance.csv"
    trades_root = shadow_root / "trades"
    out_dir = shadow_root

    rows = load_performance_history(perf_csv)
    metrics = compute_portfolio_metrics(rows)
    fills = load_fill_quality(trades_root)

    report_path = write_portfolio_report(metrics, fills, out_dir / "portfolio_report.md")
    json_path = write_portfolio_metrics_json(metrics, fills, out_dir / "portfolio_metrics.json")

    return {
        "report_path": str(report_path),
        "json_path": str(json_path),
        "metrics": metrics,
        "fills": fills,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build portfolio analytics report")
    parser.add_argument("--out-dir", type=str, help="Output directory (default: artifacts/live_shadow)")
    args = parser.parse_args()

    shadow_root = Path(args.out_dir) if args.out_dir else SHADOW_ROOT

    result = build_portfolio_report(shadow_root)
    m = result["metrics"]
    print(f"Portfolio report: {m['n_periods']} periods")
    if m["n_periods"] > 0:
        print(f"  Cumulative return: {m['cumulative_return_pct']:+.2f}%")
        print(f"  Max drawdown: {m['max_drawdown_pct']:.2f}%")
        print(f"  Sharpe: {m['sharpe_ratio']:.2f}")
    print(f"  Report: {result['report_path']}")
    print(f"  JSON: {result['json_path']}")


if __name__ == "__main__":
    main()
