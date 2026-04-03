#!/usr/bin/env python3
"""Coinvest anchor shadow tracker — 30-day forward validation (Check 4).

Runs daily as part of production pipeline. For each day's snapshot, computes
alternative top-30 selections using coinvest-based signals and tracks:
  - Top-30 overlap vs current DEM baseline
  - Turnover vs prior day's shadow
  - Realized excess vs EW and vs XBI (once forward returns mature)
  - Regime label
  - Signal decay (weekly IC recomputation)

Signals tracked:
  - DEM baseline (actionable_rank)
  - coinvest_score_z (original)
  - coinvest_z_size_resid (size-corrected)
  - coinvest_65_inst_35 (recommended bundle)
  - resid_65_inst_35 (honest bundle)

Output:
    artifacts/coinvest_shadow/YYYY-MM-DD.json   — daily snapshot
    artifacts/coinvest_shadow/history.csv        — append-only ledger
    artifacts/coinvest_shadow/summary.md         — rolling summary

Usage:
    python3 tools/coinvest_shadow_tracker.py --as-of-date 2026-04-03
    python3 tools/coinvest_shadow_tracker.py --as-of-date 2026-04-03 --backfill
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
SHADOW_DIR = PROJECT_ROOT / "artifacts" / "coinvest_shadow"
HISTORY_CSV = SHADOW_DIR / "history.csv"
SUMMARY_MD = SHADOW_DIR / "summary.md"

SCHEMA_VERSION = "coinvest_shadow.v1"
TOP_N = 30
SHADOW_WINDOW_DAYS = 30
START_DATE = "2026-04-03"

# Cost model (same as Spec 049)
COST_BPS_PER_TURN = 16.7
MONTHLY_RW_EXTRA_BPS = 65


# ── Signal definitions ───────────────────────────────────────────────

STRATEGIES = {
    "baseline": {
        "description": "DEM actionable_rank (current production)",
        "type": "rank",
        "sort_col": "actionable_rank",
        "ascending": True,
    },
    "coinvest_orig": {
        "description": "coinvest_score_z only",
        "type": "signal",
        "signals": {"coinvest_score_z": 1.0},
    },
    "coinvest_resid": {
        "description": "coinvest_z_size_resid only",
        "type": "signal",
        "signals": {"coinvest_z_size_resid": 1.0},
    },
    "coinvest_inst": {
        "description": "coinvest 65% + inst_delta_z 35%",
        "type": "signal",
        "signals": {"coinvest_score_z": 0.65, "inst_delta_z": 0.35},
    },
    "resid_inst": {
        "description": "resid 65% + inst_delta_z 35%",
        "type": "signal",
        "signals": {"coinvest_z_size_resid": 0.65, "inst_delta_z": 0.35},
    },
}


# ── Helpers ──────────────────────────────────────────────────────────


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def load_snapshot(snap_date: str) -> List[Dict[str, str]]:
    """Load rankings.csv for a given date."""
    path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    if not path.exists():
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def load_prices() -> Dict[str, Dict[str, float]]:
    """Load price_history.csv → {ticker: {date: close}}."""
    series: Dict[str, Dict[str, float]] = {}
    if not PRICE_CSV.exists():
        return series
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return series


def compute_size_residual(rows: List[Dict[str, str]]) -> Dict[str, float]:
    """Compute size-residualized coinvest z-score per ticker."""
    # Group by size_band
    by_band: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        t = r.get("ticker", "")
        t1 = _sf(r.get("sponsor_tier1_count"), default=None)
        sb = r.get("size_band", "?")
        if t1 is not None:
            by_band[sb].append((t, t1))

    # Band means
    band_mean = {}
    for band, pairs in by_band.items():
        band_mean[band] = sum(v for _, v in pairs) / len(pairs) if pairs else 0

    # Residuals
    residuals = {}
    for band, pairs in by_band.items():
        for t, v in pairs:
            residuals[t] = v - band_mean[band]

    # Z-score the residuals
    if not residuals:
        return {}
    vals = list(residuals.values())
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = var**0.5
    if std < 1e-9:
        return {t: 0.0 for t in residuals}
    return {t: round((v - mean) / std, 4) for t, v in residuals.items()}


def zscore_eligible(rows: List[Dict[str, str]], signal: str) -> Dict[str, float]:
    """Z-score a signal across eligible names."""
    vals, tickers = [], []
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        v = _sf(r.get(signal), default=None)
        if v is not None:
            vals.append(v)
            tickers.append(r.get("ticker", ""))
    if len(vals) < 3:
        return {}
    m = statistics.mean(vals)
    s = statistics.stdev(vals) if len(vals) >= 2 else 1.0
    if s < 1e-9:
        s = 1.0
    return {tickers[i]: (vals[i] - m) / s for i in range(len(vals))}


def select_top_n(
    rows: List[Dict[str, str]],
    strategy: Dict[str, Any],
    size_resid: Dict[str, float],
) -> List[str]:
    """Select top-N tickers for a strategy."""
    eligible = []
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        t = r.get("ticker", "")
        rank = _sf(r.get("actionable_rank"), default=None)
        if rank is None:
            continue
        eligible.append({"ticker": t, "rank": rank, "row": r})

    if strategy["type"] == "rank":
        col = strategy["sort_col"]
        asc = strategy.get("ascending", True)
        eligible.sort(key=lambda x: _sf(x["row"].get(col), default=9999), reverse=not asc)
    else:
        # Signal bundle
        signals = strategy["signals"]
        z_maps = {}
        for sig in signals:
            if sig == "coinvest_z_size_resid":
                z_maps[sig] = size_resid
            else:
                z_maps[sig] = zscore_eligible(rows, sig)

        for e in eligible:
            total, total_w = 0.0, 0.0
            for sig, w in signals.items():
                z = z_maps.get(sig, {}).get(e["ticker"])
                if z is not None:
                    total += w * z
                    total_w += w
            e["score"] = total / total_w if total_w > 0 else 0.0

        eligible.sort(key=lambda x: -x.get("score", 0))

    return [e["ticker"] for e in eligible[:TOP_N]]


def compute_forward_return(
    prices: Dict[str, Dict[str, float]],
    tickers: List[str],
    start_date: str,
    horizon_days: int,
) -> Optional[float]:
    """Compute EW forward return for a basket of tickers."""
    rets = []
    for t in tickers:
        t_prices = prices.get(t, {})
        if not t_prices:
            continue
        sorted_dates = sorted(t_prices.keys())
        # Find start
        start_idx = None
        for i, d in enumerate(sorted_dates):
            if d >= start_date:
                start_idx = i
                break
        if start_idx is None:
            continue
        end_idx = start_idx + horizon_days
        if end_idx >= len(sorted_dates):
            continue
        p0 = t_prices[sorted_dates[start_idx]]
        p1 = t_prices[sorted_dates[end_idx]]
        if p0 > 0:
            rets.append((p1 - p0) / p0)
    return statistics.mean(rets) if rets else None


def load_prior_shadow(as_of_date: str) -> Optional[Dict]:
    """Load the most recent prior shadow snapshot."""
    if not SHADOW_DIR.exists():
        return None
    for f in sorted(SHADOW_DIR.glob("20*.json"), reverse=True):
        if f.stem < as_of_date:
            try:
                return json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                pass
    return None


# ── Core computation ─────────────────────────────────────────────────


def compute_shadow(as_of_date: str, prices: Optional[Dict] = None) -> Dict[str, Any]:
    """Compute one day's shadow comparison."""
    rows = load_snapshot(as_of_date)
    if not rows:
        return {"error": f"No snapshot for {as_of_date}", "as_of_date": as_of_date}

    # Compute size-residualized signal
    size_resid = compute_size_residual(rows)

    # Inject into rows for downstream use
    for r in rows:
        t = r.get("ticker", "")
        if t in size_resid:
            r["coinvest_z_size_resid"] = str(size_resid[t])

    # Select top-N for each strategy
    selections: Dict[str, List[str]] = {}
    for name, strat in STRATEGIES.items():
        selections[name] = select_top_n(rows, strat, size_resid)

    baseline_set = set(selections["baseline"])

    # Load prior shadow for turnover
    prior = load_prior_shadow(as_of_date)
    prior_selections = prior.get("selections", {}) if prior else {}

    # Build per-strategy metrics
    strategy_metrics = {}
    for name, tickers in selections.items():
        ticker_set = set(tickers)
        overlap = len(ticker_set & baseline_set)
        turnover = None
        if name in prior_selections:
            prior_set = set(prior_selections[name])
            if prior_set:
                turnover = round(1.0 - len(ticker_set & prior_set) / TOP_N, 4)

        strategy_metrics[name] = {
            "tickers": tickers,
            "overlap_with_baseline": overlap,
            "overlap_pct": round(overlap / TOP_N * 100, 1),
            "turnover_vs_prior": turnover,
        }

    # Forward returns (5d, 20d) — will be None until prices mature
    if prices is None:
        prices = load_prices()

    for name, tickers in selections.items():
        for h in [5, 20]:
            ret = compute_forward_return(prices, tickers, as_of_date, h)
            strategy_metrics[name][f"fwd_ret_{h}d"] = round(ret * 100, 4) if ret is not None else None

        # XBI benchmark
        xbi_ret_5 = compute_forward_return(prices, ["XBI"], as_of_date, 5)
        xbi_ret_20 = compute_forward_return(prices, ["XBI"], as_of_date, 20)

    # Regime label
    xbi_prices = prices.get("XBI", {})
    xbi_sorted = sorted(xbi_prices.keys())
    regime = "unknown"
    # Use 20d trailing XBI return for regime
    try:
        start_idx = None
        for i, d in enumerate(xbi_sorted):
            if d >= as_of_date:
                start_idx = i
                break
        if start_idx is not None and start_idx >= 20:
            p_now = xbi_prices[xbi_sorted[start_idx]]
            p_20_ago = xbi_prices[xbi_sorted[start_idx - 20]]
            if p_20_ago > 0:
                trail_20 = (p_now - p_20_ago) / p_20_ago
                if trail_20 < -0.02:
                    regime = "bear"
                elif trail_20 > 0.02:
                    regime = "bull"
                else:
                    regime = "neutral"
    except (IndexError, KeyError):
        pass

    # Signal values for top-30 (for decay tracking)
    signal_snapshot = {}
    for r in rows:
        t = r.get("ticker", "")
        if t in baseline_set:
            signal_snapshot[t] = {
                "coinvest_score_z": _sf(r.get("coinvest_score_z"), default=None),
                "inst_delta_z": _sf(r.get("inst_delta_z"), default=None),
                "sponsor_tier1_count": _sf(r.get("sponsor_tier1_count"), default=None),
                "coinvest_z_size_resid": size_resid.get(t),
            }

    # Days since shadow start
    days_since_start = (date.fromisoformat(as_of_date) - date.fromisoformat(START_DATE)).days

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "start_date": START_DATE,
        "days_since_start": days_since_start,
        "in_window": 0 <= days_since_start <= SHADOW_WINDOW_DAYS,
        "regime": regime,
        "n_eligible": sum(1 for r in rows if _sf(r.get("eligible")) == 1.0),
        "strategies": strategy_metrics,
        "selections": {name: tickers for name, tickers in selections.items()},
        "signal_snapshot": signal_snapshot,
        "xbi_ret_5d": round(xbi_ret_5 * 100, 4) if xbi_ret_5 is not None else None,
        "xbi_ret_20d": round(xbi_ret_20 * 100, 4) if xbi_ret_20 is not None else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    return result


