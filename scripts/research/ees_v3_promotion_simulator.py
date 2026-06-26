"""
EES v3 no-production promotion simulator — diagnostic-only PIT backtest.

Simulates 8 candidate policies for integrating EES v3 into the ranker,
plus a baseline (ranker top quintile alone), using strict PIT data.

Policies:
  base              — final_score top quintile (baseline)
  confirmation      — final_score top-Q AND ees_v3_core top-Q
  veto_core         — final_score top-Q EXCLUDING ees_v3_core bottom-Q
  veto_misprice     — final_score top-Q EXCLUDING ees_v3_misprice_only bottom-Q
  hc_overlay        — final_score top-Q AND ees_v3_native_high_coverage >= median
  independent_sleeve — ees_v3_native_high_coverage top-Q, ignoring ranker
  lh_sleeve         — ranker_low / ees_v3_high disagreement bucket
  blend_90_10       — 0.90*z(final_score) + 0.10*z(ees_v3_native_high_coverage), top-Q
  blend_80_20       — 0.80*z(final_score) + 0.20*z(ees_v3_native_high_coverage), top-Q

Reported per policy × horizon (21d, 42d, 63d):
  IC, Newey-West t-stat, hit_rate, mean_excess_return, top_decile_spread,
  drawdown_proxy, turnover, n_names_avg, overlap_with_ranker_active,
  catalyst_days_mean, market_cap_dist, priced_move_coverage, era breakdown.

GOVERNANCE: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE
No ranker/selector/sizing/final_score/gate/snapshot/portfolio changes.
No model promotion. No cron.

Usage:
    python3 scripts/research/ees_v3_promotion_simulator.py
    python3 scripts/research/ees_v3_promotion_simulator.py --output artifacts/shadow/sim_YYYYMMDD.json
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
VERSION = "1.0"

HORIZONS = [21, 42, 63]
QUINTILE_PCT = 20  # top/bottom quintile threshold
MIN_PAIRS = 5
EPS = 1e-9

EARLY_END = "2024-08-31"
LATE_START = "2024-09-30"

POLICY_NAMES = [
    "base",
    "confirmation",
    "veto_core",
    "veto_misprice",
    "hc_overlay",
    "independent_sleeve",
    "lh_sleeve",
    "blend_90_10",
    "blend_80_20",
]

POLICY_DESCRIPTIONS = {
    "base": "final_score top quintile (baseline)",
    "confirmation": "final_score top-Q AND ees_v3_core top-Q",
    "veto_core": "final_score top-Q EXCLUDING ees_v3_core bottom-Q",
    "veto_misprice": "final_score top-Q EXCLUDING ees_v3_misprice_only bottom-Q (uncovered names kept)",
    "hc_overlay": "final_score top-Q AND ees_v3_native_high_coverage >= median",
    "independent_sleeve": "ees_v3_native_high_coverage top-Q (ranker-independent)",
    "lh_sleeve": "ranker_low / ees_v3_high disagreement bucket",
    "blend_90_10": "0.90*z(final_score) + 0.10*z(ees_v3_native_high_coverage), top-Q",
    "blend_80_20": "0.80*z(final_score) + 0.20*z(ees_v3_native_high_coverage), top-Q",
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _pit_dir() -> Path:
    return _repo_root() / "data" / "snapshots_pit_v2"


def _price_csv() -> Path:
    return _repo_root() / "production_data" / "price_history.csv"


def _shadow_dir() -> Path:
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


def _sb(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def _has_priced_move(row: dict) -> bool:
    val = row.get("priced_move_pct", "")
    if not val or val in ("None", "nan", "0", "0.0", ""):
        return False
    try:
        f = float(val)
        return not math.isnan(f) and f != 0.0
    except (ValueError, TypeError):
        return False


def _percentile_threshold(values: list[float], pct: float) -> float:
    """Return the value at pct-th percentile (bottom pct%)."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(int(len(s) * pct / 100), len(s) - 1))
    return s[idx]


def _top_q_threshold(values: list[float], q_pct: float = QUINTILE_PCT) -> float:
    """Return the value above which a name is in the top q_pct%."""
    return _percentile_threshold(values, 100 - q_pct)


