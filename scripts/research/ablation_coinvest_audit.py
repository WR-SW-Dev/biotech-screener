#!/usr/bin/env python3
"""Coinvest audit — Check 3: Ablation against simpler baselines.

Tests coinvest variants head-to-head on the SAME evaluation windows and
cost assumptions as Spec 049.  Uses the audit panel (with size-residualized
column) from audit_coinvest_decomposition.py.

Bundles tested:
  A1. coinvest_score_z only (original)
  A2. coinvest_z_size_resid only (size-corrected)
  A3. inst_delta_z only
  A4. coinvest_score_z + inst_delta_z (65/35)
  A5. coinvest_z_size_resid + inst_delta_z (65/35)
  A6. old actionable rank (baseline — Δ=0 by construction)
  A7. pure EW eligible (random / no sort signal)
  A8. clinical_score_v2_z only (known bad — sanity check)
  A9. coinvest_binary only
  A10. coinvest_z_sponsored only (among-sponsored z)

Usage:
    python3 scripts/research/ablation_coinvest_audit.py
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

AUDIT_PANEL = PROJECT_ROOT / "output" / "signals" / "coinvest_audit" / "research_panel_audit.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "signals" / "coinvest_audit"

# Cost model (same as Spec 049)
RW_EXTRA_COST_BPS_YR = 65
MONTHLY_COST_DRAG = RW_EXTRA_COST_BPS_YR / 12 / 10_000

BUNDLES: Dict[str, Dict[str, Tuple[float, bool]]] = {
    "A1_coinvest_original": {
        "coinvest_score_z": (1.0, True),
    },
    "A2_coinvest_size_resid": {
        "coinvest_z_size_resid": (1.0, True),
    },
    "A3_inst_delta_only": {
        "inst_delta_z": (1.0, True),
    },
    "A4_coinvest_inst_65_35": {
        "coinvest_score_z": (0.65, True),
        "inst_delta_z": (0.35, True),
    },
    "A5_resid_inst_65_35": {
        "coinvest_z_size_resid": (0.65, True),
        "inst_delta_z": (0.35, True),
    },
    # A6 (baseline) is implicit — Δ=0 by construction
    # A7 (pure EW) needs special handling
    "A8_clinical_only": {
        "clinical_score_v2_z": (1.0, True),
    },
    "A9_coinvest_binary": {
        "coinvest_binary": (1.0, True),
    },
    "A10_coinvest_sponsored": {
        "coinvest_z_sponsored": (1.0, True),
    },
}


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _safe_mean(vals):
    return statistics.mean(vals) if vals else None


def _safe_ir(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / s if s > 1e-9 else None


def _safe_tstat(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / (s / len(vals) ** 0.5) if s > 1e-9 else None


def _hit_rate(vals):
    return sum(1 for v in vals if v > 0) / len(vals) if vals else None


def _r(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)


def _pp(v):
    return v * 100 if v is not None else None


def _fmt(v, d=2):
    return f"{v:.{d}f}" if v is not None else "—"


def _fmt_pct(v):
    return f"{v*100:.0f}%" if v is not None else "—"


def zscore_eligible(rows, signal):
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


def compute_bundle_score(rows, bundle):
    z_maps = {sig: zscore_eligible(rows, sig) for sig in bundle}
    scores = {}
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        t = r.get("ticker", "")
        total, total_w = 0.0, 0.0
        for sig, (w, hib) in bundle.items():
            z = z_maps.get(sig, {}).get(t)
            if z is not None:
                total += w * (z if hib else -z)
                total_w += w
        scores[t] = total / total_w if total_w > 0 else 0.0
    return scores


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
    return num / (dx * dy) if dx > 1e-9 and dy > 1e-9 else None


def evaluate_all(snapshots, horizons, top_ns):
    """Run selector + ranker evaluation for all bundles."""
    results = {}

    for bname, bundle in BUNDLES.items():
        print(f"  {bname}...")
        results[bname] = {"selector": {}, "ranker": {}, "regime": {}}

        for tn in top_ns:
            results[bname]["selector"][str(tn)] = {}
            results[bname]["ranker"][str(tn)] = {}

            for h in horizons:
                fwd_xbi = f"fwd_excess_xbi_{h}d"
                fwd_ret = f"fwd_ret_{h}d"
                sel_imp, rnk_ic, rnk_rw_ew = [], [], []
                n_sel, n_rnk = 0, 0

                for snap_date in sorted(snapshots.keys()):
                    rows = snapshots[snap_date]

                    eligible = []
                    for r in rows:
                        if _sf(r.get("eligible")) != 1.0:
                            continue
                        fx = _sf(r.get(fwd_xbi), default=None)
                        fr = _sf(r.get(fwd_ret), default=None)
                        rank = _sf(r.get("actionable_rank"), default=None)
                        t = r.get("ticker", "")
                        if fx is not None and rank is not None:
                            eligible.append({"ticker": t, "rank": rank, "fwd_xbi": fx, "fwd_ret": fr})

                    if len(eligible) < tn:
                        continue

                    # Baseline
                    by_rank = sorted(eligible, key=lambda x: x["rank"])
                    base_ret = statistics.mean(e["fwd_xbi"] for e in by_rank[:tn])

                    # Bundle selector
                    scores = compute_bundle_score(rows, bundle)
                    for e in eligible:
                        e["bscore"] = scores.get(e["ticker"], 0.0)
                    by_bundle = sorted(eligible, key=lambda x: -x["bscore"])
                    bund_ret = statistics.mean(e["fwd_xbi"] for e in by_bundle[:tn])
                    sel_imp.append(bund_ret - base_ret)
                    n_sel += 1

                    # Ranker: within actual top-K by actionable_rank
                    topk = by_rank[:tn]
                    with_sig = [e for e in topk if e.get("bscore") is not None]
                    if len(with_sig) >= 5:
                        n_rnk += 1
                        # IC
                        ic = spearman_ic(
                            [e["bscore"] for e in with_sig],
                            [e["fwd_ret"] for e in with_sig if e["fwd_ret"] is not None][: len(with_sig)],
                        )
                        if ic is not None:
                            rnk_ic.append(ic)
                        # RW vs EW
                        ew = statistics.mean(e["fwd_ret"] for e in topk if e["fwd_ret"] is not None)
                        sorted_sig = sorted(with_sig, key=lambda x: -x["bscore"])
                        ns = len(sorted_sig)
                        weights = [(ns - i) for i in range(ns)]
                        ws = sum(weights)
                        fwd_vals = [e["fwd_ret"] for e in sorted_sig]
                        if all(v is not None for v in fwd_vals):
                            rw = sum(weights[i] * fwd_vals[i] for i in range(ns)) / ws
                            rnk_rw_ew.append(rw - ew)

                results[bname]["selector"][str(tn)][str(h)] = {
                    "improvement_pp": _r(_pp(_safe_mean(sel_imp))),
                    "improvement_tstat": _r(_safe_tstat([v * 100 for v in sel_imp])),
                    "improvement_ir": _r(_safe_ir([v * 100 for v in sel_imp])),
                    "hit_rate": _r(_hit_rate(sel_imp)),
                    "n": n_sel,
                }
                rw_ew_net = (_safe_mean(rnk_rw_ew) - MONTHLY_COST_DRAG) if rnk_rw_ew else None
                results[bname]["ranker"][str(tn)][str(h)] = {
                    "ic_mean": _r(_safe_mean(rnk_ic)),
                    "ic_tstat": _r(_safe_tstat(rnk_ic)),
                    "rw_ew_gross_pp": _r(_pp(_safe_mean(rnk_rw_ew))),
                    "rw_ew_net_pp": _r(_pp(rw_ew_net)),
                    "n": n_rnk,
                }

        # Regime (63d, top-30 only)
        for regime in ["bear", "neutral", "bull"]:
            imp_vals = []
            for snap_date, rows in sorted(snapshots.items()):
                sample_regime = None
                for r in rows:
                    sample_regime = r.get("regime_63d")
                    if sample_regime:
                        break
                if sample_regime != regime:
                    continue

                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    fx = _sf(r.get("fwd_excess_xbi_63d"), default=None)
                    rank = _sf(r.get("actionable_rank"), default=None)
                    t = r.get("ticker", "")
                    if fx is not None and rank is not None:
                        eligible.append({"ticker": t, "rank": rank, "fwd_xbi": fx})

                if len(eligible) < 30:
                    continue
                by_rank = sorted(eligible, key=lambda x: x["rank"])
                base = statistics.mean(e["fwd_xbi"] for e in by_rank[:30])
                scores = compute_bundle_score(rows, bundle)
                for e in eligible:
                    e["bscore"] = scores.get(e["ticker"], 0.0)
                by_b = sorted(eligible, key=lambda x: -x["bscore"])
                bund = statistics.mean(e["fwd_xbi"] for e in by_b[:30])
                imp_vals.append(bund - base)

            results[bname]["regime"][regime] = {
                "improvement_pp": _r(_pp(_safe_mean(imp_vals))),
                "hit_rate": _r(_hit_rate(imp_vals)),
                "n": len(imp_vals),
            }

    # Pure EW (special case — random selection from eligible)
    print("  A7_pure_ew...")
    results["A7_pure_ew"] = {"selector": {}, "ranker": {}, "regime": {}}
    for tn in top_ns:
        results["A7_pure_ew"]["selector"][str(tn)] = {}
        results["A7_pure_ew"]["ranker"][str(tn)] = {}
        for h in horizons:
            fwd_xbi = f"fwd_excess_xbi_{h}d"
            imp_vals = []
            for snap_date in sorted(snapshots.keys()):
                rows = snapshots[snap_date]
                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    fx = _sf(r.get(fwd_xbi), default=None)
                    rank = _sf(r.get("actionable_rank"), default=None)
                    if fx is not None and rank is not None:
                        eligible.append({"rank": rank, "fwd_xbi": fx})
                if len(eligible) < tn:
                    continue

                base = statistics.mean(e["fwd_xbi"] for e in sorted(eligible, key=lambda x: x["rank"])[:tn])
                ew_all = statistics.mean(e["fwd_xbi"] for e in eligible)
                # EW top-N from eligible vs baseline top-N by rank
                # Pure EW = eligible mean (since no sort signal)
                imp_vals.append(ew_all - base)

            results["A7_pure_ew"]["selector"][str(tn)][str(h)] = {
                "improvement_pp": _r(_pp(_safe_mean(imp_vals))),
                "improvement_tstat": _r(_safe_tstat([v * 100 for v in imp_vals])),
                "improvement_ir": _r(_safe_ir([v * 100 for v in imp_vals])),
                "hit_rate": _r(_hit_rate(imp_vals)),
                "n": len(imp_vals),
            }
            results["A7_pure_ew"]["ranker"][str(tn)][str(h)] = {
                "ic_mean": None,
                "ic_tstat": None,
                "rw_ew_gross_pp": None,
                "rw_ew_net_pp": None,
                "n": 0,
            }

    return results


def main():
    print("=" * 60)
    print("COINVEST ABLATION — Check 3")
    print("=" * 60)

    if not AUDIT_PANEL.exists():
        print(f"ERROR: Audit panel not found at {AUDIT_PANEL}")
        print("Run audit_coinvest_decomposition.py first.")
        sys.exit(1)

    print("\nLoading audit panel...")
    with open(AUDIT_PANEL) as f:
        panel = list(csv.DictReader(f))
    print(f"  {len(panel):,} rows")

    snapshots = defaultdict(list)
    for row in panel:
        snapshots[row["snapshot_date"]].append(row)
    snapshots = dict(sorted(snapshots.items()))
    print(f"  {len(snapshots)} snapshots")

    horizons = [20, 63]
    top_ns = [20, 30]

    print(f"\nRunning ablation ({len(BUNDLES)+1} variants, horizons={horizons}, top_ns={top_ns})...\n")
    results = evaluate_all(snapshots, horizons, top_ns)

    # Write JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "ablation_results.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nJSON: {json_path}")

    # Summary tables
    print(f"\n{'='*80}")
    print("ABLATION RESULTS — SELECTOR (Top-30, 63d, excess vs XBI)")
    print(f"{'='*80}")
    print(f"{'Variant':<30s} {'Δ pp':>8s} {'t-stat':>8s} {'IR':>8s} {'hit%':>8s} {'N':>5s}")
    print(f"{'-'*30} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*5}")

    # Sort by improvement
    all_names = sorted(
        results.keys(),
        key=lambda n: results[n]["selector"].get("30", {}).get("63", {}).get("improvement_pp") or -999,
        reverse=True,
    )

    for name in all_names:
        s = results[name]["selector"].get("30", {}).get("63", {})
        print(
            f"  {name:<28s} {_fmt(s.get('improvement_pp')):>8s} {_fmt(s.get('improvement_tstat')):>8s} "
            f"{_fmt(s.get('improvement_ir')):>8s} {_fmt_pct(s.get('hit_rate')):>8s} {s.get('n', 0):>5d}"
        )

    print(f"\n{'='*80}")
    print("ABLATION RESULTS — RANKER (within Top-30, 63d)")
    print(f"{'='*80}")
    print(f"{'Variant':<30s} {'IC':>8s} {'IC t':>8s} {'RW-EW net':>10s} {'N':>5s}")
    print(f"{'-'*30} {'-'*8} {'-'*8} {'-'*10} {'-'*5}")

    for name in all_names:
        r = results[name]["ranker"].get("30", {}).get("63", {})
        print(
            f"  {name:<28s} {_fmt(r.get('ic_mean')):>8s} {_fmt(r.get('ic_tstat')):>8s} "
            f"{_fmt(r.get('rw_ew_net_pp')):>10s} {r.get('n', 0):>5d}"
        )

    print(f"\n{'='*80}")
    print("REGIME STABILITY (Top-30, 63d)")
    print(f"{'='*80}")
    print(f"{'Variant':<30s} {'Bear Δ':>8s} {'Neutral Δ':>10s} {'Bull Δ':>8s}")
    print(f"{'-'*30} {'-'*8} {'-'*10} {'-'*8}")

    for name in all_names:
        reg = results[name].get("regime", {})
        bear = reg.get("bear", {}).get("improvement_pp")
        neut = reg.get("neutral", {}).get("improvement_pp")
        bull = reg.get("bull", {}).get("improvement_pp")
        print(f"  {name:<28s} {_fmt(bear):>8s} {_fmt(neut):>10s} {_fmt(bull):>8s}")

    # Verdicts
    print(f"\n{'='*80}")
    print("ABLATION VERDICTS")
    print(f"{'='*80}")

    orig = results.get("A1_coinvest_original", {}).get("selector", {}).get("30", {}).get("63", {})
    resid = results.get("A2_coinvest_size_resid", {}).get("selector", {}).get("30", {}).get("63", {})
    inst = results.get("A3_inst_delta_only", {}).get("selector", {}).get("30", {}).get("63", {})
    combo = results.get("A4_coinvest_inst_65_35", {}).get("selector", {}).get("30", {}).get("63", {})
    combo_r = results.get("A5_resid_inst_65_35", {}).get("selector", {}).get("30", {}).get("63", {})
    ew = results.get("A7_pure_ew", {}).get("selector", {}).get("30", {}).get("63", {})
    clinical = results.get("A8_clinical_only", {}).get("selector", {}).get("30", {}).get("63", {})

    def _v(d, k):
        v = d.get(k)
        return float(v) if v is not None else None

    print("\n1. Coinvest vs inst:")
    o, i = _v(orig, "improvement_pp"), _v(inst, "improvement_pp")
    if o is not None and i is not None:
        print(
            f"   coinvest={o:+.2f}pp  inst={i:+.2f}pp  → coinvest {'dominates' if o > i*1.5 else 'leads' if o > i else 'trails'}"
        )

    print("\n2. Size-corrected coinvest vs original:")
    o, r = _v(orig, "improvement_pp"), _v(resid, "improvement_pp")
    if o is not None and r is not None:
        pct = r / o * 100 if o != 0 else 0
        print(f"   original={o:+.2f}pp  size_resid={r:+.2f}pp  → {pct:.0f}% retained after size correction")

    print("\n3. Combined vs solo signals:")
    c = _v(combo, "improvement_pp")
    cr = _v(combo_r, "improvement_pp")
    if o is not None and c is not None:
        print(f"   coinvest_only={o:+.2f}pp  coinvest+inst={c:+.2f}pp  → combo {'helps' if c > o else 'hurts'}")
    if r is not None and cr is not None:
        print(f"   resid_only={r:+.2f}pp    resid+inst={cr:+.2f}pp    → combo {'helps' if cr > r else 'hurts'}")

    print("\n4. All vs pure EW (does any sort signal beat random?):")
    e = _v(ew, "improvement_pp")
    if e is not None:
        print(f"   Pure EW vs baseline: {e:+.2f}pp")
        if o is not None:
            print(f"   Coinvest vs pure EW: {o - e:+.2f}pp net lift")

    print("\n5. Clinical (sanity check):")
    cl = _v(clinical, "improvement_pp")
    if cl is not None:
        print(f"   clinical={cl:+.2f}pp  → {'CONFIRMED DESTRUCTIVE' if cl < 0 else 'unexpectedly positive'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
