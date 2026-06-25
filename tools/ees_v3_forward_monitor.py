#!/usr/bin/env python3
"""EES v3 Forward Monitor — tracks rolling evidence toward WS4 clearance.

Reads production snapshots (data/snapshots/), computes v3 scores on-the-fly
for pre-v3 snapshots, and pairs with forward returns from price_history.csv
to build an independent forward observation set.

Outputs:
  1. Rolling IC (Spearman) per snapshot date
  2. Cumulative WS4 progress (n_eff, t_adj vs 1.65 threshold)
  3. Distribution health (saturation %, unique values, spread)
  4. Signal stability (6-period rolling IC)
  5. JSON artifact for audit trail

Designed to run daily after production, or ad-hoc for status checks.

Usage:
    cd /mnt/c/Projects/biotech_screener/biotech-screener
    python -m tools.ees_v3_forward_monitor
    python -m tools.ees_v3_forward_monitor --output artifacts/v3_monitor.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import statistics
import sys
from datetime import date as dt_date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
DEFAULT_PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
DEFAULT_TRIAL_RECORDS = PROJECT_ROOT / "production_data" / "trial_records.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "ees_v3_monitor.json"

# Forward return horizon (trading days) for IC computation
HORIZON = 21  # ~1 month, fastest feedback loop

# WS4 threshold
WS4_T_THRESHOLD = 1.65

# Native v3 epoch: first snapshot with ees_v3_score natively populated
V3_NATIVE_EPOCH = "2026-04-14"

SIGNALS = [
    "ees_v3_score",
    "conditional_misprice_score",
    "conditional_expected_move",
]


# ═════════════════════════════════════════════════════════════════════════
# Utilities (minimal, self-contained)
# ═════════════════════════════════════════════════════════════════════════


def _sf(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _avg_ranks(values: List[float]) -> List[float]:
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[indexed[j + 1]] == values[indexed[j]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def _spearman_ic(signal: List[float], returns: List[float]) -> Optional[float]:
    n = len(signal)
    if n < 5 or len(returns) != n:
        return None
    if len(set(round(s, 8) for s in signal)) < 3:
        return None
    rx = _avg_ranks(signal)
    ry = _avg_ranks(returns)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    sy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if sx < 1e-12 or sy < 1e-12:
        return None
    return cov / (sx * sy)


# ═════════════════════════════════════════════════════════════════════════
# Data loaders
# ═════════════════════════════════════════════════════════════════════════


def _discover_snapshot_dates(snapshots_dir: Path) -> List[str]:
    """Return sorted production snapshot dates (YYYY-MM-DD only, no suffixes)."""
    import re

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    dates = []
    for d in sorted(snapshots_dir.iterdir()):
        if d.is_dir() and date_re.match(d.name):
            if (d / "rankings.csv").exists():
                dates.append(d.name)
    return dates


def _load_snapshot(snapshots_dir: Path, snap_date: str) -> List[Dict[str, Any]]:
    csv_path = snapshots_dir / snap_date / "rankings.csv"
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_prices(price_csv: Path) -> Dict[str, Dict[str, float]]:
    series: Dict[str, Dict[str, float]] = {}
    with open(price_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except (ValueError, TypeError):
                    pass
    return series


def _resolve_trade_date(sorted_dates: List[str], snap_date: str) -> Optional[str]:
    for d in sorted_dates:
        if d > snap_date:
            return d
    return None


def _forward_return(
    ticker_prices: Dict[str, float],
    sorted_dates: List[str],
    trade_date: str,
    horizon: int,
) -> Optional[float]:
    try:
        idx = sorted_dates.index(trade_date)
    except ValueError:
        return None
    end_idx = idx + horizon
    if end_idx >= len(sorted_dates):
        return None
    p0 = ticker_prices.get(sorted_dates[idx])
    p1 = ticker_prices.get(sorted_dates[end_idx])
    if p0 and p1 and p0 > 0:
        return (p1 / p0) - 1.0
    return None


# ═════════════════════════════════════════════════════════════════════════
# On-the-fly v3 scoring for pre-v3 snapshots
# ═════════════════════════════════════════════════════════════════════════


def _enrich_snapshot_with_v3(
    rows: List[Dict[str, Any]],
    snap_date: str,
    cond_model: Any,
    ees_model: Any,
    prices: Dict[str, Dict[str, float]],
    sorted_dates_by_ticker: Dict[str, List[str]],
) -> None:
    """Compute v3 fields in-place for snapshots that lack them.

    Applies the same pre-enrichment (iem→pm, close_price) and scoring
    pipeline used in the PIT backtest.
    """
    # Pre-enrich: priced_move_pct from implied_event_move
    for row in rows:
        if not row.get("priced_move_pct") or row["priced_move_pct"] in ("", "None"):
            iem = _sf(row.get("implied_event_move"))
            if iem is not None and iem > 0:
                row["priced_move_pct"] = round(iem * 100.0, 4)
        if not row.get("close_price") or row["close_price"] in ("", "None"):
            tk = row.get("ticker", "")
            tk_dates = sorted_dates_by_ticker.get(tk)
            if tk_dates:
                for d in tk_dates:
                    if d <= snap_date:
                        best = d
                    else:
                        break
                else:
                    best = tk_dates[-1] if tk_dates else None
                if best:
                    px = prices.get(tk, {}).get(best)
                    if px and px > 0:
                        row["close_price"] = px

    # EES scoring
    ees_scores = ees_model.score_batch(rows, snap_date)
    for row, ees in zip(rows, ees_scores):
        row["conditional_misprice_score"] = ees.conditional_misprice_score

    # Conditional model scoring
    cond_scores = cond_model.score_batch(rows, snap_date)
    for row, cond in zip(rows, cond_scores):
        row["conditional_expected_move"] = cond.conditional_expected_move
        row["conditional_gap_score"] = cond.conditional_gap_score

    # V3 composite (z-score + combine)
    from event_ev.ees_v3 import compute_v3_scores

    v3_overlays = compute_v3_scores(rows, snap_date)
    for row, v3 in zip(rows, v3_overlays):
        row["ees_v3_score"] = v3.ees_v3_score


# ═════════════════════════════════════════════════════════════════════════
# WS4 progress tracker
# ═════════════════════════════════════════════════════════════════════════


def _ws4_progress(ics: List[float]) -> Dict[str, Any]:
    """Compute WS4 effective-N progress toward threshold."""
    n = len(ics)
    if n < 3:
        return {
            "n_periods": n,
            "mean_ic": None,
            "rho1": None,
            "n_eff": None,
            "t_adj": 0.0,
            "gap_to_threshold": WS4_T_THRESHOLD,
            "cleared": False,
        }

    m = statistics.mean(ics)
    s = statistics.stdev(ics)

    # Lag-1 autocorrelation
    demeaned = [ic - m for ic in ics]
    var = sum(d * d for d in demeaned) / n
    if var < 1e-12:
        rho1 = 0.0
    else:
        cov1 = sum(demeaned[i] * demeaned[i + 1] for i in range(n - 1)) / (n - 1)
        rho1 = cov1 / var

    denom = max(0.1, 1 + rho1)
    n_eff = max(3, n * (1 - rho1) / denom)
    t_adj = m / (s / math.sqrt(n_eff)) if s > 1e-12 else 0.0

    return {
        "n_periods": n,
        "mean_ic": round(m, 4),
        "rho1": round(rho1, 3),
        "n_eff": round(n_eff, 1),
        "t_adj": round(t_adj, 2),
        "gap_to_threshold": round(WS4_T_THRESHOLD - t_adj, 2),
        "cleared": t_adj >= WS4_T_THRESHOLD,
    }


# ═════════════════════════════════════════════════════════════════════════
# Distribution health
# ═════════════════════════════════════════════════════════════════════════


def _distribution_health(
    rows: List[Dict[str, Any]],
    signal: str,
) -> Dict[str, Any]:
    """Check distribution health for a signal in a single snapshot."""
    vals = []
    for r in rows:
        v = _sf(r.get(signal))
        if v is not None:
            vals.append(v)
    if not vals:
        return {"n": 0, "healthy": False}

    n = len(vals)
    s = sorted(vals)
    n_unique = len(set(round(v, 4) for v in vals))
    n_at_ceil = sum(1 for v in vals if abs(v) >= 0.99)

    return {
        "n": n,
        "n_unique": n_unique,
        "pct_at_ceiling": round(n_at_ceil / n * 100, 1),
        "min": round(s[0], 4),
        "median": round(s[n // 2], 4),
        "max": round(s[-1], 4),
        "spread": round(s[-1] - s[0], 4),
        "healthy": n_unique >= n * 0.10 and n_at_ceil < n * 0.20,
    }


# ═════════════════════════════════════════════════════════════════════════
# Main monitor
# ═════════════════════════════════════════════════════════════════════════


def run_monitor(
    snapshots_dir: Path,
    price_csv: Path,
    trial_records_path: Path,
    horizon: int = HORIZON,
    min_dates: int = 3,
    max_snapshots: int = 60,
    start_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Run forward monitor across production snapshots.

    Args:
        max_snapshots: Only process the most recent N snapshots.
            Re-scoring 460+ historical snapshots is too slow for daily use.
            Default 60 (~2 months of daily snapshots).
        start_date: ISO date (YYYY-MM-DD). Only process snapshots on or after
            this date. Pass V3_NATIVE_EPOCH for clean WS4 tracking on native
            v3 data only (excludes re-scored pre-fix historical snapshots).
    """

    sys.path.insert(0, str(PROJECT_ROOT))
    from event_ev.conditional_model import ConditionalModel
    from event_ev.expectation_error_model import ExpectationErrorModel

    cond_model = ConditionalModel(trial_records_path=trial_records_path)
    ees_model = ExpectationErrorModel()

    prices = _load_prices(price_csv)
    sorted_dates_by_ticker = {tk: sorted(px.keys()) for tk, px in prices.items()}

    all_snap_dates = _discover_snapshot_dates(snapshots_dir)
    if start_date:
        all_snap_dates = [d for d in all_snap_dates if d >= start_date]
        logger.info("start_date=%s: %d snapshot dates after filter", start_date, len(all_snap_dates))
    snap_dates = all_snap_dates[-max_snapshots:]
    logger.info("Processing %d production snapshot dates", len(snap_dates))

    # ── Per-date scoring + forward returns ──────────────────────────
    ic_series: Dict[str, List[Tuple[str, float]]] = {s: [] for s in SIGNALS}
    date_details: List[Dict[str, Any]] = []
    n_rescored = 0
    n_native = 0

    for snap_date in snap_dates:
        rows = _load_snapshot(snapshots_dir, snap_date)
        if not rows:
            continue

        # Check if v3 columns exist natively
        has_v3 = "ees_v3_score" in rows[0] and rows[0].get("ees_v3_score") not in (
            "",
            "None",
            None,
        )

        if not has_v3:
            # Re-score on-the-fly
            _enrich_snapshot_with_v3(
                rows,
                snap_date,
                cond_model,
                ees_model,
                prices,
                sorted_dates_by_ticker,
            )
            n_rescored += 1
        else:
            n_native += 1

        # Filter to events with catalyst data
        event_rows = [r for r in rows if _sf(r.get("catalyst_days")) is not None]
        if len(event_rows) < 5:
            continue

        # Compute forward returns
        paired = []
        for r in event_rows:
            tk = r.get("ticker", "")
            tk_dates = sorted_dates_by_ticker.get(tk)
            if not tk_dates:
                continue
            trade_date = _resolve_trade_date(tk_dates, snap_date)
            if not trade_date:
                continue
            fwd_ret = _forward_return(prices[tk], tk_dates, trade_date, horizon)
            if fwd_ret is None:
                continue
            r["_fwd_return"] = fwd_ret
            paired.append(r)

        if len(paired) < 5:
            date_details.append(
                {"date": snap_date, "n_events": len(event_rows), "n_paired": len(paired), "status": "insufficient_fwd"}
            )
            continue

        # Compute IC per signal
        date_entry: Dict[str, Any] = {
            "date": snap_date,
            "n_events": len(event_rows),
            "n_paired": len(paired),
            "native_v3": has_v3,
            "status": "scored",
        }

        for sig in SIGNALS:
            sigs = []
            rets = []
            for r in paired:
                v = _sf(r.get(sig))
                if v is not None:
                    sigs.append(v)
                    rets.append(r["_fwd_return"])

            ic = _spearman_ic(sigs, rets) if len(sigs) >= 5 else None
            if ic is not None:
                ic_series[sig].append((snap_date, ic))
                date_entry[f"{sig}_ic"] = round(ic, 4)
            else:
                date_entry[f"{sig}_ic"] = None

        # Distribution health for latest
        for sig in ["conditional_misprice_score", "ees_v3_score"]:
            dh = _distribution_health(event_rows, sig)
            date_entry[f"{sig}_health"] = dh

        date_details.append(date_entry)

    logger.info(
        "Processed %d dates (%d re-scored, %d native v3)",
        len(date_details),
        n_rescored,
        n_native,
    )

    # ── WS4 progress per signal ─────────────────────────────────────
    ws4_progress: Dict[str, Dict[str, Any]] = {}
    for sig in SIGNALS:
        ics = [ic for _, ic in ic_series[sig]]
        ws4_progress[sig] = _ws4_progress(ics)

    # ── Rolling 6-period IC ─────────────────────────────────────────
    rolling_ic: Dict[str, List[Dict[str, Any]]] = {}
    for sig in SIGNALS:
        series = ic_series[sig]
        rolling = []
        window = 6
        for i in range(window, len(series) + 1):
            chunk = series[i - window : i]
            ics_chunk = [c[1] for c in chunk]
            rolling.append(
                {
                    "end_date": chunk[-1][0],
                    "mean_ic": round(statistics.mean(ics_chunk), 4),
                }
            )
        rolling_ic[sig] = rolling

    # ── Assemble report ─────────────────────────────────────────────
    report = {
        "schema": "ees_v3_forward_monitor.v1",
        "generated": dt_date.today().isoformat(),
        "horizon_trading_days": horizon,
        "start_date_filter": start_date,
        "native_only_mode": start_date == V3_NATIVE_EPOCH,
        "n_snapshots_total": len(snap_dates),
        "n_snapshots_scored": sum(1 for d in date_details if d["status"] == "scored"),
        "n_rescored": n_rescored,
        "n_native_v3": n_native,
        "ws4_progress": ws4_progress,
        "rolling_ic": rolling_ic,
        "date_detail": date_details,
    }

    return report


