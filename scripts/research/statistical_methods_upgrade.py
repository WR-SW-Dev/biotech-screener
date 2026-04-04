#!/usr/bin/env python3
"""Spec 055 — Statistical Methods Upgrade Pass.

Runs all 6 statistical methods on the research panel and existing
signal/model results. Produces structured artifacts for each method.

Usage:
    python3 scripts/research/statistical_methods_upgrade.py
    python3 scripts/research/statistical_methods_upgrade.py --method fama_macbeth
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from common.stats.bootstrap import block_bootstrap, compare_strategies
from common.stats.calibration import calibration_report
from common.stats.cross_sectional import fama_macbeth, run_incremental_test
from common.stats.multiple_testing import benjamini_hochberg, whites_reality_check
from common.stats.robustness import multi_slice_robustness
from common.stats.survival import cox_ph_simple, kaplan_meier, stratified_kaplan_meier

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "statistical_methods"

# Signal groups for testing
INCUMBENT_CONTROLS = ["coinvest_score_z", "inst_delta_z"]
RISK_CONTROLS = ["financial_score"]

CANDIDATE_SIGNALS = [
    # Institutional block
    "coinvest_score_z",
    "inst_delta_z",
    # Risk block
    "financial_score",
    # Clinical block
    "clinical_score_v2_z",
    # Options block
    "cheap_vol_score",
    "ovf11_score",
    "opt_atm_iv",
    # Insider block
    "insider_net_buy_value_90d",
    "insider_exec_buy_value_90d",
    # Execution block
    "aact_execution_score",
    # Pipeline scale
    "competitive_intensity_z",
]

SELECTOR_SIGNALS_FOR_BOOTSTRAP = [
    "coinvest_score_z",
    "inst_delta_z",
    "cheap_vol_score",
    "aact_execution_score",
    "insider_net_buy_value_90d",
    "clinical_score_v2_z",
]


def _sf(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f if not math.isnan(f) else None
    except (ValueError, TypeError):
        return None


def _round(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)


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


# ── Method 1: Fama-MacBeth Cross-Sectional Regression ────────────────


def run_fama_macbeth(snapshots):
    print("\n" + "=" * 70)
    print("METHOD 1 — FAMA-MACBETH CROSS-SECTIONAL REGRESSIONS")
    print("=" * 70)

    results = {"method": "fama_macbeth", "models": {}, "incremental_tests": {}}

    # Model 1: Each candidate signal univariate
    print("\n  1a. Univariate regressions...")
    for signal in CANDIDATE_SIGNALS:
        fm = fama_macbeth(snapshots, "fwd_excess_xbi_63d", [signal], nw_lags=3)
        if "error" in fm:
            print(f"    {signal}: SKIP ({fm['error']})")
            continue
        sig = fm["signals"].get(signal, {})
        nw_t = sig.get("newey_west_t", 0) or 0
        coef = sig.get("mean_coefficient", 0) or 0
        print(f"    {signal}: coef={coef:+.4f} NW-t={nw_t:+.2f} "
              f"{'***' if abs(nw_t) >= 2.58 else '**' if abs(nw_t) >= 1.96 else '*' if abs(nw_t) >= 1.64 else ''}")
        results["models"][f"univariate_{signal}"] = fm

    # Model 2: Incumbent controls only
    print("\n  1b. Incumbent controls...")
    controls_fm = fama_macbeth(
        snapshots, "fwd_excess_xbi_63d",
        INCUMBENT_CONTROLS + RISK_CONTROLS, nw_lags=3,
    )
    if "error" not in controls_fm:
        for sig_name, sig_data in controls_fm["signals"].items():
            if sig_name == "intercept":
                continue
            nw_t = sig_data.get("newey_west_t", 0) or 0
            print(f"    {sig_name}: NW-t={nw_t:+.2f}")
        results["models"]["incumbent_controls"] = controls_fm

    # Model 3: Incremental tests for each non-incumbent signal
    print("\n  1c. Incremental tests (candidate + incumbent controls)...")
    test_signals = [
        s for s in CANDIDATE_SIGNALS
        if s not in INCUMBENT_CONTROLS and s not in RISK_CONTROLS
    ]
    for signal in test_signals:
        inc = run_incremental_test(
            snapshots, signal, INCUMBENT_CONTROLS + RISK_CONTROLS,
        )
        if "error" in inc.get("incremental", {}):
            continue
        uni_t = inc["univariate"].get("nw_t", 0) or 0
        inc_t = inc["incremental"].get("nw_t", 0) or 0
        verdict = inc["verdict"]
        print(f"    {signal}: uni-t={uni_t:+.2f} → incr-t={inc_t:+.2f} → {verdict}")
        results["incremental_tests"][signal] = inc

    # Model 4: Full block model
    print("\n  1d. Full block model...")
    all_signals = [
        s for s in CANDIDATE_SIGNALS
        if s not in RISK_CONTROLS  # risk is in controls
    ]
    full_fm = fama_macbeth(
        snapshots, "fwd_excess_xbi_63d", all_signals, nw_lags=3,
    )
    if "error" not in full_fm:
        print(f"    R² = {full_fm.get('mean_r_squared', 'N/A')}")
        for sig_name, sig_data in sorted(
            full_fm["signals"].items(),
            key=lambda x: abs(x[1].get("newey_west_t", 0) or 0),
            reverse=True,
        ):
            if sig_name == "intercept":
                continue
            nw_t = sig_data.get("newey_west_t", 0) or 0
            survives = sig_data.get("survives_controls", False)
            print(f"    {sig_name:30s} NW-t={nw_t:+.2f} {'✓' if survives else '✗'}")
        results["models"]["full_block"] = full_fm

    return results


# ── Method 2: Block Bootstrap ────────────────────────────────────────


def run_bootstrap(snapshots):
    print("\n" + "=" * 70)
    print("METHOD 2 — BLOCK BOOTSTRAP ON PORTFOLIO RETURNS")
    print("=" * 70)

    results = {"method": "block_bootstrap", "strategies": {}, "comparisons": {}}

    # Compute monthly excess returns for top-30 by each signal
    strategy_returns = {}
    for signal in SELECTOR_SIGNALS_FOR_BOOTSTRAP:
        higher_better = signal not in ("opt_atm_iv",)
        monthly_rets = []
        for snap_date in sorted(snapshots.keys()):
            rows = snapshots[snap_date]
            eligible = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal))
                fwd = _sf(r.get("fwd_excess_xbi_63d"))
                rank = _sf(r.get("actionable_rank"))
                if sv is not None and fwd is not None and rank is not None:
                    eligible.append({"signal": sv, "fwd": fwd, "rank": rank})
            if len(eligible) < 30:
                continue
            if higher_better:
                by_signal = sorted(eligible, key=lambda x: -x["signal"])
            else:
                by_signal = sorted(eligible, key=lambda x: x["signal"])
            top30_ret = np.mean([e["fwd"] for e in by_signal[:30]])
            monthly_rets.append(top30_ret)

        if len(monthly_rets) >= 12:
            strategy_returns[signal] = monthly_rets

    # Also compute baseline (top-30 by actionable_rank)
    baseline_rets = []
    for snap_date in sorted(snapshots.keys()):
        rows = snapshots[snap_date]
        eligible = []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            fwd = _sf(r.get("fwd_excess_xbi_63d"))
            rank = _sf(r.get("actionable_rank"))
            if fwd is not None and rank is not None:
                eligible.append({"fwd": fwd, "rank": rank})
        if len(eligible) < 30:
            continue
        by_rank = sorted(eligible, key=lambda x: x["rank"])
        baseline_rets.append(np.mean([e["fwd"] for e in by_rank[:30]]))

    if len(baseline_rets) >= 12:
        strategy_returns["baseline_rank"] = baseline_rets

    # Bootstrap each strategy
    print("\n  Individual strategy bootstraps:")
    for name, rets in strategy_returns.items():
        boot = block_bootstrap(rets, block_length=6, n_bootstrap=10000, seed=42)
        results["strategies"][name] = boot
        ci_str = f"[{boot.get('ci_lower', '?'):.4f}, {boot.get('ci_upper', '?'):.4f}]"
        excl = "CI excl 0" if boot.get("ci_excludes_zero") else "CI includes 0"
        print(f"    {name:30s} mean={boot.get('boot_mean', 0):+.4f} "
              f"95% CI={ci_str} P(>0)={boot.get('prob_positive', 0):.2f} {excl}")

    # Pairwise comparisons vs baseline
    if "baseline_rank" in strategy_returns:
        print("\n  Strategy vs baseline comparisons:")
        base = strategy_returns["baseline_rank"]
        for name, rets in strategy_returns.items():
            if name == "baseline_rank":
                continue
            # Align lengths (use min length)
            min_len = min(len(base), len(rets))
            comp = compare_strategies(
                rets[:min_len], base[:min_len],
                labels=(name, "baseline_rank"),
                block_length=6, n_bootstrap=10000, seed=42,
            )
            results["comparisons"][name] = comp
            prob = comp.get("prob_a_better", 0) or 0
            diff = comp.get("mean_diff", 0) or 0
            excl = "sig" if comp.get("ci_excludes_zero") else "n.s."
            print(f"    {name:30s} Δ={diff:+.4f} P(beats baseline)={prob:.2f} {excl}")

    return results


# ── Method 3: Multiple-Testing Correction ────────────────────────────


def run_multiple_testing(snapshots, fm_results):
    print("\n" + "=" * 70)
    print("METHOD 3 — MULTIPLE-TESTING CORRECTION")
    print("=" * 70)

    results = {"method": "multiple_testing"}

    # Collect p-values from Fama-MacBeth univariate models
    univariate_pvals = {}
    for key, model in fm_results.get("models", {}).items():
        if not key.startswith("univariate_"):
            continue
        signal = key.replace("univariate_", "")
        for sig_name, sig_data in model.get("signals", {}).items():
            if sig_name == "intercept":
                continue
            p = sig_data.get("p_value")
            if p is not None:
                univariate_pvals[signal] = p

    # Collect p-values from incremental tests
    incremental_pvals = {}
    for signal, test in fm_results.get("incremental_tests", {}).items():
        p = test.get("incremental", {}).get("p_value")
        if p is not None:
            incremental_pvals[signal] = p

    # BH FDR on univariate family
    print("\n  3a. BH FDR on univariate signal family...")
    if univariate_pvals:
        bh_uni = benjamini_hochberg(univariate_pvals, alpha=0.10)
        results["bh_univariate"] = bh_uni
        for name in sorted(univariate_pvals, key=univariate_pvals.get):
            r = bh_uni["results"][name]
            status = "REJECT" if r["rejected"] else "retain"
            print(f"    {name:30s} p={r['raw_p']:.4f} q={r['q_value']:.4f} → {status}")
        print(f"    → {bh_uni['n_rejected']}/{bh_uni['n_tests']} rejected at FDR=0.10")

    # BH FDR on incremental family
    print("\n  3b. BH FDR on incremental tests...")
    if incremental_pvals:
        bh_inc = benjamini_hochberg(incremental_pvals, alpha=0.10)
        results["bh_incremental"] = bh_inc
        for name in sorted(incremental_pvals, key=incremental_pvals.get):
            r = bh_inc["results"][name]
            status = "REJECT" if r["rejected"] else "retain"
            print(f"    {name:30s} p={r['raw_p']:.4f} q={r['q_value']:.4f} → {status}")
        print(f"    → {bh_inc['n_rejected']}/{bh_inc['n_tests']} rejected at FDR=0.10")

    # White's Reality Check on selector strategies
    print("\n  3c. White's Reality Check on selector signals...")
    selector_monthly = {}
    for signal in SELECTOR_SIGNALS_FOR_BOOTSTRAP:
        higher_better = signal not in ("opt_atm_iv",)
        monthly = []
        for snap_date in sorted(snapshots.keys()):
            rows = snapshots[snap_date]
            eligible = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal))
                fwd = _sf(r.get("fwd_excess_xbi_63d"))
                rank = _sf(r.get("actionable_rank"))
                if sv is not None and fwd is not None and rank is not None:
                    eligible.append({"signal": sv, "fwd": fwd, "rank": rank})
            if len(eligible) < 30:
                monthly.append(0.0)
                continue
            by_rank = sorted(eligible, key=lambda x: x["rank"])[:30]
            baseline = np.mean([e["fwd"] for e in by_rank])
            if higher_better:
                by_signal = sorted(eligible, key=lambda x: -x["signal"])
            else:
                by_signal = sorted(eligible, key=lambda x: x["signal"])
            selected = np.mean([e["fwd"] for e in by_signal[:30]])
            monthly.append(selected - baseline)

        if monthly:
            selector_monthly[signal] = monthly

    if selector_monthly:
        # Align lengths
        min_len = min(len(v) for v in selector_monthly.values())
        aligned = {k: v[:min_len] for k, v in selector_monthly.items()}
        wrc = whites_reality_check(aligned, n_bootstrap=10000, block_length=6, seed=42)
        results["whites_rc"] = wrc
        print(f"    Best: {wrc.get('best_strategy')} (mean={wrc.get('best_mean', 0):.4f})")
        print(f"    WRC p-value: {wrc.get('wrc_p_value', 'N/A')}")
        print(f"    Significant at 5%: {wrc.get('significant_at_05')}")

    return results


# ── Method 4: Pairwise Score Calibration ─────────────────────────────


def run_calibration(panel, snapshots):
    print("\n" + "=" * 70)
    print("METHOD 4 — PAIRWISE SCORE CALIBRATION")
    print("=" * 70)

    results = {"method": "calibration"}

    # Build pairwise outcomes: for each pair in top-60, did higher-scored
    # name outperform lower-scored name over 63d?
    # Use coinvest_score_z as the score (production selector anchor)
    all_predicted = []
    all_actual = []

    for snap_date in sorted(snapshots.keys()):
        rows = snapshots[snap_date]
        eligible = []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            rank = _sf(r.get("actionable_rank"))
            if rank is None or rank > 60:
                continue
            cv = _sf(r.get("coinvest_score_z"))
            fwd = _sf(r.get("fwd_ret_63d"))
            if cv is not None and fwd is not None:
                eligible.append({"coinvest": cv, "fwd": fwd})

        if len(eligible) < 10:
            continue

        # Generate pairs
        for i in range(len(eligible)):
            for j in range(i + 1, min(len(eligible), i + 10)):
                diff_score = eligible[i]["coinvest"] - eligible[j]["coinvest"]
                # Predict: higher coinvest → higher return
                from scipy.special import expit
                pred_prob = expit(diff_score)  # sigmoid of score difference
                actual_win = 1.0 if eligible[i]["fwd"] > eligible[j]["fwd"] else 0.0
                all_predicted.append(pred_prob)
                all_actual.append(actual_win)

    predicted = np.array(all_predicted)
    actual = np.array(all_actual)
    print(f"  {len(predicted):,} pairs evaluated")

    if len(predicted) < 100:
        print("  Too few pairs for calibration")
        return results

    # Full calibration report
    report = calibration_report(predicted, actual, n_bins=10)
    results["full_sample"] = {
        k: v for k, v in report.items() if k != "calibrated_scores"
    }
    print(f"  Brier score: {report.get('brier_score', 'N/A')}")
    print(f"  ECE: {report.get('ece', 'N/A')}")
    print(f"  Verdict: {report.get('calibration_verdict', 'N/A')}")

    if "platt" in report:
        print(f"  Platt calibrated Brier: {report['platt'].get('brier_calibrated', 'N/A')}")
    if "isotonic" in report:
        print(f"  Isotonic calibrated Brier: {report['isotonic'].get('brier_calibrated', 'N/A')}")

    return results


# ── Method 5: Leave-One-Slice-Out Robustness ─────────────────────────


def run_robustness(snapshots):
    print("\n" + "=" * 70)
    print("METHOD 5 — LEAVE-ONE-SLICE-OUT ROBUSTNESS")
    print("=" * 70)

    results = {"method": "robustness"}

    test_signals = [
        ("coinvest_score_z", True),
        ("inst_delta_z", True),
        ("aact_execution_score", True),
        ("clinical_score_v2_z", True),
    ]

    for signal, higher_better in test_signals:
        print(f"\n  {signal}...")
        rob = multi_slice_robustness(
            snapshots, signal,
            higher_is_better=higher_better,
            top_n=30,
        )
        # Compact output (exclude full details)
        compact = {
            "signal": signal,
            "overall_verdict": rob.get("overall_verdict"),
            "verdicts": rob.get("verdicts"),
            "slice_summaries": {},
        }
        for dim, slice_result in rob.get("slices", {}).items():
            compact["slice_summaries"][dim] = {
                "worst_slice": slice_result.get("worst_slice"),
                "worst_delta": slice_result.get("worst_slice_delta"),
                "best_slice": slice_result.get("best_slice"),
                "best_delta": slice_result.get("best_slice_delta"),
                "verdict": slice_result.get("stability_verdict"),
            }
            print(f"    {dim}: worst={slice_result.get('worst_slice')} "
                  f"({slice_result.get('worst_slice_delta', 'N/A')}pp) "
                  f"→ {slice_result.get('stability_verdict', '?')}")

        print(f"    OVERALL: {rob.get('overall_verdict')}")
        results[signal] = compact

    return results


# ── Method 6: Survival / Hazard Scaffold ─────────────────────────────


def run_survival(panel):
    print("\n" + "=" * 70)
    print("METHOD 6 — SURVIVAL / HAZARD SCAFFOLD")
    print("=" * 70)

    results = {"method": "survival_scaffold"}

    # Use catalyst_days as time-to-event proxy
    # Event = catalyst resolved (catalyst_days <= 0 or catalyst arrived)
    # Covariates = execution features, clinical score, etc.

    durations = []
    events = []
    covariates = []
    covariate_names = [
        "clinical_score_v2_z", "financial_score", "coinvest_score_z",
    ]

    for row in panel:
        if _sf(row.get("eligible")) != 1.0:
            continue
        cat_days = _sf(row.get("catalyst_days"))
        if cat_days is None or cat_days <= 0:
            continue

        cov_vals = []
        skip = False
        for cn in covariate_names:
            v = _sf(row.get(cn))
            if v is None:
                skip = True
                break
            cov_vals.append(v)
        if skip:
            continue

        # Duration = catalyst_days (time until catalyst)
        durations.append(cat_days)
        # Event = 1 if catalyst is within 90 days (observable window)
        events.append(1 if cat_days <= 90 else 0)
        covariates.append(cov_vals)

    if len(durations) < 50:
        print("  Insufficient catalyst timing data")
        return results

    dur = np.array(durations)
    ev = np.array(events)
    X = np.array(covariates)

    print(f"  {len(dur)} observations, {np.sum(ev)} events")

    # Kaplan-Meier
    km = kaplan_meier(dur, ev)
    results["kaplan_meier"] = km
    print(f"  KM median survival: {km.get('median_survival', 'N/A')} days")

    # Stratified KM by stage
    stages = []
    for row in panel:
        if _sf(row.get("eligible")) != 1.0:
            continue
        cat_days = _sf(row.get("catalyst_days"))
        if cat_days is None or cat_days <= 0:
            continue
        cov_ok = all(_sf(row.get(cn)) is not None for cn in covariate_names)
        if not cov_ok:
            continue
        phase = _sf(row.get("lead_program_phase"))
        if phase is not None and phase >= 2.5:
            stages.append("late_stage")
        else:
            stages.append("early_stage")

    if len(stages) == len(dur):
        strat_km = stratified_kaplan_meier(dur, ev, np.array(stages))
        results["stratified_km"] = {
            k: v for k, v in strat_km.items()
            if k != "groups"  # exclude full survival tables
        }
        for g, gdata in strat_km.get("groups", {}).items():
            print(f"  {g}: n={gdata.get('n_obs')}, events={gdata.get('n_events')}, "
                  f"median={gdata.get('median_survival', 'N/A')}")

    # Cox PH
    print("  Running Cox PH...")
    cox = cox_ph_simple(dur, ev, X, feature_names=covariate_names)
    if "error" in cox:
        print(f"  Cox PH error: {cox['error']}")
    else:
        results["cox_ph"] = cox
        print(f"  C-index: {cox.get('c_index', 'N/A')}")
        for feat, fdata in cox.get("features", {}).items():
            hr = fdata.get("hazard_ratio", 0)
            z = fdata.get("z_stat", 0) or 0
            sig = "***" if abs(z) >= 2.58 else "**" if abs(z) >= 1.96 else ""
            print(f"    {feat:25s} HR={hr:.3f} z={z:+.2f} {sig}")

    return results


# ── Output Writers ───────────────────────────────────────────────────


def write_cross_sectional_summary(fm_results, path):
    lines = [
        "# Fama-MacBeth Cross-Sectional Regression Summary",
        "",
        "## Incremental Tests (candidate signal + institutional controls)",
        "",
        "| Signal | Uni NW-t | Incr NW-t | Incr p | Verdict |",
        "|--------|----------|-----------|--------|---------|",
    ]
    for signal, test in sorted(
        fm_results.get("incremental_tests", {}).items(),
        key=lambda x: abs(x[1].get("incremental", {}).get("nw_t", 0) or 0),
        reverse=True,
    ):
        uni_t = test.get("univariate", {}).get("nw_t", "---")
        inc_t = test.get("incremental", {}).get("nw_t", "---")
        inc_p = test.get("incremental", {}).get("p_value", "---")
        verdict = test.get("verdict", "?")
        uni_s = f"{uni_t:+.2f}" if isinstance(uni_t, (int, float)) else "---"
        inc_s = f"{inc_t:+.2f}" if isinstance(inc_t, (int, float)) else "---"
        p_s = f"{inc_p:.4f}" if isinstance(inc_p, (int, float)) else "---"
        lines.append(f"| `{signal}` | {uni_s} | {inc_s} | {p_s} | {verdict} |")

    lines.append("")
    path.write_text("\n".join(lines))


def write_bootstrap_summary(boot_results, path):
    lines = [
        "# Block Bootstrap Summary",
        "",
        "## Strategy Bootstrap (block=6, n=10000)",
        "",
        "| Strategy | Mean | 95% CI | P(>0) | CI excl 0? |",
        "|----------|------|--------|-------|------------|",
    ]
    for name, boot in boot_results.get("strategies", {}).items():
        mean = boot.get("boot_mean", 0)
        ci_l = boot.get("ci_lower", 0)
        ci_u = boot.get("ci_upper", 0)
        prob = boot.get("prob_positive", 0)
        excl = "YES" if boot.get("ci_excludes_zero") else "no"
        lines.append(
            f"| `{name}` | {mean:+.4f} | [{ci_l:.4f}, {ci_u:.4f}] "
            f"| {prob:.2f} | {excl} |"
        )
    lines.append("")
    path.write_text("\n".join(lines))


def write_multiple_testing_summary(mt_results, path):
    lines = [
        "# Multiple-Testing Correction Summary",
        "",
    ]
    for family_name, family_key in [
        ("Univariate Signals", "bh_univariate"),
        ("Incremental Tests", "bh_incremental"),
    ]:
        bh = mt_results.get(family_key)
        if not bh:
            continue
        lines.append(f"## {family_name} (BH FDR α=0.10)")
        lines.append("")
        lines.append("| Signal | raw p | q-value | Rejected? |")
        lines.append("|--------|-------|---------|-----------|")
        for name in sorted(
            bh["results"],
            key=lambda n: bh["results"][n]["raw_p"],
        ):
            r = bh["results"][name]
            status = "**REJECT**" if r["rejected"] else "retain"
            lines.append(
                f"| `{name}` | {r['raw_p']:.4f} | {r['q_value']:.4f} | {status} |"
            )
        lines.append(f"\n{bh['n_rejected']}/{bh['n_tests']} rejected at FDR=0.10\n")

    wrc = mt_results.get("whites_rc")
    if wrc:
        lines.append("## White's Reality Check")
        lines.append(f"- Best: `{wrc.get('best_strategy')}` (mean={wrc.get('best_mean', 0):.4f})")
        lines.append(f"- WRC p-value: {wrc.get('wrc_p_value', 'N/A')}")
        lines.append(f"- Significant at 5%: {wrc.get('significant_at_05')}")
        lines.append("")

    path.write_text("\n".join(lines))


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Spec 055 — Statistical Methods Upgrade")
    parser.add_argument("--method", default="ALL", help="Method to run: fama_macbeth, bootstrap, multiple_testing, calibration, robustness, survival, or ALL")
    args = parser.parse_args()

    panel = load_panel()
    snapshots = group_by_snapshot(panel)
    print(f"  {len(snapshots)} snapshots")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    methods = args.method.lower().split(",") if args.method != "ALL" else [
        "fama_macbeth", "bootstrap", "multiple_testing",
        "calibration", "robustness", "survival",
    ]

    all_results = {}

    if "fama_macbeth" in methods:
        fm = run_fama_macbeth(snapshots)
        all_results["fama_macbeth"] = fm
        write_cross_sectional_summary(fm, OUTPUT_DIR / "cross_sectional_summary.md")
        with open(OUTPUT_DIR / "cross_sectional_results.json", "w") as f:
            json.dump(fm, f, indent=2, default=str)

    if "bootstrap" in methods:
        boot = run_bootstrap(snapshots)
        all_results["bootstrap"] = boot
        write_bootstrap_summary(boot, OUTPUT_DIR / "bootstrap_summary.md")
        with open(OUTPUT_DIR / "bootstrap_results.json", "w") as f:
            json.dump(boot, f, indent=2, default=str)

    if "multiple_testing" in methods:
        fm = all_results.get("fama_macbeth")
        if not fm:
            print("  Running FM first for p-values...")
            fm = run_fama_macbeth(snapshots)
            all_results["fama_macbeth"] = fm
        mt = run_multiple_testing(snapshots, fm)
        all_results["multiple_testing"] = mt
        write_multiple_testing_summary(mt, OUTPUT_DIR / "multiple_testing_summary.md")
        with open(OUTPUT_DIR / "multiple_testing_results.json", "w") as f:
            json.dump(mt, f, indent=2, default=str)

    if "calibration" in methods:
        cal = run_calibration(panel, snapshots)
        all_results["calibration"] = cal
        with open(OUTPUT_DIR / "calibration_results.json", "w") as f:
            json.dump(cal, f, indent=2, default=str)

    if "robustness" in methods:
        rob = run_robustness(snapshots)
        all_results["robustness"] = rob
        with open(OUTPUT_DIR / "robustness_results.json", "w") as f:
            json.dump(rob, f, indent=2, default=str)

    if "survival" in methods:
        surv = run_survival(panel)
        all_results["survival"] = surv
        with open(OUTPUT_DIR / "survival_results.json", "w") as f:
            json.dump(surv, f, indent=2, default=str)

    # Master results
    master = {
        "schema": "statistical_methods_upgrade.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methods_run": methods,
        "n_snapshots": len(snapshots),
        "n_panel_rows": len(panel),
    }
    with open(OUTPUT_DIR / "master_results.json", "w") as f:
        json.dump(master, f, indent=2, default=str)

    print(f"\n{'='*70}")
    print("STATISTICAL METHODS UPGRADE COMPLETE")
    print(f"{'='*70}")
    print(f"Artifacts in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
