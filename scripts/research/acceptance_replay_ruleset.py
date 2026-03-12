#!/usr/bin/env python3
"""Acceptance replay: compare active ruleset vs predecessor under live policy.

RESEARCH ONLY — does not change production behavior or rulesets.

Produces:
    output/research/ruleset_acceptance_{cand}_vs_{base}/ACCEPTANCE.json
    output/research/ruleset_acceptance_{cand}_vs_{base}/ACCEPTANCE.md

Sections:
  1. Snapshot-level ranking deltas (top-20/60 overlap, churn, tier transitions)
  2. Portfolio-level deltas under weekly policy (P&L, hedged, turnover)
  3. Risk rails deltas (gap-risk, concentration)
  4. Verdict: KEEP_ACTIVE vs ROLLBACK vs NEEDS_MORE
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from decision_engine import DecisionRuleset
from scripts.research.rerank_snapshots import rerank
from tools.live_shadow_portfolio import BUCKET_DISPLAY, BUCKET_NAMES, build_positions, compute_performance, load_policy

DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "snapshots"
DEFAULT_POLICY_PATH = PROJECT_ROOT / "production_data" / "portfolio_policy.json"
DEFAULT_PRICE_PATH = PROJECT_ROOT / "production_data" / "price_history.csv"

# Minimum columns for a snapshot to be usable
MIN_COLS = 50


# ---------------------------------------------------------------------------
# Ranking delta helpers
# ---------------------------------------------------------------------------


def top_k_tickers(rows: List[Dict[str, str]], k: int) -> List[str]:
    """Return tickers with actionable_rank 1..k, in rank order."""
    ranked = []
    for r in rows:
        ar = r.get("actionable_rank", "")
        if ar and ar.isdigit():
            ranked.append((int(ar), r.get("ticker", "")))
    ranked.sort()
    return [t for _, t in ranked[:k]]


def pct_overlap(a: List[str], b: List[str], k: int) -> float:
    """Fraction of top-k names in common (0..1)."""
    sa, sb = set(a[:k]), set(b[:k])
    if not sa:
        return 1.0
    return len(sa & sb) / k


def compute_rank_map(rows: List[Dict[str, str]]) -> Dict[str, int]:
    """Return {ticker: actionable_rank} for eligible rows."""
    result = {}
    for r in rows:
        ar = r.get("actionable_rank", "")
        if ar and ar.isdigit():
            result[r["ticker"]] = int(ar)
    return result


def compute_tier_counts(rows: List[Dict[str, str]], k: int) -> Dict[str, int]:
    """Count tier_dev values among top-k rows."""
    top = set(top_k_tickers(rows, k))
    counts: Dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}
    for r in rows:
        if r.get("ticker", "") in top:
            tier = r.get("tier_dev", r.get("tier_any", "")).upper()
            if tier and tier[0] in counts:
                counts[tier[0]] += 1
    return counts


def compute_ranking_delta_for_date(
    csv_path: Path,
    baseline_rs: DecisionRuleset,
    candidate_rs: DecisionRuleset,
    top_ks: List[int],
    candidate_pre_fn: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Rerank one snapshot with both rulesets and compute deltas.

    candidate_pre_fn: optional callable(rows, ruleset) -> rows that transforms
        candidate rows before reranking (e.g. sleeve-scoped neutralization).
    """
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        rows = list(reader)

    if len(cols) < MIN_COLS:
        return None

    rows_base = copy.deepcopy(rows)
    rows_cand = copy.deepcopy(rows)

    # Apply optional pre-processing to candidate arm (e.g. neutralization)
    if candidate_pre_fn is not None:
        rows_cand = candidate_pre_fn(rows_cand, candidate_rs)

    rerank(rows_base, baseline_rs)
    rerank(rows_cand, candidate_rs)

    result: Dict[str, Any] = {}

    # Per top-K metrics
    for k in top_ks:
        base_top = top_k_tickers(rows_base, k)
        cand_top = top_k_tickers(rows_cand, k)
        base_set = set(base_top)
        cand_set = set(cand_top)
        entering = sorted(cand_set - base_set)
        leaving = sorted(base_set - cand_set)

        result[f"top_{k}"] = {
            "pct_overlap": round(pct_overlap(base_top, cand_top, k), 4),
            "entering": entering,
            "leaving": leaving,
            "churn": len(entering),
        }

    # Rank changes for all common tickers
    base_ranks = compute_rank_map(rows_base)
    cand_ranks = compute_rank_map(rows_cand)
    common = set(base_ranks) & set(cand_ranks)
    rank_changes = []
    for t in common:
        delta = cand_ranks[t] - base_ranks[t]
        if delta != 0:
            rank_changes.append({"ticker": t, "base_rank": base_ranks[t], "cand_rank": cand_ranks[t], "delta": delta})
    rank_changes.sort(key=lambda x: x["delta"])

    max_up = min((rc["delta"] for rc in rank_changes), default=0)
    max_down = max((rc["delta"] for rc in rank_changes), default=0)

    result["rank_changes"] = {
        "n_changed": len(rank_changes),
        "n_common": len(common),
        "max_up": max_up,
        "max_down": max_down,
        "top_movers_up": rank_changes[:5],
        "top_movers_down": rank_changes[-5:][::-1] if rank_changes else [],
    }

    # Tier counts (top-20 portfolio)
    base_tiers = compute_tier_counts(rows_base, 20)
    cand_tiers = compute_tier_counts(rows_cand, 20)
    result["tier_counts"] = {
        "baseline": base_tiers,
        "candidate": cand_tiers,
        "delta_A": cand_tiers["A"] - base_tiers["A"],
    }

    # Return reranked rows for portfolio sim
    result["_rows_base"] = rows_base
    result["_rows_cand"] = rows_cand

    return result


