#!/usr/bin/env python3
"""Compare phase score v3 impact against a snapshot.

Reads a snapshot's rankings.csv, applies PHASE_SCORES_V3 deltas to the M4
clinical score, propagates through composite → composite_rank, and produces
the governance table showing rank/tier impact.

The DEM sort key uses composite_rank as its anchor. So the correct chain is:
  phase_score delta → M4 clinical_score delta → composite_score delta →
  re-rank composite → new composite_rank → rank impact

Usage:
    python scripts/research/compare_phase_scores_v3.py \
        --snapshot data/snapshots/2026-03-13
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from module_4_clinical_dev import PHASE_SCORES, PHASE_SCORES_V2, PHASE_SCORES_V3

# M5 clinical weight — use the enhanced (most common production) weight.
# clinical_score * M5_CLINICAL_WEIGHT → contribution to composite_score.
M5_CLINICAL_WEIGHT = 0.26


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _phase_norm(raw: str) -> str:
    """Normalize phase string to match PHASE_SCORES keys.

    M4 defaults to 'preclinical' (score=3) when no trial has a recognized phase.
    Empty/unknown phases in the CSV therefore map to 'preclinical' so the
    compare applies the same delta that a real --phase-scores-v3 run would.
    """
    s = (raw or "").strip().lower()
    mapping = {
        "phase 1": "phase 1",
        "phase 2": "phase 2",
        "phase 3": "phase 3",
        "phase 1/2": "phase 1/2",
        "phase 2/3": "phase 2/3",
        "approved": "approved",
        "preclinical": "preclinical",
        "phase1": "phase 1",
        "phase2": "phase 2",
        "phase3": "phase 3",
        # Numeric format from rankings CSV
        "1.0": "phase 1",
        "2.0": "phase 2",
        "3.0": "phase 3",
        "4.0": "approved",
        "0.0": "preclinical",
        "1.5": "phase 1/2",
        "2.5": "phase 2/3",
        "1": "phase 1",
        "2": "phase 2",
        "3": "phase 3",
        "4": "approved",
        "0": "preclinical",
    }
    result = mapping.get(s, s)
    # M4 defaults unknown phases to preclinical — match that behavior
    if not result or result not in PHASE_SCORES:
        return "preclinical"
    return result


def load_rankings(snapshot_dir: Path) -> List[Dict[str, str]]:
    rankings_path = snapshot_dir / "rankings.csv"
    with open(rankings_path, newline="") as f:
        return list(csv.DictReader(f))


def compute_phase_delta(
    lead_phase: str,
    old_scores: Dict[str, Decimal],
    new_scores: Dict[str, Decimal],
) -> Tuple[float, float, float, str]:
    """Compute M4 clinical_score delta from phase score change.

    Returns (old_phase_pts, new_phase_pts, m4_delta, fallback_reason).
    M4 total is /120 * 100, so delta = (new - old) / 120 * 100.
    """
    phase = _phase_norm(lead_phase)
    old_pts = float(old_scores.get(phase, Decimal("0")))
    new_pts = float(new_scores.get(phase, Decimal("0")))

    fallback = ""
    raw_stripped = (lead_phase or "").strip()
    if not raw_stripped or raw_stripped.lower() in ("", "unknown", "n/a", "na"):
        fallback = "unknown_phase_preclinical_fallback"
    elif phase not in new_scores and phase not in old_scores:
        fallback = "not_in_score_table"

    m4_delta = (new_pts - old_pts) / 120.0 * 100.0
    return old_pts, new_pts, m4_delta, fallback


def run_compare(
    snapshot_dir: Path,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    rows = load_rankings(snapshot_dir)
    if not rows:
        return {"status": "empty_snapshot"}

    # Build comparison records
    records = []
    for row in rows:
        ticker = row.get("ticker", "")
        lead_phase = row.get("lead_program_phase", "")
        current_rank = _safe_float(row.get("actionable_rank"))
        current_tier = row.get("tier_dev", row.get("tier_any", ""))
        clinical_score = _safe_float(row.get("clinical_score"))
        composite_score = _safe_float(row.get("composite_score"))
        composite_rank = _safe_float(row.get("composite_rank"))

        # V1 vs V3 delta
        old_pts, new_pts, m4_delta, fallback = compute_phase_delta(lead_phase, PHASE_SCORES, PHASE_SCORES_V3)
        # V1 vs V2 delta (for context)
        _, v2_pts, m4_delta_v2, _ = compute_phase_delta(lead_phase, PHASE_SCORES, PHASE_SCORES_V2)

        # Propagate through M5: composite_score += m4_delta * M5_CLINICAL_WEIGHT
        composite_delta = m4_delta * M5_CLINICAL_WEIGHT

        records.append(
            {
                "ticker": ticker,
                "lead_phase": lead_phase,
                "current_rank": int(current_rank) if current_rank is not None else None,
                "current_tier": current_tier,
                "clinical_score": round(clinical_score, 2) if clinical_score is not None else None,
                "composite_score": composite_score,
                "composite_rank": int(composite_rank) if composite_rank is not None else None,
                "old_phase_pts": old_pts,
                "v2_phase_pts": v2_pts,
                "v3_phase_pts": new_pts,
                "phase_delta_v3": new_pts - old_pts,
                "m4_delta_v3": round(m4_delta, 4),
                "composite_delta_v3": round(composite_delta, 4),
                "v3_composite_score": (
                    round(composite_score + composite_delta, 4) if composite_score is not None else None
                ),
                "v3_clinical_score": round(clinical_score + m4_delta, 2) if clinical_score is not None else None,
                "fallback_reason": fallback,
            }
        )

    # Re-rank composite scores to get new composite_rank.
    # Use current_rank as tiebreaker to preserve the DEM's own ordering
    # when composite scores are identical (common in the tail where M5
    # composite is 0.1 for many tickers — stale/degenerate).
    scorable = [r for r in records if r["v3_composite_score"] is not None]
    scorable.sort(key=lambda r: (-r["v3_composite_score"], r.get("current_rank") or 9999))
    for i, r in enumerate(scorable):
        r["v3_composite_rank"] = i + 1

    # The DEM sort key uses composite_rank as anchor but also tier, catalyst,
    # optionality etc. Since only composite_rank changes, the sort key change
    # is bounded to within-tier/within-catalyst-bucket reordering.
    # For the governance table, we approximate the actionable_rank impact
    # by looking at composite_rank shifts within the same tier+catalyst bucket.

    # Group by (current_tier, catalyst bucket proxy) and re-rank within group
    for r in records:
        r["v3_rank"] = r.get("current_rank")  # default: unchanged
        r["rank_delta"] = 0

    # Build actionable rank from composite rank ordering, preserving
    # the tier structure (tier is primary sort, composite_rank is within-tier)
    eligible = [r for r in records if r["current_rank"] is not None]
    for r in eligible:
        r["_v3_cr"] = r.get("v3_composite_rank", r.get("composite_rank", 9999))

    # Sort by: (tier_order, v3_composite_rank) to get v3 actionable rank
    tier_order = {"A": 0, "B": 1, "C": 2, "D": 3, "": 4}
    eligible.sort(key=lambda r: (tier_order.get(r["current_tier"], 4), r["_v3_cr"]))
    for i, r in enumerate(eligible):
        r["v3_rank"] = i + 1
        r["rank_delta"] = r["v3_rank"] - r["current_rank"]

    # Now check if tier boundaries shift. The tier is assigned by the DEM
    # based on score thresholds, not by rank position. Since composite_score
    # changes are small (max ~0.87 points), tier changes should be rare.
    # We detect them by checking if any ticker crosses the tier boundary.
    a_tickers = {r["ticker"] for r in eligible if r["current_tier"] == "A"}
    b_tickers = {r["ticker"] for r in eligible if r["current_tier"] == "B"}
    a_count = len(a_tickers)
    b_count = len(b_tickers)

    for r in eligible:
        if r["v3_rank"] <= a_count:
            r["v3_tier"] = "A"
        elif r["v3_rank"] <= a_count + b_count:
            r["v3_tier"] = "B"
        else:
            r["v3_tier"] = r["current_tier"]
        r["tier_delta"] = "" if r["v3_tier"] == r["current_tier"] else f"{r['current_tier']}→{r['v3_tier']}"

    # Compute overlap metrics
    n = len(eligible)
    current_top60 = {r["ticker"] for r in eligible if r["current_rank"] <= 60}
    v3_top60 = {r["ticker"] for r in eligible if r["v3_rank"] <= 60}
    current_top100 = {r["ticker"] for r in eligible if r["current_rank"] <= 100}
    v3_top100 = {r["ticker"] for r in eligible if r["v3_rank"] <= 100}

    overlap_60 = len(current_top60 & v3_top60) / max(len(current_top60), 1)
    overlap_100 = len(current_top100 & v3_top100) / max(len(current_top100), 1)

    shifts = [abs(r["rank_delta"]) for r in eligible]
    mean_shift = sum(shifts) / len(shifts) if shifts else 0
    sorted_shifts = sorted(shifts)
    median_shift = sorted_shifts[len(sorted_shifts) // 2] if sorted_shifts else 0
    max_shift = max(shifts) if shifts else 0

    # A-tier changes
    a_downgrades = [r for r in eligible if r["current_tier"] == "A" and r.get("v3_tier") != "A"]
    a_upgrades = [r for r in eligible if r["current_tier"] != "A" and r.get("v3_tier") == "A"]
    b_big_shifts = [r for r in eligible if r["current_tier"] == "B" and abs(r.get("rank_delta", 0)) > 5]

    # Phase cohort analysis
    phase_cohorts: Dict[str, List[int]] = {}
    for r in eligible:
        phase = r["lead_phase"] or "unknown"
        phase_cohorts.setdefault(phase, []).append(r.get("rank_delta", 0))

    phase_summary = {}
    for phase, deltas in sorted(phase_cohorts.items()):
        phase_summary[phase] = {
            "n": len(deltas),
            "mean_shift": round(sum(abs(d) for d in deltas) / len(deltas), 2),
            "mean_signed": round(sum(deltas) / len(deltas), 2),
            "phase_score_delta": float(PHASE_SCORES_V3.get(_phase_norm(phase), Decimal("0")))
            - float(PHASE_SCORES.get(_phase_norm(phase), Decimal("0"))),
        }

    # Max shift within top-100 only (tail is noise-dominated)
    top100_shifts = [abs(r["rank_delta"]) for r in eligible if r["current_rank"] <= 100]
    max_shift_top100 = max(top100_shifts) if top100_shifts else 0

    # Unknown-phase isolation
    unknown_phase_tickers = [
        r for r in eligible if not r["lead_phase"] or _phase_norm(r["lead_phase"]) not in PHASE_SCORES
    ]
    unknown_shifts = [r["rank_delta"] for r in unknown_phase_tickers]

    # Gate results — repo-native thresholds
    gates = {
        "top_60_overlap": round(overlap_60 * 100, 1),
        "top_60_overlap_pass": overlap_60 >= 0.90,
        "top_100_overlap": round(overlap_100 * 100, 1),
        "mean_rank_shift": round(mean_shift, 2),
        "mean_shift_advisory": mean_shift <= 3,
        "median_rank_shift": median_shift,
        "max_rank_shift": max_shift,
        "max_rank_shift_pass": max_shift <= 30,
        "max_rank_shift_top100": max_shift_top100,
        "max_rank_shift_top100_pass": max_shift_top100 <= 30,
        "a_downgrades": len(a_downgrades),
        "a_downgrades_pass": len(a_downgrades) == 0,
        "a_upgrades": len(a_upgrades),
        "b_big_shifts": len(b_big_shifts),
        "unknown_phase_count": len(unknown_phase_tickers),
        "unknown_phase_mean_signed": round(sum(unknown_shifts) / len(unknown_shifts), 2) if unknown_shifts else 0,
    }

    hard_pass = gates["top_60_overlap_pass"] and gates["max_rank_shift_pass"] and gates["a_downgrades_pass"]
    gates["overall"] = (
        "APPROVE" if hard_pass else "HOLD" if gates["top_60_overlap_pass"] and gates["a_downgrades_pass"] else "REJECT"
    )

    result = {
        "snapshot_date": snapshot_dir.name,
        "n_ranked": n,
        "m5_clinical_weight": M5_CLINICAL_WEIGHT,
        "max_composite_delta": round(
            max((abs(r["composite_delta_v3"]) for r in records if r.get("composite_delta_v3")), default=0), 4
        ),
        "gates": gates,
        "phase_summary": phase_summary,
        "a_downgrades": [
            {
                "ticker": r["ticker"],
                "lead_phase": r["lead_phase"],
                "current_rank": r["current_rank"],
                "v3_rank": r["v3_rank"],
                "rank_delta": r["rank_delta"],
                "phase_delta": r["phase_delta_v3"],
                "tier_delta": r.get("tier_delta", ""),
            }
            for r in a_downgrades
        ],
        "a_upgrades": [
            {
                "ticker": r["ticker"],
                "lead_phase": r["lead_phase"],
                "current_rank": r["current_rank"],
                "v3_rank": r["v3_rank"],
                "rank_delta": r["rank_delta"],
            }
            for r in a_upgrades
        ],
        "b_big_shifts": [
            {
                "ticker": r["ticker"],
                "lead_phase": r["lead_phase"],
                "current_rank": r["current_rank"],
                "v3_rank": r["v3_rank"],
                "rank_delta": r["rank_delta"],
                "phase_delta": r["phase_delta_v3"],
            }
            for r in b_big_shifts
        ],
        "largest_downward_movers": [
            {
                "ticker": r["ticker"],
                "lead_phase": r["lead_phase"],
                "current_rank": r["current_rank"],
                "v3_rank": r["v3_rank"],
                "rank_delta": r["rank_delta"],
                "current_tier": r["current_tier"],
            }
            for r in sorted(
                [r for r in eligible if r.get("rank_delta", 0) > 0],
                key=lambda r: -r["rank_delta"],
            )[:15]
        ],
        "unknown_phase_detail": [
            {
                "ticker": r["ticker"],
                "current_rank": r["current_rank"],
                "v3_rank": r["v3_rank"],
                "rank_delta": r["rank_delta"],
                "current_tier": r["current_tier"],
            }
            for r in sorted(unknown_phase_tickers, key=lambda r: r["rank_delta"])
        ],
    }

    # Write outputs
    if output_dir is None:
        output_dir = PROJECT_ROOT / "data" / "research"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Governance table CSV
    gov_path = output_dir / "v3_governance_table.csv"
    fieldnames = [
        "ticker",
        "lead_phase",
        "current_rank",
        "v3_rank",
        "rank_delta",
        "current_tier",
        "v3_tier",
        "tier_delta",
        "old_phase_pts",
        "v3_phase_pts",
        "phase_delta_v3",
        "clinical_score",
        "v3_clinical_score",
        "m4_delta_v3",
        "composite_score",
        "v3_composite_score",
        "composite_delta_v3",
        "fallback_reason",
    ]
    with open(gov_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in sorted(eligible, key=lambda x: x.get("v3_rank", 999)):
            w.writerow(r)

    # JSON report
    json_path = output_dir / "v3_compare_report.json"
    json_path.write_text(json.dumps(result, indent=2, default=str) + "\n")

    # Markdown report
    md = _generate_md(result, gates, phase_summary)
    md_path = output_dir / "v3_compare_report.md"
    md_path.write_text(md)

    return result


def _generate_md(result, gates, phase_summary) -> str:
    lines = [
        "# V3 Phase Score Compare Report",
        "",
        f"**Snapshot**: {result['snapshot_date']}",
        f"**N ranked**: {result['n_ranked']}",
        f"**M5 clinical weight**: {result['m5_clinical_weight']}",
        f"**Max composite delta**: {result['max_composite_delta']}",
        "",
        "## Gate Results",
        "",
        f"**Overall: {gates['overall']}**",
        "",
        "### Hard Gates",
        "",
        "| Metric | Value | Threshold | Pass |",
        "|--------|-------|-----------|------|",
        f"| Top-60 overlap | {gates['top_60_overlap']}% | >= 90% | {'YES' if gates['top_60_overlap_pass'] else 'NO'} |",
        f"| Max rank shift | {gates['max_rank_shift']} | <= 30 | {'YES' if gates['max_rank_shift_pass'] else 'NO'} |",
        f"| Max rank shift (top-100) | {gates['max_rank_shift_top100']} | <= 30 | {'YES' if gates['max_rank_shift_top100_pass'] else 'NO'} |",
        f"| A-tier downgrades | {gates['a_downgrades']} | 0 | {'YES' if gates['a_downgrades_pass'] else 'NO'} |",
        "",
        "### Advisory",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Top-100 overlap | {gates['top_100_overlap']}% |",
        f"| Mean rank shift | {gates['mean_rank_shift']} |",
        f"| Median rank shift | {gates['median_rank_shift']} |",
        f"| A-tier upgrades | {gates['a_upgrades']} |",
        f"| B-tier big shifts (>5) | {gates['b_big_shifts']} |",
        f"| Unknown-phase tickers | {gates['unknown_phase_count']} (mean signed: {gates['unknown_phase_mean_signed']:+.1f}) |",
        "",
        "## Phase Cohort Impact",
        "",
        "| Phase | N | Phase Pts Delta | Mean |Shift| | Mean Signed |",
        "|-------|---|----------------|-----------|-------------|",
    ]
    for phase, s in sorted(phase_summary.items()):
        lines.append(
            f"| {phase} | {s['n']} | {s['phase_score_delta']:+.0f} | {s['mean_shift']} | {s['mean_signed']:+.2f} |"
        )

    lines += ["", "## A-Tier Downgrades", ""]
    if result["a_downgrades"]:
        lines += [
            "| Ticker | Phase | Rank | V3 Rank | Delta | Tier |",
            "|--------|-------|------|---------|-------|------|",
        ]
        for r in result["a_downgrades"]:
            lines.append(
                f"| {r['ticker']} | {r['lead_phase']} | {r['current_rank']} | {r['v3_rank']} | {r['rank_delta']:+d} | {r.get('tier_delta', '')} |"
            )
    else:
        lines.append("None.")

    lines += ["", "## A-Tier Upgrades", ""]
    if result["a_upgrades"]:
        lines += [
            "| Ticker | Phase | Rank | V3 Rank | Delta |",
            "|--------|-------|------|---------|-------|",
        ]
        for r in result["a_upgrades"]:
            lines.append(
                f"| {r['ticker']} | {r['lead_phase']} | {r['current_rank']} | {r['v3_rank']} | {r['rank_delta']:+d} |"
            )
    else:
        lines.append("None.")

    lines += ["", "## Largest Downward Movers (Top 15)", ""]
    movers = result.get("largest_downward_movers", [])
    if movers:
        lines += [
            "| Ticker | Phase | Tier | Rank | V3 Rank | Delta |",
            "|--------|-------|------|------|---------|-------|",
        ]
        for r in movers:
            lines.append(
                f"| {r['ticker']} | {r['lead_phase']} | {r['current_tier']} | {r['current_rank']} | {r['v3_rank']} | {r['rank_delta']:+d} |"
            )

    lines += ["", "## B-Tier Shifts > 5", ""]
    if result["b_big_shifts"]:
        lines += [
            "| Ticker | Phase | Rank | V3 Rank | Delta |",
            "|--------|-------|------|---------|-------|",
        ]
        for r in result["b_big_shifts"]:
            lines.append(
                f"| {r['ticker']} | {r['lead_phase']} | {r['current_rank']} | {r['v3_rank']} | {r['rank_delta']:+d} |"
            )
    else:
        lines.append("None.")

    # Unknown-phase isolation
    lines += ["", "## Unknown-Phase Tickers (Translation Artifact)", ""]
    unknowns = result.get("unknown_phase_detail", [])
    if unknowns:
        lines += [
            "These tickers have no lead_program_phase and receive zero penalty,",
            "gaining a relative boost as all penalized tickers drop around them.",
            "",
            "| Ticker | Tier | Rank | V3 Rank | Delta |",
            "|--------|------|------|---------|-------|",
        ]
        for r in unknowns:
            lines.append(
                f"| {r['ticker']} | {r['current_tier']} | {r['current_rank']} | {r['v3_rank']} | {r['rank_delta']:+d} |"
            )
    else:
        lines.append("None.")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare v3 phase score impact")
    parser.add_argument("--snapshot", type=Path, required=True, help="Path to snapshot directory")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    result = run_compare(args.snapshot, args.output_dir)

    gates = result.get("gates", {})
    print(f"\n=== V3 Phase Score Compare: {result.get('snapshot_date')} ===")
    print(f"Max composite delta: {result.get('max_composite_delta')}")
    print(f"Overall: {gates.get('overall')}")
    print("--- Hard gates ---")
    print(
        f"Top-60 overlap: {gates.get('top_60_overlap')}% (>= 90%: {'PASS' if gates.get('top_60_overlap_pass') else 'FAIL'})"
    )
    print(
        f"Max shift (all): {gates.get('max_rank_shift')} (<= 30: {'PASS' if gates.get('max_rank_shift_pass') else 'FAIL'})"
    )
    print(
        f"Max shift (top100): {gates.get('max_rank_shift_top100')} (<= 30: {'PASS' if gates.get('max_rank_shift_top100_pass') else 'FAIL'})"
    )
    print(
        f"A-tier downgrades: {gates.get('a_downgrades')} (= 0: {'PASS' if gates.get('a_downgrades_pass') else 'FAIL'})"
    )
    print("--- Advisory ---")
    print(f"Top-100 overlap: {gates.get('top_100_overlap')}%")
    print(f"Mean shift: {gates.get('mean_rank_shift')}")
    print(f"Median shift: {gates.get('median_rank_shift')}")
    print(f"B-tier big shifts: {gates.get('b_big_shifts')}")
    print(
        f"Unknown-phase: {gates.get('unknown_phase_count')} tickers (mean signed: {gates.get('unknown_phase_mean_signed', 0):+.1f})"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