def _bottom_q_threshold(values: list[float], q_pct: float = QUINTILE_PCT) -> float:
    """Return the value below which a name is in the bottom q_pct%."""
    return _percentile_threshold(values, q_pct)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


# ---------------------------------------------------------------------------
# Z-score helpers
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


# ---------------------------------------------------------------------------
# Variant computation
# ---------------------------------------------------------------------------


def compute_variants(rows: list[dict]) -> list[dict]:
    """Add ees_v3_core, ees_v3_misprice_only, ees_v3_native_high_coverage, misprice_available."""
    misprice_raw = [_sf(r.get("conditional_misprice_score")) for r in rows]
    expected_raw = [_sf(r.get("conditional_expected_move")) for r in rows]
    core_scores = [_sf(r.get("ees_v3_score")) for r in rows]
    misprice_avail = [_has_priced_move(r) for r in rows]

    # misprice_only: z-scored within covered subset, None for uncovered
    misprice_for_subset = [m if misprice_avail[i] else None for i, m in enumerate(misprice_raw)]
    v_misprice_only = _z_subset_or_none(misprice_for_subset)

    # native_high_coverage: full 0.70/0.30 composite, z-scored within covered subset
    hi_idx = [i for i, a in enumerate(misprice_avail) if a]
    if len(hi_idx) >= 3:
        hi_mz = _z_full([misprice_raw[i] for i in hi_idx])
        hi_ez = _z_full([expected_raw[i] for i in hi_idx])
        hi_comp = {i: 0.70 * hi_mz[k] + 0.30 * hi_ez[k] for k, i in enumerate(hi_idx)}
        v_hc: list[Optional[float]] = [hi_comp.get(i) for i in range(len(rows))]
    else:
        v_hc = [None] * len(rows)

    result = []
    for i, r in enumerate(rows):
        ext = dict(r)
        ext["ees_v3_core"] = core_scores[i]
        ext["ees_v3_misprice_only"] = v_misprice_only[i]
        ext["ees_v3_native_high_coverage"] = v_hc[i]
        ext["misprice_available"] = misprice_avail[i]
        result.append(ext)
    return result


# ---------------------------------------------------------------------------
# Policy application
# ---------------------------------------------------------------------------


