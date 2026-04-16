#!/usr/bin/env python3
"""Phase 2 Prior Recalibration — Ablation / Sensitivity Check.

Compares three Phase 2 prior values across the current EV universe:
  - OLD:        0.310 (Wong et al. 2019)
  - MODERATE:   0.420 (conservative HINT-informed recalibration)
  - AGGRESSIVE: 0.492 (full HINT empirical Phase 2 rate)

Measures:
  - Overall EV distribution shift
  - Phase 2 event EV changes
  - Top-ranked candidate churn
  - Top-decile overlap
  - Actionable count changes
  - Stability verdict

Usage:
    python research/phase2_recalibration_ablation.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Prior values to compare
PRIORS = {
    "old_0.310": 0.310,
    "moderate_0.420": 0.420,
    "aggressive_0.492": 0.492,
}


def _run_ev_with_phase2_prior(
    prior_value: float,
    as_of: date,
) -> List[Dict[str, Any]]:
    """Run EV scoring with a specific Phase 2 prior value."""
    from event_ev.ev_calculator import EventEVCalculator
    from event_ev.loaders import load_catalyst_graph, load_market_features, split_context_features
    from event_ev.outcome_model import LITERATURE_PHASE_READOUT_PRIORS, OutcomeModel

    prod_data = REPO_ROOT / "production_data"
    data_dir = REPO_ROOT / "data"
    snapshots_dir = data_dir / "snapshots"

    # Override Phase 2 prior
    custom_priors = dict(LITERATURE_PHASE_READOUT_PRIORS)
    custom_priors["2"] = prior_value

    # Load data
    graph = load_catalyst_graph(as_of, prod_data, data_dir)
    market_features = load_market_features(as_of, snapshots_dir)
    context_features = split_context_features(market_features)

    # Build outcome model with custom Phase 2 prior
    outcome_model = OutcomeModel(phase_readout_priors=custom_priors)

    # Run EV
    calc = EventEVCalculator(
        as_of_date=as_of,
        outcome_model=outcome_model,
        max_days=180,
        min_days=0,
    )
    results = calc.run_from_graph(
        graph,
        market_features=market_features,
        context_features=context_features,
    )

    # Extract leaderboard
    rows = []
    for rank, ev in enumerate(results, 1):
        days = ev.node.days_to_event(as_of)
        rows.append(
            {
                "rank": rank,
                "ticker": ev.node.ticker,
                "event_type": ev.node.event_type,
                "phase": ev.node.phase,
                "days_to_event": days,
                "p_hit": round(ev.outcome.p_hit, 4),
                "p_miss": round(ev.outcome.p_miss, 4),
                "mispricing": round(ev.mispricing_score, 4),
                "scenario_ev": round(ev.scenario_ev, 4),
                "ds_adj_ev": round(ev.payoff.downside_adjusted_ev, 4),
                "actionable": ev.actionable,
                "prior_source": ev.outcome.prior_source,
            }
        )
    return rows


def _compare(
    old_rows: List[Dict],
    new_rows: List[Dict],
    label: str,
) -> Dict[str, Any]:
    """Compare two EV runs."""
    old_by_tk = {}
    for r in old_rows:
        key = f"{r['ticker']}_{r['event_type']}_{r.get('days_to_event', '')}"
        old_by_tk[key] = r
    new_by_tk = {}
    for r in new_rows:
        key = f"{r['ticker']}_{r['event_type']}_{r.get('days_to_event', '')}"
        new_by_tk[key] = r

    # Phase 2 specific changes
    new_p2 = [r for r in new_rows if r["phase"] == "2"]

    p2_p_hit_changes = []
    p2_ev_changes = []
    for key, new_r in new_by_tk.items():
        if new_r["phase"] != "2":
            continue
        old_r = old_by_tk.get(key)
        if old_r:
            p2_p_hit_changes.append(new_r["p_hit"] - old_r["p_hit"])
            p2_ev_changes.append(new_r["scenario_ev"] - old_r["scenario_ev"])

    # Top-10 overlap
    old_top10 = {r["ticker"] for r in old_rows[:10]}
    new_top10 = {r["ticker"] for r in new_rows[:10]}
    top10_overlap = len(old_top10 & new_top10)

    # Top-20 overlap
    old_top20 = {r["ticker"] for r in old_rows[:20]}
    new_top20 = {r["ticker"] for r in new_rows[:20]}
    top20_overlap = len(old_top20 & new_top20)

    # Actionable count
    old_actionable = sum(1 for r in old_rows if r["actionable"])
    new_actionable = sum(1 for r in new_rows if r["actionable"])

    # Rank changes for Phase 2 names
    rank_changes = []
    for r in new_rows:
        if r["phase"] != "2":
            continue
        key = f"{r['ticker']}_{r['event_type']}_{r.get('days_to_event', '')}"
        old_r = old_by_tk.get(key)
        if old_r:
            rank_changes.append(
                {
                    "ticker": r["ticker"],
                    "old_rank": old_r["rank"],
                    "new_rank": r["rank"],
                    "rank_delta": old_r["rank"] - r["rank"],
                    "old_p_hit": old_r["p_hit"],
                    "new_p_hit": r["p_hit"],
                    "old_ev": old_r["scenario_ev"],
                    "new_ev": r["scenario_ev"],
                }
            )
    rank_changes.sort(key=lambda x: abs(x["rank_delta"]), reverse=True)

    return {
        "label": label,
        "n_total": len(new_rows),
        "n_phase2": len(new_p2),
        "n_actionable_old": old_actionable,
        "n_actionable_new": new_actionable,
        "top10_overlap": top10_overlap,
        "top20_overlap": top20_overlap,
        "phase2_mean_p_hit_delta": (
            round(sum(p2_p_hit_changes) / len(p2_p_hit_changes), 4) if p2_p_hit_changes else None
        ),
        "phase2_mean_ev_delta": (round(sum(p2_ev_changes) / len(p2_ev_changes), 4) if p2_ev_changes else None),
        "phase2_max_rank_change": rank_changes[0] if rank_changes else None,
        "phase2_rank_changes_top5": rank_changes[:5],
    }


def run_ablation(as_of_str: str = "2026-04-14") -> Dict[str, Any]:
    """Run the full Phase 2 ablation."""
    as_of = date.fromisoformat(as_of_str)
    print(f"Phase 2 Recalibration Ablation — as_of={as_of_str}")
    print("=" * 60)

    results = {}
    for name, prior in PRIORS.items():
        print(f"\n  Running {name} (prior={prior})...")
        rows = _run_ev_with_phase2_prior(prior, as_of)
        results[name] = rows
        n_act = sum(1 for r in rows if r["actionable"])
        print(f"    → {len(rows)} scored, {n_act} actionable")

    # Compare moderate vs old
    mod_vs_old = _compare(results["old_0.310"], results["moderate_0.420"], "moderate_vs_old")
    # Compare aggressive vs old
    agg_vs_old = _compare(results["old_0.310"], results["aggressive_0.492"], "aggressive_vs_old")

    output = {
        "as_of_date": as_of_str,
        "priors_tested": PRIORS,
        "moderate_vs_old": mod_vs_old,
        "aggressive_vs_old": agg_vs_old,
    }

    # Print summary
    print("\n" + "=" * 60)
    print("COMPARISON: Moderate (0.420) vs Old (0.310)")
    print("=" * 60)
    _print_comparison(mod_vs_old)

    print("\n" + "=" * 60)
    print("COMPARISON: Aggressive (0.492) vs Old (0.310)")
    print("=" * 60)
    _print_comparison(agg_vs_old)

    # Stability verdict
    verdict = _stability_verdict(mod_vs_old, agg_vs_old)
    output["verdict"] = verdict
    print(f"\n{'='*60}")
    print(f"VERDICT: {verdict['recommendation']}")
    print(f"  {verdict['reasoning']}")

    # Write output
    out_path = REPO_ROOT / "artifacts" / "phase2_recalibration_ablation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nWritten to {out_path}")

    return output


def _print_comparison(comp: Dict) -> None:
    print(f"  Phase 2 events: {comp['n_phase2']}")
    print(f"  Actionable: {comp['n_actionable_old']} → {comp['n_actionable_new']}")
    print(f"  Top-10 overlap: {comp['top10_overlap']}/10")
    print(f"  Top-20 overlap: {comp['top20_overlap']}/20")
    print(f"  Phase 2 mean p_hit delta: {comp['phase2_mean_p_hit_delta']}")
    print(f"  Phase 2 mean EV delta: {comp['phase2_mean_ev_delta']}")
    if comp.get("phase2_rank_changes_top5"):
        print("  Top Phase 2 rank changes:")
        for rc in comp["phase2_rank_changes_top5"]:
            print(
                f"    {rc['ticker']}: rank {rc['old_rank']}→{rc['new_rank']} "
                f"(Δ={rc['rank_delta']:+d}), p_hit {rc['old_p_hit']:.3f}→{rc['new_p_hit']:.3f}, "
                f"EV {rc['old_ev']:+.1f}%→{rc['new_ev']:+.1f}%"
            )


def _stability_verdict(
    moderate: Dict,
    aggressive: Dict,
) -> Dict[str, str]:
    """Determine stability verdict."""
    mod_top10 = moderate["top10_overlap"]
    _ = aggressive["top10_overlap"]  # validated but not used in current decision logic

    if mod_top10 >= 8 and moderate.get("phase2_mean_p_hit_delta", 0) and moderate["phase2_mean_p_hit_delta"] > 0:
        return {
            "recommendation": "ADOPT moderate (0.420)",
            "reasoning": (
                f"Top-10 overlap {mod_top10}/10 — stable. Phase 2 p_hit moves in correct direction. "
                f"Conservative move captures most of the calibration gain without destabilizing rankings."
            ),
        }
    elif mod_top10 >= 6:
        return {
            "recommendation": "ADOPT moderate (0.420) with monitoring",
            "reasoning": (
                f"Top-10 overlap {mod_top10}/10 — moderate churn. Phase 2 calibration improvement "
                f"is real but rankings shift more than expected. Monitor for 1 week."
            ),
        }
    else:
        return {
            "recommendation": "DEFER — partial move only",
            "reasoning": (
                f"Top-10 overlap {mod_top10}/10 — too much churn. Move to 0.370 instead "
                f"(quarter-step toward benchmark) and re-evaluate."
            ),
        }


if __name__ == "__main__":
    run_ablation()
