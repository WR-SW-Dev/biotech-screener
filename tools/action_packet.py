#!/usr/bin/env python3
"""Action Packet Generator.

Reads a promoted snapshot and produces:
  ACTION.json  (machine-readable, bucketed by catalyst horizon)
  ACTION.md    (human-readable summary with tables)

Usage:
    python3 tools/action_packet.py --snapshot-dir data/snapshots/2026-03-08
    python3 tools/action_packet.py --as-of-date 2026-03-08
    python3 tools/action_packet.py --as-of-date 2026-03-08 --top-n 40
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "snapshots"

SCHEMA = "action_packet.v1"

# Catalyst horizon bucket definitions (days)
BUCKET_BINARY_NOW_MAX = 30
BUCKET_BUILD_WINDOW_MAX = 90
BUCKET_LESS_BINARY_MAX = 180

# catalyst_mode values that map to "core" regardless of days
CORE_MODES = frozenset({"no_upcoming", "missing"})


# ── Helpers ──────────────────────────────────────────────────────────


def _find_latest_snapshot_date() -> Optional[str]:
    """Return the most recent YYYY-MM-DD snapshot directory name."""
    candidates = []
    if not SNAPSHOTS_ROOT.is_dir():
        return None
    for d in SNAPSHOTS_ROOT.iterdir():
        name = d.name
        if len(name) == 10 and name[4] == "-" and name[7] == "-":
            try:
                datetime.strptime(name, "%Y-%m-%d")
                candidates.append(name)
            except ValueError:
                pass
    return max(candidates) if candidates else None


def _load_json(path: Path) -> Optional[Dict]:
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with open(path) as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert a value to float, returning default on failure."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """Convert a value to int, returning default on failure."""
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


# ── Bucket assignment ────────────────────────────────────────────────


def assign_bucket(catalyst_days: Optional[int], catalyst_mode: str) -> str:
    """Assign a ticker to a catalyst horizon bucket.

    Returns one of: "binary_now", "build_window", "less_binary", "core".
    """
    if catalyst_mode in CORE_MODES:
        return "core"
    if catalyst_days is None:
        return "core"
    if catalyst_days <= BUCKET_BINARY_NOW_MAX:
        return "binary_now"
    if catalyst_days <= BUCKET_BUILD_WINDOW_MAX:
        return "build_window"
    if catalyst_days <= BUCKET_LESS_BINARY_MAX:
        return "less_binary"
    return "core"


# ── Performance summary ──────────────────────────────────────────────

# Lookback periods: label, approximate trading days
PERF_PERIODS = [
    ("1d", 1),
    ("1w", 5),
    ("1m", 21),
    ("3m", 63),
    ("6m", 126),
    ("1y", 252),
    ("2y", 504),
    ("3y", 756),
]


def compute_performance_summary(
    as_of_date: str,
    price_csv: Path,
    tickers: List[str],
    benchmark: str = "XBI",
) -> Dict[str, Any]:
    """Compute total return over standard lookback periods.

    Uses equal-weight portfolio of given tickers plus benchmark.
    Returns dict with period labels as keys.
    """
    if not price_csv.is_file():
        return {}

    # Load prices for portfolio tickers + benchmark
    target = set(tickers) | {benchmark}
    prices: Dict[str, List[tuple]] = {}  # ticker -> [(date, close), ...]
    with open(price_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t in target and d and c and d <= as_of_date:
                try:
                    prices.setdefault(t, []).append((d, float(c)))
                except ValueError:
                    pass

    # Sort each ticker's prices by date
    for t in prices:
        prices[t].sort()

    # Get latest price date for each ticker
    latest_prices: Dict[str, float] = {}
    for t, series in prices.items():
        if series:
            latest_prices[t] = series[-1][1]

    if not latest_prices:
        return {}

    periods = {}
    for label, lookback_days in PERF_PERIODS:
        # Find portfolio return over this period
        ticker_returns = []
        for t in tickers:
            series = prices.get(t, [])
            if len(series) < lookback_days + 1:
                continue
            end_price = series[-1][1]
            start_idx = max(0, len(series) - 1 - lookback_days)
            start_price = series[start_idx][1]
            if start_price > 0:
                ticker_returns.append((end_price - start_price) / start_price)

        # Benchmark return
        bench_series = prices.get(benchmark, [])
        bench_return = None
        if len(bench_series) >= lookback_days + 1:
            end_b = bench_series[-1][1]
            start_idx_b = max(0, len(bench_series) - 1 - lookback_days)
            start_b = bench_series[start_idx_b][1]
            if start_b > 0:
                bench_return = (end_b - start_b) / start_b

        if ticker_returns:
            port_return = sum(ticker_returns) / len(ticker_returns)
            excess = (port_return - bench_return) if bench_return is not None else None
            periods[label] = {
                "portfolio_pct": round(port_return * 100, 2),
                "benchmark_pct": round(bench_return * 100, 2) if bench_return is not None else None,
                "excess_pct": round(excess * 100, 2) if excess is not None else None,
                "n_tickers": len(ticker_returns),
            }

    return periods


# ── Build packet ─────────────────────────────────────────────────────


def build_action_packet(snapshot_dir: Path, top_n: int = 60) -> Dict[str, Any]:
    """Build structured action packet from a snapshot directory.

    Args:
        snapshot_dir: Path to the snapshot (e.g. data/snapshots/2026-03-08)
        top_n: Number of top eligible names to include

    Returns:
        Structured dict with schema "action_packet.v1"
    """
    rows = _load_csv(snapshot_dir / "rankings.csv")
    metadata = _load_json(snapshot_dir / "metadata.json") or {}

    # Filter to eligible, sort by actionable_rank
    eligible = [r for r in rows if r.get("eligible") == "1"]
    eligible.sort(key=lambda r: _safe_float(r.get("actionable_rank", "9999")))
    top = eligible[:top_n]

    # Count portfolio names (weight > 0)
    portfolio_count = sum(1 for r in top if _safe_float(r.get("target_weight_pct", "0")) > 0)

    # Build name entries and assign to buckets
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "binary_now": [],
        "build_window": [],
        "less_binary": [],
        "core": [],
    }

    for r in top:
        cat_days = _safe_int(r.get("catalyst_days"))
        cat_mode = r.get("catalyst_mode", "") or ""
        weight = _safe_float(r.get("target_weight_pct", "0"))
        bucket = assign_bucket(cat_days, cat_mode)

        entry = {
            "ticker": r.get("ticker", ""),
            "rank": _safe_int(r.get("actionable_rank"), 0),
            "weight_pct": round(weight, 2),
            "tier": r.get("tier_any", "") or r.get("tier_dev", ""),
            "catalyst_days": cat_days,
            "catalyst_mode": cat_mode,
            "catalyst_detail": r.get("catalyst_reason_detail", ""),
            "alpha_cohort_key": r.get("alpha_cohort_key", ""),
            "archetype": r.get("archetype", ""),
            "in_portfolio": weight > 0,
        }
        buckets[bucket].append(entry)

    # Per-bucket stats
    bucket_meta = {
        "binary_now": {"horizon": "0-30d"},
        "build_window": {"horizon": "31-90d"},
        "less_binary": {"horizon": "91-180d"},
        "core": {"horizon": ">180d / no catalyst"},
    }

    structured_buckets = {}
    for key, entries in buckets.items():
        cat_days_vals = [e["catalyst_days"] for e in entries if e["catalyst_days"] is not None]
        structured_buckets[key] = {
            "horizon": bucket_meta[key]["horizon"],
            "names": entries,
            "count": len(entries),
            "total_weight_pct": round(sum(e["weight_pct"] for e in entries), 2),
            "avg_catalyst_days": (round(sum(cat_days_vals) / len(cat_days_vals), 1) if cat_days_vals else None),
        }

    # Provenance from metadata.json
    cst = metadata.get("clinical_sort_telemetry") or {}
    health = _load_json(snapshot_dir / "phase2_health.json") or {}
    ruleset_id = health.get("expected_ruleset_id") or cst.get("ruleset_id") or ""
    engine_version = metadata.get("version", "")
    as_of_date = metadata.get("as_of_date", snapshot_dir.name)

    # Performance summary (equal-weight portfolio of top-N vs XBI)
    price_csv = PROJECT_ROOT / "production_data" / "price_history.csv"
    portfolio_tickers = [r.get("ticker", "") for r in top if r.get("ticker")]
    performance = compute_performance_summary(as_of_date, price_csv, portfolio_tickers)

    return {
        "schema": SCHEMA,
        "as_of_date": as_of_date,
        "ruleset_id": ruleset_id,
        "engine_version": engine_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "top_n": top_n,
        "portfolio_names": portfolio_count,
        "buckets": structured_buckets,
        "performance": performance,
        "summary": {
            "total_eligible_screened": len(top),
            "in_portfolio": portfolio_count,
        },
    }


# ── Markdown rendering ───────────────────────────────────────────────

BUCKET_DISPLAY = {
    "binary_now": "Binary Now (0-30d)",
    "build_window": "Build Window (31-90d)",
    "less_binary": "Less Binary (91-180d)",
    "core": "Core (>180d / no catalyst)",
}


def render_action_markdown(packet: Dict[str, Any]) -> str:
    """Render action packet as human-readable markdown."""
    lines: List[str] = []

    lines.append(f"# Action Packet — {packet['as_of_date']}")
    lines.append("")
    lines.append(f"**Ruleset**: `{packet['ruleset_id']}`")
    lines.append(f"**Engine**: `{packet['engine_version']}`")
    lines.append(f"**Generated**: {packet['generated_at']}")
    lines.append(f"**Top N**: {packet['top_n']}")
    lines.append(f"**Portfolio names**: {packet['portfolio_names']}")
    lines.append("")

    buckets = packet.get("buckets", {})
    for key in ["binary_now", "build_window", "less_binary", "core"]:
        bucket = buckets.get(key, {})
        display_name = BUCKET_DISPLAY.get(key, key)
        names = bucket.get("names", [])
        count = bucket.get("count", 0)
        total_wt = bucket.get("total_weight_pct", 0)
        avg_days = bucket.get("avg_catalyst_days")

        lines.append(f"## {display_name}")
        lines.append("")
        avg_str = f"{avg_days:.0f}d" if avg_days is not None else "N/A"
        lines.append(f"**Count**: {count} | **Weight**: {total_wt:.1f}% | **Avg cat days**: {avg_str}")
        lines.append("")

        if names:
            lines.append("| Rank | Ticker | Tier | Cat Days | Mode | Weight | Portfolio? |")
            lines.append("|------|--------|------|----------|------|--------|------------|")
            for n in names:
                cat_d = str(n["catalyst_days"]) if n["catalyst_days"] is not None else "—"
                port = "Yes" if n["in_portfolio"] else "No"
                lines.append(
                    f"| {n['rank']} | {n['ticker']} | {n['tier']} | {cat_d} | {n['catalyst_mode']} | {n['weight_pct']:.1f}% | {port} |"
                )
        else:
            lines.append("_No names in this bucket._")
        lines.append("")

    # Performance summary
    performance = packet.get("performance", {})
    if performance:
        lines.append("## Performance (equal-weight top-N vs XBI)")
        lines.append("")
        lines.append("| Period | Portfolio | XBI | Excess | Names |")
        lines.append("|--------|----------|-----|--------|-------|")
        for label, _ in PERF_PERIODS:
            p = performance.get(label)
            if p:
                port = f"{p['portfolio_pct']:+.2f}%"
                bench = f"{p['benchmark_pct']:+.2f}%" if p.get("benchmark_pct") is not None else "n/a"
                excess = f"{p['excess_pct']:+.2f}%" if p.get("excess_pct") is not None else "n/a"
                lines.append(f"| {label} | {port} | {bench} | {excess} | {p['n_tickers']} |")
        lines.append("")

    # Summary footer
    summary = packet.get("summary", {})
    lines.append("---")
    lines.append("")
    lines.append(f"**Total eligible screened**: {summary.get('total_eligible_screened', 0)}")
    lines.append(f"**In portfolio**: {summary.get('in_portfolio', 0)}")
    lines.append("")

    return "\n".join(lines)


# ── Write ────────────────────────────────────────────────────────────


def write_action_packet(snapshot_dir: Path, top_n: int = 60) -> Path:
    """Build, render, and write ACTION.json + ACTION.md into snapshot_dir.

    Returns the path to ACTION.json.
    """
    packet = build_action_packet(snapshot_dir, top_n=top_n)

    json_path = snapshot_dir / "ACTION.json"
    with open(json_path, "w") as f:
        json.dump(packet, f, indent=2, default=str)

    md_path = snapshot_dir / "ACTION.md"
    md_text = render_action_markdown(packet)
    with open(md_path, "w") as f:
        f.write(md_text)

    return json_path


# ── CLI ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Generate action packet (ACTION.json + ACTION.md) from a snapshot.")
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=None,
        help="Path to snapshot directory (e.g. data/snapshots/2026-03-08)",
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        help="Snapshot date (YYYY-MM-DD); discovers snapshot in data/snapshots/",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=60,
        help="Number of top eligible names to include (default: 60)",
    )
    args = parser.parse_args()

    if args.snapshot_dir:
        snap_dir = args.snapshot_dir
    elif args.as_of_date:
        snap_dir = SNAPSHOTS_ROOT / args.as_of_date
    else:
        latest = _find_latest_snapshot_date()
        if latest is None:
            print("ERROR: No snapshots found and no --snapshot-dir / --as-of-date given.", file=sys.stderr)
            sys.exit(1)
        snap_dir = SNAPSHOTS_ROOT / latest

    if not snap_dir.is_dir():
        print(f"ERROR: Snapshot directory not found: {snap_dir}", file=sys.stderr)
        sys.exit(1)

    json_path = write_action_packet(snap_dir, top_n=args.top_n)
    md_path = snap_dir / "ACTION.md"
    print(f"ACTION.json → {json_path}")
    print(f"ACTION.md   → {md_path}")


if __name__ == "__main__":
    main()