def apply_policies(rows: list[dict]) -> dict[str, dict[str, float]]:
    """
    Return {policy_name: {ticker: policy_score}} for each policy.

    Binary policies: score = 1.0 if selected, 0.0 if not.
    Blend policies: continuous blended score (then top-Q defines "selected").
    All scores are comparable within a policy (not across policies).
    """
    tickers = [r.get("ticker", "") for r in rows]

    # Extract scores
    fs = [_sf(r.get("final_score")) for r in rows]
    v3 = [r.get("ees_v3_core") for r in rows]
    mis = [r.get("ees_v3_misprice_only") for r in rows]
    hc = [r.get("ees_v3_native_high_coverage") for r in rows]
    avail = [r.get("misprice_available", False) for r in rows]

    fs_valid = [v for v in fs if v is not None]
    v3_valid = [v for v in v3 if v is not None]
    hc_valid = [v for v in hc if v is not None]
    mis_valid = [v for v in mis if v is not None]

    if not fs_valid:
        return {p: {} for p in POLICY_NAMES}

    # Thresholds (per-snapshot)
    fs_top_q = _top_q_threshold(fs_valid)
    fs_median = _median(fs_valid)
    v3_top_q = _top_q_threshold(v3_valid) if v3_valid else None
    v3_bot_q = _bottom_q_threshold(v3_valid) if v3_valid else None
    hc_top_q = _top_q_threshold(hc_valid) if hc_valid else None
    hc_median = _median(hc_valid) if hc_valid else None
    mis_bot_q = _bottom_q_threshold(mis_valid) if mis_valid else None
    v3_median = _median(v3_valid) if v3_valid else None

    # Blend z-scores (for blend policies)
    fs_z = _z_full(fs)
    hc_z = _z_full(hc)
    blend_90_10 = [0.90 * fs_z[i] + 0.10 * hc_z[i] for i in range(len(rows))]
    blend_80_20 = [0.80 * fs_z[i] + 0.20 * hc_z[i] for i in range(len(rows))]

    results: dict[str, dict[str, float]] = {p: {} for p in POLICY_NAMES}

    for i, ticker in enumerate(tickers):
        fsi = fs[i]
        v3i = v3[i]
        hci = hc[i]
        misi = mis[i]

        in_fs_top = fsi is not None and fsi >= fs_top_q
        in_fs_low = fsi is None or fsi < fs_median
        in_v3_top = v3i is not None and v3_top_q is not None and v3i >= v3_top_q
        in_v3_bot = v3i is not None and v3_bot_q is not None and v3i <= v3_bot_q
        in_v3_high_for_lh = v3i is not None and v3_median is not None and v3i >= v3_median
        in_hc_top = hci is not None and hc_top_q is not None and hci >= hc_top_q
        in_hc_ge_median = hci is not None and hc_median is not None and hci >= hc_median
        # Misprice veto: only exclude if misprice data available AND score in bottom quintile
        mis_bottom_and_available = avail[i] and misi is not None and mis_bot_q is not None and misi <= mis_bot_q

        results["base"][ticker] = 1.0 if in_fs_top else 0.0
        results["confirmation"][ticker] = 1.0 if (in_fs_top and in_v3_top) else 0.0
        results["veto_core"][ticker] = 1.0 if (in_fs_top and not in_v3_bot) else 0.0
        results["veto_misprice"][ticker] = 1.0 if (in_fs_top and not mis_bottom_and_available) else 0.0
        results["hc_overlay"][ticker] = 1.0 if (in_fs_top and in_hc_ge_median) else 0.0
        results["independent_sleeve"][ticker] = 1.0 if in_hc_top else 0.0
        results["lh_sleeve"][ticker] = 1.0 if (in_fs_low and in_v3_high_for_lh) else 0.0
        results["blend_90_10"][ticker] = blend_90_10[i]
        results["blend_80_20"][ticker] = blend_80_20[i]

    return results


# ---------------------------------------------------------------------------
# Price loading + excess return
# ---------------------------------------------------------------------------


