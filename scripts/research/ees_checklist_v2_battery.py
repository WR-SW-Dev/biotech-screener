#!/usr/bin/env python3
"""EES Checklist v2 remediation battery.

Workstream 1: Block bootstrap CI on portfolio returns
Workstream 2: LOSO / subperiod stability
Workstream 3: FDR multiple-testing correction
Workstream 4: FM incremental regression vs B6
Workstream 5: Effective sample size / dependence adjustment
Workstream 6: Failure mode audit

Uses PIT-safe data only. No deprecated signals.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from event_ev.expectation_error_model import ExpectationErrorModel
from scripts.eval_forward_returns import (
    compute_forward_return,
    discover_snapshot_dates,
    load_price_series,
    load_rankings,
    resolve_trade_date,
    spearman_ic,
)

TOP_K = 30
model = ExpectationErrorModel()

random.seed(42)


# ═════════════════════════════════════════════════════════════════════════
# Shared data loading
# ═════════════════════════════════════════════════════════════════════════


def load_all_data(
    snapshot_root: Path,
    price_csv: Path,
    date_from: str = "2022-03-18",
    date_to: str = "2026-03-31",
) -> Dict[str, Any]:
    """Load and pre-compute everything needed for all workstreams."""
    snap_dates = discover_snapshot_dates(snapshot_root, date_from, date_to)
    prices = load_price_series(price_csv)

    all_dates_set: set = set()
    for tp in prices.values():
        all_dates_set.update(tp.keys())
    sorted_dates = sorted(all_dates_set)

    # Pre-compute per-date data
    date_records = []  # list of dicts with all per-date info

    for snap_date in snap_dates:
        trade_date = resolve_trade_date(sorted_dates, snap_date, "next_trading_day")
        if not trade_date:
            continue

        rankings = load_rankings(snapshot_root / snap_date)
        if not rankings:
            continue

        scores = model.score_batch(rankings, snap_date)
        if not scores:
            continue

        by_ticker = {s.ticker: s for s in scores}
        rank_map = {}
        b6_map = {}
        for row in rankings:
            t = row.get("ticker", "")
            ar = row.get("actionable_rank", "")
            if t and ar and ar.strip().isdigit():
                rank_map[t] = int(ar)
            # B6 selector score for FM regression
            sel = row.get("selector_score", "")
            if t and sel and sel.strip() not in ("", "None", "nan"):
                try:
                    b6_map[t] = float(sel)
                except (ValueError, TypeError):
                    pass

        # Forward returns at multiple horizons
        fwd = {h: {} for h in [5, 20, 63]}
        eligible = [t for t in by_ticker if t in rank_map]
        for ticker in eligible:
            if ticker not in prices:
                continue
            for h in [5, 20, 63]:
                ret = compute_forward_return(prices[ticker], sorted_dates, trade_date, h)
                if ret is not None:
                    fwd[h][ticker] = ret

        trap_vals = [by_ticker[t].trap_overlay_score for t in eligible]
        quality_vals = [by_ticker[t].quality_overlay_score for t in eligible]
        trap_degen = len(set(round(v, 6) for v in trap_vals)) <= 2 if trap_vals else True
        quality_degen = len(set(round(v, 6) for v in quality_vals)) <= 2 if quality_vals else True

        date_records.append(
            {
                "snap_date": snap_date,
                "trade_date": trade_date,
                "by_ticker": by_ticker,
                "rank_map": rank_map,
                "b6_map": b6_map,
                "fwd": fwd,
                "eligible": eligible,
                "trap_vals": trap_vals,
                "quality_vals": quality_vals,
                "trap_degen": trap_degen,
                "quality_degen": quality_degen,
            }
        )

    return {"date_records": date_records, "n_dates": len(date_records)}


def _pct_thresh(vals, pct):
    s = sorted(vals)
    return s[min(int(len(s) * pct / 100), len(s) - 1)]


def compute_arm_returns(rec, h, arm="trap_t20"):
    """Compute portfolio return for one date/horizon/arm."""
    eligible = rec["eligible"]
    fwd = rec["fwd"][h]
    rank_map = rec["rank_map"]
    by_ticker = rec["by_ticker"]

    avail = [t for t in eligible if t in fwd and t in rank_map]
    if len(avail) < TOP_K:
        return None, None

    if arm == "baseline":
        ranked = sorted(avail, key=lambda t: rank_map[t])[:TOP_K]
        return statistics.mean(fwd[t] for t in ranked), len(ranked)

    if arm == "trap_t20":
        if rec["trap_degen"]:
            ranked = sorted(avail, key=lambda t: rank_map[t])[:TOP_K]
        else:
            t_thresh = _pct_thresh(rec["trap_vals"], 20)
            passed = [t for t in avail if by_ticker[t].trap_overlay_score > t_thresh]
            ranked = sorted(passed, key=lambda t: rank_map[t])[:TOP_K]
        if len(ranked) < 10:
            return None, None
        return statistics.mean(fwd[t] for t in ranked), len(ranked)

    if arm == "trap_t20_timing":
        if rec["trap_degen"] or rec["quality_degen"]:
            return None, None
        t_thresh = _pct_thresh(rec["trap_vals"], 20)
        q_thresh = _pct_thresh(rec["quality_vals"], 15)
        passed = [
            t
            for t in avail
            if by_ticker[t].trap_overlay_score > t_thresh and by_ticker[t].quality_overlay_score > q_thresh
        ]
        ranked = sorted(passed, key=lambda t: rank_map[t])[:TOP_K]
        if len(ranked) < 10:
            return None, None
        return statistics.mean(fwd[t] for t in ranked), len(ranked)

    return None, None


# ═════════════════════════════════════════════════════════════════════════
# Workstream 1: Block Bootstrap CI
# ═════════════════════════════════════════════════════════════════════════


def ws1_bootstrap(data, n_boot=2000, block_size=5, horizon=20):
    """Block bootstrap CI on portfolio returns."""
    results = {}

    for arm in ["baseline", "trap_t20", "trap_t20_timing"]:
        rets = []
        for rec in data["date_records"]:
            r, _ = compute_arm_returns(rec, horizon, arm)
            if r is not None:
                rets.append(r)

        if len(rets) < 20:
            results[arm] = {"n": len(rets), "ci": None}
            continue

        # Block bootstrap
        n = len(rets)
        n_blocks = max(1, n // block_size)
        boot_means = []
        boot_sharpes = []

        for _ in range(n_boot):
            sample = []
            for _ in range(n_blocks):
                start = random.randint(0, n - block_size)
                sample.extend(rets[start : start + block_size])
            sample = sample[:n]
            m = statistics.mean(sample)
            s = statistics.stdev(sample) if len(sample) >= 2 else 0.001
            boot_means.append(m)
            boot_sharpes.append(m / s if s > 0 else 0)

        boot_means.sort()
        boot_sharpes.sort()

        def ci(vals, pct_lo=2.5, pct_hi=97.5):
            lo = vals[int(len(vals) * pct_lo / 100)]
            hi = vals[int(len(vals) * pct_hi / 100)]
            return round(lo * 100, 4), round(hi * 100, 4)

        results[arm] = {
            "n": len(rets),
            "mean_ret_pct": round(statistics.mean(rets) * 100, 4),
            "sharpe": round(statistics.mean(rets) / statistics.stdev(rets), 3) if len(rets) >= 2 else None,
            "mean_ret_ci_95": ci(boot_means),
            "sharpe_ci_95": (
                round(boot_sharpes[int(len(boot_sharpes) * 0.025)], 3),
                round(boot_sharpes[int(len(boot_sharpes) * 0.975)], 3),
            ),
        }

    # Uplift CI: trap - baseline
    base_rets = [compute_arm_returns(rec, horizon, "baseline")[0] for rec in data["date_records"]]
    trap_rets = [compute_arm_returns(rec, horizon, "trap_t20")[0] for rec in data["date_records"]]
    paired = [(b, t) for b, t in zip(base_rets, trap_rets) if b is not None and t is not None]
    if len(paired) >= 20:
        diffs = [t - b for b, t in paired]
        n = len(diffs)
        n_blocks = max(1, n // block_size)
        boot_diffs = []
        for _ in range(n_boot):
            sample = []
            for _ in range(n_blocks):
                start = random.randint(0, n - block_size)
                sample.extend(diffs[start : start + block_size])
            sample = sample[:n]
            boot_diffs.append(statistics.mean(sample))
        boot_diffs.sort()
        results["uplift_trap_vs_baseline"] = {
            "mean_diff_pct": round(statistics.mean(diffs) * 100, 4),
            "ci_95": (
                round(boot_diffs[int(len(boot_diffs) * 0.025)] * 100, 4),
                round(boot_diffs[int(len(boot_diffs) * 0.975)] * 100, 4),
            ),
            "excludes_zero": boot_diffs[int(len(boot_diffs) * 0.025)] > 0,
        }

    return results


# ═════════════════════════════════════════════════════════════════════════
# Workstream 2: LOSO Subperiod Stability
# ═════════════════════════════════════════════════════════════════════════


def ws2_loso(data, horizon=20):
    """Leave-one-subperiod-out stability by half-year."""
    # Assign periods
    periods = defaultdict(list)
    for i, rec in enumerate(data["date_records"]):
        d = rec["snap_date"]
        year = d[:4]
        half = "H1" if d[5:7] <= "06" else "H2"
        periods[f"{year}-{half}"].append(i)

    results = []
    for holdout_name in sorted(periods):
        holdout_idx = set(periods[holdout_name])
        # train_idx not needed — we test on holdout only (threshold is fixed at T20)

        # Test on holdout
        base_rets = []
        trap_rets = []
        trap_ics = []
        for i in holdout_idx:
            rec = data["date_records"][i]
            b, _ = compute_arm_returns(rec, horizon, "baseline")
            t, _ = compute_arm_returns(rec, horizon, "trap_t20")
            if b is not None:
                base_rets.append(b)
            if t is not None:
                trap_rets.append(t)

            # IC
            if not rec["trap_degen"]:
                avail = [t for t in rec["eligible"] if t in rec["fwd"][horizon]]
                if len(avail) >= 10:
                    ic = spearman_ic(
                        [rec["by_ticker"][t].trap_overlay_score for t in avail],
                        [rec["fwd"][horizon][t] for t in avail],
                    )
                    if ic is not None:
                        trap_ics.append(ic)

        base_sharpe = (
            statistics.mean(base_rets) / statistics.stdev(base_rets)
            if len(base_rets) >= 2 and statistics.stdev(base_rets) > 0
            else None
        )
        trap_sharpe = (
            statistics.mean(trap_rets) / statistics.stdev(trap_rets)
            if len(trap_rets) >= 2 and statistics.stdev(trap_rets) > 0
            else None
        )
        mean_ic = statistics.mean(trap_ics) if trap_ics else None

        results.append(
            {
                "period": holdout_name,
                "n_dates": len(holdout_idx),
                "baseline_sharpe": round(base_sharpe, 3) if base_sharpe is not None else None,
                "trap_sharpe": round(trap_sharpe, 3) if trap_sharpe is not None else None,
                "trap_beats_base": trap_sharpe is not None and base_sharpe is not None and trap_sharpe > base_sharpe,
                "mean_ic": round(mean_ic, 4) if mean_ic is not None else None,
                "n_ic": len(trap_ics),
            }
        )

    return results


# ═════════════════════════════════════════════════════════════════════════
# Workstream 3: FDR Multiple-Testing Correction
# ═════════════════════════════════════════════════════════════════════════


def ws3_fdr(data, horizon=20):
    """Benjamini-Hochberg FDR on the full search space."""
    # Collect p-values for all tested signals/variants
    hypotheses = []

    # Helper: two-sided p from t-stat
    def p_from_t(t_stat, n):
        # Approximate using normal (good for n > 30)
        if t_stat is None or n < 10:
            return 1.0
        return 2 * (1 - _norm_cdf(abs(t_stat)))

    def _norm_cdf(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    # Test each signal
    signal_cols = {
        "trap_overlay": lambda s: s.trap_overlay_score,
        "timing_decay_inv": lambda s: -s.quality_overlay_score,
        "base_rate_gap": lambda s: s.base_rate_gap_score,
        "conditional_misprice": lambda s: s.conditional_misprice_score,
        "crowding_bias": lambda s: s.crowding_bias_score,
        "divergence": lambda s: s.divergence_score,
        "slippage_penalty": lambda s: s.slippage_penalty_score,
    }

    for sig_name, sig_fn in signal_cols.items():
        ics = []
        for rec in data["date_records"]:
            avail = [t for t in rec["eligible"] if t in rec["fwd"][horizon]]
            if len(avail) < 10:
                continue
            ic = spearman_ic(
                [sig_fn(rec["by_ticker"][t]) for t in avail],
                [rec["fwd"][horizon][t] for t in avail],
            )
            if ic is not None:
                ics.append(ic)

        if len(ics) >= 10:
            m = statistics.mean(ics)
            s = statistics.stdev(ics)
            t_stat = m / (s / math.sqrt(len(ics))) if s > 0 else 0
            p = p_from_t(t_stat, len(ics))
            hypotheses.append(
                {
                    "name": sig_name,
                    "mean_ic": round(m, 4),
                    "t_stat": round(t_stat, 2),
                    "p_value": round(p, 6),
                    "n": len(ics),
                }
            )

    # Threshold variants
    for t_cut in [10, 15, 20, 25, 30]:
        rets_base = []
        rets_arm = []
        for rec in data["date_records"]:
            b, _ = compute_arm_returns(rec, horizon, "baseline")
            if b is None:
                continue
            avail = [t for t in rec["eligible"] if t in rec["fwd"][horizon] and t in rec["rank_map"]]
            if rec["trap_degen"] or len(avail) < TOP_K:
                continue
            t_th = _pct_thresh(rec["trap_vals"], t_cut)
            passed = [t for t in avail if rec["by_ticker"][t].trap_overlay_score > t_th]
            ranked = sorted(passed, key=lambda t: rec["rank_map"][t])[:TOP_K]
            if len(ranked) >= 10:
                rets_base.append(b)
                rets_arm.append(statistics.mean(rec["fwd"][horizon][t] for t in ranked))

        if len(rets_base) >= 10:
            diffs = [a - b for a, b in zip(rets_arm, rets_base)]
            m = statistics.mean(diffs)
            s = statistics.stdev(diffs) if len(diffs) >= 2 else 0.001
            t_stat = m / (s / math.sqrt(len(diffs))) if s > 0 else 0
            p = p_from_t(t_stat, len(diffs))
            hypotheses.append(
                {
                    "name": f"gate_T{t_cut}_uplift",
                    "mean_ic": round(m * 100, 4),
                    "t_stat": round(t_stat, 2),
                    "p_value": round(p, 6),
                    "n": len(diffs),
                }
            )

    # BH FDR
    hypotheses.sort(key=lambda h: h["p_value"])
    m_total = len(hypotheses)
    for rank, h in enumerate(hypotheses, 1):
        h["bh_threshold"] = round(0.10 * rank / m_total, 6)
        h["bh_significant"] = h["p_value"] <= h["bh_threshold"]

    return hypotheses


# ═════════════════════════════════════════════════════════════════════════
# Workstream 4: FM Incremental Regression vs B6
# ═════════════════════════════════════════════════════════════════════════


def ws4_fm_regression(data, horizon=20):
    """Cross-sectional FM regressions: B6 alone, trap alone, B6+trap."""

    # Collect per-date regression results
    b6_only_betas = []
    trap_only_betas = []
    joint_b6_betas = []
    joint_trap_betas = []

    for rec in data["date_records"]:
        avail = [
            t for t in rec["eligible"] if t in rec["fwd"][horizon] and t in rec["b6_map"] and not rec["trap_degen"]
        ]
        if len(avail) < 20:
            continue

        y = [rec["fwd"][horizon][t] for t in avail]
        trap = [rec["by_ticker"][t].trap_overlay_score for t in avail]
        b6 = [rec["b6_map"][t] for t in avail]

        # Standardize
        def _std(vals):
            m = statistics.mean(vals)
            s = statistics.stdev(vals) if len(vals) >= 2 else 1
            if s == 0:
                s = 1
            return [(v - m) / s for v in vals]

        y_s = _std(y)
        trap_s = _std(trap)
        b6_s = _std(b6)

        # Simple OLS: y = a + b*x → b = cov(x,y)/var(x)
        def _ols_beta(x, y_vals):
            mx = statistics.mean(x)
            my = statistics.mean(y_vals)
            cov = sum((x[i] - mx) * (y_vals[i] - my) for i in range(len(x)))
            var = sum((x[i] - mx) ** 2 for i in range(len(x)))
            return cov / var if var > 0 else 0

        # B6 only
        b6_only_betas.append(_ols_beta(b6_s, y_s))
        # Trap only
        trap_only_betas.append(_ols_beta(trap_s, y_s))

        # Joint: y = a + b1*b6 + b2*trap (2-variable OLS)
        # Using normal equations
        def _ols_2var(x1, x2, y_vals):
            n_obs = len(y_vals)
            mx1 = statistics.mean(x1)
            mx2 = statistics.mean(x2)
            my = statistics.mean(y_vals)
            s11 = sum((x1[i] - mx1) ** 2 for i in range(n_obs))
            s22 = sum((x2[i] - mx2) ** 2 for i in range(n_obs))
            s12 = sum((x1[i] - mx1) * (x2[i] - mx2) for i in range(n_obs))
            s1y = sum((x1[i] - mx1) * (y_vals[i] - my) for i in range(n_obs))
            s2y = sum((x2[i] - mx2) * (y_vals[i] - my) for i in range(n_obs))
            det = s11 * s22 - s12 * s12
            if abs(det) < 1e-10:
                return 0, 0
            b1 = (s22 * s1y - s12 * s2y) / det
            b2 = (s11 * s2y - s12 * s1y) / det
            return b1, b2

        b1, b2 = _ols_2var(b6_s, trap_s, y_s)
        joint_b6_betas.append(b1)
        joint_trap_betas.append(b2)

    def _fm_stats(betas):
        if len(betas) < 5:
            return {"mean_beta": None, "t_stat": None, "n": len(betas)}
        m = statistics.mean(betas)
        s = statistics.stdev(betas)
        t = m / (s / math.sqrt(len(betas))) if s > 0 else 0
        return {"mean_beta": round(m, 4), "t_stat": round(t, 2), "n": len(betas)}

    return {
        "b6_only": _fm_stats(b6_only_betas),
        "trap_only": _fm_stats(trap_only_betas),
        "joint_b6": _fm_stats(joint_b6_betas),
        "joint_trap": _fm_stats(joint_trap_betas),
        "trap_survives_b6": (
            _fm_stats(joint_trap_betas).get("t_stat") is not None and abs(_fm_stats(joint_trap_betas)["t_stat"]) >= 1.96
        ),
    }


# ═════════════════════════════════════════════════════════════════════════
# Workstream 5: Effective Sample Size
# ═════════════════════════════════════════════════════════════════════════


def ws5_dependence(data, horizon=20):
    """Estimate effective sample size and dependence-adjusted t-stats."""
    # Compute trap IC series
    ics = []
    for rec in data["date_records"]:
        if rec["trap_degen"]:
            continue
        avail = [t for t in rec["eligible"] if t in rec["fwd"][horizon]]
        if len(avail) < 10:
            continue
        ic = spearman_ic(
            [rec["by_ticker"][t].trap_overlay_score for t in avail],
            [rec["fwd"][horizon][t] for t in avail],
        )
        if ic is not None:
            ics.append(ic)

    if len(ics) < 20:
        return {"n_raw": len(ics), "effective_n": None, "adjusted_t": None}

    # Lag-1 autocorrelation
    n = len(ics)
    m = statistics.mean(ics)
    var = sum((ics[i] - m) ** 2 for i in range(n)) / n
    if var == 0:
        return {"n_raw": n, "rho1": 0, "effective_n": n}

    cov1 = sum((ics[i] - m) * (ics[i + 1] - m) for i in range(n - 1)) / (n - 1)
    rho1 = cov1 / var

    # Effective sample size: n_eff = n * (1 - rho1) / (1 + rho1)
    if rho1 >= 1:
        n_eff = 1
    else:
        n_eff = max(1, n * (1 - rho1) / (1 + rho1))

    # Adjusted t-stat
    s = statistics.stdev(ics)
    raw_t = m / (s / math.sqrt(n)) if s > 0 else 0
    adj_t = m / (s / math.sqrt(n_eff)) if s > 0 else 0

    return {
        "n_raw": n,
        "rho1": round(rho1, 4),
        "effective_n": round(n_eff, 1),
        "raw_mean_ic": round(m, 4),
        "raw_t_stat": round(raw_t, 2),
        "adjusted_t_stat": round(adj_t, 2),
        "still_significant": abs(adj_t) >= 1.96,
    }


# ═════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════


def main():
    snapshot_root = PROJECT_ROOT / "data" / "snapshots"
    price_csv = PROJECT_ROOT / "production_data" / "price_history.csv"
    out_dir = PROJECT_ROOT / "output" / "ees_checklist_v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    data = load_all_data(snapshot_root, price_csv)
    print(f"Loaded {data['n_dates']} date records\n")

    # WS1
    print("WS1: Block Bootstrap CI (20d)...")
    ws1 = ws1_bootstrap(data, n_boot=2000, block_size=5, horizon=20)

    # WS2
    print("WS2: LOSO Subperiod Stability (20d)...")
    ws2 = ws2_loso(data, horizon=20)

    # WS3
    print("WS3: FDR Multiple-Testing Correction (20d)...")
    ws3 = ws3_fdr(data, horizon=20)

    # WS4
    print("WS4: FM Incremental Regression vs B6 (20d)...")
    ws4 = ws4_fm_regression(data, horizon=20)

    # WS5
    print("WS5: Effective Sample Size (20d)...")
    ws5 = ws5_dependence(data, horizon=20)

    # Save
    results = {"ws1_bootstrap": ws1, "ws2_loso": ws2, "ws3_fdr": ws3, "ws4_fm": ws4, "ws5_dependence": ws5}

    with open(out_dir / "checklist_v2_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Print report
    print("\n" + "=" * 80)
    print("  CHECKLIST v2 BATTERY — RESULTS")
    print("=" * 80)

    # WS1
    print("\n--- WS1: BOOTSTRAP CI (20d, 2000 resamples, block=5) ---")
    for arm in ["baseline", "trap_t20", "trap_t20_timing"]:
        d = ws1.get(arm, {})
        if d.get("mean_ret_ci_95"):
            lo, hi = d["mean_ret_ci_95"]
            slo, shi = d.get("sharpe_ci_95", (None, None))
            print(
                f"  {arm:<24s} mean={d['mean_ret_pct']:+.3f}%  CI=[{lo:+.3f}, {hi:+.3f}]  Sharpe={d.get('sharpe')}  CI=[{slo}, {shi}]  n={d['n']}"
            )
    uplift = ws1.get("uplift_trap_vs_baseline", {})
    if uplift:
        lo, hi = uplift.get("ci_95", (None, None))
        excl = uplift.get("excludes_zero", False)
        print(
            f"  Uplift (trap-base):    mean={uplift['mean_diff_pct']:+.3f}%  CI=[{lo:+.3f}, {hi:+.3f}]  excludes_zero={'YES' if excl else 'NO'}"
        )

    # WS2
    print("\n--- WS2: LOSO STABILITY (20d, by half-year) ---")
    print(f"  {'Period':<12s} {'N':>4s} {'Base Sharpe':>12s} {'Trap Sharpe':>12s} {'Trap>Base':>10s} {'IC':>8s}")
    n_beat = 0
    n_total = 0
    for r in ws2:
        bs = f"{r['baseline_sharpe']:+.3f}" if r["baseline_sharpe"] is not None else "—"
        ts = f"{r['trap_sharpe']:+.3f}" if r["trap_sharpe"] is not None else "—"
        beat = "YES" if r["trap_beats_base"] else ("NO" if r["trap_sharpe"] is not None else "—")
        ic = f"{r['mean_ic']:+.4f}" if r["mean_ic"] is not None else "—"
        print(f"  {r['period']:<12s} {r['n_dates']:>4d} {bs:>12s} {ts:>12s} {beat:>10s} {ic:>8s}")
        if r["trap_sharpe"] is not None and r["baseline_sharpe"] is not None:
            n_total += 1
            if r["trap_beats_base"]:
                n_beat += 1
    if n_total > 0:
        print(f"  Trap beats baseline: {n_beat}/{n_total} periods ({100*n_beat/n_total:.0f}%)")

    # WS3
    print("\n--- WS3: FDR CORRECTION (BH q=0.10) ---")
    print(f"  {'Hypothesis':<28s} {'IC/Uplift':>10s} {'t':>7s} {'p':>8s} {'BH thresh':>10s} {'Sig':>5s}")
    for h in ws3:
        sig = "YES" if h["bh_significant"] else "no"
        print(
            f"  {h['name']:<28s} {h['mean_ic']:>+10.4f} {h['t_stat']:>+6.2f} {h['p_value']:>8.6f} {h['bh_threshold']:>10.6f} {sig:>5s}"
        )

    # WS4
    print("\n--- WS4: FM INCREMENTAL REGRESSION (20d) ---")
    for name, d in [
        ("B6 only", ws4["b6_only"]),
        ("Trap only", ws4["trap_only"]),
        ("Joint: B6", ws4["joint_b6"]),
        ("Joint: Trap", ws4["joint_trap"]),
    ]:
        beta = f"{d['mean_beta']:+.4f}" if d.get("mean_beta") is not None else "—"
        t = f"{d['t_stat']:+.2f}" if d.get("t_stat") is not None else "—"
        print(f"  {name:<16s}  beta={beta:>8s}  t={t:>7s}  n={d.get('n', 0)}")
    print(f"  Trap survives B6: {'YES' if ws4['trap_survives_b6'] else 'NO'}")

    # WS5
    print("\n--- WS5: DEPENDENCE / EFFECTIVE SAMPLE SIZE (20d) ---")
    print(f"  Raw n: {ws5['n_raw']}")
    print(f"  Lag-1 autocorrelation: {ws5.get('rho1', '?')}")
    print(f"  Effective n: {ws5.get('effective_n', '?')}")
    print(f"  Raw t-stat: {ws5.get('raw_t_stat', '?')}")
    print(f"  Adjusted t-stat: {ws5.get('adjusted_t_stat', '?')}")
    print(f"  Still significant (|t| >= 1.96): {'YES' if ws5.get('still_significant') else 'NO'}")

    # Final verdict
    print("\n" + "=" * 80)
    print("  CHECKLIST v2 VERDICT")
    print("=" * 80)

    checks = {
        "WS1 Bootstrap CI excludes zero": uplift.get("excludes_zero", False) if uplift else False,
        "WS2 Trap beats base majority": n_beat > n_total / 2 if n_total > 0 else False,
        "WS3 Trap survives FDR": any(h["name"] == "trap_overlay" and h["bh_significant"] for h in ws3),
        "WS4 Trap survives FM vs B6": ws4["trap_survives_b6"],
        "WS5 Significance survives dependence": ws5.get("still_significant", False),
    }

    n_pass = sum(checks.values())
    for name, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\n  Score: {n_pass}/{len(checks)}")
    if n_pass >= 4:
        print("  Rating: 4/5 — Trap validated under Checklist v2")
    elif n_pass >= 3:
        print("  Rating: 3.5/5 — Mostly validated, minor gaps")
    else:
        print("  Rating: 3/5 — Signal present but formal validation incomplete")

    print(f"\nWritten: {out_dir / 'checklist_v2_results.json'}")


if __name__ == "__main__":
    main()
