#!/usr/bin/env python3
"""Daily Event EV Scoring Tool (Spec 060).

Runs the Event EV engine on the current catalyst universe and produces:
  - Full EventEV scores per catalyst
  - Compact leaderboard (sorted by downside-adjusted EV)
  - Operator-readable markdown memo

Designed to be called from run_daily_production.py (Step 5k.21)
or standalone for ad-hoc analysis.

Usage:
    python tools/build_event_ev_scores.py --as-of 2026-04-06
    python tools/build_event_ev_scores.py  # uses today
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from event_ev.data_contracts import EventEV
from event_ev.ev_calculator import EventEVCalculator
from event_ev.loaders import load_catalyst_graph, load_evidence_snapshots, load_market_features, split_context_features
from event_ev.outcome_model import OutcomeModel

logger = logging.getLogger(__name__)


def build_scores(
    as_of_date: str,
    repo_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    max_days: int = 180,
    enrich_pubmed: bool = False,
) -> Dict[str, Any]:
    """Run the Event EV engine and produce scored leaderboard.

    Args:
        as_of_date: ISO date string (e.g. "2026-04-06").
        repo_root: Project root (default: auto-detect).
        output_dir: Where to write artifacts (default: artifacts/event_ev/).
        max_days: Maximum days to catalyst for inclusion.
        enrich_pubmed: If True, fetch PubMed literature scores via NCBI API.
            Default False to avoid API calls during fast production runs.

    Returns:
        Dict with n_total, n_actionable, leaderboard, events, stats.
    """
    root = repo_root or REPO_ROOT
    prod_data = root / "production_data"
    data_dir = root / "data"
    snapshots_dir = data_dir / "snapshots"

    as_of = date.fromisoformat(as_of_date)

    # Load data
    graph = load_catalyst_graph(as_of, prod_data, data_dir)
    market_features = load_market_features(as_of, snapshots_dir)
    context_features = split_context_features(market_features)

    if graph.node_count == 0:
        logger.info("Empty catalyst graph — no events to score")
        result = _empty_result(as_of_date)
        if output_dir:
            _write_artifacts(result, as_of_date, output_dir)
        return result

    # Build CRT-calibrated outcome model
    crt_cal = None
    resolutions_dir = data_dir / "snapshots" / "resolutions"
    if resolutions_dir.exists():
        try:
            crt_cal = OutcomeModel.build_crt_calibration(resolutions_dir)
        except Exception:
            logger.debug("CRT calibration failed — using base rates")
    outcome_model = OutcomeModel(crt_calibration=crt_cal) if crt_cal else None

    # Load evidence snapshots (optional PubMed enrichment)
    all_nodes = graph.get_event_cohort(as_of, max_days=max_days, min_days=0)
    evidence_snapshots = {}
    try:
        evidence_snapshots = load_evidence_snapshots(
            all_nodes,
            as_of,
            prod_data,
            data_dir,
            enrich_pubmed=enrich_pubmed,
        )
    except Exception:
        logger.warning("Evidence snapshot loading failed — continuing without evidence")

    # Compute clinical stack v2 scores and inject into context_features
    # so the outcome model's transmission layer can use them.
    try:
        import json as _json

        trial_path = prod_data / "trial_records.json"
        if trial_path.exists():
            _trials = _json.loads(trial_path.read_text())

            from common.protocol_quality import compute_protocol_quality

            _pq = compute_protocol_quality(_trials, as_of_date)

            from common.biomarker_context import compute_biomarker_context_score

            _bm = compute_biomarker_context_score(_trials, as_of_date, protocol_quality=_pq)

            from common.endpoint_quality import compute_endpoint_quality

            _ep = compute_endpoint_quality(_trials, as_of_date)

            for ticker in context_features:
                if ticker in _pq:
                    context_features[ticker]["protocol_quality_score"] = _pq[ticker]["protocol_quality_score"]
                if ticker in _bm:
                    context_features[ticker]["biomarker_context_score"] = _bm[ticker]["biomarker_context_score"]
                if ticker in _ep:
                    context_features[ticker]["endpoint_quality_score"] = _ep[ticker]["endpoint_quality_score"]

            logger.info(
                "Clinical stack v2: %d protocol, %d biomarker, %d endpoint scores injected",
                sum(1 for t in context_features.values() if "protocol_quality_score" in t),
                sum(1 for t in context_features.values() if "biomarker_context_score" in t),
                sum(1 for t in context_features.values() if "endpoint_quality_score" in t),
            )
    except Exception as _clin_err:
        logger.warning("Clinical stack v2 injection failed: %s", _clin_err)

    # Run EV calculator
    calc = EventEVCalculator(
        as_of_date=as_of,
        outcome_model=outcome_model,
        max_days=max_days,
        min_days=0,
    )
    results = calc.run_from_graph(
        graph,
        market_features=market_features,
        context_features=context_features,
        current_weights=None,
        sizing_mode="ew_filter",
        evidence_snapshots=evidence_snapshots,
    )

    # Build leaderboard
    leaderboard = _build_leaderboard(results, as_of)
    stats = _compute_stats(results, as_of)

    result = {
        "as_of_date": as_of_date,
        "n_total": len(results),
        "n_actionable": sum(1 for ev in results if ev.actionable),
        "n_graph_nodes": graph.node_count,
        "n_market_features": len(market_features),
        "leaderboard": leaderboard,
        "stats": stats,
        "events": [ev.to_dict() for ev in results],
    }

    if output_dir:
        _write_artifacts(result, as_of_date, output_dir)

    return result


def _build_leaderboard(results: List[EventEV], as_of: date) -> List[Dict[str, Any]]:
    """Build compact leaderboard from EventEV results."""
    rows = []
    for rank, ev in enumerate(results, 1):
        days = ev.node.days_to_event(as_of)

        row: Dict[str, Any] = {
            "rank": rank,
            "ticker": ev.node.ticker,
            "event_type": ev.node.event_type,
            "event_family": ev.node.event_family,
            "phase": ev.node.phase,
            "days_to_event": days,
            "p_hit": round(ev.outcome.p_hit, 3),
            "p_miss": round(ev.outcome.p_miss, 3),
            "implied_p_hit": round(ev.expectation.implied_p_hit, 3),
            "mispricing": round(ev.mispricing_score, 3),
            "upside_hit": round(ev.payoff.upside_hit, 1),
            "downside_miss": round(ev.payoff.downside_miss, 1),
            "scenario_ev": round(ev.scenario_ev, 2),
            "ds_adj_ev": round(ev.payoff.downside_adjusted_ev, 2),
            "timing_on_time": round(ev.timing.prob_on_time, 3),
            "analog_conf": ev.payoff.analog_confidence,
            "actionable": ev.actionable,
            "source": ev.node.source,
            "date_confidence": round(ev.node.date_confidence, 3),
            "is_overdue_window": "OVERDUE_WINDOW" in (ev.node.event_subtype or ""),
            "is_supplement": ev.node.source == "M3_RANKINGS_SUPPLEMENT",
        }

        # Evidence snapshot fields (when available)
        evi = ev.evidence
        if evi:
            row["literature_support_score"] = evi.literature_support_score
            row["evidence_confidence"] = evi.evidence_confidence
            row["randomized_flag"] = evi.randomized_flag
            row["blinded_flag"] = evi.blinded_flag
            row["enrollment_n"] = evi.enrollment_n
            row["endpoint_type"] = evi.endpoint_type
            row["orphan_flag"] = evi.orphan_flag
            row["breakthrough_flag"] = evi.breakthrough_flag
            row["ctgov_study_id"] = evi.ctgov_study_id
        else:
            row["literature_support_score"] = None
            row["evidence_confidence"] = None

        # Spec 059 overlays
        bs = ev.branch_sensitivity
        if bs:
            be = bs.get("breakeven", {})
            row["breakeven_straddle"] = be.get("breakeven_move_pct") if be else None
            row["term_shape"] = bs.get("term_shape")
            row["belief_modifier"] = bs.get("belief_modifier")
        else:
            row["breakeven_straddle"] = None
            row["term_shape"] = None
            row["belief_modifier"] = None

        rows.append(row)

    return rows


def _compute_stats(results: List[EventEV], as_of: date) -> Dict[str, Any]:
    """Compute summary statistics."""
    if not results:
        return {"n_total": 0}

    evs = [ev.payoff.scenario_ev for ev in results]
    ds_adj = [ev.payoff.downside_adjusted_ev for ev in results]

    stats: Dict[str, Any] = {
        "n_total": len(results),
        "n_actionable": sum(1 for ev in results if ev.actionable),
        "n_positive_ev": sum(1 for e in evs if e > 0),
        "n_negative_ev": sum(1 for e in evs if e < 0),
        "top_ev": round(max(evs), 2),
        "mean_ev": round(sum(evs) / len(evs), 2),
        "top_ds_adj_ev": round(max(ds_adj), 2),
    }

    # Family breakdown
    fam_counts: Dict[str, int] = {}
    for ev in results:
        fam_counts[ev.node.event_family] = fam_counts.get(ev.node.event_family, 0) + 1
    stats["family_breakdown"] = fam_counts

    return stats


def _empty_result(as_of_date: str) -> Dict[str, Any]:
    return {
        "as_of_date": as_of_date,
        "n_total": 0,
        "n_actionable": 0,
        "n_graph_nodes": 0,
        "n_market_features": 0,
        "leaderboard": [],
        "stats": {"n_total": 0},
        "events": [],
    }


def _write_artifacts(
    result: Dict[str, Any],
    as_of_date: str,
    output_dir: Path,
) -> None:
    """Write JSON + markdown artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Full scores (without events to keep size manageable)
    scores_path = output_dir / f"{as_of_date}_event_ev_scores.json"
    scores_out = {k: v for k, v in result.items() if k != "events"}
    scores_path.write_text(json.dumps(scores_out, indent=2, default=str))

    # Full events (separate file for detail)
    events_path = output_dir / f"{as_of_date}_event_ev_full.json"
    events_path.write_text(
        json.dumps(
            {
                "as_of_date": as_of_date,
                "n_events": len(result.get("events", [])),
                "events": result.get("events", []),
            },
            indent=2,
            default=str,
        )
    )

    # Leaderboard JSON
    lb_path = output_dir / f"{as_of_date}_ev_leaderboard.json"
    lb_path.write_text(json.dumps(result["leaderboard"], indent=2, default=str))

    # Operator memo (markdown)
    md_path = output_dir / f"{as_of_date}_ev_leaderboard.md"
    md_path.write_text(_render_memo(result, as_of_date))

    logger.info("Artifacts written to %s", output_dir)