# ── History ledger ───────────────────────────────────────────────────

HISTORY_COLUMNS = [
    "date",
    "days",
    "regime",
    "n_eligible",
    "baseline_overlap_pct",
    "coinvest_orig_overlap_pct",
    "coinvest_resid_overlap_pct",
    "coinvest_inst_overlap_pct",
    "resid_inst_overlap_pct",
    "baseline_turnover",
    "coinvest_orig_turnover",
    "coinvest_resid_turnover",
    "coinvest_inst_turnover",
    "resid_inst_turnover",
    "baseline_fwd_5d",
    "coinvest_orig_fwd_5d",
    "coinvest_inst_fwd_5d",
    "resid_inst_fwd_5d",
    "xbi_fwd_5d",
    "baseline_fwd_20d",
    "coinvest_orig_fwd_20d",
    "coinvest_inst_fwd_20d",
    "resid_inst_fwd_20d",
    "xbi_fwd_20d",
]


def append_history(result: Dict[str, Any]):
    """Append one row to history.csv."""
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = HISTORY_CSV.exists()

    # Check for duplicate
    if file_exists:
        with open(HISTORY_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("date") == result["as_of_date"]:
                    return  # already recorded

    strats = result.get("strategies", {})

    def _get(name, key, default=""):
        return strats.get(name, {}).get(key, default)

    row = {
        "date": result["as_of_date"],
        "days": result.get("days_since_start", ""),
        "regime": result.get("regime", ""),
        "n_eligible": result.get("n_eligible", ""),
    }
    for sname in ["baseline", "coinvest_orig", "coinvest_resid", "coinvest_inst", "resid_inst"]:
        row[f"{sname}_overlap_pct"] = _get(sname, "overlap_pct", "")
        row[f"{sname}_turnover"] = _get(sname, "turnover_vs_prior", "")
        row[f"{sname}_fwd_5d"] = _get(sname, "fwd_ret_5d", "")
        row[f"{sname}_fwd_20d"] = _get(sname, "fwd_ret_20d", "")

    row["xbi_fwd_5d"] = result.get("xbi_ret_5d", "")
    row["xbi_fwd_20d"] = result.get("xbi_ret_20d", "")

    with open(HISTORY_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ── Summary report ───────────────────────────────────────────────────


def write_summary():
    """Generate rolling summary markdown from history."""
    if not HISTORY_CSV.exists():
        return

    with open(HISTORY_CSV) as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return

    lines = [
        "# Coinvest Anchor Shadow — Rolling Summary",
        f"\nGenerated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Shadow start: {START_DATE}",
        f"Days tracked: {len(rows)}",
        "",
        "## Daily Log",
        "",
        "| Date | Day | Regime | Baseline overlap | CI overlap | RI overlap | CI turnover | RI turnover |",
        "|------|-----|--------|-----------------|------------|------------|-------------|-------------|",
    ]

    for r in rows:
        lines.append(
            f"| {r.get('date', '')} "
            f"| {r.get('days', '')} "
            f"| {r.get('regime', '')} "
            f"| — "
            f"| {r.get('coinvest_inst_overlap_pct', '')}% "
            f"| {r.get('resid_inst_overlap_pct', '')}% "
            f"| {r.get('coinvest_inst_turnover', '')} "
            f"| {r.get('resid_inst_turnover', '')} |"
        )

    # Forward returns (once they mature)
    has_fwd = any(r.get("coinvest_inst_fwd_5d", "") not in ("", "None") for r in rows)
    if has_fwd:
        lines.extend(
            [
                "",
                "## Forward Returns (once matured)",
                "",
                "| Date | Baseline 5d | CI 5d | RI 5d | XBI 5d | Baseline 20d | CI 20d | RI 20d | XBI 20d |",
                "|------|------------|-------|-------|--------|-------------|--------|--------|---------|",
            ]
        )
        for r in rows:
            if r.get("coinvest_inst_fwd_5d", "") in ("", "None"):
                continue
            lines.append(
                f"| {r.get('date', '')} "
                f"| {r.get('baseline_fwd_5d', '')} "
                f"| {r.get('coinvest_inst_fwd_5d', '')} "
                f"| {r.get('resid_inst_fwd_5d', '')} "
                f"| {r.get('xbi_fwd_5d', '')} "
                f"| {r.get('baseline_fwd_20d', '')} "
                f"| {r.get('coinvest_inst_fwd_20d', '')} "
                f"| {r.get('resid_inst_fwd_20d', '')} "
                f"| {r.get('xbi_fwd_20d', '')} |"
            )

    # Cumulative stats
    n = len(rows)
    if n >= 2:
        lines.extend(["", "## Cumulative Statistics", ""])

        for sname, label in [
            ("coinvest_inst", "Coinvest+Inst (65/35)"),
            ("resid_inst", "Resid+Inst (65/35)"),
        ]:
            overlaps = [
                float(r[f"{sname}_overlap_pct"]) for r in rows if r.get(f"{sname}_overlap_pct", "") not in ("", "None")
            ]
            turnovers = [
                float(r[f"{sname}_turnover"]) for r in rows if r.get(f"{sname}_turnover", "") not in ("", "None")
            ]

            if overlaps:
                lines.append(f"**{label}:**")
                lines.append(f"- Mean overlap with baseline: {statistics.mean(overlaps):.1f}%")
                if turnovers:
                    lines.append(f"- Mean daily turnover: {statistics.mean(turnovers):.1%}")
                lines.append("")

    lines.append("")
    SUMMARY_MD.write_text("\n".join(lines))


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Coinvest anchor shadow tracker")
    parser.add_argument("--as-of-date", required=True, help="Date to evaluate (YYYY-MM-DD)")
    parser.add_argument("--backfill", action="store_true", help="Backfill from START_DATE to as-of-date")
    args = parser.parse_args()

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    prices = load_prices()

    if args.backfill:
        current = date.fromisoformat(START_DATE)
        end = date.fromisoformat(args.as_of_date)
        while current <= end:
            if current.weekday() < 5:  # weekdays only
                d_str = current.isoformat()
                snap_path = SNAPSHOTS_DIR / d_str / "rankings.csv"
                if snap_path.exists():
                    print(f"  Backfill {d_str}...")
                    result = compute_shadow(d_str, prices)
                    if "error" not in result:
                        out_path = SHADOW_DIR / f"{d_str}.json"
                        with open(out_path, "w") as f:
                            json.dump(result, f, indent=2, default=str)
                        append_history(result)
            current += timedelta(days=1)
        write_summary()
        print(f"\nBackfill complete. Summary: {SUMMARY_MD}")
        return

    print(f"Computing coinvest shadow for {args.as_of_date}...")
    result = compute_shadow(args.as_of_date, prices)

    if "error" in result:
        print(f"  {result['error']}")
        sys.exit(1)

    # Write daily snapshot
    out_path = SHADOW_DIR / f"{args.as_of_date}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    # Append to history
    append_history(result)

    # Update summary
    write_summary()

    # Print quick report
    print(f"  Day {result['days_since_start']}/{SHADOW_WINDOW_DAYS}  Regime: {result['regime']}")
    for sname in ["coinvest_inst", "resid_inst"]:
        sm = result["strategies"].get(sname, {})
        overlap = sm.get("overlap_pct", "?")
        turnover = sm.get("turnover_vs_prior")
        t_str = f"{turnover:.1%}" if turnover is not None else "—"
        print(f"  {sname}: overlap={overlap}%, turnover={t_str}")

    print(f"\n  Snapshot: {out_path}")
    print(f"  History:  {HISTORY_CSV}")
    print(f"  Summary:  {SUMMARY_MD}")


if __name__ == "__main__":
    main()
