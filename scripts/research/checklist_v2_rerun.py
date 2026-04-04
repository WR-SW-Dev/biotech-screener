#!/usr/bin/env python3
"""Checklist v2 Selective Rerun — 2026-04-04.

Reruns the Promotion Checklist v2 battery on the signals that matter
for live or near-live decisions. Does NOT rerun closed lanes.

Rerun queue:
  A. Standalone signals: coinvest_score_z, inst_delta_z, event_type_score,
     insider_exec_buy_value_90d, aact_execution_score
  B. Pairwise minimal feature set: calibration + ordinal assessment
  C. B6 bundle: bootstrap + LOSO on the production selector

Five gates per signal:
  1. Signal card (selector Δ, ranker IC)
  2. Fama-MacBeth incremental (NW-t ≥ 1.96 with controls)
  3. Block bootstrap (95% CI excludes zero)
  4. BH FDR (q < 0.10 within rerun family)
  5. LOSO robustness (worst-slice positive)

Usage:
    python3 scripts/research/checklist_v2_rerun.py
    python3 scripts/research/checklist_v2_rerun.py --queue A
    python3 scripts/research/checklist_v2_rerun.py --queue B
    python3 scripts/research/checklist_v2_rerun.py --queue C
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

from common.stats.bootstrap import block_bootstrap
from common.stats.calibration import calibration_report
from common.stats.cross_sectional import fama_macbeth, run_incremental_test
from common.stats.multiple_testing import benjamini_hochberg
from common.stats.robustness import multi_slice_robustness

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "checklist_v2_rerun"

SCHEMA_VERSION = "checklist_v2_rerun.v1"

# ── Signal definitions ──────────────────────────────────────────────

# Queue A: standalone signals to evaluate
RERUN_SIGNALS = [
    "coinvest_score_z",
    "inst_delta_z",
    "event_type_score",
    "insider_exec_buy_value_90d",
    "aact_execution_score",
]

SIGNAL_DIRECTION = {
    "coinvest_score_z": True,
    "inst_delta_z": True,
    "event_type_score": True,
    "insider_exec_buy_value_90d": True,
    "aact_execution_score": True,
}

# Controls for incremental FM (Spec 055 standard)
INCUMBENT_CONTROLS = ["coinvest_score_z", "inst_delta_z", "financial_score"]

# Queue B: pairwise minimal features (calibration assessment)
PAIRWISE_FEATURES = [
    "coinvest_score_z",
    "inst_delta_z",
    "clinical_score_v2_z",
    "catalyst_decay_w",
    "binary_quality_score",
    "financial_score",
]

# Queue C: B6 bundle
B6_BUNDLE = {"coinvest_score_z": (0.65, True), "inst_delta_z": (0.35, True)}

# Horizons
HORIZON = "fwd_excess_xbi_63d"
HORIZON_RET = "fwd_ret_63d"
TOP_K = 30
BOOTSTRAP_BLOCKS = 6
BOOTSTRAP_N = 10000

EVENT_TYPE_SCORE_MAP = {
    "FDA_PDUFA_DATE": 3,
    "DATA_READOUT": 2,
    "CT_PRIMARY_COMPLETION": 1,
    "CT_STUDY_COMPLETION": 1,
    "CT_RESULTS_POSTED": 0,
    "CT_TRIAL_SUSPENDED": 0,
    "IR_EVENT": 0,
}


# ── Helpers ─────────────────────────────────────────────────────────


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


def _pp(v):
    return v * 100 if v is not None else None


def _safe_mean(vals):
    return statistics.mean(vals) if vals else None


def _safe_tstat(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / (s / len(vals) ** 0.5) if s > 1e-9 else None


def spearman_ic(x, y):
    n = len(x)
    if n < 5:
        return None

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[indexed[j + 1]] == vals[indexed[j]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy)


# ── Data loading ────────────────────────────────────────────────────


def load_panel():
    print("Loading research panel...")
    with open(PANEL_CSV) as f:
        panel = list(csv.DictReader(f))
    print(f"  {len(panel):,} rows")
    return panel


def enrich_panel(panel):
    """Add derived signals not already in the panel (event_type_score)."""
    for row in panel:
        evt = row.get("catalyst_event_type", "")
        if evt and "event_type_score" not in row:
            row["event_type_score"] = EVENT_TYPE_SCORE_MAP.get(evt, 0)
        elif not evt and "event_type_score" not in row:
            row["event_type_score"] = ""
    return panel


def group_by_snapshot(panel):
    groups = defaultdict(list)
    for row in panel:
        groups[row["snapshot_date"]].append(row)
    return dict(sorted(groups.items()))


# ── Gate 1: Signal Card ─────────────────────────────────────────────


def run_gate1_signal_cards(snapshots):
    """Selector delta and ranker IC for each rerun signal."""
    print("\n" + "=" * 70)
    print("GATE 1 — SIGNAL CARDS (selector Δ + ranker IC)")
    print("=" * 70)

    results = {}
    for signal in RERUN_SIGNALS:
        higher_better = SIGNAL_DIRECTION.get(signal, True)
        sel_improvements = []
        ranker_ics = []

        for snap_date, rows in sorted(snapshots.items()):
            elig = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal))
                fwd = _sf(r.get(HORIZON))
                rank = _sf(r.get("actionable_rank"))
                if sv is not None and fwd is not None and rank is not None:
                    elig.append({"signal": sv, "fwd": fwd, "rank": rank})
            if len(elig) < TOP_K:
                continue

            by_rank = sorted(elig, key=lambda x: x["rank"])[:TOP_K]
            baseline = statistics.mean(e["fwd"] for e in by_rank)
            if higher_better:
                by_sig = sorted(elig, key=lambda x: -x["signal"])
            else:
                by_sig = sorted(elig, key=lambda x: x["signal"])
            sel_ret = statistics.mean(e["fwd"] for e in by_sig[:TOP_K])
            sel_improvements.append(sel_ret - baseline)

            top30 = by_rank
            if len(top30) >= 10:
                sigs = [e["signal"] for e in top30]
                fwds = [e["fwd"] for e in top30]
                if not higher_better:
                    sigs = [-s for s in sigs]
                ic = spearman_ic(sigs, fwds)
                if ic is not None:
                    ranker_ics.append(ic)

        sel_pp = _r(_pp(_safe_mean(sel_improvements)))
        sel_t = _r(_safe_tstat([v * 100 for v in sel_improvements]))
        ic_mean = _r(_safe_mean(ranker_ics))
        ic_t = _r(_safe_tstat(ranker_ics))
        n_periods = len(sel_improvements)

        # Pass/fail
        passes = (sel_t or 0) >= 1.64 and (sel_pp or 0) > 0
        results[signal] = {
            "selector_delta_pp": sel_pp,
            "selector_tstat": sel_t,
            "ranker_ic": ic_mean,
            "ranker_ic_tstat": ic_t,
            "n_periods": n_periods,
            "gate1_pass": passes,
        }
        tag = "PASS" if passes else "FAIL"
        print(
            f"  {signal:35s} Δ={sel_pp or 0:+.2f}pp  t={sel_t or 0:+.2f}  "
            f"IC={ic_mean or 0:+.3f}  (n={n_periods})  → {tag}"
        )

    return results


# ── Gate 2: Fama-MacBeth Incremental ────────────────────────────────


def run_gate2_fm_incremental(snapshots):
    """FM incremental test: each signal + incumbent controls."""
    print("\n" + "=" * 70)
    print("GATE 2 — FAMA-MACBETH INCREMENTAL (NW-t ≥ 1.96)")
    print("=" * 70)

    results = {}

    # For coinvest and inst_delta, they ARE the controls —
    # test them univariate and against each other
    print("\n  2a. Univariate regressions...")
    for signal in RERUN_SIGNALS:
        fm = fama_macbeth(snapshots, HORIZON, [signal], nw_lags=3)
        if "error" in fm:
            print(f"    {signal}: SKIP ({fm['error']})")
            results[signal] = {"univariate_nw_t": None, "error": fm["error"]}
            continue
        sig_data = fm["signals"].get(signal, {})
        nw_t = sig_data.get("newey_west_t", 0) or 0
        coef = sig_data.get("mean_coefficient", 0) or 0
        p_val = sig_data.get("p_value")
        stars = "***" if abs(nw_t) >= 2.58 else "**" if abs(nw_t) >= 1.96 else "*" if abs(nw_t) >= 1.64 else ""
        print(f"    {signal:35s} coef={coef:+.4f}  NW-t={nw_t:+.2f} {stars}")
        results[signal] = {
            "univariate_coef": _r(coef),
            "univariate_nw_t": _r(nw_t),
            "univariate_p": _r(p_val),
        }

    # Incremental tests
    print("\n  2b. Incremental tests (signal + controls)...")
    for signal in RERUN_SIGNALS:
        # For incumbent controls, test against each other
        if signal in INCUMBENT_CONTROLS:
            other_controls = [c for c in INCUMBENT_CONTROLS if c != signal]
            if not other_controls:
                results[signal]["incremental_nw_t"] = results[signal].get("univariate_nw_t")
                results[signal]["incremental_verdict"] = "UNIVARIATE_ONLY"
                results[signal]["gate2_pass"] = abs(results[signal].get("univariate_nw_t") or 0) >= 1.96
                continue
        else:
            other_controls = list(INCUMBENT_CONTROLS)

        inc = run_incremental_test(snapshots, signal, other_controls)
        if "error" in inc.get("incremental", {}):
            results[signal]["incremental_nw_t"] = None
            results[signal]["incremental_verdict"] = "ERROR"
            results[signal]["gate2_pass"] = False
            continue

        inc_t = inc["incremental"].get("nw_t", 0) or 0
        inc_p = inc["incremental"].get("p_value")
        verdict = inc["verdict"]
        passes = abs(inc_t) >= 1.96
        results[signal]["incremental_nw_t"] = _r(inc_t)
        results[signal]["incremental_p"] = _r(inc_p)
        results[signal]["incremental_verdict"] = verdict
        results[signal]["gate2_pass"] = passes

        tag = "PASS" if passes else "FAIL"
        print(f"    {signal:35s} incr-t={inc_t:+.2f}  p={inc_p or 0:.4f}  → {verdict}  [{tag}]")

    return results


# ── Gate 3: Block Bootstrap ─────────────────────────────────────────


def run_gate3_bootstrap(snapshots):
    """Bootstrap on top-30 EW portfolio sorted by each signal."""
    print("\n" + "=" * 70)
    print("GATE 3 — BLOCK BOOTSTRAP (95% CI excludes zero)")
    print("=" * 70)

    results = {}

    for signal in RERUN_SIGNALS:
        higher_better = SIGNAL_DIRECTION.get(signal, True)
        monthly_excess = []

        for snap_date in sorted(snapshots.keys()):
            rows = snapshots[snap_date]
            elig = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal))
                fwd = _sf(r.get(HORIZON))
                rank = _sf(r.get("actionable_rank"))
                if sv is not None and fwd is not None and rank is not None:
                    elig.append({"signal": sv, "fwd": fwd, "rank": rank})
            if len(elig) < TOP_K:
                continue

            by_rank = sorted(elig, key=lambda x: x["rank"])[:TOP_K]
            baseline = np.mean([e["fwd"] for e in by_rank])
            if higher_better:
                by_sig = sorted(elig, key=lambda x: -x["signal"])
            else:
                by_sig = sorted(elig, key=lambda x: x["signal"])
            selected = np.mean([e["fwd"] for e in by_sig[:TOP_K]])
            monthly_excess.append(selected - baseline)

        if len(monthly_excess) < 12:
            print(f"  {signal:35s} SKIP (n={len(monthly_excess)} < 12)")
            results[signal] = {"gate3_pass": False, "reason": "insufficient_periods"}
            continue

        boot = block_bootstrap(
            monthly_excess,
            block_length=BOOTSTRAP_BLOCKS,
            n_bootstrap=BOOTSTRAP_N,
            seed=42,
        )
        passes = boot.get("ci_excludes_zero", False)
        results[signal] = {
            "boot_mean": _r(boot.get("boot_mean")),
            "ci_lower": _r(boot.get("ci_lower")),
            "ci_upper": _r(boot.get("ci_upper")),
            "prob_positive": _r(boot.get("prob_positive")),
            "ci_excludes_zero": passes,
            "n_periods": len(monthly_excess),
            "gate3_pass": passes,
        }
        tag = "PASS" if passes else "FAIL"
        ci = f"[{boot.get('ci_lower', 0):.4f}, {boot.get('ci_upper', 0):.4f}]"
        print(
            f"  {signal:35s} mean={boot.get('boot_mean', 0):+.4f}  "
            f"95%CI={ci}  P(>0)={boot.get('prob_positive', 0):.2f}  → {tag}"
        )

    return results


# ── Gate 4: BH FDR ──────────────────────────────────────────────────


def run_gate4_fdr(fm_results):
    """BH FDR on the rerun family p-values."""
    print("\n" + "=" * 70)
    print("GATE 4 — BENJAMINI-HOCHBERG FDR (q < 0.10)")
    print("=" * 70)

    # Collect incremental p-values (or univariate for controls)
    p_values = {}
    for signal in RERUN_SIGNALS:
        sr = fm_results.get(signal, {})
        p = sr.get("incremental_p") or sr.get("univariate_p")
        if p is not None:
            p_values[signal] = p

    if not p_values:
        print("  No p-values available")
        return {}

    bh = benjamini_hochberg(p_values, alpha=0.10)
    results = {}
    for signal in RERUN_SIGNALS:
        if signal not in bh.get("results", {}):
            results[signal] = {"gate4_pass": False, "reason": "no_p_value"}
            continue
        r = bh["results"][signal]
        passes = r["rejected"]
        results[signal] = {
            "raw_p": _r(r["raw_p"]),
            "q_value": _r(r["q_value"]),
            "rejected": passes,
            "gate4_pass": passes,
        }
        tag = "PASS" if passes else "FAIL"
        print(f"  {signal:35s} p={r['raw_p']:.4f}  q={r['q_value']:.4f}  → {tag}")

    print(f"\n  {bh['n_rejected']}/{bh['n_tests']} rejected at FDR=0.10")
    return results


# ── Gate 5: LOSO Robustness ─────────────────────────────────────────


def run_gate5_robustness(snapshots):
    """Multi-slice LOSO for each rerun signal."""
    print("\n" + "=" * 70)
    print("GATE 5 — LEAVE-ONE-SLICE-OUT ROBUSTNESS")
    print("=" * 70)

    results = {}
    for signal in RERUN_SIGNALS:
        higher_better = SIGNAL_DIRECTION.get(signal, True)
        print(f"\n  {signal}...")

        rob = multi_slice_robustness(
            snapshots,
            signal,
            higher_is_better=higher_better,
            top_n=TOP_K,
        )

        overall = rob.get("overall_verdict", "UNKNOWN")
        # PASS if not UNSTABLE/FRAGILE/CAUTIOUS
        passes = "ROBUST" in overall or "MODERATE" in overall

        compact = {
            "overall_verdict": overall,
            "gate5_pass": passes,
            "slices": {},
        }
        for dim, sr in rob.get("slices", {}).items():
            compact["slices"][dim] = {
                "worst_slice": sr.get("worst_slice"),
                "worst_delta": _r(sr.get("worst_slice_delta")),
                "best_slice": sr.get("best_slice"),
                "best_delta": _r(sr.get("best_slice_delta")),
                "verdict": sr.get("stability_verdict"),
            }
            print(
                f"    {dim:20s} worst={sr.get('worst_slice'):15s} "
                f"Δ={sr.get('worst_slice_delta', 'N/A')}  → {sr.get('stability_verdict', '?')}"
            )

        tag = "PASS" if passes else "FAIL"
        print(f"    OVERALL: {overall} → {tag}")
        results[signal] = compact

    return results


# ── Queue B: Pairwise Calibration ───────────────────────────────────


def run_queue_b_pairwise_calibration(panel, snapshots):
    """Calibration assessment of pairwise minimal feature set."""
    print("\n" + "=" * 70)
    print("QUEUE B — PAIRWISE MINIMAL FEATURE SET CALIBRATION")
    print("=" * 70)

    # Load production model weights
    model_path = PROJECT_ROOT / "production_data" / "ranker_v2_model.json"
    if not model_path.exists():
        print("  WARNING: ranker_v2_model.json not found, using equal weights")
        weights = {f: 1.0 / len(PAIRWISE_FEATURES) for f in PAIRWISE_FEATURES}
    else:
        with open(model_path) as f:
            model = json.load(f)
        # Weights stored as list in model.model.weights with model.model.feature_names
        model_inner = model.get("model", model)
        w_list = model_inner.get("weights", [])
        f_list = model_inner.get("feature_names", PAIRWISE_FEATURES)
        if isinstance(w_list, list) and f_list:
            weights = dict(zip(f_list, w_list))
        else:
            weights = model_inner.get("weights", {})
        print(f"  Model loaded: {len(weights)} feature weights")
        for fn, fw in weights.items():
            print(f"    {fn:30s} w={fw:+.4f}")

    # Build pairwise outcomes within top-60 cohort
    all_predicted = []
    all_actual = []
    n_snapshots_used = 0

    for snap_date in sorted(snapshots.keys()):
        rows = snapshots[snap_date]
        eligible = []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            rank = _sf(r.get("actionable_rank"))
            if rank is None or rank > 60:
                continue
            feats = {}
            skip = False
            for feat in PAIRWISE_FEATURES:
                v = _sf(r.get(feat))
                if v is None:
                    skip = True
                    break
                feats[feat] = v
            fwd = _sf(r.get(HORIZON_RET))
            if skip or fwd is None:
                continue
            eligible.append({"feats": feats, "fwd": fwd})

        if len(eligible) < 10:
            continue
        n_snapshots_used += 1

        # Score each name using model weights
        for e in eligible:
            e["score"] = sum(weights.get(f, 0) * e["feats"][f] for f in PAIRWISE_FEATURES)

        # Generate pairs (sample to limit compute)
        from scipy.special import expit

        pairs_this = 0
        for i in range(len(eligible)):
            for j in range(i + 1, min(len(eligible), i + 10)):
                diff = eligible[i]["score"] - eligible[j]["score"]
                pred_prob = expit(diff)
                actual_win = 1.0 if eligible[i]["fwd"] > eligible[j]["fwd"] else 0.0
                all_predicted.append(pred_prob)
                all_actual.append(actual_win)
                pairs_this += 1

    predicted = np.array(all_predicted)
    actual = np.array(all_actual)
    print(f"  {len(predicted):,} pairs from {n_snapshots_used} snapshots")

    if len(predicted) < 100:
        print("  Too few pairs for calibration")
        return {"error": "insufficient_pairs"}

    report = calibration_report(predicted, actual, n_bins=10)
    result = {
        "n_pairs": len(predicted),
        "n_snapshots": n_snapshots_used,
        "brier_score": _r(report.get("brier_score")),
        "ece": _r(report.get("ece")),
        "calibration_verdict": report.get("calibration_verdict"),
        "pairwise_accuracy": _r(float(np.mean((predicted > 0.5) == actual))),
    }

    if "platt" in report:
        result["platt_brier"] = _r(report["platt"].get("brier_calibrated"))
        result["platt_ece"] = _r(report["platt"].get("ece_calibrated"))
    if "isotonic" in report:
        result["isotonic_brier"] = _r(report["isotonic"].get("brier_calibrated"))

    print(f"  Brier: {result['brier_score']}")
    print(f"  ECE: {result['ece']}")
    print(f"  Pairwise accuracy: {result['pairwise_accuracy']}")
    print(f"  Calibration verdict: {result['calibration_verdict']}")
    if result.get("platt_ece"):
        print(f"  Platt-calibrated ECE: {result['platt_ece']}")

    # Also run FM on each pairwise feature as ranker within top-30
    print("\n  Feature-level FM within top-30 cohort...")
    top30_snapshots = {}
    for snap_date, rows in snapshots.items():
        top30 = [r for r in rows if _sf(r.get("eligible")) == 1.0 and (_sf(r.get("actionable_rank")) or 999) <= 30]
        if len(top30) >= 10:
            top30_snapshots[snap_date] = top30

    feature_fm = {}
    if len(top30_snapshots) >= 12:
        for feat in PAIRWISE_FEATURES:
            fm = fama_macbeth(top30_snapshots, HORIZON_RET, [feat], nw_lags=3)
            if "error" not in fm:
                sig = fm["signals"].get(feat, {})
                nw_t = sig.get("newey_west_t", 0) or 0
                coef = sig.get("mean_coefficient", 0) or 0
                stars = "***" if abs(nw_t) >= 2.58 else "**" if abs(nw_t) >= 1.96 else ""
                print(f"    {feat:30s} coef={coef:+.4f}  NW-t={nw_t:+.2f} {stars}")
                feature_fm[feat] = {
                    "coef": _r(coef),
                    "nw_t": _r(nw_t),
                    "survives": abs(nw_t) >= 1.96,
                }
    result["feature_fm_within_top30"] = feature_fm

    return result


# ── Queue C: B6 Bundle Validation ───────────────────────────────────


def compute_bundle_score(rows, bundle):
    """Z-score each signal within snapshot, weighted sum."""
    z_maps = {}
    for signal in bundle:
        vals, tickers = [], []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            v = _sf(r.get(signal))
            if v is not None:
                vals.append(v)
                tickers.append(r.get("ticker", ""))
        if len(vals) < 3:
            z_maps[signal] = {}
            continue
        m = statistics.mean(vals)
        s = statistics.stdev(vals) if len(vals) >= 2 else 1.0
        if s < 1e-9:
            s = 1.0
        z_maps[signal] = {tickers[i]: (vals[i] - m) / s for i in range(len(tickers))}

    scores = {}
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        ticker = r.get("ticker", "")
        total, total_w = 0.0, 0.0
        for signal, (weight, higher_better) in bundle.items():
            z = z_maps.get(signal, {}).get(ticker)
            if z is not None:
                if not higher_better:
                    z = -z
                total += weight * z
                total_w += weight
        scores[ticker] = total / total_w if total_w > 0 else 0.0
    return scores


def run_queue_c_b6_bundle(snapshots):
    """Bootstrap + LOSO on B6 production bundle."""
    print("\n" + "=" * 70)
    print("QUEUE C — B6 BUNDLE VALIDATION (bootstrap + LOSO)")
    print("=" * 70)

    # Compute monthly excess returns for B6-sorted top-30
    monthly_excess = []
    for snap_date in sorted(snapshots.keys()):
        rows = snapshots[snap_date]
        scores = compute_bundle_score(rows, B6_BUNDLE)

        elig_fwd = {}
        baseline_list = []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            ticker = r.get("ticker", "")
            fwd = _sf(r.get(HORIZON))
            rank = _sf(r.get("actionable_rank"))
            if fwd is not None and rank is not None:
                baseline_list.append({"fwd": fwd, "rank": rank})
            if fwd is not None and ticker in scores:
                elig_fwd[ticker] = fwd

        if len(baseline_list) < TOP_K or len(elig_fwd) < TOP_K:
            continue

        by_rank = sorted(baseline_list, key=lambda x: x["rank"])[:TOP_K]
        baseline = np.mean([e["fwd"] for e in by_rank])

        by_bundle = sorted(elig_fwd.items(), key=lambda x: -scores.get(x[0], 0))[:TOP_K]
        selected = np.mean([fwd for _, fwd in by_bundle])

        monthly_excess.append(selected - baseline)

    result = {"n_periods": len(monthly_excess)}

    # Bootstrap
    if len(monthly_excess) >= 12:
        boot = block_bootstrap(
            monthly_excess,
            block_length=BOOTSTRAP_BLOCKS,
            n_bootstrap=BOOTSTRAP_N,
            seed=42,
        )
        result["bootstrap"] = {
            "boot_mean": _r(boot.get("boot_mean")),
            "ci_lower": _r(boot.get("ci_lower")),
            "ci_upper": _r(boot.get("ci_upper")),
            "prob_positive": _r(boot.get("prob_positive")),
            "ci_excludes_zero": boot.get("ci_excludes_zero"),
        }
        tag = "PASS" if boot.get("ci_excludes_zero") else "FAIL"
        ci = f"[{boot.get('ci_lower', 0):.4f}, {boot.get('ci_upper', 0):.4f}]"
        print(
            f"  B6 bootstrap: mean={boot.get('boot_mean', 0):+.4f}  "
            f"95%CI={ci}  P(>0)={boot.get('prob_positive', 0):.2f}  → {tag}"
        )
    else:
        print(f"  Insufficient periods for bootstrap (n={len(monthly_excess)})")
        result["bootstrap"] = {"error": "insufficient_periods"}

    # Inject B6 bundle score into snapshots for LOSO
    print("\n  B6 LOSO robustness...")
    for snap_date, rows in snapshots.items():
        scores = compute_bundle_score(rows, B6_BUNDLE)
        for r in rows:
            ticker = r.get("ticker", "")
            r["_b6_score"] = scores.get(ticker, "")

    rob = multi_slice_robustness(
        snapshots,
        "_b6_score",
        higher_is_better=True,
        top_n=TOP_K,
    )
    overall = rob.get("overall_verdict", "UNKNOWN")
    result["robustness"] = {
        "overall_verdict": overall,
        "passes": "ROBUST" in overall or "MODERATE" in overall,
    }
    for dim, sr in rob.get("slices", {}).items():
        result["robustness"][dim] = {
            "worst_slice": sr.get("worst_slice"),
            "worst_delta": _r(sr.get("worst_slice_delta")),
            "verdict": sr.get("stability_verdict"),
        }
        print(
            f"    {dim:20s} worst={sr.get('worst_slice'):15s} "
            f"Δ={sr.get('worst_slice_delta', 'N/A')}  → {sr.get('stability_verdict', '?')}"
        )
    tag = "PASS" if result["robustness"]["passes"] else "FAIL"
    print(f"    OVERALL: {overall} → {tag}")

    # Clean up injected column
    for snap_date, rows in snapshots.items():
        for r in rows:
            r.pop("_b6_score", None)

    return result


# ── Scorecard Assembly ──────────────────────────────────────────────


def assemble_scorecard(g1, g2, g3, g4, g5):
    """Merge all gate results into a single scorecard per signal."""
    scorecard = {}
    for signal in RERUN_SIGNALS:
        card = {"signal": signal}
        card.update(g1.get(signal, {}))
        card.update(g2.get(signal, {}))
        card.update(g3.get(signal, {}))
        card.update(g4.get(signal, {}))
        card.update(g5.get(signal, {}))

        gates_passed = sum(
            1 for g in ["gate1_pass", "gate2_pass", "gate3_pass", "gate4_pass", "gate5_pass"] if card.get(g)
        )
        card["gates_passed"] = gates_passed
        card["full_pass"] = gates_passed == 5

        scorecard[signal] = card
    return scorecard


def write_operator_memo(scorecard, queue_b, queue_c, output_dir):
    """Write human-readable markdown memo."""
    lines = [
        "# Checklist v2 Selective Rerun — Operator Memo",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Queue A: Standalone Signal Scorecard",
        "",
        "| Signal | G1 Card | G2 FM | G3 Boot | G4 FDR | G5 LOSO | Total | Verdict |",
        "|--------|---------|-------|---------|--------|---------|-------|---------|",
    ]

    for signal in RERUN_SIGNALS:
        c = scorecard[signal]

        def _gate(k, card=c):
            return "PASS" if card.get(k) else "FAIL"

        total = c.get("gates_passed", 0)
        verdict = "**PROMOTE**" if total == 5 else f"SHADOW ({total}/5)" if total >= 3 else f"NO_GO ({total}/5)"
        lines.append(
            f"| `{signal}` | {_gate('gate1_pass')} | {_gate('gate2_pass')} | "
            f"{_gate('gate3_pass')} | {_gate('gate4_pass')} | {_gate('gate5_pass')} | "
            f"{total}/5 | {verdict} |"
        )

    lines.append("")
    lines.append("### Signal Details")
    for signal in RERUN_SIGNALS:
        c = scorecard[signal]
        lines.append(f"\n**{signal}**")
        lines.append(f"- Selector Δ: {c.get('selector_delta_pp', '---')}pp (t={c.get('selector_tstat', '---')})")
        lines.append(f"- Ranker IC: {c.get('ranker_ic', '---')} (t={c.get('ranker_ic_tstat', '---')})")
        lines.append(f"- FM univariate NW-t: {c.get('univariate_nw_t', '---')}")
        lines.append(
            f"- FM incremental NW-t: {c.get('incremental_nw_t', '---')} ({c.get('incremental_verdict', '---')})"
        )
        lines.append(
            f"- Bootstrap: mean={c.get('boot_mean', '---')}, CI=[{c.get('ci_lower', '---')}, {c.get('ci_upper', '---')}]"
        )
        lines.append(f"- FDR q-value: {c.get('q_value', '---')}")
        lines.append(f"- LOSO: {c.get('overall_verdict', '---')}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Queue B: Pairwise Minimal Calibration")
    lines.append("")
    if "error" in queue_b:
        lines.append(f"Error: {queue_b['error']}")
    else:
        lines.append(f"- Pairs evaluated: {queue_b.get('n_pairs', '---'):,}")
        lines.append(f"- Brier score: {queue_b.get('brier_score', '---')}")
        lines.append(f"- ECE: {queue_b.get('ece', '---')}")
        lines.append(f"- Pairwise accuracy: {queue_b.get('pairwise_accuracy', '---')}")
        lines.append(f"- Calibration verdict: **{queue_b.get('calibration_verdict', '---')}**")
        if queue_b.get("platt_ece"):
            lines.append(f"- Platt-calibrated ECE: {queue_b.get('platt_ece')}")

        feat_fm = queue_b.get("feature_fm_within_top30", {})
        if feat_fm:
            lines.append("")
            lines.append("### Feature-Level FM Within Top-30")
            lines.append("")
            lines.append("| Feature | Coef | NW-t | Survives? |")
            lines.append("|---------|------|------|-----------|")
            for feat in PAIRWISE_FEATURES:
                fd = feat_fm.get(feat, {})
                surv = "YES" if fd.get("survives") else "no"
                lines.append(f"| `{feat}` | {fd.get('coef', '---')} | {fd.get('nw_t', '---')} | {surv} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Queue C: B6 Bundle Validation")
    lines.append("")
    lines.append(f"- Periods: {queue_c.get('n_periods', '---')}")
    boot = queue_c.get("bootstrap", {})
    if "error" not in boot:
        tag = "PASS" if boot.get("ci_excludes_zero") else "FAIL"
        lines.append(
            f"- Bootstrap: mean={boot.get('boot_mean', '---')}, "
            f"CI=[{boot.get('ci_lower', '---')}, {boot.get('ci_upper', '---')}] → **{tag}**"
        )
        lines.append(f"- P(>0): {boot.get('prob_positive', '---')}")
    rob = queue_c.get("robustness", {})
    if rob:
        tag = "PASS" if rob.get("passes") else "FAIL"
        lines.append(f"- LOSO overall: **{rob.get('overall_verdict', '---')}** → {tag}")
        for dim in rob:
            if dim in ("overall_verdict", "passes"):
                continue
            rd = rob[dim]
            if isinstance(rd, dict):
                lines.append(
                    f"  - {dim}: worst={rd.get('worst_slice', '---')} "
                    f"(Δ={rd.get('worst_delta', '---')}) → {rd.get('verdict', '---')}"
                )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Operator Decisions Required")
    lines.append("")

    # Auto-generate decision prompts
    for signal in RERUN_SIGNALS:
        c = scorecard[signal]
        total = c.get("gates_passed", 0)
        if total == 5:
            lines.append(f"- **{signal}**: Full pass. Eligible for promotion if bundle test positive.")
        elif total >= 3:
            failed = [g for g in ["gate1_pass", "gate2_pass", "gate3_pass", "gate4_pass", "gate5_pass"] if not c.get(g)]
            lines.append(
                f"- **{signal}**: {total}/5 — failed: {', '.join(g.replace('_pass', '') for g in failed)}. "
                f"Shadow continues."
            )
        else:
            lines.append(f"- **{signal}**: {total}/5 — below bar. Review if data regime changes.")

    cal_verdict = queue_b.get("calibration_verdict", "")
    if "POOR" in str(cal_verdict).upper() or "NOT" in str(cal_verdict).upper():
        lines.append(
            f"- **Pairwise ranker**: Calibration={cal_verdict}. "
            f"Confirms ordinal-only policy (no rank-weighting or confidence sizing)."
        )
    else:
        lines.append(
            f"- **Pairwise ranker**: Calibration={cal_verdict}. " f"Review whether rank-weighting becomes viable."
        )

    b6_boot_pass = boot.get("ci_excludes_zero", False)
    b6_rob_pass = rob.get("passes", False)
    if b6_boot_pass and b6_rob_pass:
        lines.append("- **B6 bundle**: Bootstrap + LOSO pass. Production selector validated.")
    else:
        issues = []
        if not b6_boot_pass:
            issues.append("bootstrap CI includes zero")
        if not b6_rob_pass:
            issues.append(f"LOSO={rob.get('overall_verdict', '?')}")
        lines.append(f"- **B6 bundle**: Issues: {', '.join(issues)}. Review selector composition.")

    lines.append("")
    path = output_dir / "operator_memo.md"
    path.write_text("\n".join(lines))
    print(f"\nMemo written to: {path}")
    return path


# ── Main ────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Checklist v2 Selective Rerun")
    parser.add_argument("--queue", default="ALL", help="Which queue to run: A, B, C, or ALL")
    args = parser.parse_args()

    queues = args.queue.upper().split(",") if args.queue != "ALL" else ["A", "B", "C"]

    panel = load_panel()
    panel = enrich_panel(panel)
    snapshots = group_by_snapshot(panel)
    print(f"  {len(snapshots)} snapshots")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    scorecard = {}
    queue_b_result = {}
    queue_c_result = {}

    if "A" in queues:
        print("\n" + "#" * 70)
        print("# QUEUE A — STANDALONE SIGNAL EVALUATION")
        print("#" * 70)

        g1 = run_gate1_signal_cards(snapshots)
        g2 = run_gate2_fm_incremental(snapshots)
        g3 = run_gate3_bootstrap(snapshots)
        g4 = run_gate4_fdr(g2)
        g5 = run_gate5_robustness(snapshots)
        scorecard = assemble_scorecard(g1, g2, g3, g4, g5)

        with open(OUTPUT_DIR / "queue_a_scorecard.json", "w") as f:
            json.dump(scorecard, f, indent=2, default=str)

    if "B" in queues:
        print("\n" + "#" * 70)
        print("# QUEUE B — PAIRWISE CALIBRATION")
        print("#" * 70)
        queue_b_result = run_queue_b_pairwise_calibration(panel, snapshots)
        with open(OUTPUT_DIR / "queue_b_pairwise.json", "w") as f:
            json.dump(queue_b_result, f, indent=2, default=str)

    if "C" in queues:
        print("\n" + "#" * 70)
        print("# QUEUE C — B6 BUNDLE VALIDATION")
        print("#" * 70)
        queue_c_result = run_queue_c_b6_bundle(snapshots)
        with open(OUTPUT_DIR / "queue_c_b6_bundle.json", "w") as f:
            json.dump(queue_c_result, f, indent=2, default=str)

    # Master results
    master = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queues_run": queues,
        "n_snapshots": len(snapshots),
        "n_panel_rows": len(panel),
        "rerun_signals": RERUN_SIGNALS,
    }
    with open(OUTPUT_DIR / "master_results.json", "w") as f:
        json.dump(master, f, indent=2, default=str)

    # Operator memo (if all queues ran)
    if scorecard and queue_b_result and queue_c_result:
        write_operator_memo(scorecard, queue_b_result, queue_c_result, OUTPUT_DIR)

    print(f"\n{'=' * 70}")
    print("CHECKLIST v2 SELECTIVE RERUN COMPLETE")
    print(f"{'=' * 70}")
    print(f"Artifacts in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
