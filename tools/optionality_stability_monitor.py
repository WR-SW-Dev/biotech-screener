#!/usr/bin/env python3
"""
optionality_stability_monitor.py — Rolling IC monitor for clinical optionality.

Computes Spearman IC between clinical_optionality_pct_dev and PIT-cached
forward returns over a rolling window of recent snapshots.  Emits a
GREEN / YELLOW / RED classification based on sign consistency and mean IC.

Designed as a WARN-only observability gate for run_daily_production.py.
Never FAIL — always returns PASS or WARN with a status color.

Thresholds:
    GREEN:  60d sign consistency >= 60% AND mean IC > 0
    YELLOW: 60d sign consistency >= 40% OR mean IC > -0.02
    RED:    sustained negative (sign consistency < 40% AND mean IC <= -0.02)

Usage:
    python tools/optionality_stability_monitor.py --as-of-date 2026-03-19

    # Or import for gate integration:
    from tools.optionality_stability_monitor import evaluate_optionality_stability
"""
from __future__ import annotations

import csv
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("optionality_monitor")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class SnapshotIC:
    """IC result for a single snapshot."""

    date: str
    horizon: int
    n: int
    ic: float


@dataclass
class StabilityResult:
    """Aggregate stability assessment."""

    status: str  # GREEN, YELLOW, RED
    gate: str  # PASS or WARN
    detail: str
    mean_ic_20d: Optional[float]
    mean_ic_60d: Optional[float]
    sign_consistency_20d: Optional[float]  # fraction positive
    sign_consistency_60d: Optional[float]
    spread_60d: Optional[float]
    n_snapshots_20d: int
    n_snapshots_60d: int
    per_snapshot: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# IC computation
# ---------------------------------------------------------------------------


def _spearman_ic(xs: List[float], ys: List[float]) -> Optional[float]:
    """Spearman rank correlation. Returns None if < 10 pairs."""
    if len(xs) < 10 or len(ys) < 10:
        return None
    from scipy.stats import spearmanr

    rho, _ = spearmanr(xs, ys)
    return round(float(rho), 4)


def _load_snapshot_rankings(snapshot_dir: Path) -> List[Dict[str, str]]:
    """Load rankings.csv from a snapshot directory."""
    rankings_path = snapshot_dir / "rankings.csv"
    if not rankings_path.exists():
        return []
    with open(rankings_path) as f:
        return list(csv.DictReader(f))


def _load_pit_prices(cache_dir: Path, snap_date: str) -> Dict[str, Dict[str, float]]:
    """Load PIT-cached prices for a snapshot date.

    Returns {ticker: {date_str: close}}.
    """
    date_dir = cache_dir / snap_date
    if not date_dir.exists():
        return {}

    result: Dict[str, Dict[str, float]] = {}
    for ticker_file in date_dir.glob("*.json"):
        ticker = ticker_file.stem.upper()
        try:
            data = json.loads(ticker_file.read_text())
            prices = {}
            for entry in data.get("prices", []):
                d = entry.get("date", "")
                c = entry.get("close")
                if d and c is not None:
                    prices[d] = float(c)
            if prices:
                result[ticker] = prices
        except (json.JSONDecodeError, ValueError):
            continue

    return result


def _compute_forward_return_csv(
    csv_prices: Dict[str, Dict[str, float]],
    all_dates: List[str],
    date_idx: Dict[str, int],
    ticker: str,
    snap_date: str,
    horizon: int,
) -> Optional[float]:
    """Compute forward return from price CSV data."""
    if ticker not in csv_prices or snap_date not in date_idx:
        return None
    idx = date_idx[snap_date]
    target_idx = idx + horizon
    if target_idx >= len(all_dates):
        return None
    p0 = csv_prices[ticker].get(snap_date)
    p1 = csv_prices[ticker].get(all_dates[target_idx])
    if p0 and p1 and p0 > 0:
        return (p1 - p0) / p0
    return None


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------


