#!/usr/bin/env python3
"""Clinical Stack v2 — Integrated Ablation & Validation.

Compares old clinical stack vs new stack across all four layers:
  1. Phase 2 prior recalibration (0.310 → 0.420)
  2. protocol_quality_score (phase-conditional)
  3. biomarker_context_score (conditional)
  4. endpoint_quality_v2 (7-bucket, phase-aware)

Runs baseline, incremental, full, and leave-one-out variants.

Usage:
    python research/clinical_stack_v2_ablation.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

AS_OF = "2026-04-14"


def _load_data():
    """Load shared data once."""
    trials = json.loads((REPO_ROOT / "production_data" / "trial_records.json").read_text())
    return trials


def _run_ev_variant(
    trials: list,
    phase2_prior: float = 0.420,
    use_protocol: bool = True,
    use_biomarker: bool = True,
    use_endpoint_v2: bool = True,
    label: str = "",
) -> List[Dict[str, Any]]:
    """Run EV scoring with a specific stack configuration."""
    from event_ev.ev_calculator import EventEVCalculator
    from event_ev.loaders import load_catalyst_graph, load_market_features, split_context_features
    from event_ev.outcome_model import LITERATURE_PHASE_READOUT_PRIORS, OutcomeModel

    as_of = date.fromisoformat(AS_OF)
    prod_data = REPO_ROOT / "production_data"
    data_dir = REPO_ROOT / "data"
    snapshots_dir = data_dir / "snapshots"

    # Custom Phase 2 prior
    custom_priors = dict(LITERATURE_PHASE_READOUT_PRIORS)
    custom_priors["2"] = phase2_prior
    outcome_model = OutcomeModel(phase_readout_priors=custom_priors)

    graph = load_catalyst_graph(as_of, prod_data, data_dir)
    market_features = load_market_features(as_of, snapshots_dir)
    context_features = split_context_features(market_features)

    # Optionally compute and inject layer scores into context
    if use_protocol or use_biomarker or use_endpoint_v2:
        _enrich_context(
            context_features,
            trials,
            AS_OF,
            use_protocol=use_protocol,
            use_biomarker=use_biomarker,
            use_endpoint_v2=use_endpoint_v2,
        )

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

    rows = []
    for rank, ev in enumerate(results, 1):
        days = ev.node.days_to_event(as_of)
        rows.append(
            {
                "rank": rank,
                "ticker": ev.node.ticker,
                "phase": ev.node.phase,
                "p_hit": round(ev.outcome.p_hit, 4),
                "scenario_ev": round(ev.scenario_ev, 4),
                "ds_adj_ev": round(ev.payoff.downside_adjusted_ev, 4),
                "actionable": ev.actionable,
                "prior_source": ev.outcome.prior_source,
                "days_to_event": days,
                "event_type": ev.node.event_type,
            }
        )
    return rows


def _enrich_context(
    context_features: Dict[str, Dict],
    trials: list,
    as_of_date: str,
    use_protocol: bool = True,
    use_biomarker: bool = True,
    use_endpoint_v2: bool = True,
):
    """Inject protocol/biomarker/endpoint scores into context features."""
    pq_results = {}
    if use_protocol or use_biomarker:
        from common.protocol_quality import compute_protocol_quality

        pq_results = compute_protocol_quality(trials, as_of_date)

    bm_results = {}
    if use_biomarker:
        from common.biomarker_context import compute_biomarker_context_score

        bm_results = compute_biomarker_context_score(trials, as_of_date, protocol_quality=pq_results)

    ep_results = {}
    if use_endpoint_v2:
        from common.endpoint_quality import compute_endpoint_quality

        ep_results = compute_endpoint_quality(trials, as_of_date)

    for ticker in context_features:
        if use_protocol and ticker in pq_results:
            context_features[ticker]["protocol_quality_score"] = pq_results[ticker]["protocol_quality_score"]
        if use_biomarker and ticker in bm_results:
            context_features[ticker]["biomarker_context_score"] = bm_results[ticker]["biomarker_context_score"]
        if use_endpoint_v2 and ticker in ep_results:
            context_features[ticker]["endpoint_quality_score"] = ep_results[ticker]["endpoint_quality_score"]


def _compare(base: List[Dict], variant: List[Dict], label: str) -> Dict[str, Any]:
    """Compare two EV runs."""
    base_by_key = {f"{r['ticker']}_{r['event_type']}": r for r in base}
    var_by_key = {f"{r['ticker']}_{r['event_type']}": r for r in variant}

    base_top10 = {r["ticker"] for r in base[:10]}
    var_top10 = {r["ticker"] for r in variant[:10]}
    base_top20 = {r["ticker"] for r in base[:20]}
    var_top20 = {r["ticker"] for r in variant[:20]}

    # Phase 2 specific
    var_p2 = [r for r in variant if r["phase"] == "2"]

    p2_phit_delta = []
    for key, vr in var_by_key.items():
        if vr["phase"] != "2":
            continue
        br = base_by_key.get(key)
        if br:
            p2_phit_delta.append(vr["p_hit"] - br["p_hit"])

    # Rank movers
    movers = []
    for key, vr in var_by_key.items():
        br = base_by_key.get(key)
        if br:
            delta = br["rank"] - vr["rank"]
            if abs(delta) >= 5:
                movers.append(
                    {
                        "ticker": vr["ticker"],
                        "phase": vr["phase"],
                        "old_rank": br["rank"],
                        "new_rank": vr["rank"],
                        "rank_delta": delta,
                        "old_p_hit": br["p_hit"],
                        "new_p_hit": vr["p_hit"],
                        "old_ev": br["scenario_ev"],
                        "new_ev": vr["scenario_ev"],
                    }
                )
    movers.sort(key=lambda x: -abs(x["rank_delta"]))

    return {
        "label": label,
        "n_total": len(variant),
        "n_actionable_base": sum(1 for r in base if r["actionable"]),
        "n_actionable_var": sum(1 for r in variant if r["actionable"]),
        "top10_overlap": len(base_top10 & var_top10),
        "top20_overlap": len(base_top20 & var_top20),
        "n_phase2": len(var_p2),
        "phase2_mean_phit_delta": round(sum(p2_phit_delta) / len(p2_phit_delta), 4) if p2_phit_delta else None,
        "n_movers_5plus": len(movers),
        "top_movers": movers[:10],
    }


def _compound_movers(base: List[Dict], full: List[Dict], trials: list) -> List[Dict]:
    """Find names where 3+ layers push in the same direction."""
    from common.biomarker_context import compute_biomarker_context_score
    from common.endpoint_quality import compute_endpoint_quality
    from common.protocol_quality import compute_protocol_quality

    pq = compute_protocol_quality(trials, AS_OF)
    bm = compute_biomarker_context_score(trials, AS_OF, protocol_quality=pq)
    ep = compute_endpoint_quality(trials, AS_OF)

    base_by_tk = {f"{r['ticker']}_{r['event_type']}": r for r in base}
    full_by_tk = {f"{r['ticker']}_{r['event_type']}": r for r in full}

    compounds = []
    for key, fr in full_by_tk.items():
        br = base_by_tk.get(key)
        if not br:
            continue
        tk = fr["ticker"]
        rank_delta = br["rank"] - fr["rank"]

        pq_val = pq.get(tk, {}).get("protocol_quality_score", 0)
        bm_val = bm.get(tk, {}).get("biomarker_context_score", 0)
        ep_val = ep.get(tk, {}).get("endpoint_quality_score", 0)

        # Count how many layers push positive (above median)
        positive_layers = sum(
            [
                pq_val > 0.5,
                bm_val > 0.15,
                ep_val > 0.5,
            ]
        )
        negative_layers = sum(
            [
                pq_val < 0.15,
                bm_val == 0,
                ep_val < 0.15,
            ]
        )

        if positive_layers >= 3 or negative_layers >= 3:
            compounds.append(
                {
                    "ticker": tk,
                    "phase": fr["phase"],
                    "rank_delta": rank_delta,
                    "old_rank": br["rank"],
                    "new_rank": fr["rank"],
                    "pq": pq_val,
                    "bm": bm_val,
                    "ep": ep_val,
                    "direction": "all_positive" if positive_layers >= 3 else "all_negative",
                    "pq_signals": pq.get(tk, {}).get("protocol_signals", ""),
                    "bm_signals": bm.get(tk, {}).get("biomarker_signals", ""),
                    "ep_bucket": ep.get(tk, {}).get("best_bucket", ""),
                }
            )

    compounds.sort(key=lambda x: -abs(x["rank_delta"]))
    return compounds


def run_ablation() -> Dict[str, Any]:
    print("Clinical Stack v2 — Integrated Ablation")
    print(f"as_of={AS_OF}")
    print("=" * 70)

    trials = _load_data()

    # Define variants
    variants = {
        "baseline": {"phase2_prior": 0.310, "use_protocol": False, "use_biomarker": False, "use_endpoint_v2": False},
        "prior_only": {"phase2_prior": 0.420, "use_protocol": False, "use_biomarker": False, "use_endpoint_v2": False},
        "protocol_only": {
            "phase2_prior": 0.310,
            "use_protocol": True,
            "use_biomarker": False,
            "use_endpoint_v2": False,
        },
        "biomarker_only": {
            "phase2_prior": 0.310,
            "use_protocol": False,
            "use_biomarker": True,
            "use_endpoint_v2": False,
        },
        "endpoint_only": {
            "phase2_prior": 0.310,
            "use_protocol": False,
            "use_biomarker": False,
            "use_endpoint_v2": True,
        },
        "full_v2": {"phase2_prior": 0.420, "use_protocol": True, "use_biomarker": True, "use_endpoint_v2": True},
        "full_minus_prior": {
            "phase2_prior": 0.310,
            "use_protocol": True,
            "use_biomarker": True,
            "use_endpoint_v2": True,
        },
        "full_minus_protocol": {
            "phase2_prior": 0.420,
            "use_protocol": False,
            "use_biomarker": True,
            "use_endpoint_v2": True,
        },
        "full_minus_biomarker": {
            "phase2_prior": 0.420,
            "use_protocol": True,
            "use_biomarker": False,
            "use_endpoint_v2": True,
        },
        "full_minus_endpoint": {
            "phase2_prior": 0.420,
            "use_protocol": True,
            "use_biomarker": True,
            "use_endpoint_v2": False,
        },
    }

    results = {}
    for name, kwargs in variants.items():
        print(f"\n  Running {name}...")
        rows = _run_ev_variant(trials, label=name, **kwargs)
        results[name] = rows
        n_act = sum(1 for r in rows if r["actionable"])
        print(f"    → {len(rows)} scored, {n_act} actionable")

    # Compare all vs baseline
    baseline = results["baseline"]
    comparisons = {}
    for name, rows in results.items():
        if name == "baseline":
            continue
        comparisons[name] = _compare(baseline, rows, name)

    # Print summary table
    print(f"\n{'='*70}")
    print("ABLATION SUMMARY (vs baseline)")
    print(f"{'Variant':>25s} {'Act':>4s} {'T10':>4s} {'T20':>4s} {'Ph2Δ':>8s} {'Mov5+':>5s}")
    print("-" * 55)
    for name, comp in comparisons.items():
        act = f"{comp['n_actionable_var']}"
        t10 = f"{comp['top10_overlap']}/10"
        t20 = f"{comp['top20_overlap']}/20"
        p2d = f"{comp['phase2_mean_phit_delta']:+.3f}" if comp["phase2_mean_phit_delta"] else "n/a"
        mov = f"{comp['n_movers_5plus']}"
        print(f"{name:>25s} {act:>4s} {t10:>4s} {t20:>4s} {p2d:>8s} {mov:>5s}")

    # Compound movers
    print(f"\n{'='*70}")
    print("COMPOUND MOVERS (3+ layers same direction)")
    print("=" * 70)
    compounds = _compound_movers(baseline, results["full_v2"], trials)
    for c in compounds[:15]:
        print(
            f"  {c['ticker']:>6s} ph={c['phase']} {c['direction']:15s} Δrank={c['rank_delta']:+4d} "
            f"pq={c['pq']:.2f} bm={c['bm']:.2f} ep={c['ep']:.2f} ep_bucket={c['ep_bucket']}"
        )

    # Full v2 top movers
    full_comp = comparisons["full_v2"]
    print(f"\n{'='*70}")
    print("FULL v2 TOP MOVERS (vs baseline)")
    print("=" * 70)
    for m in full_comp["top_movers"][:15]:
        print(
            f"  {m['ticker']:>6s} ph={m['phase']} rank {m['old_rank']}→{m['new_rank']} "
            f"(Δ={m['rank_delta']:+d}) p_hit {m['old_p_hit']:.3f}→{m['new_p_hit']:.3f} "
            f"EV {m['old_ev']:+.1f}→{m['new_ev']:+.1f}"
        )

    # Subgroup: by phase
    print(f"\n{'='*70}")
    print("SUBGROUP: FULL v2 BY PHASE (mean p_hit)")
    print("=" * 70)
    for phase_label in ["1", "2", "3"]:
        base_ph = [r["p_hit"] for r in baseline if r["phase"] == phase_label]
        full_ph = [r["p_hit"] for r in results["full_v2"] if r["phase"] == phase_label]
        if base_ph and full_ph:
            b_mean = sum(base_ph) / len(base_ph)
            f_mean = sum(full_ph) / len(full_ph)
            print(
                f"  Phase {phase_label}: n={len(base_ph)} base_mean={b_mean:.3f} full_mean={f_mean:.3f} Δ={f_mean-b_mean:+.3f}"
            )

    # Verdict
    verdict = _verdict(comparisons, compounds)
    print(f"\n{'='*70}")
    print(f"VERDICT: {verdict['recommendation']}")
    print(f"  {verdict['reasoning']}")

    output = {
        "as_of_date": AS_OF,
        "variants": list(variants.keys()),
        "comparisons": comparisons,
        "compound_movers": compounds[:20],
        "verdict": verdict,
    }
    out_path = REPO_ROOT / "artifacts" / "clinical_stack_v2_ablation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nWritten to {out_path}")
    return output


def _verdict(comparisons: Dict, compounds: List) -> Dict[str, str]:
    full = comparisons.get("full_v2", {})
    t10 = full.get("top10_overlap", 0)
    t20 = full.get("top20_overlap", 0)
    n_compound_bad = sum(1 for c in compounds if c["direction"] == "all_negative" and c["rank_delta"] > 20)

    if t10 >= 7 and t20 >= 15 and n_compound_bad <= 3:
        return {
            "recommendation": "PROMOTE full clinical stack v2",
            "reasoning": f"Top-10 overlap {t10}/10, top-20 {t20}/20 — stable. "
            f"Compound movers are sensible ({len(compounds)} total, {n_compound_bad} suspicious). "
            f"Changes are concentrated where expected (Phase 2, biomarker, endpoint quality).",
        }
    elif t10 >= 5:
        return {
            "recommendation": "PROMOTE behind flag pending 2-week forward validation",
            "reasoning": f"Top-10 overlap {t10}/10 — moderate churn. Monitor for stability.",
        }
    else:
        return {
            "recommendation": "REVISE — too much churn for immediate promotion",
            "reasoning": f"Top-10 overlap {t10}/10 — excessive. Review layer interaction.",
        }


if __name__ == "__main__":
    run_ablation()
