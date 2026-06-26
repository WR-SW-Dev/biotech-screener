"""
EES v3 recent-regime degradation analysis — diagnostic-only batch PIT analysis.

Compares signal behavior in two periods:
  EARLY: 2020-01-31 through 2024-08-31
  LATE:  2024-09-30 through 2026-04-16

For each period, computes IC, t-stat, hit_rate, n_dates for:
  - ees_v3_core (stored composite)
  - ees_v3_expected_move_only
  - ees_v3_misprice_only
  - ees_v3_native_high_coverage
  - final_score (production ranker)

Sliced by: market_cap_bucket, catalyst_timing, catalyst_family, misprice_available,
           implied_move_bucket, final_score quantile.

Horizons: 21d and 63d (consistent with existing PIT backtest).

Usage:
    python3 scripts/research/ees_v3_regime_analysis.py
    python3 scripts/research/ees_v3_regime_analysis.py --output artifacts/shadow/regime_YYYYMMDD.json

GOVERNANCE: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

GOVERNANCE = "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE"

EARLY_END = "2024-08-31"
LATE_START = "2024-09-30"

HORIZONS = [21, 63]
MIN_PAIRS = 5
EPS = 1e-6

# Signals to evaluate
SIGNALS = [
    "ees_v3_core",
    "ees_v3_expected_move_only",
    "ees_v3_misprice_only",
    "ees_v3_native_high_coverage",
    "final_score",
]

# Slice dimensions
SLICE_DIMS = [
    "market_cap_bucket",
    "catalyst_timing_bucket",
    "catalyst_family",
    "misprice_available",
    "implied_move_bucket",
    "final_score_quartile",
]


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _pit_dir() -> Path:
    return _repo_root() / "data" / "snapshots_pit_v2"


def _price_csv() -> Path:
    return _repo_root() / "production_data" / "price_history.csv"


def _output_dir() -> Path:
    return _repo_root() / "artifacts" / "shadow"


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def _sf(v: object) -> Optional[float]:
    if v is None or v == "" or v == "None" or v == "nan":
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _has_priced_move(row: dict) -> bool:
    val = row.get("priced_move_pct", "")
    if not val or val in ("None", "nan", "0", "0.0", ""):
        return False
    try:
        f = float(val)
        return not math.isnan(f) and f != 0.0
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Variant computation (mirrors ees_v3_shadow_variants.py)
# ---------------------------------------------------------------------------


def _z_full(values: list[Optional[float]]) -> list[float]:
    valid = [v for v in values if v is not None]
    if len(valid) < 3:
        return [0.0] * len(values)
    m = sum(valid) / len(valid)
    var = sum((v - m) ** 2 for v in valid) / len(valid)
    s = math.sqrt(var)
    if s < EPS:
        return [0.0] * len(values)
    return [(v - m) / s if v is not None else 0.0 for v in values]


def _z_subset_or_none(values: list[Optional[float]]) -> list[Optional[float]]:
    indexed = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(indexed) < 3:
        return [None if v is None else 0.0 for v in values]
    vals = [v for _, v in indexed]
    m = sum(vals) / len(vals)
    var = sum((v - m) ** 2 for v in vals) / len(vals)
    s = math.sqrt(var)
    if s < EPS:
        return [None if v is None else 0.0 for v in values]
    result: list[Optional[float]] = [None] * len(values)
    for i, v in indexed:
        result[i] = (v - m) / s
    return result


def compute_variants_for_rows(rows: list[dict]) -> list[dict]:
    """Return extended rows with variant score columns added."""
    misprice_raw = [_sf(r.get("conditional_misprice_score")) for r in rows]
    expected_raw = [_sf(r.get("conditional_expected_move")) for r in rows]
    core_scores = [_sf(r.get("ees_v3_score")) for r in rows]
    misprice_avail = [_has_priced_move(r) for r in rows]

    v2 = _z_full(expected_raw)

    misprice_for_subset = [m if misprice_avail[i] else None for i, m in enumerate(misprice_raw)]
    v3 = _z_subset_or_none(misprice_for_subset)

    hi_idx = [i for i, a in enumerate(misprice_avail) if a]
    if len(hi_idx) >= 3:
        hi_mz = _z_full([misprice_raw[i] for i in hi_idx])
        hi_ez = _z_full([expected_raw[i] for i in hi_idx])
        hi_comp = {i: 0.70 * hi_mz[k] + 0.30 * hi_ez[k] for k, i in enumerate(hi_idx)}
        v5: list[Optional[float]] = [hi_comp.get(i) for i in range(len(rows))]
    else:
        v5 = [None] * len(rows)

    result = []
    for i, r in enumerate(rows):
        extended = dict(r)
        extended["ees_v3_core"] = core_scores[i]
        extended["ees_v3_expected_move_only"] = v2[i]
        extended["ees_v3_misprice_only"] = v3[i]
        extended["ees_v3_native_high_coverage"] = v5[i]
        extended["misprice_available"] = misprice_avail[i]
        result.append(extended)
    return result


# ---------------------------------------------------------------------------
# Slice key computation
# ---------------------------------------------------------------------------


def _catalyst_timing_bucket(row: dict) -> str:
    days = _sf(row.get("catalyst_days"))
    if days is None:
        return "no_catalyst"
    if days < 0:
        return "post_catalyst"
    if days <= 7:
        return "0_7d"
    if days <= 30:
        return "8_30d"
    if days <= 90:
        return "31_90d"
    return "91plus"


def _implied_move_bucket(row: dict) -> str:
    im = _sf(row.get("implied_event_move"))
    if im is None:
        return "no_implied"
    if im < 0.10:
        return "low_lt10pct"
    if im < 0.20:
        return "mid_10_20pct"
    if im < 0.35:
        return "high_20_35pct"
    return "very_high_gt35pct"


def _final_score_quartile(fs: Optional[float], fs_vals: list[float]) -> Optional[str]:
    if fs is None or not fs_vals:
        return None
    s = sorted(fs_vals)
    n = len(s)
    q25 = s[n // 4]
    q50 = s[n // 2]
    q75 = s[3 * n // 4]
    if fs <= q25:
        return "Q1_bottom"
    if fs <= q50:
        return "Q2"
    if fs <= q75:
        return "Q3"
    return "Q4_top"


def add_slice_keys(rows: list[dict]) -> list[dict]:
    """Add slice dimension values to each row."""
    fs_vals = [_sf(r.get("final_score")) for r in rows]
    fs_valid = [v for v in fs_vals if v is not None]

    result = []
    for i, r in enumerate(rows):
        extended = dict(r)
        extended["slice_market_cap_bucket"] = r.get("market_cap_bucket", "unknown") or "unknown"
        extended["slice_catalyst_timing_bucket"] = _catalyst_timing_bucket(r)
        extended["slice_catalyst_family"] = r.get("catalyst_family", "none") or "none"
        extended["slice_misprice_available"] = "yes" if r.get("misprice_available") else "no"
        extended["slice_implied_move_bucket"] = _implied_move_bucket(r)
        extended["slice_final_score_quartile"] = _final_score_quartile(_sf(r.get("final_score")), fs_valid)
        result.append(extended)
    return result


# ---------------------------------------------------------------------------
# Price loading + forward returns
# ---------------------------------------------------------------------------


def load_prices() -> tuple[dict[str, dict[str, float]], list[str]]:
    path = _price_csv()
    if not path.exists():
        log.error("Price history not found: %s", path)
        return {}, []
    prices: dict[str, dict[str, float]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t, d, c_str = row.get("ticker", ""), row.get("date", ""), row.get("close", "")
            if not t or not d or not c_str:
                continue
            try:
                prices.setdefault(t, {})[d] = float(c_str)
            except (ValueError, TypeError):
                continue
    all_dates = sorted(set(d for td in prices.values() for d in td))
    log.info("Loaded prices: %d tickers, %d dates", len(prices), len(all_dates))
    return prices, all_dates


def _excess_return(ticker: str, snap_date: str, horizon: int, prices: dict, sorted_dates: list) -> Optional[float]:
    tp = prices.get(ticker, {})
    anchor_d = (
        snap_date if snap_date in tp else next((d for d in reversed(sorted_dates) if d <= snap_date and d in tp), None)
    )
    if anchor_d is None:
        return None
    anchor_c = tp[anchor_d]
    if anchor_c == 0:
        return None
    try:
        idx = sorted_dates.index(anchor_d)
    except ValueError:
        return None
    fwd_idx = idx + horizon
    if fwd_idx >= len(sorted_dates):
        return None
    fwd_c = tp.get(sorted_dates[fwd_idx])
    if fwd_c is None:
        return None
    ticker_ret = (fwd_c - anchor_c) / anchor_c

    xp = prices.get("XBI", {})
    xbi_anch = xp.get(anchor_d) or next((xp[d] for d in reversed(sorted_dates) if d <= snap_date and d in xp), None)
    if xbi_anch is None or xbi_anch == 0:
        return None
    xbi_fwd = xp.get(sorted_dates[fwd_idx])
    if xbi_fwd is None:
        return None
    xbi_ret = (xbi_fwd - xbi_anch) / xbi_anch
    return ticker_ret - xbi_ret


# ---------------------------------------------------------------------------
# IC computation
# ---------------------------------------------------------------------------


def _rank(xs: list[float]) -> list[float]:
    sorted_vals = sorted(enumerate(xs), key=lambda t: t[1])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(sorted_vals):
        j = i
        while j < len(sorted_vals) - 1 and sorted_vals[j + 1][1] == sorted_vals[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[sorted_vals[k][0]] = avg_rank
        i = j + 1
    return ranks


def _spearman_ic(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < MIN_PAIRS:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((r - mx) ** 2 for r in rx)
    vy = sum((r - my) ** 2 for r in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def _t_stat_simple(vals: list[float]) -> Optional[float]:
    n = len(vals)
    if n < 3:
        return None
    m = sum(vals) / n
    var = sum((x - m) ** 2 for x in vals) / (n - 1)
    if var == 0:
        return None
    return m / math.sqrt(var / n)


def _ic_stats(observations: list[dict], signal: str, hz: int) -> Optional[dict]:
    """Compute per-date Spearman IC for signal vs excess_return_Nd."""
    ret_key = f"excess_return_{hz}d"
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for obs in observations:
        score = obs.get(signal)
        ret = obs.get(ret_key)
        if score is None or ret is None:
            continue
        by_date[obs["snap_date"]].append((score, ret))

    ics: list[float] = []
    for pairs in by_date.values():
        if len(pairs) < MIN_PAIRS:
            continue
        xs, ys = zip(*pairs)
        ic = _spearman_ic(list(xs), list(ys))
        if ic is not None:
            ics.append(ic)

    if not ics:
        return None

    n = len(ics)
    m = sum(ics) / n
    ts = _t_stat_simple(ics)
    return {
        "mean_ic": round(m, 4),
        "t_stat": round(ts, 3) if ts is not None else None,
        "hit_rate": round(sum(1 for ic in ics if ic > 0) / n, 3),
        "n_dates": n,
        "n_obs": sum(len(pairs) for pairs in by_date.values() if len(pairs) >= MIN_PAIRS),
    }


# ---------------------------------------------------------------------------
# Main analysis loop
# ---------------------------------------------------------------------------


def build_observations(snap_dates: list[str], pit_root: Path, prices: dict, sorted_dates: list) -> list[dict]:
    """Build one observation per (snap_date, ticker, horizon) with all signal scores."""
    all_obs: list[dict] = []
    n_snaps = len(snap_dates)
    for i, snap_date in enumerate(snap_dates):
        if i % 10 == 0:
            log.info("Processing snapshot %d/%d: %s", i + 1, n_snaps, snap_date)
        path = pit_root / snap_date / "rankings.csv"
        if not path.exists():
            continue
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue

        # Add variant scores and slice keys
        rows_with_variants = compute_variants_for_rows(rows)
        rows_with_slices = add_slice_keys(rows_with_variants)

        for r in rows_with_slices:
            ticker = r.get("ticker", "")
            for hz in HORIZONS:
                excess = _excess_return(ticker, snap_date, hz, prices, sorted_dates)
                obs = {
                    "snap_date": snap_date,
                    "ticker": ticker,
                    f"excess_return_{hz}d": excess,
                }
                for sig in SIGNALS:
                    obs[sig] = r.get(sig)
                for dim in SLICE_DIMS:
                    obs[f"slice_{dim}"] = r.get(f"slice_{dim}")
                obs["misprice_available"] = r.get("misprice_available", False)
                all_obs.append(obs)

    return all_obs


def split_observations(all_obs: list[dict]) -> tuple[list[dict], list[dict]]:
    early = [o for o in all_obs if o["snap_date"] <= EARLY_END]
    late = [o for o in all_obs if o["snap_date"] >= LATE_START]
    return early, late


def compute_period_ic(observations: list[dict], period_name: str) -> dict:
    """Compute aggregate IC for each signal x horizon in this period."""
    result: dict = {"period": period_name}
    snap_dates = sorted(set(o["snap_date"] for o in observations))
    result["n_snapshots"] = len(snap_dates)
    result["date_range"] = [snap_dates[0] if snap_dates else None, snap_dates[-1] if snap_dates else None]

    for hz in HORIZONS:
        hz_obs = [o for o in observations if o.get(f"excess_return_{hz}d") is not None]
        result[f"hz_{hz}d"] = {}
        for sig in SIGNALS:
            ic_stats = _ic_stats(hz_obs, sig, hz)
            result[f"hz_{hz}d"][sig] = ic_stats

    return result


def compute_slice_ic(observations: list[dict], period_name: str) -> dict:
    """Compute IC for each (signal, horizon, slice_dim, slice_value)."""
    result: dict = {"period": period_name, "slices": {}}

    for dim in SLICE_DIMS:
        slice_key = f"slice_{dim}"
        slice_values = sorted(set(o.get(slice_key) for o in observations if o.get(slice_key) is not None))
        result["slices"][dim] = {}

        for val in slice_values:
            if val is None:
                continue
            subset = [o for o in observations if o.get(slice_key) == val]
            val_stats: dict = {"n_obs_total": len(subset)}
            for hz in HORIZONS:
                hz_subset = [o for o in subset if o.get(f"excess_return_{hz}d") is not None]
                val_stats[f"hz_{hz}d"] = {}
                for sig in SIGNALS:
                    ic_stats = _ic_stats(hz_subset, sig, hz)
                    val_stats[f"hz_{hz}d"][sig] = ic_stats
            result["slices"][dim][str(val)] = val_stats

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EES v3 regime degradation analysis — DIAGNOSTIC_ONLY")
    p.add_argument("--output", default=None, help="Output JSON path (default: artifacts/shadow/)")
    p.add_argument("--slices", action="store_true", help="Include per-slice IC breakdown (slow)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_date = run_ts[:10]

    log.info("=== EES v3 Regime Analysis ===")
    log.info("run_ts=%s | GOVERNANCE: %s", run_ts, GOVERNANCE)
    log.info("Periods: EARLY ≤ %s | LATE ≥ %s", EARLY_END, LATE_START)

    pit_root = _pit_dir()
    if not pit_root.exists():
        log.error("PIT snapshots not found: %s", pit_root)
        return 1

    snap_dates = sorted(d.name for d in pit_root.iterdir() if d.is_dir() and (d / "rankings.csv").exists())
    log.info("Found %d PIT snapshots: %s → %s", len(snap_dates), snap_dates[0], snap_dates[-1])

    early_dates = [d for d in snap_dates if d <= EARLY_END]
    late_dates = [d for d in snap_dates if d >= LATE_START]
    log.info("EARLY: %d snapshots | LATE: %d snapshots", len(early_dates), len(late_dates))

    # Load prices
    prices, sorted_dates = load_prices()
    if not prices:
        log.error("No price data available")
        return 1

    # Build observations
    log.info("Building observations for all %d snapshots...", len(snap_dates))
    all_obs = build_observations(snap_dates, pit_root, prices, sorted_dates)
    log.info("Total observations (snap x ticker x horizon): %d", len(all_obs))

    # Split by period
    early_obs, late_obs = split_observations(all_obs)
    log.info("EARLY obs: %d | LATE obs: %d", len(early_obs), len(late_obs))

    # Compute aggregate IC per period
    log.info("Computing aggregate IC...")
    early_ic = compute_period_ic(early_obs, "EARLY")
    late_ic = compute_period_ic(late_obs, "LATE")
    all_ic = compute_period_ic(all_obs, "ALL")

    # Compute regime delta (LATE - EARLY) for each signal x horizon
    regime_delta: dict = {}
    for hz in HORIZONS:
        regime_delta[f"hz_{hz}d"] = {}
        for sig in SIGNALS:
            e_ic = (early_ic.get(f"hz_{hz}d", {}).get(sig) or {}).get("mean_ic")
            l_ic = (late_ic.get(f"hz_{hz}d", {}).get(sig) or {}).get("mean_ic")
            if e_ic is not None and l_ic is not None:
                regime_delta[f"hz_{hz}d"][sig] = {
                    "early_mean_ic": e_ic,
                    "late_mean_ic": l_ic,
                    "delta": round(l_ic - e_ic, 4),
                    "pct_change": round((l_ic - e_ic) / abs(e_ic) * 100, 1) if abs(e_ic) > EPS else None,
                }
            else:
                regime_delta[f"hz_{hz}d"][sig] = {"early_mean_ic": e_ic, "late_mean_ic": l_ic, "delta": None}

    # Log regime delta summary
    log.info("--- Regime delta (LATE - EARLY) ---")
    for sig in SIGNALS:
        d21 = regime_delta.get("hz_21d", {}).get(sig, {})
        log.info(
            "  %s: 21d early=%.4f late=%.4f delta=%.4f",
            sig,
            d21.get("early_mean_ic") or 0,
            d21.get("late_mean_ic") or 0,
            d21.get("delta") or 0,
        )

    # Slice analysis (optional — slow)
    early_slices: Optional[dict] = None
    late_slices: Optional[dict] = None
    if args.slices:
        log.info("Computing slice IC for EARLY period...")
        early_slices = compute_slice_ic(early_obs, "EARLY")
        log.info("Computing slice IC for LATE period...")
        late_slices = compute_slice_ic(late_obs, "LATE")

    output = {
        "run_ts": run_ts,
        "governance": GOVERNANCE,
        "periods": {
            "EARLY": {
                "date_range": [early_dates[0] if early_dates else None, EARLY_END],
                "n_snapshots": len(early_dates),
            },
            "LATE": {
                "date_range": [LATE_START, late_dates[-1] if late_dates else None],
                "n_snapshots": len(late_dates),
            },
        },
        "aggregate_ic": {
            "ALL": all_ic,
            "EARLY": early_ic,
            "LATE": late_ic,
        },
        "regime_delta": regime_delta,
        "slice_ic": (
            {
                "EARLY": early_slices,
                "LATE": late_slices,
            }
            if args.slices
            else None
        ),
        "signals_evaluated": SIGNALS,
        "horizons_days": HORIZONS,
        "interpretation_note": (
            "Positive delta = signal strengthened in LATE regime. "
            "Negative delta = signal degraded. "
            "Slice IC shows where degradation is concentrated vs broad."
        ),
    }

    # Write output
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = _output_dir() / f"ees_v3_regime_analysis_{run_date}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")
    log.info("Output written: %s", out_path)

    log.info("=== Done === DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
