#!/usr/bin/env python3
"""DEM robustness battery for the 2026-04-28 snapshot — read-only.

Seven structural-stress tests on today's selector. No production state
modified, no model rerun, no feed added. Methodology is fixed in this
file; pre-registered hypothesis included verbatim in the output.

Inputs:
  data/snapshots/2026-04-28/rankings.csv
  artifacts/audit/inst_delta_attribution_2026-04-28.json (optional)

Outputs:
  artifacts/audit/inst_delta_robustness_battery_2026-04-28.md
  artifacts/audit/inst_delta_robustness_battery_2026-04-28.json
"""

from __future__ import annotations

import csv
import json
import random
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RANK_FILE = REPO / "data" / "snapshots" / "2026-04-28" / "rankings.csv"
ATTR_FILE = REPO / "artifacts" / "audit" / "inst_delta_attribution_2026-04-28.json"
OUT_DIR = REPO / "artifacts" / "audit"
OUT_MD = OUT_DIR / "inst_delta_robustness_battery_2026-04-28.md"
OUT_JSON = OUT_DIR / "inst_delta_robustness_battery_2026-04-28.json"

KNOWN_ARTIFACT_TICKERS = {"NRIX", "COGT", "ZYME", "MIRM", "ORKA", "ABVX"}
INDEPENDENT_SIGNAL_COLS = [
    "clinical_score_v2_z",
    "financial_score",
    "selector_clinical_block",
    "selector_catalyst_block",
    "selector_survivability_block",
    "selector_market_block",
]

USER_PRE_REGISTERED_EXPECTATION = """\
- DEM grades "mixed/fragile," not fully broken.
- Top-10 is least robust because overlap between CURRENT and CF is only 4/10.
- Top-30 will show material contamination, but not all 13 artifact entrants are equally bad.
- Structurally defensible cutoff is likely top-40 or top-60 for monitoring, not top-10.
- Production action should remain: none; observe until h20d and post-13F refresh."""


def f(s):
    try:
        return float(s) if s not in ("", None, "nan") else None
    except (ValueError, TypeError):
        return None


def spearman(rank_a, rank_b):
    """Spearman correlation given two dicts {ticker: rank}."""
    common = sorted(set(rank_a) & set(rank_b))
    if len(common) < 3:
        return None
    n = len(common)
    a = [rank_a[t] for t in common]
    b = [rank_b[t] for t in common]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    den = (sum((x - ma) ** 2 for x in a) * sum((x - mb) ** 2 for x in b)) ** 0.5
    return num / den if den else None


def percentile_rank(values, x):
    """Percentile rank of x in values (0..1). Higher x → higher percentile."""
    if x is None:
        return None
    n = len(values)
    if n == 0:
        return None
    below = sum(1 for v in values if v is not None and v < x)
    return below / n