def _render_memo(result: Dict[str, Any], as_of_date: str) -> str:
    """Render operator-readable markdown memo."""
    lb = result.get("leaderboard", [])
    stats = result.get("stats", {})
    n_total = result.get("n_total", 0)
    n_actionable = result.get("n_actionable", 0)

    lines = [
        f"# Event EV Leaderboard — {as_of_date}",
        "",
        f"**{n_total} catalysts scored, {n_actionable} actionable (EV > 0, within 180d)**",
        "",
    ]

    if stats.get("family_breakdown"):
        fam = stats["family_breakdown"]
        parts = [f"{k}: {v}" for k, v in sorted(fam.items())]
        lines.append(f"Family mix: {', '.join(parts)}")
        lines.append("")

    if stats.get("top_ev"):
        lines.append(f"Top scenario EV: {stats['top_ev']:.1f}% | Mean: {stats.get('mean_ev', 0):.1f}%")
        lines.append("")

    if lb:
        lines.append("## Top Catalysts by Downside-Adjusted EV")
        lines.append("")
        lines.append("| # | Ticker | Type | Days | P(hit) | Misprice | EV% | DS-EV% | Shape | Conf |")
        lines.append("|---|--------|------|------|--------|----------|-----|--------|-------|------|")
        for row in lb[:20]:
            shape = row.get("term_shape") or ""
            lines.append(
                f"| {row['rank']} "
                f"| {row['ticker']} "
                f"| {row['event_type'][:12]} "
                f"| {row.get('days_to_event', '?')} "
                f"| {row['p_hit']:.2f} "
                f"| {row['mispricing']:+.2f} "
                f"| {row['scenario_ev']:+.1f} "
                f"| {row['ds_adj_ev']:+.1f} "
                f"| {shape[:8]} "
                f"| {row['analog_conf'][:3]} |"
            )
        lines.append("")
    else:
        lines.append("No actionable catalysts in scoring window.")
        lines.append("")

    lines.append("---")
    lines.append("*Diagnostic only — does not feed selector/ranker/construction.*")

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Daily Event EV Scoring (Spec 060)")
    parser.add_argument("--as-of", default=str(date.today()), help="Evaluation date (YYYY-MM-DD)")
    parser.add_argument("--max-days", type=int, default=180, help="Max days to catalyst")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory")
    parser.add_argument("--pubmed", action="store_true", help="Enrich with PubMed literature scores")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else REPO_ROOT / "artifacts" / "event_ev"

    result = build_scores(
        as_of_date=args.as_of,
        output_dir=out_dir,
        max_days=args.max_days,
        enrich_pubmed=args.pubmed,
    )

    print(f"\nEvent EV Scoring — {args.as_of}")
    print(f"  Graph nodes: {result['n_graph_nodes']}")
    print(f"  Catalysts scored: {result['n_total']}")
    print(f"  Actionable: {result['n_actionable']}")
    if result["leaderboard"]:
        top = result["leaderboard"][0]
        print(
            f"  Top: {top['ticker']} ({top['event_type']}) — EV={top['scenario_ev']:+.1f}%, DS-EV={top['ds_adj_ev']:+.1f}%"
        )