def aggregate_ranking_deltas(by_date: Dict[str, Dict[str, Any]], top_ks: List[int]) -> Dict[str, Any]:
    """Aggregate ranking delta metrics across dates."""
    agg: Dict[str, Any] = {}
    dates = sorted(by_date.keys())

    for k in top_ks:
        key = f"top_{k}"
        overlaps = [by_date[d][key]["pct_overlap"] for d in dates if key in by_date[d]]
        churns = [by_date[d][key]["churn"] for d in dates if key in by_date[d]]
        if overlaps:
            agg[key] = {
                "mean_overlap": round(statistics.mean(overlaps), 4),
                "median_overlap": round(statistics.median(overlaps), 4),
                "min_overlap": round(min(overlaps), 4),
                "mean_churn": round(statistics.mean(churns), 2),
                "max_churn": max(churns),
            }

    # Tier A deltas
    tier_deltas = [by_date[d]["tier_counts"]["delta_A"] for d in dates if "tier_counts" in by_date[d]]
    if tier_deltas:
        agg["tier_A_delta"] = {
            "mean": round(statistics.mean(tier_deltas), 2),
            "median": round(statistics.median(tier_deltas), 2),
            "max_abs": max(abs(d) for d in tier_deltas),
        }

    # Rank change distribution
    n_changed_list = [by_date[d]["rank_changes"]["n_changed"] for d in dates if "rank_changes" in by_date[d]]
    n_common_list = [by_date[d]["rank_changes"]["n_common"] for d in dates if "rank_changes" in by_date[d]]
    if n_changed_list and n_common_list:
        churn_pcts = [c / t * 100 if t > 0 else 0 for c, t in zip(n_changed_list, n_common_list)]
        agg["rank_churn"] = {
            "mean_pct": round(statistics.mean(churn_pcts), 2),
            "median_pct": round(statistics.median(churn_pcts), 2),
        }

    # Collect persistent entrants/exits across dates
    for k in top_ks:
        key = f"top_{k}"
        enter_counts: Dict[str, int] = {}
        exit_counts: Dict[str, int] = {}
        for d in dates:
            if key not in by_date[d]:
                continue
            for t in by_date[d][key]["entering"]:
                enter_counts[t] = enter_counts.get(t, 0) + 1
            for t in by_date[d][key]["leaving"]:
                exit_counts[t] = exit_counts.get(t, 0) + 1
        agg[f"{key}_persistent_entrants"] = sorted(enter_counts.items(), key=lambda x: -x[1])[:10]
        agg[f"{key}_persistent_exits"] = sorted(exit_counts.items(), key=lambda x: -x[1])[:10]

    return agg


# ---------------------------------------------------------------------------
# Weekly policy simulation
# ---------------------------------------------------------------------------