def evaluate_optionality_stability(
    as_of_date: str,
    snapshot_dir: Path = REPO_ROOT / "data" / "snapshots",
    price_csv: Path = REPO_ROOT / "production_data" / "price_history.csv",
    lookback_n: int = 10,
    horizons: Optional[List[int]] = None,
) -> StabilityResult:
    """Evaluate clinical optionality stability over recent snapshots.

    Args:
        as_of_date: Current date (snapshots before this date are used).
        snapshot_dir: Directory containing dated snapshot subdirectories.
        price_csv: Path to price_history.csv for forward returns.
        lookback_n: Number of recent snapshots to evaluate.
        horizons: Forward return horizons in trading days. Default: [20, 60].

    Returns:
        StabilityResult with status, gate verdict, and per-snapshot details.
    """
    if horizons is None:
        horizons = [20, 60]

    # Discover recent snapshot dates
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    snap_dates: List[str] = []
    if snapshot_dir.exists():
        for entry in sorted(snapshot_dir.iterdir(), reverse=True):
            if not entry.is_dir() or not date_re.match(entry.name):
                continue
            if entry.name >= as_of_date:
                continue
            rankings_path = entry / "rankings.csv"
            if rankings_path.exists():
                snap_dates.append(entry.name)
            if len(snap_dates) >= lookback_n:
                break

    snap_dates.sort()

    if not snap_dates:
        return StabilityResult(
            status="YELLOW",
            gate="PASS",
            detail="No recent snapshots found for optionality monitor",
            mean_ic_20d=None,
            mean_ic_60d=None,
            sign_consistency_20d=None,
            sign_consistency_60d=None,
            spread_60d=None,
            n_snapshots_20d=0,
            n_snapshots_60d=0,
            per_snapshot=[],
        )

    # Load price CSV
    csv_prices: Dict[str, Dict[str, float]] = {}
    with open(price_csv) as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    csv_prices.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass

    all_dates = sorted(set(d for tk in csv_prices.values() for d in tk.keys()))
    date_idx = {d: i for i, d in enumerate(all_dates)}

    # Compute IC for each snapshot × horizon
    per_snapshot: List[Dict[str, Any]] = []
    ics_by_horizon: Dict[int, List[float]] = {h: [] for h in horizons}
    spreads_60: List[float] = []

    for snap_date in snap_dates:
        rows = _load_snapshot_rankings(snapshot_dir / snap_date)
        if not rows:
            continue

        # Extract dev-stage optionality
        devs = []
        for r in rows:
            arch = r.get("archetype", r.get("company_archetype", ""))
            opt = r.get("clinical_optionality_pct_dev", "").strip()
            ticker = r.get("ticker", "").strip()
            if arch == "drug_developer" and opt and ticker:
                try:
                    devs.append({"ticker": ticker, "opt": float(opt)})
                except ValueError:
                    pass

        if len(devs) < 20:
            continue

        snap_row: Dict[str, Any] = {"date": snap_date, "n_devs": len(devs)}

        for h in horizons:
            pairs = []
            for d in devs:
                ret = _compute_forward_return_csv(csv_prices, all_dates, date_idx, d["ticker"], snap_date, h)
                if ret is not None:
                    pairs.append((d["opt"], ret))

            if len(pairs) < 15:
                snap_row[f"ic_{h}d"] = None
                snap_row[f"n_{h}d"] = len(pairs)
                continue

            opts, rets = zip(*pairs)
            ic = _spearman_ic(list(opts), list(rets))
            snap_row[f"ic_{h}d"] = ic
            snap_row[f"n_{h}d"] = len(pairs)

            if ic is not None:
                ics_by_horizon[h].append(ic)

            # Top vs bottom spread at 60d
            if h == 60 and len(pairs) >= 15:
                sorted_pairs = sorted(pairs, key=lambda x: x[0], reverse=True)
                q = max(3, len(sorted_pairs) // 5)
                top_mean = sum(p[1] for p in sorted_pairs[:q]) / q
                bot_mean = sum(p[1] for p in sorted_pairs[-q:]) / q
                spread = (top_mean - bot_mean) * 100
                snap_row["spread_60d"] = round(spread, 2)
                spreads_60.append(spread)

        per_snapshot.append(snap_row)

    # Aggregate
    def _mean(xs: List[float]) -> Optional[float]:
        return round(sum(xs) / len(xs), 4) if xs else None

    def _sign_consistency(xs: List[float]) -> Optional[float]:
        if not xs:
            return None
        return round(sum(1 for x in xs if x > 0) / len(xs), 4)

    mean_ic_20d = _mean(ics_by_horizon.get(20, []))
    mean_ic_60d = _mean(ics_by_horizon.get(60, []))
    sc_20d = _sign_consistency(ics_by_horizon.get(20, []))
    sc_60d = _sign_consistency(ics_by_horizon.get(60, []))
    spread_60d = _mean(spreads_60)

    # Classification
    # GREEN:  60d sign consistency >= 60% AND mean IC > 0
    # YELLOW: 60d sign consistency >= 40% OR mean IC > -0.02
    # RED:    sustained negative
    if sc_60d is not None and sc_60d >= 0.60 and mean_ic_60d is not None and mean_ic_60d > 0:
        status = "GREEN"
    elif sc_60d is not None and sc_60d < 0.40 and mean_ic_60d is not None and mean_ic_60d <= -0.02:
        status = "RED"
    else:
        status = "YELLOW"

    gate = "WARN" if status == "RED" else "PASS"

    parts = []
    if mean_ic_60d is not None:
        parts.append(f"60d_mean_ic={mean_ic_60d:+.4f}")
    if sc_60d is not None:
        parts.append(f"60d_sign_pos={sc_60d:.0%}")
    if mean_ic_20d is not None:
        parts.append(f"20d_mean_ic={mean_ic_20d:+.4f}")
    if spread_60d is not None:
        parts.append(f"60d_spread={spread_60d:+.1f}pp")
    parts.append(f"n_snap={len(per_snapshot)}")

    detail = f"{status}: {', '.join(parts)}"

    return StabilityResult(
        status=status,
        gate=gate,
        detail=detail,
        mean_ic_20d=mean_ic_20d,
        mean_ic_60d=mean_ic_60d,
        sign_consistency_20d=sc_20d,
        sign_consistency_60d=sc_60d,
        spread_60d=spread_60d,
        n_snapshots_20d=len(ics_by_horizon.get(20, [])),
        n_snapshots_60d=len(ics_by_horizon.get(60, [])),
        per_snapshot=per_snapshot,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Clinical optionality stability monitor")
    parser.add_argument("--as-of-date", required=True, help="As-of date (YYYY-MM-DD)")
    parser.add_argument("--lookback", type=int, default=10, help="Number of snapshots (default: 10)")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args()

    result = evaluate_optionality_stability(
        as_of_date=args.as_of_date,
        lookback_n=args.lookback,
    )

    if args.json:
        print(json.dumps(asdict(result), indent=2, default=str))
    else:
        print(f"Optionality Stability: {result.status} ({result.gate})")
        print(f"  {result.detail}")
        if result.per_snapshot:
            print(f"\n  {'Date':<12} {'IC_20d':>8} {'IC_60d':>8} {'Spread':>8}")
            for s in result.per_snapshot:
                ic20 = f"{s.get('ic_20d', 'N/A'):+.4f}" if s.get("ic_20d") is not None else "    N/A"
                ic60 = f"{s.get('ic_60d', 'N/A'):+.4f}" if s.get("ic_60d") is not None else "    N/A"
                sp = f"{s.get('spread_60d', 'N/A'):+.1f}" if s.get("spread_60d") is not None else "    N/A"
                print(f"  {s['date']:<12} {ic20:>8} {ic60:>8} {sp:>8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
