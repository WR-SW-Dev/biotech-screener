#!/usr/bin/env python3
"""Spec 050 — Ranker composition audit.

Tests within-top-30 ordering quality for different ranker weight mixes,
all applied on top of the A4 selector.

Three ranker variants + a baseline (no ranker):
  R0: A4 selector only (no ranker)
  R1: Clinical/catalyst-heavy ranker (the DEFAULT IC source)
  R2: Survivability/catalyst/clinical ranker (balanced fundamentals)
  R3: Light options overlay (options at 10%, not 35%)

Metrics per variant:
  - Within-top-30 Spearman IC (63d)
  - RW-EW net spread
  - Selection delta vs DEM baseline
  - Regime splits
  - Turnover

Usage:
    python3 scripts/research/eval_ranker_composition.py
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
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_engine import RankerConfig, RankerSignalSpec, compute_ranker_adjustments
from selector_engine import BlockWeight, SelectorConfig, SignalSpec, compute_selector_scores

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "signals"
TOP_N = 30

# ── A4 selector (fixed for all variants) ─────────────────────────────

A4_CONFIG = SelectorConfig(
    block_weights=(
        BlockWeight("clinical", 0.05),
        BlockWeight("catalyst", 0.10),
        BlockWeight("survivability", 0.10),
        BlockWeight("institutional", 0.65),
        BlockWeight("market_structure", 0.10),
    ),
    institutional_signals=(
        SignalSpec("coinvest_score_z", 0.65),
        SignalSpec("inst_delta_z", 0.35),
        SignalSpec(
            "coinvest_recency_state", 0.00, categorical=True, value_map=(("fresh", 1.0), ("stale", 0.3), ("", 0.0))
        ),
    ),
)

# ── Ranker variants ──────────────────────────────────────────────────

# R1: Clinical/catalyst-heavy — maximize the signal source that showed IC
R1_CONFIG = RankerConfig(
    options_weight=0.05,
    institutional_weight=0.10,
    aact_weight=0.10,
    catalyst_nuance_weight=0.35,
    microstructure_weight=0.05,
    # Add clinical signals via the aact block (hijack it for clinical)
    aact_signals=(
        RankerSignalSpec("clinical_score_v2_z", 0.30),
        RankerSignalSpec("clinical_optionality_pct_dev", 0.25),
        RankerSignalSpec("endpoint_strength_score", 0.20),
        RankerSignalSpec("design_quality_score", 0.15),
        RankerSignalSpec("execution_momentum", 0.10),
    ),
    # Override catalyst_nuance to include survivability signals
    catalyst_nuance_signals=(
        RankerSignalSpec(
            "catalyst_family",
            0.20,
            categorical=True,
            value_map=(("REGULATORY", 1.0), ("CLINICAL", 0.6), ("SAFETY", 0.3), ("", 0.0)),
        ),
        RankerSignalSpec("cat_priority", 0.15, higher_is_better=False),
        RankerSignalSpec("binary_quality_score", 0.25),
        RankerSignalSpec("financial_score", 0.20),
        RankerSignalSpec(
            "severity",
            0.20,
            higher_is_better=False,
            categorical=True,
            value_map=(("NONE", 0.0), ("", 0.0), ("SEV1", 0.33), ("SEV2", 0.67), ("SEV3", 1.0)),
        ),
    ),
    activation_require_options=False,  # Don't gate on options — this is fundamentals-only
)

# R2: Balanced fundamentals — clinical + catalyst + survivability, no options
R2_CONFIG = RankerConfig(
    options_weight=0.00,
    institutional_weight=0.15,
    aact_weight=0.30,  # repurposed for clinical
    catalyst_nuance_weight=0.30,
    microstructure_weight=0.25,  # repurposed for survivability
    aact_signals=(
        RankerSignalSpec("clinical_score_v2_z", 0.30),
        RankerSignalSpec("clinical_optionality_pct_dev", 0.30),
        RankerSignalSpec("endpoint_strength_score", 0.20),
        RankerSignalSpec("readout_density_90", 0.20),
    ),
    catalyst_nuance_signals=(
        RankerSignalSpec(
            "catalyst_family",
            0.25,
            categorical=True,
            value_map=(("REGULATORY", 1.0), ("CLINICAL", 0.6), ("SAFETY", 0.3), ("", 0.0)),
        ),
        RankerSignalSpec("cat_priority", 0.25, higher_is_better=False),
        RankerSignalSpec("binary_quality_score", 0.30),
        RankerSignalSpec(
            "catalyst_type_tier",
            0.20,
            categorical=True,
            value_map=(("T1", 1.0), ("T2", 0.8), ("T3", 0.5), ("T4", 0.3), ("T5", 0.2), ("", 0.0)),
        ),
    ),
    microstructure_signals=(
        RankerSignalSpec("financial_score", 0.40),
        RankerSignalSpec(
            "severity",
            0.30,
            higher_is_better=False,
            categorical=True,
            value_map=(("NONE", 0.0), ("", 0.0), ("SEV1", 0.33), ("SEV2", 0.67), ("SEV3", 1.0)),
        ),
        RankerSignalSpec(
            "runway_bucket",
            0.30,
            categorical=True,
            value_map=(("adequate", 1.0), ("short", 0.4), ("critical", 0.0), ("", 0.5)),
        ),
    ),
    activation_require_options=False,
)

# R3: Light options overlay — options demoted to 10%, rest is fundamentals
R3_CONFIG = RankerConfig(
    options_weight=0.10,
    institutional_weight=0.15,
    aact_weight=0.25,  # repurposed for clinical
    catalyst_nuance_weight=0.25,
    microstructure_weight=0.25,  # repurposed for survivability
    aact_signals=(
        RankerSignalSpec("clinical_score_v2_z", 0.35),
        RankerSignalSpec("clinical_optionality_pct_dev", 0.30),
        RankerSignalSpec("endpoint_strength_score", 0.20),
        RankerSignalSpec("execution_momentum", 0.15),
    ),
    catalyst_nuance_signals=(
        RankerSignalSpec(
            "catalyst_family",
            0.25,
            categorical=True,
            value_map=(("REGULATORY", 1.0), ("CLINICAL", 0.6), ("SAFETY", 0.3), ("", 0.0)),
        ),
        RankerSignalSpec("cat_priority", 0.20, higher_is_better=False),
        RankerSignalSpec("binary_quality_score", 0.30),
        RankerSignalSpec("financial_score", 0.25),
    ),
    microstructure_signals=(
        RankerSignalSpec(
            "severity",
            0.35,
            higher_is_better=False,
            categorical=True,
            value_map=(("NONE", 0.0), ("", 0.0), ("SEV1", 0.33), ("SEV2", 0.67), ("SEV3", 1.0)),
        ),
        RankerSignalSpec(
            "runway_bucket",
            0.35,
            categorical=True,
            value_map=(("adequate", 1.0), ("short", 0.4), ("critical", 0.0), ("", 0.5)),
        ),
        RankerSignalSpec("total_volume_z", 0.30),
    ),
    # Keep options gate for the options block to matter
)

RANKER_VARIANTS = {
    "R0_no_ranker": None,
    "R1_clinical_catalyst_heavy": R1_CONFIG,
    "R2_balanced_fundamentals": R2_CONFIG,
    "R3_light_options": R3_CONFIG,
    "R_DEFAULT_original": None,  # sentinel — use default RankerConfig
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


def _safe_mean(vals):
    return statistics.mean(vals) if vals else None


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


def _rank(values):
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    for pos, idx in enumerate(indexed):
        ranks[idx] = pos + 1
    return ranks


def _spearman_ic(xs, ys):
    if len(xs) < 5:
        return None
    rx, ry = _rank(xs), _rank(ys)
    n = len(xs)
    d_sq = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - 6 * d_sq / (n * (n * n - 1))


# ── Panel loading ────────────────────────────────────────────────────


def load_panel():
    if not PANEL_CSV.exists():
        print(f"ERROR: {PANEL_CSV} not found")
        sys.exit(1)
    snaps = defaultdict(list)
    with open(PANEL_CSV) as f:
        for row in csv.DictReader(f):
            d = row.get("snapshot_date", "")
            if d:
                snaps[d].append(row)
    print(f"Loaded {len(snaps)} snapshots, {sum(len(v) for v in snaps.values())} rows")
    return dict(snaps)


# ── Core evaluation ──────────────────────────────────────────────────


def evaluate_variant(
    snapshots: Dict[str, List[Dict]],
    name: str,
    ranker_config,  # None = no ranker, "default" sentinel handled below
) -> Dict[str, Any]:
    """Evaluate a ranker variant on A4-selected top-30."""

    use_default_ranker = name == "R_DEFAULT_original"
    if use_default_ranker:
        from ranker_engine import DEFAULT_RANKER_CONFIG

        ranker_config = DEFAULT_RANKER_CONFIG

    ic_vals = []
    rw_ew_spread = []
    improvement = []
    baseline_excess = []
    turnover_vals = []
    prev_tickers = set()
    regime_data = defaultdict(list)  # regime -> [improvement_val]

    for snap_date in sorted(snapshots.keys()):
        rows = snapshots[snap_date]
        fwd_col = "fwd_excess_xbi_63d"

        eligible = []
        elig_rows = []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            fwd = _sf(r.get(fwd_col), default=None)
            rank_val = _sf(r.get("actionable_rank"), default=None)
            t = r.get("ticker", "")
            if fwd is not None and rank_val is not None:
                eligible.append({"ticker": t, "rank": rank_val, "fwd_xbi": fwd, "row": r})
                elig_rows.append(r)

        if len(eligible) < TOP_N:
            continue

        # Baseline
        by_rank = sorted(eligible, key=lambda x: x["rank"])
        bl_ret = statistics.mean(e["fwd_xbi"] for e in by_rank[:TOP_N])
        baseline_excess.append(bl_ret)

        # Selector (A4)
        sel_results = compute_selector_scores(elig_rows, config=A4_CONFIG)

        if ranker_config is not None:
            sel_scores = [sr.selector_score for sr in sel_results]
            sel_buckets = [sr.selector_rank_bucket for sr in sel_results]
            rnk_results = compute_ranker_adjustments(elig_rows, sel_scores, sel_buckets, config=ranker_config)
            for e, rr in zip(eligible, rnk_results):
                e["final_score"] = rr.final_score
        else:
            for e, sr in zip(eligible, sel_results):
                e["final_score"] = sr.selector_score

        by_final = sorted(eligible, key=lambda x: -x["final_score"])
        topk = by_final[:TOP_N]

        # EW return
        ew_ret = statistics.mean(e["fwd_xbi"] for e in topk)
        improvement.append(ew_ret - bl_ret)

        # RW return
        scores = [e["final_score"] for e in topk]
        s_sum = sum(scores)
        if s_sum > 1e-9:
            rw_ret = sum(e["fwd_xbi"] * (e["final_score"] / s_sum) for e in topk)
        else:
            rw_ret = ew_ret
        rw_ew_spread.append(rw_ret - ew_ret)

        # Within-top-30 IC
        ic = _spearman_ic(scores, [e["fwd_xbi"] for e in topk])
        if ic is not None:
            ic_vals.append(ic)

        # Turnover
        curr = {e["ticker"] for e in topk}
        if prev_tickers:
            turnover_vals.append(1.0 - len(curr & prev_tickers) / TOP_N)
        prev_tickers = curr

        # Regime
        regime = None
        for r in rows:
            regime = r.get("regime_63d")
            if regime:
                break
        if regime:
            regime_data[regime].append(ew_ret - bl_ret)

    # Summarize
    result = {
        "name": name,
        "n_periods": len(improvement),
        "selection_delta_pp": _r((_safe_mean(improvement) or 0) * 100),
        "selection_tstat": _r(_safe_tstat([v * 100 for v in improvement])),
        "selection_hit_pct": _r((_hit_rate(improvement) or 0) * 100),
        "within_top30_ic": _r(_safe_mean(ic_vals)),
        "ic_tstat": _r(_safe_tstat(ic_vals)),
        "ic_hit_pct": _r((_hit_rate(ic_vals) or 0) * 100),
        "rw_ew_spread_pp": _r((_safe_mean(rw_ew_spread) or 0) * 100),
        "mean_turnover": _r(_safe_mean(turnover_vals)),
        "regime": {},
    }
    for regime_label in ["bear", "neutral", "bull"]:
        vals = regime_data.get(regime_label, [])
        result["regime"][regime_label] = {
            "n": len(vals),
            "delta_pp": _r((_safe_mean(vals) or 0) * 100),
            "hit_pct": _r((_hit_rate(vals) or 0) * 100),
        }

    return result


# ── Main ─────────────────────────────────────────────────────────────


def main():
    snapshots = load_panel()
    results = []

    for name, cfg in RANKER_VARIANTS.items():
        print(f"\nEvaluating {name}...")
        r = evaluate_variant(snapshots, name, cfg)
        results.append(r)

    # Print results
    print("\n" + "=" * 120)
    print(
        f"{'Variant':35s} {'Δ(pp)':>7s} {'t':>6s} {'hit%':>5s} {'IC':>7s} {'IC_t':>6s} {'IC hit%':>7s} {'RW-EW':>7s} {'TO':>6s} {'Bear':>7s} {'Neut':>7s} {'Bull':>7s}"
    )
    print("-" * 120)
    for r in results:
        rg = r["regime"]
        print(
            f"{r['name']:35s} "
            f"{r['selection_delta_pp']:+7.2f} "
            f"{r['selection_tstat'] or 0:6.2f} "
            f"{r['selection_hit_pct'] or 0:4.0f}% "
            f"{r['within_top30_ic'] or 0:+7.4f} "
            f"{r['ic_tstat'] or 0:6.2f} "
            f"{r['ic_hit_pct'] or 0:6.0f}% "
            f"{r['rw_ew_spread_pp'] or 0:+7.2f} "
            f"{r['mean_turnover'] or 0:6.3f} "
            f"{rg.get('bear', {}).get('delta_pp', 0) or 0:+7.2f} "
            f"{rg.get('neutral', {}).get('delta_pp', 0) or 0:+7.2f} "
            f"{rg.get('bull', {}).get('delta_pp', 0) or 0:+7.2f}"
        )

    # Save
    out_json = OUTPUT_DIR / "ranker_composition_audit.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(
            {
                "schema": "ranker_composition_audit.v1",
                "generated": datetime.now(timezone.utc).isoformat(),
                "top_n": TOP_N,
                "selector": "A4",
                "results": results,
            },
            f,
            indent=2,
        )
    print(f"\nSaved: {out_json}")


if __name__ == "__main__":
    main()
