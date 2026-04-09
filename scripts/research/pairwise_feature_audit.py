#!/usr/bin/env python3
"""Pairwise Feature Audit — Clinical & Financial Within Top-30.

Investigates why clinical_score_v2_z and financial_score have significantly
negative FM coefficients within the top-30 cohort (NW-t = -2.13, -3.18).

Hypotheses:
  H1 (Collider): B6 selection on coinvest+inst creates selection bias that
      inverts the clinical/financial→return relationship.
  H2 (True penalty): Within already-approved names, higher clinical/financial
      proxies for "mature, less volatile, less binary upside."

Tests:
  1. FM within wider cohorts (top-60, top-120, full eligible) — if collider,
     the sign should flip or attenuate as we widen.
  2. Conditional splits: stratify top-30 by high/low clinical and financial,
     compare forward returns.
  3. Interaction with coinvest: does the penalty only exist for high-coinvest
     names? (collider signature)
  4. Feature correlation structure: within top-30, how correlated are clinical
     and financial with coinvest/inst_delta?
  5. Regime splits: is the penalty bear-only or universal?

Usage:
    python3 scripts/research/pairwise_feature_audit.py
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from common.stats.cross_sectional import fama_macbeth

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "pairwise_feature_audit"

AUDIT_FEATURES = ["clinical_score_v2_z", "financial_score"]
CONTEXT_FEATURES = [
    "coinvest_score_z",
    "inst_delta_z",
    "catalyst_decay_w",
    "binary_quality_score",
]
ALL_FEATURES = AUDIT_FEATURES + CONTEXT_FEATURES
HORIZON = "fwd_excess_xbi_63d"
HORIZON_RET = "fwd_ret_63d"


def _sf(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _r(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)


def _safe_mean(vals):
    return statistics.mean(vals) if vals else None


def _safe_tstat(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / (s / len(vals) ** 0.5) if s > 1e-9 else None


def load_panel():
    print("Loading research panel...")
    with open(PANEL_CSV) as f:
        panel = list(csv.DictReader(f))
    print(f"  {len(panel):,} rows")
    return panel


def group_by_snapshot(panel):
    groups = defaultdict(list)
    for row in panel:
        groups[row["snapshot_date"]].append(row)
    return dict(sorted(groups.items()))


def filter_cohort(snapshots, max_rank):
    """Filter snapshots to only include eligible rows within rank threshold."""
    filtered = {}
    for snap_date, rows in snapshots.items():
        cohort = [
            r for r in rows if _sf(r.get("eligible")) == 1.0 and (_sf(r.get("actionable_rank")) or 999) <= max_rank
        ]
        if len(cohort) >= 10:
            filtered[snap_date] = cohort
    return filtered


# ── Test 1: FM Across Widening Cohorts ──────────────────────────────


def test1_widening_cohorts(snapshots):
    """FM on audit features across top-30, top-60, top-120, full eligible."""
    print("\n" + "=" * 70)
    print("TEST 1 — FM ACROSS WIDENING COHORTS (collider test)")
    print("=" * 70)
    print("If collider: sign flips or attenuates as cohort widens.")
    print("If true penalty: sign persists across cohorts.\n")

    cohort_sizes = [30, 60, 120, 999]  # 999 = full eligible
    results = {}

    for feat in AUDIT_FEATURES:
        results[feat] = {}
        for max_rank in cohort_sizes:
            cohort = filter_cohort(snapshots, max_rank)
            label = f"top-{max_rank}" if max_rank < 999 else "full_eligible"

            fm = fama_macbeth(cohort, HORIZON, [feat], nw_lags=3)
            if "error" in fm:
                print(f"  {feat:25s} {label:15s} SKIP ({fm['error']})")
                continue

            sig = fm["signals"].get(feat, {})
            nw_t = sig.get("newey_west_t", 0) or 0
            coef = sig.get("mean_coefficient", 0) or 0
            n_dates = fm.get("n_dates", 0)
            stars = "***" if abs(nw_t) >= 2.58 else "**" if abs(nw_t) >= 1.96 else "*" if abs(nw_t) >= 1.64 else ""
            print(f"  {feat:25s} {label:15s} coef={coef:+.4f}  " f"NW-t={nw_t:+.2f} {stars:3s}  (n={n_dates})")
            results[feat][label] = {
                "coef": _r(coef),
                "nw_t": _r(nw_t),
                "n_dates": n_dates,
            }

    return results


# ── Test 2: High/Low Splits ─────────────────────────────────────────


def test2_conditional_splits(snapshots):
    """Within top-30, split by median clinical/financial and compare returns."""
    print("\n" + "=" * 70)
    print("TEST 2 — CONDITIONAL RETURN SPLITS (top-30)")
    print("=" * 70)

    top30 = filter_cohort(snapshots, 30)
    results = {}

    for feat in AUDIT_FEATURES:
        hi_rets, lo_rets = [], []

        for snap_date, rows in sorted(top30.items()):
            vals = []
            for r in rows:
                fv = _sf(r.get(feat))
                fwd = _sf(r.get(HORIZON))
                if fv is not None and fwd is not None:
                    vals.append((fv, fwd))

            if len(vals) < 10:
                continue

            median_v = sorted(v[0] for v in vals)[len(vals) // 2]
            hi = [v[1] for v in vals if v[0] >= median_v]
            lo = [v[1] for v in vals if v[0] < median_v]

            if hi and lo:
                hi_rets.append(statistics.mean(hi))
                lo_rets.append(statistics.mean(lo))

        hi_mean = _safe_mean(hi_rets)
        lo_mean = _safe_mean(lo_rets)
        spread = (hi_mean - lo_mean) if hi_mean is not None and lo_mean is not None else None
        spread_t = _safe_tstat([h - l for h, l in zip(hi_rets, lo_rets)]) if len(hi_rets) >= 2 else None

        results[feat] = {
            "high_mean_ret": _r(hi_mean),
            "low_mean_ret": _r(lo_mean),
            "spread_pp": _r(spread * 100 if spread else None),
            "spread_tstat": _r(spread_t),
            "n_periods": len(hi_rets),
        }
        print(
            f"  {feat:25s} high={hi_mean or 0:+.4f}  low={lo_mean or 0:+.4f}  "
            f"spread={spread or 0:+.4f} ({(spread or 0) * 100:+.2f}pp)  "
            f"t={spread_t or 0:+.2f}  (n={len(hi_rets)})"
        )

    return results


# ── Test 3: Interaction with Coinvest ────────────────────────────────


def test3_coinvest_interaction(snapshots):
    """Does the penalty only exist for high-coinvest names? (collider signature)"""
    print("\n" + "=" * 70)
    print("TEST 3 — COINVEST INTERACTION (collider signature test)")
    print("=" * 70)
    print("If collider: penalty only in high-coinvest stratum.")
    print("If true penalty: penalty in both strata.\n")

    top30 = filter_cohort(snapshots, 30)
    results = {}

    for feat in AUDIT_FEATURES:
        results[feat] = {}

        for stratum, stratum_label in [("high", "high_coinvest"), ("low", "low_coinvest")]:
            strat_snapshots = {}
            for snap_date, rows in top30.items():
                # Split by median coinvest
                coinvest_vals = [
                    _sf(r.get("coinvest_score_z")) for r in rows if _sf(r.get("coinvest_score_z")) is not None
                ]
                if not coinvest_vals:
                    continue
                median_cv = sorted(coinvest_vals)[len(coinvest_vals) // 2]

                if stratum == "high":
                    stratum_rows = [r for r in rows if (_sf(r.get("coinvest_score_z")) or -999) >= median_cv]
                else:
                    stratum_rows = [r for r in rows if (_sf(r.get("coinvest_score_z")) or -999) < median_cv]
                if len(stratum_rows) >= 5:
                    strat_snapshots[snap_date] = stratum_rows

            fm = fama_macbeth(strat_snapshots, HORIZON, [feat], nw_lags=3)
            if "error" in fm:
                print(f"  {feat:25s} {stratum_label:15s} SKIP")
                continue

            sig = fm["signals"].get(feat, {})
            nw_t = sig.get("newey_west_t", 0) or 0
            coef = sig.get("mean_coefficient", 0) or 0
            stars = "***" if abs(nw_t) >= 2.58 else "**" if abs(nw_t) >= 1.96 else ""
            print(f"  {feat:25s} {stratum_label:15s} coef={coef:+.4f}  " f"NW-t={nw_t:+.2f} {stars}")
            results[feat][stratum_label] = {
                "coef": _r(coef),
                "nw_t": _r(nw_t),
            }

    return results


# ── Test 4: Correlation Structure ────────────────────────────────────


def test4_correlation_structure(snapshots):
    """Correlation matrix within top-30: audit features vs selector features."""
    print("\n" + "=" * 70)
    print("TEST 4 — WITHIN-COHORT CORRELATION STRUCTURE (top-30)")
    print("=" * 70)

    top30 = filter_cohort(snapshots, 30)

    # Pool all top-30 observations
    all_obs = {f: [] for f in ALL_FEATURES + [HORIZON]}
    for snap_date, rows in top30.items():
        for r in rows:
            vals = {}
            skip = False
            for f in ALL_FEATURES + [HORIZON]:
                v = _sf(r.get(f))
                if v is None:
                    skip = True
                    break
                vals[f] = v
            if skip:
                continue
            for f in ALL_FEATURES + [HORIZON]:
                all_obs[f].append(vals[f])

    n_obs = len(all_obs[HORIZON])
    print(f"  {n_obs} pooled observations\n")

    if n_obs < 30:
        print("  Too few observations")
        return {}

    # Compute correlation matrix
    features = ALL_FEATURES + [HORIZON]
    corr_matrix = {}
    for i, f1 in enumerate(features):
        for f2 in features[i:]:
            x = np.array(all_obs[f1])
            y = np.array(all_obs[f2])
            corr = float(np.corrcoef(x, y)[0, 1])
            corr_matrix[f"{f1} × {f2}"] = _r(corr)

    # Print as a focused table: audit features vs everything
    header = f"  {'':25s}"
    for f in features:
        short = f.replace("_score", "").replace("_z", "")[:12]
        header += f" {short:>12s}"
    print(header)

    for f1 in AUDIT_FEATURES:
        row_str = f"  {f1:25s}"
        for f2 in features:
            x = np.array(all_obs[f1])
            y = np.array(all_obs[f2])
            corr = float(np.corrcoef(x, y)[0, 1])
            row_str += f" {corr:+12.3f}"
        print(row_str)

    # Also print forward return correlations
    print()
    row_str = f"  {HORIZON:25s}"
    for f2 in features:
        x = np.array(all_obs[HORIZON])
        y = np.array(all_obs[f2])
        corr = float(np.corrcoef(x, y)[0, 1])
        row_str += f" {corr:+12.3f}"
    print(row_str)

    return corr_matrix


# ── Test 5: Regime-Conditional FM ────────────────────────────────────


def test5_regime_splits(snapshots):
    """FM within top-30, split by regime (bear/neutral/bull)."""
    print("\n" + "=" * 70)
    print("TEST 5 — REGIME-CONDITIONAL FM (top-30)")
    print("=" * 70)

    top30 = filter_cohort(snapshots, 30)
    results = {}

    for regime_label in ["bear", "neutral", "bull"]:
        regime_snaps = {}
        for snap_date, rows in top30.items():
            # Check regime from first row
            regime_vals = [r.get("regime_63d", "") for r in rows if r.get("regime_63d")]
            if not regime_vals:
                continue
            snap_regime = regime_vals[0].lower().strip()
            if (
                snap_regime == regime_label
                or (regime_label == "bull" and "bull" in snap_regime)
                or (regime_label == "bear" and "bear" in snap_regime)
                or (regime_label == "neutral" and "neutral" in snap_regime)
            ):
                regime_snaps[snap_date] = rows

        if len(regime_snaps) < 6:
            print(f"\n  {regime_label}: {len(regime_snaps)} periods (skip, too few)")
            continue

        print(f"\n  {regime_label} ({len(regime_snaps)} periods):")
        for feat in AUDIT_FEATURES:
            fm = fama_macbeth(regime_snaps, HORIZON, [feat], nw_lags=2)
            if "error" in fm:
                print(f"    {feat:25s} SKIP")
                continue
            sig = fm["signals"].get(feat, {})
            nw_t = sig.get("newey_west_t", 0) or 0
            coef = sig.get("mean_coefficient", 0) or 0
            stars = "***" if abs(nw_t) >= 2.58 else "**" if abs(nw_t) >= 1.96 else ""
            print(f"    {feat:25s} coef={coef:+.4f}  NW-t={nw_t:+.2f} {stars}")
            results[f"{feat}_{regime_label}"] = {
                "coef": _r(coef),
                "nw_t": _r(nw_t),
            }

    return results


# ── Test 6: Multivariate Within Top-30 ───────────────────────────────


def test6_multivariate(snapshots):
    """Full multivariate FM within top-30 to see what survives."""
    print("\n" + "=" * 70)
    print("TEST 6 — MULTIVARIATE FM WITHIN TOP-30")
    print("=" * 70)

    top30 = filter_cohort(snapshots, 30)
    fm = fama_macbeth(top30, HORIZON, ALL_FEATURES, nw_lags=3)
    results = {}

    if "error" in fm:
        print(f"  Error: {fm['error']}")
        return results

    print(f"  R² = {fm.get('mean_r_squared', 'N/A')}")
    print(f"  {fm.get('n_dates', 0)} dates\n")

    for sig_name, sig_data in sorted(
        fm["signals"].items(),
        key=lambda x: abs(x[1].get("newey_west_t", 0) or 0),
        reverse=True,
    ):
        if sig_name == "intercept":
            continue
        nw_t = sig_data.get("newey_west_t", 0) or 0
        coef = sig_data.get("mean_coefficient", 0) or 0
        stars = "***" if abs(nw_t) >= 2.58 else "**" if abs(nw_t) >= 1.96 else "*" if abs(nw_t) >= 1.64 else ""
        print(f"  {sig_name:30s} coef={coef:+.4f}  NW-t={nw_t:+.2f} {stars}")
        results[sig_name] = {"coef": _r(coef), "nw_t": _r(nw_t)}

    return results


# ── Main ────────────────────────────────────────────────────────────


def main():
    panel = load_panel()
    snapshots = group_by_snapshot(panel)
    print(f"  {len(snapshots)} snapshots\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_results = {}

    all_results["test1_widening_cohorts"] = test1_widening_cohorts(snapshots)
    all_results["test2_conditional_splits"] = test2_conditional_splits(snapshots)
    all_results["test3_coinvest_interaction"] = test3_coinvest_interaction(snapshots)
    all_results["test4_correlation_structure"] = test4_correlation_structure(snapshots)
    all_results["test5_regime_splits"] = test5_regime_splits(snapshots)
    all_results["test6_multivariate"] = test6_multivariate(snapshots)

    # Write results
    with open(OUTPUT_DIR / "audit_results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # Write memo
    write_memo(all_results, OUTPUT_DIR / "audit_memo.md")

    print(f"\n{'=' * 70}")
    print("PAIRWISE FEATURE AUDIT COMPLETE")
    print(f"{'=' * 70}")
    print(f"Artifacts in: {OUTPUT_DIR}")


def write_memo(results, path):
    lines = [
        "# Pairwise Feature Audit — Clinical & Financial Within Top-30",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Question",
        "Why do `clinical_score_v2_z` (NW-t=−2.13) and `financial_score` (NW-t=−3.18)",
        "show significantly negative FM coefficients within the top-30 cohort?",
        "",
        "## Hypotheses",
        "- **H1 (Collider):** B6 selection creates bias — sign inverts within selected cohort",
        "- **H2 (True penalty):** Higher clinical/financial = mature/less volatile = less upside",
        "",
    ]

    # Test 1
    lines.append("## Test 1: Widening Cohorts")
    t1 = results.get("test1_widening_cohorts", {})
    for feat in AUDIT_FEATURES:
        lines.append(f"\n**{feat}:**")
        fd = t1.get(feat, {})
        for label, vals in sorted(fd.items()):
            lines.append(f"- {label}: coef={vals.get('coef', '---')}, NW-t={vals.get('nw_t', '---')}")

    # Test 2
    lines.append("\n## Test 2: High/Low Return Splits (top-30)")
    t2 = results.get("test2_conditional_splits", {})
    for feat in AUDIT_FEATURES:
        fd = t2.get(feat, {})
        lines.append(f"- **{feat}**: spread={fd.get('spread_pp', '---')}pp " f"(t={fd.get('spread_tstat', '---')})")

    # Test 3
    lines.append("\n## Test 3: Coinvest Interaction")
    t3 = results.get("test3_coinvest_interaction", {})
    for feat in AUDIT_FEATURES:
        fd = t3.get(feat, {})
        for stratum, vals in fd.items():
            lines.append(f"- {feat} | {stratum}: coef={vals.get('coef', '---')}, " f"NW-t={vals.get('nw_t', '---')}")

    # Test 5
    lines.append("\n## Test 5: Regime Splits")
    t5 = results.get("test5_regime_splits", {})
    for key, vals in sorted(t5.items()):
        lines.append(f"- {key}: coef={vals.get('coef', '---')}, NW-t={vals.get('nw_t', '---')}")

    # Test 6
    lines.append("\n## Test 6: Multivariate FM (top-30)")
    t6 = results.get("test6_multivariate", {})
    lines.append("\n| Feature | Coef | NW-t |")
    lines.append("|---------|------|------|")
    for feat, vals in sorted(t6.items(), key=lambda x: abs(x[1].get("nw_t", 0) or 0), reverse=True):
        lines.append(f"| `{feat}` | {vals.get('coef', '---')} | {vals.get('nw_t', '---')} |")

    lines.append("\n## Verdict")
    lines.append("*(Filled after reviewing results)*")
    lines.append("")

    path.write_text("\n".join(lines))
    print(f"  Memo written to: {path}")


if __name__ == "__main__":
    main()