def simulate_weekly_policy(
    dates: List[str],
    by_date: Dict[str, Dict[str, Any]],
    policy: Dict[str, Any],
    price_path: Path,
) -> Dict[str, Any]:
    """Run weekly-cadence portfolio sim for both arms using reranked rows.

    Returns comparison metrics: cumulative P&L, hedged delta, turnover, bucket attribution.
    """
    base_positions_prev: Optional[List[Dict[str, Any]]] = None
    cand_positions_prev: Optional[List[Dict[str, Any]]] = None
    base_date_prev: Optional[str] = None
    cand_date_prev: Optional[str] = None

    base_weekly: List[Dict[str, Any]] = []
    cand_weekly: List[Dict[str, Any]] = []

    for date in dates:
        dd = by_date.get(date)
        if dd is None:
            continue

        rows_base = dd.get("_rows_base")
        rows_cand = dd.get("_rows_cand")
        if rows_base is None or rows_cand is None:
            continue

        # Build positions from reranked rows
        base_pos_data = build_positions(rows_base, policy)
        cand_pos_data = build_positions(rows_cand, policy)

        base_positions = base_pos_data["positions"]
        cand_positions = cand_pos_data["positions"]

        # Compute performance vs prior if we have prior positions
        base_perf = None
        cand_perf = None

        if base_positions_prev is not None and base_date_prev is not None:
            try:
                base_perf = compute_performance(
                    base_positions_prev,
                    base_positions,
                    base_date_prev,
                    date,
                    price_path,
                )
            except Exception:
                pass

        if cand_positions_prev is not None and cand_date_prev is not None:
            try:
                cand_perf = compute_performance(
                    cand_positions_prev,
                    cand_positions,
                    cand_date_prev,
                    date,
                    price_path,
                )
            except Exception:
                pass

        if base_perf is not None:
            base_weekly.append({"date": date, "perf": base_perf, "positions": base_positions})
        if cand_perf is not None:
            cand_weekly.append({"date": date, "perf": cand_perf, "positions": cand_positions})

        base_positions_prev = base_positions
        cand_positions_prev = cand_positions
        base_date_prev = date
        cand_date_prev = date

    return _compare_weekly_results(base_weekly, cand_weekly)