def load_prices() -> tuple[dict[str, dict[str, float]], list[str]]:
    path = _price_csv()
    if not path.exists():
        log.error("Price history not found: %s", path)
        return {}, []
    prices: dict[str, dict[str, float]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t, d, c = row.get("ticker", ""), row.get("date", ""), row.get("close", "")
            if not t or not d or not c:
                continue
            try:
                prices.setdefault(t, {})[d] = float(c)
            except (ValueError, TypeError):
                continue
    all_dates = sorted(set(d for td in prices.values() for d in td))
    log.info("Prices loaded: %d tickers, %d dates", len(prices), len(all_dates))
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
    return ticker_ret - (xbi_fwd - xbi_anch) / xbi_anch


# ---------------------------------------------------------------------------
# IC and stats helpers
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


def _nw_tstat(series: list[float]) -> dict:
    n = len(series)
    if n < 5:
        return {"mean_ic": None, "t_nw": None, "n": n}
    mean = sum(series) / n
    demeaned = [s - mean for s in series]
    max_lag = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    max_lag = max(0, min(max_lag, n - 2))
    gamma_0 = sum(d * d for d in demeaned) / n
    hac_var = gamma_0
    for lag in range(1, max_lag + 1):
        gamma_j = sum(demeaned[t] * demeaned[t - lag] for t in range(lag, n)) / n
        hac_var += 2.0 * (1.0 - lag / (max_lag + 1.0)) * gamma_j
    se = math.sqrt(max(hac_var / n, 1e-20))
    t_nw = mean / se if se > 1e-12 else 0.0
    return {"mean_ic": round(mean, 4), "t_nw": round(t_nw, 2), "n": n}


def _mean_safe(vals: list[float]) -> Optional[float]:
    return round(sum(vals) / len(vals), 4) if vals else None


def _hit_rate(vals: list[float]) -> Optional[float]:
    return round(sum(1 for v in vals if v > 0) / len(vals), 3) if vals else None


def _top_decile_spread(scores: list[float], returns: list[float]) -> Optional[float]:
    """Mean excess return of top decile vs bottom decile."""
    pairs = sorted(zip(scores, returns), key=lambda p: p[0])
    if len(pairs) < 10:
        return None
    q = max(1, len(pairs) // 10)
    bot = _mean_safe([p[1] for p in pairs[:q]])
    top = _mean_safe([p[1] for p in pairs[-q:]])
    if top is None or bot is None:
        return None
    return round(top - bot, 4)


def _drawdown_proxy(per_date_excess: list[float]) -> dict:
    """Max consecutive negative periods and worst single-period excess."""
    if not per_date_excess:
        return {"max_consecutive_neg": 0, "worst_period": None}
    worst = min(per_date_excess)
    max_streak = 0
    cur = 0
    for v in per_date_excess:
        if v < 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    return {"max_consecutive_neg": max_streak, "worst_period": round(worst, 4)}


def _turnover(prev_selected: set[str], curr_selected: set[str]) -> Optional[float]:
    if not prev_selected and not curr_selected:
        return None
    union = len(prev_selected | curr_selected)
    if union == 0:
        return None
    inter = len(prev_selected & curr_selected)
    return round(1 - inter / union, 3)


# ---------------------------------------------------------------------------
# Main observation builder
# ---------------------------------------------------------------------------


def build_all_observations(snap_dates: list[str], pit_root: Path, prices: dict, sorted_dates: list) -> list[dict]:
    """Build one observation per (snap_date, ticker, horizon) with all policy scores."""
    all_obs: list[dict] = []
    prev_selections: dict[str, set[str]] = {p: set() for p in POLICY_NAMES}

    n_snaps = len(snap_dates)
    for snap_idx, snap_date in enumerate(snap_dates):
        if snap_idx % 10 == 0:
            log.info("  Snapshot %d/%d: %s", snap_idx + 1, n_snaps, snap_date)

        path = pit_root / snap_date / "rankings.csv"
        if not path.exists():
            continue
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue

        # Add variants
        rows = compute_variants(rows)

        # Apply policies
        policy_scores = apply_policies(rows)

        # Diagnostics per ticker
        ticker_meta: dict[str, dict] = {}
        fs_vals = [_sf(r.get("final_score")) for r in rows]
        fs_valid = [v for v in fs_vals if v is not None]
        fs_top_q = _top_q_threshold(fs_valid) if fs_valid else 0.0
        for r in rows:
            t = r.get("ticker", "")
            ticker_meta[t] = {
                "market_cap_bucket": r.get("market_cap_bucket", "unknown") or "unknown",
                "catalyst_days": _sf(r.get("catalyst_days")),
                "priced_move_available": r.get("misprice_available", False),
                "ranker_active": _sb(r.get("ranker_active", False)),
                "in_ranker_top_q": (
                    _sf(r.get("final_score")) is not None and _sf(r.get("final_score")) >= fs_top_q
                    if fs_valid
                    else False
                ),
            }

        # Blend "selected" sets for turnover: top quintile of blended score
        blend_90_scores = [(t, policy_scores["blend_90_10"].get(t, 0.0)) for r in rows for t in [r.get("ticker", "")]]
        blend_90_scores.sort(key=lambda x: -x[1])
        top_q_n = max(1, len(blend_90_scores) * QUINTILE_PCT // 100)
        blend_90_selected = set(t for t, _ in blend_90_scores[:top_q_n])

        blend_80_scores = [(t, policy_scores["blend_80_20"].get(t, 0.0)) for r in rows for t in [r.get("ticker", "")]]
        blend_80_scores.sort(key=lambda x: -x[1])
        blend_80_selected = set(t for t, _ in blend_80_scores[:top_q_n])

        # Effective selected sets for all policies (for turnover and exposure)
        effective_selected: dict[str, set[str]] = {}
        for p in POLICY_NAMES:
            if p in ("blend_90_10",):
                effective_selected[p] = blend_90_selected
            elif p in ("blend_80_20",):
                effective_selected[p] = blend_80_selected
            else:
                effective_selected[p] = {t for t, s in policy_scores[p].items() if s >= 0.5}

        # Compute forward returns per ticker × horizon
        ticker_returns: dict[str, dict[int, Optional[float]]] = {}
        for r in rows:
            t = r.get("ticker", "")
            ticker_returns[t] = {}
            for hz in HORIZONS:
                ticker_returns[t][hz] = _excess_return(t, snap_date, hz, prices, sorted_dates)

        # Turnover vs previous period
        snap_turnover: dict[str, Optional[float]] = {}
        for p in POLICY_NAMES:
            snap_turnover[p] = _turnover(prev_selections[p], effective_selected[p])
        prev_selections = effective_selected

        # Build observations
        for r in rows:
            t = r.get("ticker", "")
            meta = ticker_meta.get(t, {})
            for hz in HORIZONS:
                obs: dict = {
                    "snap_date": snap_date,
                    "ticker": t,
                    "horizon": hz,
                    "excess_return": ticker_returns[t].get(hz),
                    "market_cap_bucket": meta.get("market_cap_bucket", "unknown"),
                    "catalyst_days": meta.get("catalyst_days"),
                    "priced_move_available": meta.get("priced_move_available", False),
                    "ranker_active": meta.get("ranker_active", False),
                    "in_ranker_top_q": meta.get("in_ranker_top_q", False),
                }
                for p in POLICY_NAMES:
                    obs[f"score_{p}"] = policy_scores[p].get(t, 0.0)
                    obs[f"selected_{p}"] = t in effective_selected[p]
                obs["turnover"] = {p: snap_turnover[p] for p in POLICY_NAMES}
                all_obs.append(obs)

    return all_obs


# ---------------------------------------------------------------------------
# Aggregation per policy
# ---------------------------------------------------------------------------


def aggregate_policy(all_obs: list[dict], policy: str, hz: int) -> dict:
    """Compute all metrics for one policy × horizon combination."""
    hz_obs = [o for o in all_obs if o["horizon"] == hz]
    if not hz_obs:
        return {"error": "no observations"}

    # Separate: observations for selected vs all vs with returns
    selected_obs = [o for o in hz_obs if o.get(f"selected_{policy}")]
    selected_with_ret = [o for o in selected_obs if o.get("excess_return") is not None]
    all_with_ret = [o for o in hz_obs if o.get("excess_return") is not None]

    # IC: per-date Spearman of policy score vs excess return (across all names)
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for o in all_with_ret:
        score = o.get(f"score_{policy}")
        ret = o.get("excess_return")
        if score is not None and ret is not None:
            by_date[o["snap_date"]].append((score, ret))

    ics: list[float] = []
    for pairs in by_date.values():
        if len(pairs) < MIN_PAIRS:
            continue
        xs, ys = zip(*pairs)
        ic = _spearman_ic(list(xs), list(ys))
        if ic is not None:
            ics.append(ic)

    nw = _nw_tstat(ics) if ics else {"mean_ic": None, "t_nw": None, "n": 0}

    # Mean excess return: selected set per date → mean over dates
    by_date_selected: dict[str, list[float]] = defaultdict(list)
    for o in selected_with_ret:
        by_date_selected[o["snap_date"]].append(o["excess_return"])

    per_date_excess = [_mean_safe(v) for v in by_date_selected.values() if v]
    per_date_excess_vals = [v for v in per_date_excess if v is not None]

    mean_excess = _mean_safe(per_date_excess_vals)
    hit_rate_dates = _hit_rate(per_date_excess_vals)

    # Also compute per-date excess for base (ranker top-Q) for comparison
    by_date_base: dict[str, list[float]] = defaultdict(list)
    for o in all_with_ret:
        if o.get("selected_base"):
            by_date_base[o["snap_date"]].append(o["excess_return"])
    per_date_base = [_mean_safe(v) for v in by_date_base.values() if v]
    per_date_base_vals = [v for v in per_date_base if v is not None]
    mean_excess_base = _mean_safe(per_date_base_vals)

    # Top-decile spread within selected set (for ranked policies)
    all_scores = [o.get(f"score_{policy}", 0.0) for o in all_with_ret]
    all_rets = [o["excess_return"] for o in all_with_ret]
    td_spread = _top_decile_spread(all_scores, all_rets)

    # Drawdown proxy: per-date mean excess of selected set
    drawdown = _drawdown_proxy(per_date_excess_vals)

    # Turnover: mean across all snapshots
    all_turnover = [o["turnover"].get(policy) for o in hz_obs if o.get("turnover", {}).get(policy) is not None]
    mean_turnover = _mean_safe([v for v in all_turnover if v is not None])

    # N names: avg selected per snapshot
    by_date_n: dict[str, int] = defaultdict(int)
    for o in hz_obs:
        if o.get(f"selected_{policy}"):
            by_date_n[o["snap_date"]] += 1
    n_names_avg = _mean_safe(list(by_date_n.values())) if by_date_n else 0.0

    # Overlap with ranker_active
    n_selected = sum(1 for o in selected_obs)
    n_both_active = sum(1 for o in selected_obs if o.get("ranker_active"))
    overlap_ranker_active = round(n_both_active / n_selected, 3) if n_selected else None

    # Catalyst timing exposure
    cat_days = [o["catalyst_days"] for o in selected_obs if o.get("catalyst_days") is not None]
    catalyst_days_mean = _mean_safe(cat_days)

    # Market cap distribution
    mcap_dist: dict[str, int] = defaultdict(int)
    for o in selected_obs:
        mcap_dist[o.get("market_cap_bucket", "unknown")] += 1

    # Priced_move coverage
    n_sel_with_priced = sum(1 for o in selected_obs if o.get("priced_move_available"))
    priced_move_coverage = round(n_sel_with_priced / n_selected, 3) if n_selected else None

    # Era concentration
    early_sel = [o for o in selected_with_ret if o["snap_date"] <= EARLY_END]
    late_sel = [o for o in selected_with_ret if o["snap_date"] >= LATE_START]

    def _era_stats(obs: list[dict]) -> Optional[dict]:
        by_d: dict[str, list[float]] = defaultdict(list)
        for o in obs:
            by_d[o["snap_date"]].append(o["excess_return"])
        per_d = [_mean_safe(v) for v in by_d.values() if v]
        per_d_v = [v for v in per_d if v is not None]
        return (
            {
                "mean_excess_return": _mean_safe(per_d_v),
                "hit_rate": _hit_rate(per_d_v),
                "n_dates": len(per_d_v),
            }
            if per_d_v
            else None
        )

    return {
        "ic": nw,
        "hit_rate_dates": hit_rate_dates,
        "mean_excess_return_selected": mean_excess,
        "mean_excess_return_base": mean_excess_base,
        "excess_vs_base": (
            round(mean_excess - mean_excess_base, 4)
            if mean_excess is not None and mean_excess_base is not None
            else None
        ),
        "top_decile_spread": td_spread,
        "drawdown_proxy": drawdown,
        "turnover_mean": mean_turnover,
        "n_names_avg": round(n_names_avg, 1) if n_names_avg is not None else None,
        "n_total_selected": n_selected,
        "overlap_with_ranker_active": overlap_ranker_active,
        "catalyst_days_mean": catalyst_days_mean,
        "market_cap_dist": dict(sorted(mcap_dist.items())),
        "priced_move_coverage": priced_move_coverage,
        "era": {
            "EARLY": _era_stats(early_sel),
            "LATE": _era_stats(late_sel),
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EES v3 promotion simulator — DIAGNOSTIC_ONLY")
    p.add_argument("--output", default=None, help="Output path (default: artifacts/shadow/)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_date = run_ts[:10]

    log.info("=== EES v3 Promotion Simulator ===")
    log.info("run_ts=%s | GOVERNANCE: %s", run_ts, GOVERNANCE)
    log.info("Policies: %s", POLICY_NAMES)
    log.info("Horizons: %s | Top-Q: %d%%", HORIZONS, QUINTILE_PCT)

    pit_root = _pit_dir()
    if not pit_root.exists():
        log.error("PIT snapshots not found: %s", pit_root)
        return 1

    snap_dates = sorted(d.name for d in pit_root.iterdir() if d.is_dir() and (d / "rankings.csv").exists())
    log.info("PIT snapshots: %d (%s → %s)", len(snap_dates), snap_dates[0], snap_dates[-1])

    prices, sorted_dates = load_prices()
    if not prices:
        log.error("No price data")
        return 1

    # Build observations
    log.info("Building observations (76 snapshots × tickers × 3 horizons)...")
    all_obs = build_all_observations(snap_dates, pit_root, prices, sorted_dates)
    log.info("Total observations: %d", len(all_obs))

    # Aggregate per policy × horizon
    log.info("Aggregating per policy × horizon...")
    results: dict[str, dict] = {}
    for policy in POLICY_NAMES:
        log.info("  Policy: %s", policy)
        results[policy] = {
            "description": POLICY_DESCRIPTIONS[policy],
        }
        for hz in HORIZONS:
            stats = aggregate_policy(all_obs, policy, hz)
            results[policy][f"hz_{hz}d"] = stats
            ic_val = (stats.get("ic") or {}).get("mean_ic")
            t_val = (stats.get("ic") or {}).get("t_nw")
            excess = stats.get("mean_excess_return_selected")
            vs_base = stats.get("excess_vs_base")
            log.info(
                "    hz=%dd | IC=%.4f t=%.2f | excess=%.4f vs_base=%s | n_avg=%.1f | turnover=%s",
                hz,
                ic_val or 0,
                t_val or 0,
                excess or 0,
                f"{vs_base:+.4f}" if vs_base is not None else "N/A",
                stats.get("n_names_avg") or 0,
                f"{stats.get('turnover_mean'):.3f}" if stats.get("turnover_mean") is not None else "N/A",
            )

    # Build output
    output = {
        "run_ts": run_ts,
        "governance": GOVERNANCE,
        "simulator_version": VERSION,
        "n_pit_snapshots": len(snap_dates),
        "pit_range": [snap_dates[0], snap_dates[-1]],
        "horizons_days": HORIZONS,
        "top_quintile_pct": QUINTILE_PCT,
        "era_split": {"EARLY_end": EARLY_END, "LATE_start": LATE_START},
        "policies": results,
        "interpretation_notes": {
            "ic": "Spearman IC of policy score vs excess return, per-date then mean. Newey-West t-stat corrects for autocorrelation.",
            "binary_ic_note": "For binary selection policies (score=0/1), IC measures whether selected=1 predicts higher returns. Low IC is expected; prefer mean_excess_return.",
            "excess_vs_base": "Mean excess return of policy's selected set minus base (ranker top-Q) selected set per date.",
            "turnover": "1 - Jaccard overlap in selected set between consecutive monthly snapshots.",
            "drawdown_proxy": "max_consecutive_neg = longest streak of monthly periods with negative mean excess return.",
            "era": "EARLY = 2020-01-31 to 2024-08-31 | LATE = 2024-09-30 to 2026-04-16.",
        },
    }

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = _shadow_dir() / f"ees_v3_promotion_simulator_{run_date}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")
    log.info("Output written: %s", out_path)

    # Print summary table
    log.info("=== SUMMARY TABLE (21d IC, excess return vs base) ===")
    log.info("%-26s %8s %7s %10s %10s %8s", "Policy", "IC_21d", "t_NW", "Excess", "vs_Base", "N_avg")
    for p in POLICY_NAMES:
        hz_r = results[p].get("hz_21d", {})
        ic_d = hz_r.get("ic") or {}
        log.info(
            "  %-24s %8s %7s %10s %10s %8s",
            p,
            f"{ic_d.get('mean_ic') or 0:.4f}",
            f"{ic_d.get('t_nw') or 0:.2f}",
            f"{hz_r.get('mean_excess_return_selected') or 0:.4f}",
            f"{hz_r.get('excess_vs_base') or 0:+.4f}",
            f"{hz_r.get('n_names_avg') or 0:.1f}",
        )

    log.info("=== Done === DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
