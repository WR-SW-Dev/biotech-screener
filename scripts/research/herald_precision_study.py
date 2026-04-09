#!/usr/bin/env python3
"""Spec 056 — Herald Precision / Catalyst Quality Signal Study.

Tests whether catalyst date quality signals (hard catalyst, source quality,
event type, precision) predict returns. First study to apply full Promotion
Checklist v2 (Fama-MacBeth, bootstrap, FDR, LOSO robustness).

Usage:
    python3 scripts/research/herald_precision_study.py
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from common.stats.bootstrap import block_bootstrap
from common.stats.cross_sectional import run_incremental_test
from common.stats.multiple_testing import benjamini_hochberg
from common.stats.robustness import multi_slice_robustness

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "herald_precision_study"

SCHEMA_VERSION = "herald_precision_study.v1"
HORIZONS = [20, 63]
TOP_NS = [20, 30]
RW_EXTRA_COST_BPS_YR = 65
MONTHLY_COST_DRAG = RW_EXTRA_COST_BPS_YR / 12 / 10_000

INCUMBENT_CONTROLS = ["coinvest_score_z", "inst_delta_z", "financial_score"]

SOURCE_QUALITY_MAP = {
    "SEC_8K_FILING": 3,
    "FDA_CALENDAR": 3,
    "PDUFA_MANUAL": 3,
    "CTGOV_CALENDAR": 2,
    "IR_EVENTS": 2,
    "CTGOV_PCD_FAR": 1,
    "CTGOV": 1,
}
EVENT_TYPE_SCORE_MAP = {
    "FDA_PDUFA_DATE": 3,
    "DATA_READOUT": 2,
    "CT_PRIMARY_COMPLETION": 1,
    "CT_STUDY_COMPLETION": 1,
    "CT_RESULTS_POSTED": 0,
    "CT_TRIAL_SUSPENDED": 0,
    "IR_EVENT": 0,
}

HERALD_SIGNALS = [
    "is_hard_catalyst",
    "hard_catalyst_z",
    "catalyst_proximity_z",
    "source_quality_score",
    "event_type_score",
    "binary_now_flag",
    "has_catalyst_flag",
    "hard_clinical_flag",
    "regulatory_flag",
    "clinical_date_confidence",
]

SIGNAL_DIRECTION = {
    "is_hard_catalyst": True,
    "hard_catalyst_z": True,
    "catalyst_proximity_z": True,
    "source_quality_score": True,
    "event_type_score": True,
    "binary_now_flag": True,
    "has_catalyst_flag": True,
    "hard_clinical_flag": True,
    "regulatory_flag": True,
    "clinical_date_confidence": True,
}


# ── Helpers ──────────────────────────────────────────────────────────


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


def _fmt(v, d=2):
    return f"{v:.{d}f}" if v is not None else "---"


def _safe_mean(vals):
    return statistics.mean(vals) if vals else None


def _safe_tstat(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / (s / len(vals) ** 0.5) if s > 1e-9 else None


def _hit_rate(vals):
    return sum(1 for v in vals if v > 0) / len(vals) if vals else None


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


# ── Data Loading & Feature Computation ───────────────────────────────


def load_panel():
    print("Loading research panel...")
    with open(PANEL_CSV) as f:
        panel = list(csv.DictReader(f))
    print(f"  {len(panel):,} rows")
    return panel


def compute_derived_signals(panel):
    """Add derived Herald signals to each panel row."""
    snapshots = defaultdict(list)
    for row in panel:
        snapshots[row["snapshot_date"]].append(row)

    for snap_date, rows in snapshots.items():
        # Collect for z-scoring
        hard_vals, hard_tickers = [], []
        prox_vals, prox_tickers = [], []

        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            h = _sf(r.get("is_hard_catalyst"))
            if h is not None:
                hard_vals.append(h)
                hard_tickers.append(r.get("ticker", ""))
            cd = _sf(r.get("catalyst_days"))
            if cd is not None and cd > 0:
                prox_vals.append(1.0 / cd)
                prox_tickers.append(r.get("ticker", ""))

        # Z-score maps
        hard_z = {}
        if len(hard_vals) >= 3:
            m, s = statistics.mean(hard_vals), statistics.stdev(hard_vals)
            if s > 1e-9:
                hard_z = {hard_tickers[i]: (hard_vals[i] - m) / s for i in range(len(hard_vals))}

        prox_z = {}
        if len(prox_vals) >= 3:
            m, s = statistics.mean(prox_vals), statistics.stdev(prox_vals)
            if s > 1e-9:
                prox_z = {prox_tickers[i]: (prox_vals[i] - m) / s for i in range(len(prox_vals))}

        for r in rows:
            ticker = r.get("ticker", "")
            r["hard_catalyst_z"] = hard_z.get(ticker, "")
            r["catalyst_proximity_z"] = prox_z.get(ticker, "")

            src = r.get("catalyst_source", "")
            r["source_quality_score"] = SOURCE_QUALITY_MAP.get(src, 0) if src else ""

            evt = r.get("catalyst_event_type", "")
            r["event_type_score"] = EVENT_TYPE_SCORE_MAP.get(evt, 0) if evt else ""

            bucket = r.get("catalyst_bucket", "")
            r["binary_now_flag"] = 1.0 if bucket == "binary_now" else 0.0

            cd = _sf(r.get("catalyst_days"))
            r["has_catalyst_flag"] = 1.0 if cd is not None else 0.0

            hard = _sf(r.get("is_hard_catalyst"))
            fam = r.get("catalyst_family", "")
            r["hard_clinical_flag"] = 1.0 if hard == 1.0 and fam == "CLINICAL" else 0.0

            r["regulatory_flag"] = 1.0 if fam == "REGULATORY" else 0.0

    print("  Derived signals computed")
    return panel


def group_by_snapshot(panel):
    groups = defaultdict(list)
    for row in panel:
        groups[row["snapshot_date"]].append(row)
    return dict(sorted(groups.items()))


# ── Track A: Univariate Signal Cards ─────────────────────────────────


def run_track_a(panel, snapshots):
    print("\n" + "=" * 70)
    print("TRACK A — UNIVARIATE HERALD SIGNAL CARDS")
    print("=" * 70)

    results = []
    for signal in HERALD_SIGNALS:
        higher_better = SIGNAL_DIRECTION.get(signal, True)
        n_eligible = sum(1 for r in panel if _sf(r.get("eligible")) == 1.0 and r.get(signal) not in (None, ""))
        cov_pct = n_eligible / sum(1 for r in panel if _sf(r.get("eligible")) == 1.0) * 100

        print(f"  {signal} (cov={cov_pct:.0f}%)...", end=" ")

        if n_eligible < 50:
            results.append(
                {"signal": signal, "coverage_pct": _r(cov_pct), "verdict": "NO_GO", "reason": "low coverage"}
            )
            print("SKIP")
            continue

        # Selector delta and ranker IC at 63d
        sel_improvements = []
        ranker_ics = []
        for snap_date, rows in sorted(snapshots.items()):
            elig = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal))
                fwd = _sf(r.get("fwd_excess_xbi_63d"))
                rank = _sf(r.get("actionable_rank"))
                if sv is not None and fwd is not None and rank is not None:
                    elig.append({"signal": sv, "fwd": fwd, "rank": rank})
            if len(elig) < 30:
                continue

            by_rank = sorted(elig, key=lambda x: x["rank"])[:30]
            baseline = statistics.mean(e["fwd"] for e in by_rank)
            if higher_better:
                by_sig = sorted(elig, key=lambda x: -x["signal"])
            else:
                by_sig = sorted(elig, key=lambda x: x["signal"])
            sel_ret = statistics.mean(e["fwd"] for e in by_sig[:30])
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

        # Verdict
        if (sel_t or 0) >= 1.6 and (sel_pp or 0) > 0:
            verdict = "PROMOTE_CANDIDATE"
        elif (sel_t or 0) >= 1.0 and (sel_pp or 0) > 0 or (ic_t or 0) >= 1.6:
            verdict = "SHADOW"
        elif (sel_pp or 0) > 0:
            verdict = "HOLD"
        else:
            verdict = "NO_GO"

        results.append(
            {
                "signal": signal,
                "coverage_pct": _r(cov_pct),
                "selector_delta_pp": sel_pp,
                "selector_tstat": sel_t,
                "ranker_ic": ic_mean,
                "ranker_ic_tstat": ic_t,
                "n_periods": len(sel_improvements),
                "verdict": verdict,
            }
        )
        print(f"Δ={sel_pp or 0:+.2f}pp t={sel_t or 0:.2f} IC={ic_mean or 0:+.3f} → {verdict}")

    return results


# ── Track B: Bundle Tests ────────────────────────────────────────────


SELECTOR_BUNDLES = {
    "S0_incumbent_B6": {"coinvest_score_z": (0.65, True), "inst_delta_z": (0.35, True)},
    "S1_B6_plus_hard_catalyst": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "is_hard_catalyst": (0.20, True),
    },
    "S2_B6_plus_source_quality": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "source_quality_score": (0.20, True),
    },
    "S3_B6_plus_event_type": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "event_type_score": (0.20, True),
    },
    "S4_B6_plus_hard_clinical": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "hard_clinical_flag": (0.20, True),
    },
    "S5_B6_plus_binary_now": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "binary_now_flag": (0.20, True),
    },
    "S6_B6_plus_proximity": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "catalyst_proximity_z": (0.20, True),
    },
    "S7_catalyst_quality_only": {
        "is_hard_catalyst": (0.30, True),
        "source_quality_score": (0.30, True),
        "event_type_score": (0.20, True),
        "catalyst_proximity_z": (0.20, True),
    },
    "S8_B6_light_herald": {
        "coinvest_score_z": (0.50, True),
        "inst_delta_z": (0.25, True),
        "is_hard_catalyst": (0.10, True),
        "source_quality_score": (0.10, True),
        "event_type_score": (0.05, True),
    },
}


def compute_bundle_score_snap(rows, bundle):
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


def run_track_b(snapshots):
    print("\n" + "=" * 70)
    print("TRACK B — SELECTOR BUNDLE TESTS")
    print("=" * 70)

    results = []
    for bname, bundle in SELECTOR_BUNDLES.items():
        improvements = []
        for snap_date, rows in sorted(snapshots.items()):
            eligible = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                fwd = _sf(r.get("fwd_excess_xbi_63d"))
                rank = _sf(r.get("actionable_rank"))
                if fwd is not None and rank is not None:
                    eligible.append({"ticker": r.get("ticker", ""), "rank": rank, "fwd": fwd})
            if len(eligible) < 30:
                continue
            by_rank = sorted(eligible, key=lambda x: x["rank"])[:30]
            baseline = statistics.mean(e["fwd"] for e in by_rank)
            scores = compute_bundle_score_snap(rows, bundle)
            for e in eligible:
                e["score"] = scores.get(e["ticker"], 0.0)
            by_score = sorted(eligible, key=lambda x: -x["score"])[:30]
            bundle_ret = statistics.mean(e["fwd"] for e in by_score)
            improvements.append(bundle_ret - baseline)

        imp_pp = _r(_pp(_safe_mean(improvements)))
        imp_t = _r(_safe_tstat([v * 100 for v in improvements]))
        print(f"  {bname:35s} Δ={imp_pp or 0:+.2f}pp t={imp_t or 0:.2f}")
        results.append(
            {
                "bundle_name": bname,
                "improvement_pp": imp_pp,
                "improvement_tstat": imp_t,
                "n_periods": len(improvements),
                "monthly_improvements": [v * 100 for v in improvements],
            }
        )
    return results


# ── Checklist v2: Fama-MacBeth ───────────────────────────────────────


def run_fama_macbeth_tests(snapshots):
    print("\n" + "=" * 70)
    print("CHECKLIST v2 — FAMA-MACBETH INCREMENTAL TESTS")
    print("=" * 70)

    results = {}
    testable = [s for s in HERALD_SIGNALS if s not in INCUMBENT_CONTROLS]
    for signal in testable:
        inc = run_incremental_test(snapshots, signal, INCUMBENT_CONTROLS)
        uni_t = inc.get("univariate", {}).get("nw_t", 0) or 0
        inc_t = inc.get("incremental", {}).get("nw_t", 0) or 0
        verdict = inc.get("verdict", "?")
        print(f"  {signal:30s} uni-t={uni_t:+.2f} incr-t={inc_t:+.2f} → {verdict}")
        results[signal] = inc
    return results


# ── Checklist v2: Bootstrap ──────────────────────────────────────────


def run_bootstrap_tests(snapshots):
    print("\n" + "=" * 70)
    print("CHECKLIST v2 — BLOCK BOOTSTRAP")
    print("=" * 70)

    results = {}
    # Compute monthly excess for top-30 by each signal
    for signal in [
        "is_hard_catalyst",
        "hard_clinical_flag",
        "source_quality_score",
        "event_type_score",
        "binary_now_flag",
    ]:
        monthly = []
        for snap_date in sorted(snapshots.keys()):
            rows = snapshots[snap_date]
            elig = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal))
                fwd = _sf(r.get("fwd_excess_xbi_63d"))
                rank = _sf(r.get("actionable_rank"))
                if sv is not None and fwd is not None and rank is not None:
                    elig.append({"signal": sv, "fwd": fwd, "rank": rank})
            if len(elig) < 30:
                continue
            by_rank = sorted(elig, key=lambda x: x["rank"])[:30]
            baseline = statistics.mean(e["fwd"] for e in by_rank)
            by_sig = sorted(elig, key=lambda x: -x["signal"])[:30]
            sel_ret = statistics.mean(e["fwd"] for e in by_sig)
            monthly.append(sel_ret - baseline)

        if len(monthly) >= 12:
            boot = block_bootstrap(monthly, block_length=6, n_bootstrap=10000, seed=42)
            excl = "CI excl 0" if boot.get("ci_excludes_zero") else "CI incl 0"
            print(
                f"  {signal:30s} Δ={boot.get('boot_mean', 0):+.4f} "
                f"95% CI=[{boot.get('ci_lower', 0):.4f}, {boot.get('ci_upper', 0):.4f}] {excl}"
            )
            results[signal] = boot
        else:
            print(f"  {signal:30s} SKIP (only {len(monthly)} months)")
    return results


# ── Checklist v2: FDR ────────────────────────────────────────────────


def run_fdr(fm_results):
    print("\n" + "=" * 70)
    print("CHECKLIST v2 — BH FDR CORRECTION")
    print("=" * 70)

    pvals = {}
    for signal, test in fm_results.items():
        p = test.get("incremental", {}).get("p_value")
        if p is not None:
            pvals[signal] = p

    if not pvals:
        print("  No p-values available")
        return {}

    bh = benjamini_hochberg(pvals, alpha=0.10)
    for name in sorted(pvals, key=pvals.get):
        r = bh["results"][name]
        status = "REJECT" if r["rejected"] else "retain"
        print(f"  {name:30s} p={r['raw_p']:.4f} q={r['q_value']:.4f} → {status}")
    print(f"  → {bh['n_rejected']}/{bh['n_tests']} rejected at FDR=0.10")
    return bh


# ── Checklist v2: LOSO Robustness ────────────────────────────────────


def run_robustness(snapshots):
    print("\n" + "=" * 70)
    print("CHECKLIST v2 — LEAVE-ONE-SLICE-OUT ROBUSTNESS")
    print("=" * 70)

    results = {}
    for signal in ["is_hard_catalyst", "hard_clinical_flag", "source_quality_score"]:
        print(f"\n  {signal}...")
        rob = multi_slice_robustness(snapshots, signal, higher_is_better=True, top_n=30)
        for dim, sr in rob.get("slices", {}).items():
            print(
                f"    {dim}: worst={sr.get('worst_slice')} "
                f"({sr.get('worst_slice_delta', 'N/A')}pp) → {sr.get('stability_verdict', '?')}"
            )
        print(f"    OVERALL: {rob.get('overall_verdict')}")
        results[signal] = {
            "overall_verdict": rob.get("overall_verdict"),
            "verdicts": rob.get("verdicts"),
        }
    return results


# ── Track C: Interaction Tests ───────────────────────────────────────


def run_interactions(panel, snapshots):
    print("\n" + "=" * 70)
    print("TRACK C — INTERACTION TESTS")
    print("=" * 70)

    results = {}

    # C1: hard × coinvest interaction
    print("  C1: hard_catalyst × coinvest_score_z interaction...")
    hi_hi, hi_lo, lo_hi, lo_lo = [], [], [], []
    for snap_date, rows in sorted(snapshots.items()):
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            hard = _sf(r.get("is_hard_catalyst"))
            cv = _sf(r.get("coinvest_score_z"))
            fwd = _sf(r.get("fwd_excess_xbi_63d"))
            if hard is None or cv is None or fwd is None:
                continue
            if hard == 1.0 and cv > 0:
                hi_hi.append(fwd)
            elif hard == 1.0 and cv <= 0:
                hi_lo.append(fwd)
            elif hard == 0.0 and cv > 0:
                lo_hi.append(fwd)
            else:
                lo_lo.append(fwd)

    for label, vals in [("hard+hi_cv", hi_hi), ("hard+lo_cv", hi_lo), ("soft+hi_cv", lo_hi), ("soft+lo_cv", lo_lo)]:
        if vals:
            print(f"    {label:15s} mean={_safe_mean(vals) * 100:+.2f}pp n={len(vals)}")

    results["hard_x_coinvest"] = {
        "hard_hi_cv_pp": _r(_pp(_safe_mean(hi_hi))),
        "hard_lo_cv_pp": _r(_pp(_safe_mean(hi_lo))),
        "soft_hi_cv_pp": _r(_pp(_safe_mean(lo_hi))),
        "soft_lo_cv_pp": _r(_pp(_safe_mean(lo_lo))),
        "interaction_spread_pp": _r(_pp((_safe_mean(hi_hi) or 0) - (_safe_mean(lo_lo) or 0))),
    }

    # C2: source quality within near-catalyst
    print("\n  C2: source_quality within near-catalyst (≤30d)...")
    for src_label, src_vals in [("SEC_8K", []), ("CTGOV_CAL", []), ("CTGOV_FAR", [])]:
        for r in panel:
            if _sf(r.get("eligible")) != 1.0:
                continue
            cd = _sf(r.get("catalyst_days"))
            if cd is None or cd > 30:
                continue
            fwd = _sf(r.get("fwd_excess_xbi_63d"))
            src = r.get("catalyst_source", "")
            if fwd is None:
                continue
            if src_label == "SEC_8K" and src == "SEC_8K_FILING":
                src_vals.append(fwd)
            elif src_label == "CTGOV_CAL" and src == "CTGOV_CALENDAR":
                src_vals.append(fwd)
            elif src_label == "CTGOV_FAR" and src == "CTGOV_PCD_FAR":
                src_vals.append(fwd)
        if src_vals:
            print(f"    {src_label:15s} mean={_safe_mean(src_vals) * 100:+.2f}pp n={len(src_vals)}")

    return results


# ── Main ─────────────────────────────────────────────────────────────


def main():
    panel = load_panel()
    panel = compute_derived_signals(panel)
    snapshots = group_by_snapshot(panel)
    print(f"  {len(snapshots)} snapshots\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Track A: Univariate
    track_a = run_track_a(panel, snapshots)

    # Track B: Bundles
    track_b = run_track_b(snapshots)

    # Checklist v2
    fm_results = run_fama_macbeth_tests(snapshots)
    boot_results = run_bootstrap_tests(snapshots)
    fdr_results = run_fdr(fm_results)
    rob_results = run_robustness(snapshots)

    # Track C: Interactions
    interactions = run_interactions(panel, snapshots)

    # ── Checklist v2 Summary ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("PROMOTION CHECKLIST v2 SUMMARY")
    print("=" * 70)

    checklist = {}
    for signal in HERALD_SIGNALS:
        card = next((c for c in track_a if c["signal"] == signal), {})
        fm = fm_results.get(signal, {})
        boot = boot_results.get(signal, {})
        fdr_r = fdr_results.get("results", {}).get(signal, {}) if fdr_results else {}
        rob = rob_results.get(signal, {})

        checks = {
            "1_signal_card": (card.get("selector_delta_pp") or 0) > 0 and (card.get("ranker_ic") or 0) > 0,
            "2_fama_macbeth": abs(fm.get("incremental", {}).get("nw_t", 0) or 0) >= 1.96,
            "3_bootstrap_ci": boot.get("ci_excludes_zero", False),
            "4_bh_fdr": fdr_r.get("rejected", False),
            "5_loso_robust": "UNSTABLE" not in rob.get("overall_verdict", "N/A"),
        }
        n_pass = sum(checks.values())
        overall = "PASS" if all(checks.values()) else f"FAIL ({n_pass}/5)"

        checklist[signal] = {"checks": checks, "overall": overall}
        print(
            f"  {signal:30s} card={'✓' if checks['1_signal_card'] else '✗'} "
            f"FM={'✓' if checks['2_fama_macbeth'] else '✗'} "
            f"boot={'✓' if checks['3_bootstrap_ci'] else '✗'} "
            f"FDR={'✓' if checks['4_bh_fdr'] else '✗'} "
            f"LOSO={'✓' if checks['5_loso_robust'] else '✗'} "
            f"→ {overall}"
        )

    # Write all results
    master = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "track_a": track_a,
        "track_b": [{k: v for k, v in b.items() if k != "monthly_improvements"} for b in track_b],
        "fama_macbeth": (
            {k: {kk: vv for kk, vv in v.items() if kk != "monthly_coefficients"} for k, v in fm_results.items()}
            if fm_results
            else {}
        ),
        "bootstrap": boot_results,
        "fdr": {k: v for k, v in fdr_results.items() if k != "results"} if fdr_results else {},
        "robustness": rob_results,
        "interactions": interactions,
        "checklist_v2": checklist,
    }
    with open(OUTPUT_DIR / "master_results.json", "w") as f:
        json.dump(master, f, indent=2, default=str)

    # Signal ranking table
    lines = [
        "# Spec 056 — Herald Precision Signal Ranking",
        "",
        "| Signal | Cov% | Sel Δpp | Sel t | IC | FM incr-t | Boot CI | FDR q | Verdict |",
        "|--------|------|---------|-------|----|-----------|---------|-------|---------|",
    ]
    for c in sorted(track_a, key=lambda x: x.get("selector_delta_pp") or -999, reverse=True):
        sig = c["signal"]
        fm = fm_results.get(sig, {})
        boot = boot_results.get(sig, {})
        fdr_r = fdr_results.get("results", {}).get(sig, {}) if fdr_results else {}
        inc_t = fm.get("incremental", {}).get("nw_t")
        ci = "excl" if boot.get("ci_excludes_zero") else "incl" if boot else "N/A"
        q = fdr_r.get("q_value")
        lines.append(
            f"| `{sig}` | {c.get('coverage_pct', 0):.0f} "
            f"| {_fmt(c.get('selector_delta_pp'))} | {_fmt(c.get('selector_tstat'))} "
            f"| {_fmt(c.get('ranker_ic'), 3)} | {_fmt(inc_t)} "
            f"| {ci} | {_fmt(q)} | {c.get('verdict', '?')} |"
        )
    lines.append("")
    (OUTPUT_DIR / "signal_ranking_table.md").write_text("\n".join(lines))

    print(f"\nAll artifacts in: {OUTPUT_DIR}")
    print("Done.")


if __name__ == "__main__":
    main()