def _compare_weekly_results(
    base_weekly: List[Dict[str, Any]],
    cand_weekly: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare two arms' weekly performance results."""
    result: Dict[str, Any] = {"n_weeks": len(cand_weekly)}

    if not base_weekly or not cand_weekly:
        result["error"] = "insufficient data for comparison"
        return result

    # Cumulative P&L (guard None)
    base_cum = sum(w["perf"].get("pnl_pct") or 0 for w in base_weekly)
    cand_cum = sum(w["perf"].get("pnl_pct") or 0 for w in cand_weekly)
    result["baseline_cumulative_pnl_pct"] = round(base_cum, 4)
    result["candidate_cumulative_pnl_pct"] = round(cand_cum, 4)
    result["cumulative_hedged_delta_pp"] = round(cand_cum - base_cum, 4)

    # Mean weekly hedged delta
    deltas = []
    for bw, cw in zip(base_weekly, cand_weekly):
        if bw["date"] == cw["date"]:
            deltas.append((cw["perf"].get("pnl_pct") or 0) - (bw["perf"].get("pnl_pct") or 0))
    result["mean_weekly_hedged_delta_pp"] = round(statistics.mean(deltas), 4) if deltas else 0.0

    # Turnover (guard None)
    base_turnovers = [w["perf"].get("name_turnover_pct") or 0 for w in base_weekly]
    cand_turnovers = [w["perf"].get("name_turnover_pct") or 0 for w in cand_weekly]
    base_mean_turn = statistics.mean(base_turnovers) if base_turnovers else 0
    cand_mean_turn = statistics.mean(cand_turnovers) if cand_turnovers else 0
    result["baseline_mean_turnover_pct"] = round(base_mean_turn, 2)
    result["candidate_mean_turnover_pct"] = round(cand_mean_turn, 2)
    result["turnover_delta_pp"] = round(cand_mean_turn - base_mean_turn, 2)

    # Bucket attribution deltas
    bucket_deltas: Dict[str, Dict[str, float]] = {}
    for b in BUCKET_NAMES:
        base_sleeve = [(w["perf"].get("sleeve_attribution") or {}).get(b, {}).get("return_pct", 0) for w in base_weekly]
        cand_sleeve = [(w["perf"].get("sleeve_attribution") or {}).get(b, {}).get("return_pct", 0) for w in cand_weekly]
        base_mean = statistics.mean(base_sleeve) if base_sleeve else 0
        cand_mean = statistics.mean(cand_sleeve) if cand_sleeve else 0
        bucket_deltas[b] = {
            "baseline_mean_pct": round(base_mean, 4),
            "candidate_mean_pct": round(cand_mean, 4),
            "delta_pp": round(cand_mean - base_mean, 4),
        }
    result["bucket_attribution"] = bucket_deltas

    # XBI excess (guard None values)
    base_excess = [w["perf"].get("excess_vs_xbi_pct") or 0 for w in base_weekly]
    cand_excess = [w["perf"].get("excess_vs_xbi_pct") or 0 for w in cand_weekly]
    result["baseline_mean_excess_pct"] = round(statistics.mean(base_excess), 4) if base_excess else 0
    result["candidate_mean_excess_pct"] = round(statistics.mean(cand_excess), 4) if cand_excess else 0

    # Gap-risk concentration (positions with gap_risk == "HIGH")
    gap_risk_deltas = []
    for bw, cw in zip(base_weekly, cand_weekly):
        if bw["date"] != cw["date"]:
            continue
        b_gap = sum(p.get("weight_pct", 0) for p in bw["positions"] if p.get("gap_risk") == "HIGH")
        c_gap = sum(p.get("weight_pct", 0) for p in cw["positions"] if p.get("gap_risk") == "HIGH")
        gap_risk_deltas.append(c_gap - b_gap)
    result["gap_risk_high_weight_delta_pp"] = round(statistics.mean(gap_risk_deltas), 2) if gap_risk_deltas else 0.0

    # Position overlap on each date
    overlaps = []
    for bw, cw in zip(base_weekly, cand_weekly):
        if bw["date"] != cw["date"]:
            continue
        bt = {p["ticker"] for p in bw["positions"]}
        ct = {p["ticker"] for p in cw["positions"]}
        if bt | ct:
            overlaps.append(len(bt & ct) / len(bt | ct))
    result["mean_position_overlap"] = round(statistics.mean(overlaps), 4) if overlaps else 0.0

    # Composition drivers: names consistently in one arm but not the other
    enter_counts: Dict[str, int] = {}
    exit_counts: Dict[str, int] = {}
    for bw, cw in zip(base_weekly, cand_weekly):
        if bw["date"] != cw["date"]:
            continue
        bt = {p["ticker"] for p in bw["positions"]}
        ct = {p["ticker"] for p in cw["positions"]}
        for t in ct - bt:
            enter_counts[t] = enter_counts.get(t, 0) + 1
        for t in bt - ct:
            exit_counts[t] = exit_counts.get(t, 0) + 1

    result["composition_drivers"] = {
        "candidate_only": sorted(enter_counts.items(), key=lambda x: -x[1])[:10],
        "baseline_only": sorted(exit_counts.items(), key=lambda x: -x[1])[:10],
    }

    return result


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

# Ranking stability guardrails
THRESHOLD_TOP20_OVERLAP_MEDIAN = 0.70
THRESHOLD_TOP60_OVERLAP_MEDIAN = 0.80
THRESHOLD_TIER_A_DELTA_MEDIAN = 2

# Weekly execution primary
THRESHOLD_CUMULATIVE_HEDGED_DELTA_PP = 0.20
THRESHOLD_MEAN_WEEKLY_HEDGED_DELTA_PP = -0.05
THRESHOLD_TURNOVER_DELTA_PP = 0.25
THRESHOLD_GAP_RISK_DELTA_PP = 5.0


def compute_verdict(
    ranking_agg: Dict[str, Any],
    weekly_sim: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply decision thresholds and return verdict."""
    checks: List[Dict[str, Any]] = []
    any_fail = False

    # Ranking stability
    top20 = ranking_agg.get("top_20", {})
    top60 = ranking_agg.get("top_60", {})
    tier_a = ranking_agg.get("tier_A_delta", {})

    top20_med = top20.get("median_overlap", 0)
    checks.append(
        {
            "name": "top-20 overlap median",
            "value": top20_med,
            "threshold": f">= {THRESHOLD_TOP20_OVERLAP_MEDIAN}",
            "status": "PASS" if top20_med >= THRESHOLD_TOP20_OVERLAP_MEDIAN else "FAIL",
        }
    )
    if top20_med < THRESHOLD_TOP20_OVERLAP_MEDIAN:
        any_fail = True

    top60_med = top60.get("median_overlap", 0)
    checks.append(
        {
            "name": "top-60 overlap median",
            "value": top60_med,
            "threshold": f">= {THRESHOLD_TOP60_OVERLAP_MEDIAN}",
            "status": "PASS" if top60_med >= THRESHOLD_TOP60_OVERLAP_MEDIAN else "FAIL",
        }
    )
    if top60_med < THRESHOLD_TOP60_OVERLAP_MEDIAN:
        any_fail = True

    tier_a_med = abs(tier_a.get("median", 0))
    checks.append(
        {
            "name": "tier-A count delta median",
            "value": tier_a_med,
            "threshold": f"<= {THRESHOLD_TIER_A_DELTA_MEDIAN}",
            "status": "PASS" if tier_a_med <= THRESHOLD_TIER_A_DELTA_MEDIAN else "FAIL",
        }
    )
    if tier_a_med > THRESHOLD_TIER_A_DELTA_MEDIAN:
        any_fail = True

    # Weekly execution primary
    cum_delta = weekly_sim.get("cumulative_hedged_delta_pp", 0)
    checks.append(
        {
            "name": "cumulative hedged delta",
            "value": cum_delta,
            "threshold": f">= {THRESHOLD_CUMULATIVE_HEDGED_DELTA_PP}pp",
            "status": "PASS" if cum_delta >= THRESHOLD_CUMULATIVE_HEDGED_DELTA_PP else "FAIL",
        }
    )
    exec_fail = cum_delta < THRESHOLD_CUMULATIVE_HEDGED_DELTA_PP

    mean_delta = weekly_sim.get("mean_weekly_hedged_delta_pp", 0)
    checks.append(
        {
            "name": "mean weekly hedged delta",
            "value": mean_delta,
            "threshold": f">= {THRESHOLD_MEAN_WEEKLY_HEDGED_DELTA_PP}pp",
            "status": "PASS" if mean_delta >= THRESHOLD_MEAN_WEEKLY_HEDGED_DELTA_PP else "FAIL",
        }
    )
    if mean_delta < THRESHOLD_MEAN_WEEKLY_HEDGED_DELTA_PP:
        exec_fail = True

    turn_delta = weekly_sim.get("turnover_delta_pp", 0)
    checks.append(
        {
            "name": "turnover delta",
            "value": turn_delta,
            "threshold": f"<= {THRESHOLD_TURNOVER_DELTA_PP}pp",
            "status": "PASS" if turn_delta <= THRESHOLD_TURNOVER_DELTA_PP else "FAIL",
        }
    )
    if turn_delta > THRESHOLD_TURNOVER_DELTA_PP:
        exec_fail = True

    gap_delta = weekly_sim.get("gap_risk_high_weight_delta_pp", 0)
    checks.append(
        {
            "name": "gap-risk (<=7d) weight delta",
            "value": gap_delta,
            "threshold": f"<= {THRESHOLD_GAP_RISK_DELTA_PP}pp",
            "status": "PASS" if gap_delta <= THRESHOLD_GAP_RISK_DELTA_PP else "WARN",
        }
    )
    # Verdict
    all_stability_ok = all(c["status"] == "PASS" for c in checks[:3])
    all_exec_ok = not exec_fail

    if exec_fail and any_fail:
        verdict = "ROLLBACK"
        reason = "Weekly execution guardrail(s) FAILED and ranking stability violated"
    elif exec_fail:
        verdict = "ROLLBACK"
        reason = "Weekly execution guardrail(s) FAILED"
    elif all_exec_ok and all_stability_ok:
        verdict = "KEEP_ACTIVE"
        reason = "All primary and stability checks PASS"
    else:
        verdict = "NEEDS_MORE"
        reason = "Some stability guardrails failed but execution checks pass"

    # Explicit recommendation even for NEEDS_MORE
    recommendation = "keep" if cum_delta >= 0 else "rollback"

    return {
        "verdict": verdict,
        "reason": reason,
        "recommendation": recommendation,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Date-set hash (deterministic)
# ---------------------------------------------------------------------------


def date_set_hash(dates: List[str]) -> str:
    """SHA-256 of sorted date list for reproducibility."""
    content = "\n".join(sorted(dates))
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_dates(
    snapshot_root: Path,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[str]:
    """Find valid YYYY-MM-DD snapshot dirs with rankings.csv."""
    if not snapshot_root.is_dir():
        return []
    dates = []
    for d in snapshot_root.iterdir():
        if not d.is_dir() or len(d.name) != 10 or d.name[4] != "-":
            continue
        if not (d / "rankings.csv").is_file():
            continue
        if date_from and d.name < date_from:
            continue
        if date_to and d.name > date_to:
            continue
        dates.append(d.name)
    dates.sort()
    return dates


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_acceptance_md(packet: Dict[str, Any]) -> str:
    """Render ACCEPTANCE.md from packet."""
    lines: List[str] = []
    v = packet["verdict_result"]
    verdict = v["verdict"]
    reason = v["reason"]

    lines.append(f"# Acceptance Replay: {packet['candidate_id']} vs {packet['baseline_id']}")
    lines.append("")
    lines.append(f"**Verdict: {verdict}**")
    lines.append(f"**Reason**: {reason}")
    if v.get("recommendation"):
        lines.append(f"**Recommendation**: {v['recommendation']}")
    lines.append("")
    lines.append(f"- Candidate: `{packet['candidate_id']}` ({packet.get('candidate_file', '')})")
    lines.append(f"- Baseline: `{packet['baseline_id']}` ({packet.get('baseline_file', '')})")
    lines.append(f"- Dates: {packet['n_dates']} snapshots ({packet['date_from']} → {packet['date_to']})")
    lines.append(f"- Date-set hash: `{packet['date_set_hash']}`")
    lines.append(f"- Generated: {packet['generated_at']}")
    lines.append("")

    # Threshold checks
    lines.append("## Decision Thresholds")
    lines.append("")
    lines.append("| Check | Value | Threshold | Status |")
    lines.append("|-------|-------|-----------|--------|")
    for c in v["checks"]:
        val = c["value"]
        if isinstance(val, float):
            val_str = f"{val:.4f}"
        else:
            val_str = str(val)
        lines.append(f"| {c['name']} | {val_str} | {c['threshold']} | **{c['status']}** |")
    lines.append("")

    # Ranking deltas
    ra = packet.get("ranking_aggregate", {})
    lines.append("## Ranking Deltas")
    lines.append("")
    lines.append("| Metric | Top-20 | Top-60 |")
    lines.append("|--------|--------|--------|")
    t20 = ra.get("top_20", {})
    t60 = ra.get("top_60", {})
    lines.append(f"| Mean overlap | {t20.get('mean_overlap', 0):.4f} | {t60.get('mean_overlap', 0):.4f} |")
    lines.append(f"| Median overlap | {t20.get('median_overlap', 0):.4f} | {t60.get('median_overlap', 0):.4f} |")
    lines.append(f"| Min overlap | {t20.get('min_overlap', 0):.4f} | {t60.get('min_overlap', 0):.4f} |")
    lines.append(f"| Mean churn | {t20.get('mean_churn', 0):.1f} | {t60.get('mean_churn', 0):.1f} |")
    lines.append(f"| Max churn | {t20.get('max_churn', 0)} | {t60.get('max_churn', 0)} |")
    lines.append("")

    rc = ra.get("rank_churn", {})
    if rc:
        lines.append(
            f"- Rank churn (all tickers): mean {rc.get('mean_pct', 0):.1f}%, median {rc.get('median_pct', 0):.1f}%"
        )

    ta = ra.get("tier_A_delta", {})
    if ta:
        lines.append(
            f"- Tier-A count delta: mean {ta.get('mean', 0):.1f}, median {ta.get('median', 0):.1f}, max |{ta.get('max_abs', 0)}|"
        )
    lines.append("")

    # Persistent name changes
    for k in [20, 60]:
        entrants = ra.get(f"top_{k}_persistent_entrants", [])
        exits = ra.get(f"top_{k}_persistent_exits", [])
        if entrants or exits:
            lines.append(f"### Top-{k} Persistent Name Changes")
            lines.append("")
            if entrants:
                lines.append("**Entering candidate (not in baseline):**")
                for t, c in entrants[:5]:
                    lines.append(f"- +{t}: {c} dates")
            if exits:
                lines.append("**Leaving candidate (in baseline only):**")
                for t, c in exits[:5]:
                    lines.append(f"- -{t}: {c} dates")
            lines.append("")

    # Weekly sim
    ws = packet.get("weekly_sim", {})
    lines.append("## Weekly Policy Simulation")
    lines.append("")
    lines.append(f"- Weeks simulated: {ws.get('n_weeks', 0)}")
    lines.append(f"- Baseline cumulative P&L: {ws.get('baseline_cumulative_pnl_pct', 0):+.4f}%")
    lines.append(f"- Candidate cumulative P&L: {ws.get('candidate_cumulative_pnl_pct', 0):+.4f}%")
    lines.append(f"- **Cumulative hedged delta: {ws.get('cumulative_hedged_delta_pp', 0):+.4f}pp**")
    lines.append(f"- Mean weekly hedged delta: {ws.get('mean_weekly_hedged_delta_pp', 0):+.4f}pp")
    lines.append(f"- Turnover delta: {ws.get('turnover_delta_pp', 0):+.2f}pp")
    lines.append(f"- Gap-risk HIGH weight delta: {ws.get('gap_risk_high_weight_delta_pp', 0):+.2f}pp")
    lines.append(f"- Mean position overlap: {ws.get('mean_position_overlap', 0):.4f}")
    lines.append("")

    # Bucket attribution
    ba = ws.get("bucket_attribution", {})
    if ba:
        lines.append("### Bucket Attribution Deltas")
        lines.append("")
        lines.append("| Bucket | Baseline | Candidate | Delta |")
        lines.append("|--------|----------|-----------|-------|")
        for b in BUCKET_NAMES:
            bd = ba.get(b, {})
            label = BUCKET_DISPLAY.get(b, b)
            lines.append(
                f"| {label}"
                f" | {bd.get('baseline_mean_pct', 0):+.4f}%"
                f" | {bd.get('candidate_mean_pct', 0):+.4f}%"
                f" | {bd.get('delta_pp', 0):+.4f}pp |"
            )
        lines.append("")

    # Composition drivers
    cd = ws.get("composition_drivers", {})
    cand_only = cd.get("candidate_only", [])
    base_only = cd.get("baseline_only", [])
    if cand_only or base_only:
        lines.append("### Composition Drivers (Top 10)")
        lines.append("")
        if cand_only:
            lines.append("**Candidate-only names:**")
            for t, c in cand_only[:10]:
                lines.append(f"- {t}: {c} weeks")
        if base_only:
            lines.append("")
            lines.append("**Baseline-only names:**")
            for t, c in base_only[:10]:
                lines.append(f"- {t}: {c} weeks")
        lines.append("")

    # Final verdict
    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**{verdict}**: {reason}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_acceptance_replay(
    candidate_ruleset_path: Path,
    baseline_ruleset_path: Path,
    *,
    snapshot_root: Path = DEFAULT_SNAPSHOT_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    price_path: Path = DEFAULT_PRICE_PATH,
    out_dir: Optional[Path] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    top_ks: Optional[List[int]] = None,
    candidate_pre_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run the full acceptance replay."""
    if top_ks is None:
        top_ks = [20, 60]

    candidate_rs = DecisionRuleset.from_json(str(candidate_ruleset_path))
    baseline_rs = DecisionRuleset.from_json(str(baseline_ruleset_path))

    cand_id = candidate_rs.ruleset_id
    base_id = baseline_rs.ruleset_id

    print(f"Candidate: {cand_id} ({candidate_ruleset_path.name})")
    print(f"Baseline:  {base_id} ({baseline_ruleset_path.name})")

    policy = load_policy(policy_path)

    # Discover dates
    dates = discover_dates(snapshot_root, date_from, date_to)
    print(f"Dates: {len(dates)} snapshots ({dates[0] if dates else '?'} → {dates[-1] if dates else '?'})")

    if not dates:
        return {"error": "no snapshot dates found"}

    # Step 1: Ranking deltas
    print("\n--- Ranking Deltas ---")
    by_date: Dict[str, Dict[str, Any]] = {}
    n_skip = 0
    for date in dates:
        csv_path = snapshot_root / date / "rankings.csv"
        result = compute_ranking_delta_for_date(csv_path, baseline_rs, candidate_rs, top_ks, candidate_pre_fn)
        if result is None:
            n_skip += 1
            continue
        by_date[date] = result

    valid_dates = sorted(by_date.keys())
    print(f"  {len(valid_dates)} dates compared, {n_skip} skipped")

    ranking_agg = aggregate_ranking_deltas(by_date, top_ks)

    # Step 2: Weekly policy simulation
    print("\n--- Weekly Policy Simulation ---")
    weekly_sim = simulate_weekly_policy(valid_dates, by_date, policy, price_path)
    print(f"  {weekly_sim.get('n_weeks', 0)} weeks simulated")
    print(f"  Hedged delta: {weekly_sim.get('cumulative_hedged_delta_pp', 0):+.4f}pp")

    # Step 3: Verdict
    # Strip internal data before verdict
    by_date_clean = {}
    for d in by_date:
        by_date_clean[d] = {k: v for k, v in by_date[d].items() if not k.startswith("_")}

    verdict_result = compute_verdict(ranking_agg, weekly_sim)
    print(f"\n  Verdict: {verdict_result['verdict']} — {verdict_result['reason']}")

    # Build packet
    packet = {
        "schema": "acceptance_replay.v1",
        "candidate_id": cand_id,
        "candidate_file": candidate_ruleset_path.name,
        "baseline_id": base_id,
        "baseline_file": baseline_ruleset_path.name,
        "date_from": valid_dates[0] if valid_dates else "",
        "date_to": valid_dates[-1] if valid_dates else "",
        "n_dates": len(valid_dates),
        "date_set_hash": date_set_hash(valid_dates),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ranking_aggregate": ranking_agg,
        "weekly_sim": weekly_sim,
        "verdict_result": verdict_result,
        "by_date_ranking": by_date_clean,
    }

    # Write output
    if out_dir is None:
        out_dir = PROJECT_ROOT / "output" / "research" / f"ruleset_acceptance_{cand_id}_vs_{base_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "ACCEPTANCE.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, default=str)

    md_path = out_dir / "ACCEPTANCE.md"
    md_content = render_acceptance_md(packet)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\nWritten: {json_path}")
    print(f"Written: {md_path}")

    return packet


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Acceptance replay: compare active ruleset vs predecessor under live policy"
    )
    parser.add_argument("--candidate-ruleset", type=Path, required=True)
    parser.add_argument("--baseline-ruleset", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--price-csv", type=Path, default=DEFAULT_PRICE_PATH)
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument("--top-ks", type=str, default="20,60")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--candidate-neutralize-sleeve",
        choices=["core", "binary"],
        default=None,
        help="Apply exposure neutralization to candidate arm for this sleeve only",
    )
    parser.add_argument(
        "--neutralize-exposures",
        type=str,
        default="beta,drawdown,vol,mcap",
        help="Comma-separated exposures for sleeve neutralization",
    )
    args = parser.parse_args()

    top_ks = [int(x.strip()) for x in args.top_ks.split(",")]

    # Build candidate pre-processing function for sleeve neutralization
    candidate_pre_fn = None
    if args.candidate_neutralize_sleeve:
        from scripts.research.run_alpha_experiment import neutralize_exposures
        from tools.build_action_lists import classify_action_bucket
        from tools.live_shadow_portfolio import SLEEVE_MAP

        neut_sleeve = args.candidate_neutralize_sleeve
        neut_exposures = [e.strip() for e in args.neutralize_exposures.split(",")]

        def _neutralize_sleeve(rows, ruleset):
            """Neutralize exposures for rows in the target sleeve only."""
            from common.ranking_utils import backfill_columns

            backfill_columns(rows)

            # Split rows by sleeve membership
            sleeve_indices = []
            for i, r in enumerate(rows):
                bucket = classify_action_bucket(r)
                if SLEEVE_MAP.get(bucket, "core") == neut_sleeve:
                    sleeve_indices.append(i)

            if not sleeve_indices:
                return rows

            # Extract sleeve rows, neutralize, then put back
            sleeve_rows = [rows[i] for i in sleeve_indices]
            sleeve_rows, _r2, _coeffs = neutralize_exposures(
                sleeve_rows,
                neut_exposures,
                ruleset,
            )

            for idx, orig_i in enumerate(sleeve_indices):
                rows[orig_i] = sleeve_rows[idx]

            return rows

        candidate_pre_fn = _neutralize_sleeve
        print(f"Sleeve neutralization: {neut_sleeve} with {neut_exposures}")

    run_acceptance_replay(
        args.candidate_ruleset,
        args.baseline_ruleset,
        snapshot_root=args.snapshot_root,
        policy_path=args.policy,
        price_path=args.price_csv,
        out_dir=args.out_dir,
        date_from=args.date_from,
        date_to=args.date_to,
        top_ks=top_ks,
        candidate_pre_fn=candidate_pre_fn,
    )


if __name__ == "__main__":
    main()