# ═════════════════════════════════════════════════════════════════════════
# Pretty-print
# ═════════════════════════════════════════════════════════════════════════


def _print_summary(report: Dict[str, Any]) -> None:
    print(f"\n{'=' * 65}")
    print("EES v3 FORWARD MONITOR")
    print(f"{'=' * 65}")
    print(
        f"Snapshots: {report['n_snapshots_total']} total, "
        f"{report['n_snapshots_scored']} scored "
        f"({report['n_rescored']} re-scored, {report['n_native_v3']} native)"
    )
    print(f"Horizon: {report['horizon_trading_days']}d")

    print(f"\n{'Signal':<30} {'IC':>7} {'rho1':>5} {'n_eff':>6} {'t_adj':>6} {'gap':>5} {'WS4':>5}")
    print("-" * 65)
    for sig in SIGNALS:
        ws4 = report["ws4_progress"].get(sig, {})
        ic = ws4.get("mean_ic")
        ic_str = f"{ic:+.4f}" if ic is not None else "---"
        rho = ws4.get("rho1")
        rho_str = f"{rho:.2f}" if rho is not None else "---"
        ne = ws4.get("n_eff")
        ne_str = f"{ne:.0f}" if ne is not None else "---"
        ta = ws4.get("t_adj", 0)
        gap = ws4.get("gap_to_threshold", WS4_T_THRESHOLD)
        cleared = "PASS" if ws4.get("cleared") else "WAIT"
        print(f"  {sig:<28} {ic_str:>7} {rho_str:>5} {ne_str:>6} {ta:>+6.2f} {gap:>+5.2f} {cleared:>5}")

    # Recent IC trend (last 5 scored dates)
    scored = [d for d in report["date_detail"] if d["status"] == "scored"]
    if scored:
        print(f"\nRecent IC ({len(scored[-5:])} dates):")
        for d in scored[-5:]:
            parts = [f"  {d['date']} (n={d['n_paired']})"]
            for sig in SIGNALS:
                ic = d.get(f"{sig}_ic")
                if ic is not None:
                    parts.append(f"{sig.split('_')[-1][:6]}={ic:+.3f}")
            print("  ".join(parts))

    # Distribution health from latest
    if scored:
        latest = scored[-1]
        print(f"\nDistribution health ({latest['date']}):")
        for sig in ["conditional_misprice_score", "ees_v3_score"]:
            h = latest.get(f"{sig}_health", {})
            if h:
                status = "OK" if h.get("healthy") else "WARN"
                print(
                    f"  {sig}: unique={h.get('n_unique', 0)}, "
                    f"ceil={h.get('pct_at_ceiling', 0):.0f}%, "
                    f"spread={h.get('spread', 0):.3f} [{status}]"
                )

    print(f"\n{'=' * 65}")


# ═════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="EES v3 Forward Monitor")
    parser.add_argument("--snapshots-dir", type=Path, default=DEFAULT_SNAPSHOTS_DIR)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICE_CSV)
    parser.add_argument("--trials", type=Path, default=DEFAULT_TRIAL_RECORDS)
    parser.add_argument("--horizon", type=int, default=HORIZON)
    parser.add_argument("--max-snapshots", type=int, default=60, help="Max recent snapshots to process")
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Only process snapshots on or after this ISO date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--native-only",
        action="store_true",
        help=f"Restrict to native v3 snapshots only (start_date={V3_NATIVE_EPOCH}). "
        "Produces clean WS4 tracking without re-scored pre-fix contamination.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    start_date = V3_NATIVE_EPOCH if args.native_only else args.start_date

    report = run_monitor(
        args.snapshots_dir,
        args.prices,
        args.trials,
        args.horizon,
        max_snapshots=args.max_snapshots,
        start_date=start_date,
    )

    _print_summary(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Report written to %s", args.output)


if __name__ == "__main__":
    main()