def main():
    # -- Load data --
    with open(RANK_FILE) as fh:
        rows = list(csv.DictReader(fh))
    universe = []
    for r in rows:
        rec = {
            "ticker": r["ticker"],
            "actionable_rank": f(r.get("actionable_rank")),
            "selector_score": f(r.get("selector_score")),
            "coinvest_score_z": f(r.get("coinvest_score_z")),
            "inst_delta_z": f(r.get("inst_delta_z")),
        }
        for col in INDEPENDENT_SIGNAL_COLS:
            rec[col] = f(r.get(col))
        universe.append(rec)

    # Filter to tickers with the core fields we need
    rankable = [u for u in universe if u["selector_score"] is not None]
    rankable_with_features = [
        u for u in rankable if u["coinvest_score_z"] is not None and u["inst_delta_z"] is not None
    ]
    n_universe = len(rankable_with_features)

    # Baseline ranks: by actual actionable_rank AND by selector_score (apples-to-apples for tests 1, 5)
    by_actionable = sorted(
        [u for u in rankable if u["actionable_rank"] is not None],
        key=lambda u: u["actionable_rank"],
    )
    by_selector = sorted(rankable_with_features, key=lambda u: -u["selector_score"])
    baseline_rank_selector = {u["ticker"]: i + 1 for i, u in enumerate(by_selector)}

    baseline_top30 = set(u["ticker"] for u in by_actionable[:30])

    results = {
        "as_of": "2026-04-28",
        "n_universe_rankable": n_universe,
        "user_pre_registered_expectation": USER_PRE_REGISTERED_EXPECTATION,
    }

    # =========================================================
    # Test 1 — Perturbation sensitivity
    # =========================================================
    def rerank_by(score_fn):
        scored = [(u["ticker"], score_fn(u)) for u in rankable_with_features]
        scored.sort(key=lambda x: -x[1])
        return {t: i + 1 for i, (t, _) in enumerate(scored)}

    rank_baseline_sel = baseline_rank_selector  # current B6 selector_score order
    rank_reduced_inst = rerank_by(lambda u: 0.80 * u["coinvest_score_z"] + 0.20 * u["inst_delta_z"])
    rank_coinvest_only = rerank_by(lambda u: u["coinvest_score_z"])

    def perturb_report(rank_perturbed, label):
        common = set(rank_baseline_sel) & set(rank_perturbed)
        sp = spearman(rank_baseline_sel, rank_perturbed)
        overlaps = {}
        for k in (10, 20, 30, 60):
            base_topk = set(t for t, r in rank_baseline_sel.items() if r <= k)
            pert_topk = set(t for t, r in rank_perturbed.items() if r <= k)
            overlaps[f"top{k}_overlap"] = len(base_topk & pert_topk)
        # Top-30 entrants/exits
        base_top30 = set(t for t, r in rank_baseline_sel.items() if r <= 30)
        pert_top30 = set(t for t, r in rank_perturbed.items() if r <= 30)
        entrants = sorted(pert_top30 - base_top30)
        exits = sorted(base_top30 - pert_top30)
        # Rank moves
        moves = []
        for t in common:
            d = rank_perturbed[t] - rank_baseline_sel[t]
            moves.append((t, d))
        moves_ge_10 = sum(1 for _, d in moves if abs(d) >= 10)
        moves_ge_20 = sum(1 for _, d in moves if abs(d) >= 20)
        return {
            "label": label,
            "spearman_rho": round(sp, 4) if sp is not None else None,
            **overlaps,
            "top30_entrants": entrants,
            "top30_exits": exits,
            "n_moves_ge_10": moves_ge_10,
            "n_moves_ge_20": moves_ge_20,
        }

    test1 = {
        "method": "Compare baseline (B6: 0.65×coinvest + 0.35×inst_delta) against (B) reduced-inst 0.80/0.20 and (C) coinvest-only.",
        "B_reduced_inst_0.80_0.20": perturb_report(rank_reduced_inst, "B: 0.80×coinvest + 0.20×inst_delta"),
        "C_coinvest_only": perturb_report(rank_coinvest_only, "C: coinvest_score_z only"),
    }
    # Verdict
    b30 = test1["B_reduced_inst_0.80_0.20"]["top30_overlap"]
    moves20_b = test1["B_reduced_inst_0.80_0.20"]["n_moves_ge_20"]
    if b30 >= 25:
        test1["verdict"] = "robust (top-30 overlap ≥25/30 under reduced-inst)"
    elif b30 < 22 or moves20_b >= 5:
        test1["verdict"] = "fragile (top-30 overlap <22/30 OR ≥5 names move ≥20 slots)"
    else:
        test1["verdict"] = "borderline"
    results["test1_perturbation"] = test1

    # =========================================================
    # Test 2 — Cutoff score-quality curve
    # =========================================================
    cutoffs = [10, 20, 30, 40, 50, 60]
    rows_by_actionable = by_actionable  # sorted ascending by actionable_rank
    cutoff_stats = {}
    for c in cutoffs:
        bucket = [u for u in rows_by_actionable[:c] if u["selector_score"] is not None]
        scores = [u["selector_score"] for u in bucket]
        if scores:
            cutoff_stats[f"top{c}"] = {
                "median": round(statistics.median(scores), 4),
                "mean": round(statistics.mean(scores), 4),
                "min": round(min(scores), 4),
                "n": len(scores),
            }
    # Score gaps from prior cutoff (top-N min vs top-(N+10) min)
    gap_min = {}
    sorted_cutoffs = sorted(cutoffs)
    for i, c in enumerate(sorted_cutoffs):
        if i == 0:
            continue
        prev = sorted_cutoffs[i - 1]
        if cutoff_stats.get(f"top{prev}") and cutoff_stats.get(f"top{c}"):
            gap_min[f"min_top{prev}_minus_min_top{c}"] = round(
                cutoff_stats[f"top{prev}"]["min"] - cutoff_stats[f"top{c}"]["min"], 4
            )
    # Incremental bucket medians
    bucket_medians = {}
    for i, c in enumerate(sorted_cutoffs):
        prev = 0 if i == 0 else sorted_cutoffs[i - 1]
        bucket = [u for u in rows_by_actionable[prev:c] if u["selector_score"] is not None]
        if bucket:
            scores = [u["selector_score"] for u in bucket]
            label = f"ranks_{prev+1}_{c}"
            bucket_medians[label] = round(statistics.median(scores), 4)
    # Bucket median drops
    medians_in_order = list(bucket_medians.items())
    drops = []
    for i in range(1, len(medians_in_order)):
        a_label, a = medians_in_order[i - 1]
        b_label, b = medians_in_order[i]
        drops.append((b_label, round(a - b, 4)))
    median_drop = statistics.median([d for _, d in drops]) if drops else 0.0
    largest_drop = max(drops, key=lambda x: x[1]) if drops else (None, 0.0)
    cliff_threshold = 2 * median_drop if median_drop > 0 else None
    cliff = cliff_threshold is not None and largest_drop[1] > cliff_threshold
    test2 = {
        "method": "Locked proxy = selector_score. Per-cutoff stats + incremental bucket medians + drop curve.",
        "cutoff_stats": cutoff_stats,
        "min_score_gaps_between_cutoffs": gap_min,
        "incremental_bucket_medians": bucket_medians,
        "bucket_median_drops": drops,
        "median_bucket_drop": round(median_drop, 4),
        "largest_drop_bucket": largest_drop[0],
        "largest_drop_value": largest_drop[1],
        "cliff_detected": cliff,
        "verdict": (
            "fragile (cliff: largest bucket drop >2× median bucket drop at " f"{largest_drop[0]})"
            if cliff
            else "robust (smooth monotonic decay)"
        ),
    }
    results["test2_cutoff_curve"] = test2

    # =========================================================
    # Test 3 — Feature dominance
    # =========================================================
    top30 = [u for u in by_actionable[:30] if u["coinvest_score_z"] is not None and u["inst_delta_z"] is not None]
    decomp = []
    for u in top30:
        ci = 0.65 * u["coinvest_score_z"]
        ii = 0.35 * u["inst_delta_z"]
        denom = abs(ci) + abs(ii)
        share = abs(ii) / denom if denom > 0 else None
        if share is None:
            dom = "undefined"
        elif share > 0.60:
            dom = "inst_dominated"
        elif share < 0.40:
            dom = "coinvest_dominated"
        else:
            dom = "mixed"
        decomp.append(
            {
                "rank": int(u["actionable_rank"]),
                "ticker": u["ticker"],
                "coinvest_component": round(ci, 4),
                "inst_component": round(ii, 4),
                "inst_share_abs": round(share, 4) if share is not None else None,
                "dominant_feature": dom,
                "is_known_artifact": u["ticker"] in KNOWN_ARTIFACT_TICKERS,
            }
        )
    counts = {"inst_dominated": 0, "coinvest_dominated": 0, "mixed": 0, "undefined": 0}
    for d in decomp:
        counts[d["dominant_feature"]] += 1
    n_top30 = len(decomp)
    inst_dom_artifacts = [d for d in decomp if d["dominant_feature"] == "inst_dominated" and d["is_known_artifact"]]
    test3 = {
        "method": "Per top-30 ticker: coinvest_component=0.65×coinvest_z; inst_component=0.35×inst_delta_z; inst_share=|inst|/(|inst|+|coinvest|).",
        "counts": counts,
        "decomposition": decomp,
        "inst_dominated_artifact_overlap": [d["ticker"] for d in inst_dom_artifacts],
        "verdict": (
            f"fragile ({counts['inst_dominated']}/{n_top30} inst-dominated, ≥{n_top30//3} threshold; "
            f"{len(inst_dom_artifacts)} of those are known artifacts)"
            if counts["inst_dominated"] >= n_top30 // 3
            else "robust (majority mixed or coinvest-dominated)"
        ),
    }
    results["test3_feature_dominance"] = test3

    # =========================================================
    # Test 4 — Marginal cutoff sensitivity
    # =========================================================
    rank_to_score = {int(u["actionable_rank"]): u for u in rows_by_actionable if u["selector_score"] is not None}
    windows = {"25_35": range(25, 36), "35_45": range(35, 46), "55_65": range(55, 66)}
    window_data = {}
    for label, rng in windows.items():
        rows_in = [
            (r, rank_to_score[r]["ticker"], rank_to_score[r]["selector_score"]) for r in rng if r in rank_to_score
        ]
        gaps = []
        for i in range(1, len(rows_in)):
            gaps.append(round(rows_in[i - 1][2] - rows_in[i][2], 4))
        window_data[label] = {
            "rows": [(r, t, round(s, 4)) for r, t, s in rows_in],
            "adjacent_gaps": gaps,
            "cumulative_gap": round(rows_in[0][2] - rows_in[-1][2], 4) if rows_in else None,
        }
    cutoff_score_top30 = rank_to_score.get(30, {}).get("selector_score")
    near_cutoff_005 = sum(
        1
        for u in rows_by_actionable
        if u["selector_score"] is not None
        and cutoff_score_top30 is not None
        and abs(u["selector_score"] - cutoff_score_top30) <= 0.05
    )
    near_cutoff_010 = sum(
        1
        for u in rows_by_actionable
        if u["selector_score"] is not None
        and cutoff_score_top30 is not None
        and abs(u["selector_score"] - cutoff_score_top30) <= 0.10
    )
    test4 = {
        "method": "Score gaps at boundary windows (25-35, 35-45, 55-65) + count of names within 0.05/0.10 of top-30 cutoff selector_score.",
        "top30_cutoff_selector_score": round(cutoff_score_top30, 4) if cutoff_score_top30 is not None else None,
        "names_within_0.05_of_cutoff": near_cutoff_005,
        "names_within_0.10_of_cutoff": near_cutoff_010,
        "windows": window_data,
        "verdict": (
            f"fragile ({near_cutoff_010} names within 0.10 of cutoff)"
            if near_cutoff_010 >= 15
            else (
                f"borderline ({near_cutoff_010} names within 0.10 of cutoff)"
                if near_cutoff_010 >= 8
                else f"robust (clear separation, only {near_cutoff_010} within 0.10)"
            )
        ),
    }
    results["test4_marginal_cutoff_sensitivity"] = test4

    # =========================================================
    # Test 5 — Cheap bootstrap
    # =========================================================
    rng = random.Random(20260428)
    pool = [u for u in rankable_with_features]
    pool_size = len(pool)
    drop_n = max(1, pool_size // 20)  # 5%
    overlaps = []
    inclusion_counts = {t: 0 for t in baseline_top30}
    n_trials = 1000
    # Baseline top-30 by selector_score (apples-to-apples since bootstrap reuses selector_score)
    baseline_top30_selector = set(t for t, r in baseline_rank_selector.items() if r <= 30)
    inclusion_counts = {t: 0 for t in baseline_top30_selector}
    for _ in range(n_trials):
        keep = rng.sample(pool, pool_size - drop_n)
        keep_sorted = sorted(keep, key=lambda u: -u["selector_score"])
        boot_top30 = set(u["ticker"] for u in keep_sorted[:30])
        overlap = len(boot_top30 & baseline_top30_selector)
        overlaps.append(overlap)
        for t in boot_top30:
            if t in inclusion_counts:
                inclusion_counts[t] += 1
    overlaps_sorted = sorted(overlaps)
    inclusion_freq = {t: round(c / n_trials, 4) for t, c in inclusion_counts.items()}
    unstable_names = [t for t, fr in inclusion_freq.items() if fr < 0.80]
    median_overlap = statistics.median(overlaps)
    p10 = overlaps_sorted[int(0.10 * n_trials)]
    p90 = overlaps_sorted[int(0.90 * n_trials)]
    test5 = {
        "method": f"{n_trials} trials × random 5% universe drop ({drop_n}/{pool_size}); rerank remaining by existing selector_score; overlap with baseline top-30 (selector-score sort).",
        "n_trials": n_trials,
        "drop_n": drop_n,
        "mean_top30_overlap": round(statistics.mean(overlaps), 4),
        "median_top30_overlap": median_overlap,
        "p10_top30_overlap": p10,
        "p90_top30_overlap": p90,
        "inclusion_frequency_per_baseline_top30": inclusion_freq,
        "unstable_names_below_80pct_inclusion": sorted(unstable_names),
        "verdict": (
            f"robust (median overlap {median_overlap}/30, {len(unstable_names)} names <80% inclusion)"
            if median_overlap >= 28 and len(unstable_names) <= 3
            else f"fragile (median overlap {median_overlap}/30, {len(unstable_names)} names <80% inclusion)"
        ),
    }
    results["test5_bootstrap"] = test5

    # =========================================================
    # Test 6 — Cross-signal agreement
    # =========================================================
    # Build percentile maps for available independent signals
    signal_arrays = {}
    for col in INDEPENDENT_SIGNAL_COLS:
        vals = [u[col] for u in rankable if u.get(col) is not None]
        if len(vals) >= 50:  # arbitrary minimum
            signal_arrays[col] = sorted(vals)
    available_signals = list(signal_arrays.keys())

    def percentile_of(col, x):
        arr = signal_arrays.get(col)
        if arr is None or x is None:
            return None
        below = sum(1 for v in arr if v < x)
        return below / len(arr)

    top30_records = [u for u in by_actionable[:30]]
    top30_agreement = []
    for u in top30_records:
        per_signal = {}
        top_quintile_count = 0
        n_avail = 0
        for col in available_signals:
            v = u.get(col)
            if v is None:
                continue
            n_avail += 1
            pct = percentile_of(col, v)
            per_signal[col] = round(pct, 3) if pct is not None else None
            if pct is not None and pct >= 0.80:
                top_quintile_count += 1
        agreement_score = top_quintile_count / n_avail if n_avail > 0 else None
        top30_agreement.append(
            {
                "rank": int(u["actionable_rank"]) if u["actionable_rank"] else None,
                "ticker": u["ticker"],
                "is_known_artifact": u["ticker"] in KNOWN_ARTIFACT_TICKERS,
                "n_available_signals": n_avail,
                "n_top_quintile_signals": top_quintile_count,
                "agreement_score": round(agreement_score, 4) if agreement_score is not None else None,
                "per_signal_percentiles": per_signal,
            }
        )

    def mean_agreement(records):
        scores = [r["agreement_score"] for r in records if r["agreement_score"] is not None]
        return round(statistics.mean(scores), 4) if scores else None

    artifact_low_agree = [
        r["ticker"] for r in top30_agreement if r["is_known_artifact"] and (r["agreement_score"] or 0) < 0.50
    ]
    test6 = {
        "method": "For each top-30 ticker, compute percentile rank within universe across available independent signals (excludes B6 components, institutional block). agreement_score = top-quintile signals / available signals.",
        "available_independent_signals": available_signals,
        "n_available_signals": len(available_signals),
        "mean_agreement_top10": mean_agreement(top30_agreement[:10]),
        "mean_agreement_top20": mean_agreement(top30_agreement[:20]),
        "mean_agreement_top30": mean_agreement(top30_agreement),
        "tickers_agreement_ge_50pct": sorted(
            [r["ticker"] for r in top30_agreement if (r["agreement_score"] or 0) >= 0.50]
        ),
        "tickers_agreement_zero": sorted([r["ticker"] for r in top30_agreement if r["agreement_score"] == 0]),
        "artifact_entrants_with_low_agreement": sorted(artifact_low_agree),
        "per_ticker": top30_agreement,
        "verdict": (
            "robust (top names supported by multiple independent signals)"
            if (mean_agreement(top30_agreement) or 0) >= 0.30
            else "fragile (leaders depend mostly on DEM/institutional layer; weak cross-signal corroboration)"
        ),
    }
    results["test6_cross_signal_agreement"] = test6

    # =========================================================
    # Test 7 — Artifact isolation extension
    # =========================================================
    if ATTR_FILE.exists():
        with open(ATTR_FILE) as fh:
            attr = json.load(fh)
        swap = attr.get("top30_swap_summary", {})
        stable_set = set(swap.get("stable", []))
        artifact_entrants = set(swap.get("artifact_entrants", []))
        artifact_exits = set(swap.get("artifact_exits", []))
    else:
        stable_set = artifact_entrants = artifact_exits = set()

    # Per top-30 classification
    classified = []
    delta_thr = 0.30  # |Δinst_delta_z| threshold for "high cohort move"
    for u in by_actionable[:30]:
        t = u["ticker"]
        delta = None
        # Pull Δinst_delta_z from attribution if present
        if ATTR_FILE.exists():
            for entry in attr.get("top30_today_with_attribution", []):
                if entry.get("ticker") == t:
                    delta = entry.get("inst_delta_z_delta")
                    break
        agreement = next((r["agreement_score"] for r in top30_agreement if r["ticker"] == t), None)
        # Classification
        if t in stable_set and (delta is not None and delta < 0):
            cls = "D_underweighted"
        elif t in stable_set and (delta is not None and abs(delta) >= delta_thr):
            cls = "B_durable_but_cohort_moved"
        elif t in stable_set:
            cls = "A_clean_durable"
        elif t in artifact_entrants:
            cls = "C_artifact_driven"
        else:
            cls = "unclassified"
        classified.append(
            {
                "rank": int(u["actionable_rank"]) if u["actionable_rank"] else None,
                "ticker": t,
                "is_known_artifact": t in KNOWN_ARTIFACT_TICKERS,
                "inst_delta_z_delta": round(delta, 4) if delta is not None else None,
                "cross_signal_agreement_score": agreement,
                "classification": cls,
            }
        )
    cls_counts = {}
    for c in classified:
        cls_counts[c["classification"]] = cls_counts.get(c["classification"], 0) + 1
    test7 = {
        "method": "Cross attribution counterfactual top-30 with cross-signal agreement + Δinst_delta_z magnitude. Classify each top-30 ticker as A/B/C/D.",
        "classification_counts": cls_counts,
        "stable_in_counterfactual": sorted(list(stable_set)),
        "artifact_entrants": sorted(list(artifact_entrants)),
        "artifact_exits": sorted(list(artifact_exits)),
        "high_confidence_artifact_tickers": sorted(list(KNOWN_ARTIFACT_TICKERS)),
        "per_ticker_classification": classified,
    }
    results["test7_artifact_isolation_extension"] = test7

    # =========================================================
    # Final verdict
    # =========================================================
    verdicts = {
        "test1": test1["verdict"],
        "test2": test2["verdict"],
        "test3": test3["verdict"],
        "test4": test4["verdict"],
        "test5": test5["verdict"],
        "test6": test6["verdict"],
    }
    fragile_n = sum(1 for v in verdicts.values() if v.startswith("fragile"))
    robust_n = sum(1 for v in verdicts.values() if v.startswith("robust"))
    border_n = sum(1 for v in verdicts.values() if v.startswith("borderline"))
    if fragile_n >= 4:
        grade = "fragile"
    elif fragile_n >= 2 or border_n >= 2:
        grade = "mixed"
    else:
        grade = "robust"
    # Defensible cutoff: largest k where the bucket from prev-cutoff to k has lowest
    # fragility signal (bucket median drop within 1× median drop)
    drops_dict = dict(drops) if drops else {}
    defensible_cutoff = None
    for c in cutoffs:
        bucket_label = None
        for label in drops_dict:
            if label.endswith(f"_{c}"):
                bucket_label = label
                break
        if bucket_label is None:
            continue
        if drops_dict[bucket_label] <= median_drop * 1.5:
            defensible_cutoff = c
    if defensible_cutoff is None:
        defensible_cutoff = 60  # default: widest cutoff = noisiest but most diversified
    contaminated_names = sorted(
        list(
            KNOWN_ARTIFACT_TICKERS & set(c["ticker"] for c in classified if c["classification"] == "C_artifact_driven")
        )
    )
    durable_despite_shock = sorted(
        [c["ticker"] for c in classified if c["classification"] == "B_durable_but_cohort_moved"]
    )
    final_verdict = {
        "dem_robustness_grade": grade,
        "structurally_defensible_cutoff_today": f"top-{defensible_cutoff}",
        "contaminated_names_to_treat_with_caution": contaminated_names,
        "durable_despite_cohort_shock": durable_despite_shock,
        "production_action_recommended": ("none — observe until h20d (2026-05-26) and post-13F refresh (~2026-05-15)"),
        "test_grade_distribution": {"robust": robust_n, "borderline": border_n, "fragile": fragile_n},
    }
    results["final_verdict"] = final_verdict

    # -- Persist JSON --
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as fh:
        json.dump(results, fh, indent=2, default=str)

    # -- Write Markdown --
    lines = []
    lines.append("# DEM Robustness Battery — 2026-04-28\n")
    lines.append(
        "Read-only diagnostic. No production state modified. Methodology fixed in `tools/inst_delta_robustness_battery.py` before measurement.\n"
    )
    lines.append(f"**Universe rankable**: {n_universe} tickers.\n")
    lines.append("## User pre-registered expectation\n")
    lines.append("```")
    lines.append(USER_PRE_REGISTERED_EXPECTATION)
    lines.append("```\n")
    lines.append("---\n")
    lines.append("## Final Verdict\n")
    lines.append(f"**DEM robustness grade**: `{grade}`\n")
    lines.append(f"**Test distribution**: robust={robust_n}, borderline={border_n}, fragile={fragile_n}\n")
    lines.append(f"**Structurally defensible cutoff today**: `top-{defensible_cutoff}`\n")
    lines.append(
        f"**Contaminated names (high-confidence artifact + counterfactual exits)**: {contaminated_names or '(none)'}\n"
    )
    lines.append(f"**Durable despite cohort shock**: {durable_despite_shock or '(none)'}\n")
    lines.append(
        "**Production action recommended**: none — observe until h20d (2026-05-26) and post-13F refresh (~2026-05-15).\n"
    )
    lines.append("---\n")
    lines.append("## Test 1 — Perturbation sensitivity\n")
    lines.append(f"**Verdict**: `{test1['verdict']}`\n")
    for k in ("B_reduced_inst_0.80_0.20", "C_coinvest_only"):
        d = test1[k]
        lines.append(f"### {d['label']}")
        lines.append(f"- Spearman ρ vs baseline selector_score: **{d['spearman_rho']}**")
        lines.append(
            f"- Top-30 overlap: **{d['top30_overlap']}/30**  |  Top-10: {d['top10_overlap']}/10  |  Top-20: {d['top20_overlap']}/20  |  Top-60: {d['top60_overlap']}/60"
        )
        lines.append(f"- Names with rank moves ≥10 slots: {d['n_moves_ge_10']}  |  ≥20 slots: {d['n_moves_ge_20']}")
        lines.append(f"- Top-30 entrants ({len(d['top30_entrants'])}): {', '.join(d['top30_entrants']) or '(none)'}")
        lines.append(f"- Top-30 exits ({len(d['top30_exits'])}): {', '.join(d['top30_exits']) or '(none)'}\n")
    lines.append("---\n")
    lines.append("## Test 2 — Cutoff score-quality curve\n")
    lines.append(f"**Verdict**: `{test2['verdict']}`\n")
    lines.append("### Per-cutoff stats")
    lines.append("| Cutoff | n | median | mean | min |")
    lines.append("|---|---:|---:|---:|---:|")
    for c in cutoffs:
        s = cutoff_stats.get(f"top{c}")
        if s:
            lines.append(f"| top-{c} | {s['n']} | {s['median']} | {s['mean']} | {s['min']} |")
    lines.append("\n### Incremental bucket medians + drops")
    lines.append("| Bucket | Median | Drop from prior |")
    lines.append("|---|---:|---:|")
    drop_lookup = dict(drops)
    for label, med in bucket_medians.items():
        d = drop_lookup.get(label, "—")
        lines.append(f"| {label} | {med} | {d} |")
    lines.append(
        f"\n- Median bucket drop: {round(median_drop, 4)}; cliff threshold (2×): {round(2 * median_drop, 4) if median_drop > 0 else '—'}"
    )
    lines.append(f"- Largest drop: bucket={largest_drop[0]}, value={largest_drop[1]}")
    lines.append(f"- Cliff detected: {cliff}\n")
    lines.append("---\n")
    lines.append("## Test 3 — Feature dominance\n")
    lines.append(f"**Verdict**: `{test3['verdict']}`\n")
    lines.append(
        f"- Counts among top-30: inst-dominated={counts['inst_dominated']}, coinvest-dominated={counts['coinvest_dominated']}, mixed={counts['mixed']}, undefined={counts['undefined']}"
    )
    lines.append(f"- Inst-dominated AND known artifact: {[d['ticker'] for d in inst_dom_artifacts]}\n")
    lines.append("### Top-30 decomposition (sorted by inst_share_abs desc)")
    lines.append("| Rank | Ticker | coinvest×0.65 | inst×0.35 | inst_share | dominant | artifact? |")
    lines.append("|---:|---|---:|---:|---:|---|---|")
    for d in sorted(decomp, key=lambda x: -(x["inst_share_abs"] or 0)):
        lines.append(
            f"| {d['rank']} | {d['ticker']} | {d['coinvest_component']} | {d['inst_component']} | {d['inst_share_abs']} | {d['dominant_feature']} | {'★' if d['is_known_artifact'] else ''} |"
        )
    lines.append("\n---\n")
    lines.append("## Test 4 — Marginal cutoff sensitivity\n")
    lines.append(f"**Verdict**: `{test4['verdict']}`\n")
    lines.append(f"- top-30 cutoff selector_score: **{test4['top30_cutoff_selector_score']}**")
    lines.append(f"- Names within 0.05 of cutoff: **{near_cutoff_005}**")
    lines.append(f"- Names within 0.10 of cutoff: **{near_cutoff_010}**\n")
    for label, w in window_data.items():
        lines.append(f"### Window {label} (selector_score)")
        lines.append(f"- cumulative gap: {w['cumulative_gap']}")
        lines.append(f"- adjacent gaps: {w['adjacent_gaps']}")
    lines.append("\n---\n")
    lines.append("## Test 5 — Cheap bootstrap (drop-5%, n=1000)\n")
    lines.append(f"**Verdict**: `{test5['verdict']}`\n")
    lines.append(f"- mean overlap: {test5['mean_top30_overlap']}/30")
    lines.append(f"- median overlap: {test5['median_top30_overlap']}/30")
    lines.append(f"- p10 / p90 overlap: {test5['p10_top30_overlap']} / {test5['p90_top30_overlap']}")
    lines.append(
        f"- Unstable names (<80% inclusion) ({len(unstable_names)}): {', '.join(sorted(unstable_names)) or '(none)'}\n"
    )
    lines.append("---\n")
    lines.append("## Test 6 — Cross-signal agreement\n")
    lines.append(f"**Verdict**: `{test6['verdict']}`\n")
    lines.append(f"- Independent signals available: {available_signals}")
    lines.append(
        f"- Mean agreement_score: top-10={test6['mean_agreement_top10']}, top-20={test6['mean_agreement_top20']}, top-30={test6['mean_agreement_top30']}"
    )
    lines.append(f"- Tickers with agreement ≥0.50: {test6['tickers_agreement_ge_50pct']}")
    lines.append(f"- Tickers with agreement = 0: {test6['tickers_agreement_zero']}")
    lines.append(
        f"- **Known artifact entrants with low agreement (<0.50)**: {test6['artifact_entrants_with_low_agreement']}\n"
    )
    lines.append("---\n")
    lines.append("## Test 7 — Artifact isolation extension\n")
    lines.append(f"- Classification counts: {test7['classification_counts']}\n")
    lines.append("| Rank | Ticker | Δinst_z | Agreement | Classification | Artifact? |")
    lines.append("|---:|---|---:|---:|---|---|")
    for c in classified:
        lines.append(
            f"| {c['rank']} | {c['ticker']} | {c['inst_delta_z_delta']} | "
            f"{c['cross_signal_agreement_score']} | {c['classification']} | "
            f"{'★' if c['is_known_artifact'] else ''} |"
        )
    lines.append("\n---\n")
    lines.append("## Methodology constraints\n")
    lines.append("- All scores read from `data/snapshots/2026-04-28/rankings.csv`. No model rerun.")
    lines.append("- No production data mutated. All artifacts in `artifacts/audit/`.")
    lines.append(
        "- Companion: `inst_delta_attribution_2026-04-28.{md,json}`, `inst_delta_forward_shadow/T0_2026-04-28_lock.json`."
    )

    with open(OUT_MD, "w") as fh:
        fh.write("\n".join(lines))

    print(f"wrote {OUT_MD}")
    print(f"wrote {OUT_JSON}")
    print()
    print(f"DEM robustness grade: {grade}")
    print(f"Test distribution: robust={robust_n}, borderline={border_n}, fragile={fragile_n}")
    print(f"Defensible cutoff: top-{defensible_cutoff}")
    print(f"Contaminated names: {contaminated_names}")
    print(f"Durable despite shock: {durable_despite_shock}")
    return 0


if __name__ == "__main__":
    main()
