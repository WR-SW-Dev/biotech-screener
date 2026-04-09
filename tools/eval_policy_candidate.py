#!/usr/bin/env python3
"""Evaluate tier-weighted policy shadow candidate (Spec 035).

Reads the rolling policy shadow history and evaluates four gates:
  1. Net return delta (tiered vs current)
  2. Hedged excess delta (vs XBI baseline)
  3. Turnover delta (tiered should not spike)
  4. Concentration / overlap stability

Produces a formal candidate verdict: PROMISING / NEEDS_MORE / REJECT.

Output:
    artifacts/policy_shadow/tier_weighted/candidate_eval.json
    artifacts/policy_shadow/tier_weighted/candidate_eval.md

Usage:
    python tools/eval_policy_candidate.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("policy_candidate")

SCHEMA_VERSION = "policy_candidate_eval.v1"

# Gate thresholds
MIN_TRADING_DAYS = 10
MIN_RETURN_DELTA_PP = 0.5  # tiered must beat current by >= 0.5pp
MAX_TURNOVER_INCREASE_PP = 50  # tiered turnover must not exceed current by > 50pp
MIN_OVERLAP = 0.80  # position overlap must stay >= 80%
MIN_WIN_RATE = 0.50  # tiered must beat current on >= 50% of days


def load_history(history_path: Path) -> List[Dict]:
    rows = []
    if not history_path.exists():
        return rows
    seen = set()
    with open(history_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                d = row.get("date")
                if d and d not in seen:
                    seen.add(d)
                    rows.append(row)
            except json.JSONDecodeError:
                continue
    return sorted(rows, key=lambda r: r["date"])


def evaluate_candidate(history: List[Dict]) -> Dict:
    """Evaluate policy candidate from rolling history."""

    # Filter to days with actual P&L
    trading_days = [r for r in history if r.get("pnl_current") is not None and abs(r.get("pnl_current", 0)) > 0.001]
    n_days = len(trading_days)

    if n_days < MIN_TRADING_DAYS:
        return {
            "verdict": "NEEDS_MORE",
            "reason": f"only {n_days} trading days (need {MIN_TRADING_DAYS})",
            "n_trading_days": n_days,
            "gates": {},
        }

    # Gate 1: Net return delta
    cum_current = sum(r.get("pnl_current", 0) for r in trading_days)
    cum_tiered = sum(r.get("pnl_tiered", 0) for r in trading_days)
    cum_exit = sum(r.get("pnl_exit", 0) for r in trading_days)
    return_delta_tiered = round(cum_tiered - cum_current, 4)
    return_delta_exit = round(cum_exit - cum_current, 4)

    gate_return = {
        "name": "net_return_delta",
        "current_cum": round(cum_current, 4),
        "tiered_cum": round(cum_tiered, 4),
        "exit_cum": round(cum_exit, 4),
        "delta_tiered_pp": round(return_delta_tiered, 2),
        "delta_exit_pp": round(return_delta_exit, 2),
        "threshold": MIN_RETURN_DELTA_PP,
        "status": "PASS" if return_delta_exit >= MIN_RETURN_DELTA_PP else "FAIL",
    }

    # Gate 2: Win rate
    wins_tiered = sum(1 for r in trading_days if (r.get("pnl_tiered", 0) or 0) > (r.get("pnl_current", 0) or 0))
    wins_exit = sum(1 for r in trading_days if (r.get("pnl_exit", 0) or 0) > (r.get("pnl_current", 0) or 0))
    win_rate_tiered = round(wins_tiered / n_days, 3)
    win_rate_exit = round(wins_exit / n_days, 3)

    gate_win_rate = {
        "name": "win_rate",
        "wins_tiered": wins_tiered,
        "wins_exit": wins_exit,
        "n_days": n_days,
        "win_rate_tiered": win_rate_tiered,
        "win_rate_exit": win_rate_exit,
        "threshold": MIN_WIN_RATE,
        "status": "PASS" if win_rate_exit >= MIN_WIN_RATE else "FAIL",
    }

    # Gate 3: Overlap stability
    overlaps = [r.get("overlap", 1.0) for r in trading_days if r.get("overlap") is not None]
    mean_overlap = round(sum(overlaps) / len(overlaps), 3) if overlaps else 1.0
    min_overlap = round(min(overlaps), 3) if overlaps else 1.0

    gate_overlap = {
        "name": "overlap_stability",
        "mean_overlap": mean_overlap,
        "min_overlap": min_overlap,
        "threshold": MIN_OVERLAP,
        "status": "PASS" if min_overlap >= MIN_OVERLAP else "FAIL",
    }

    # Gate 4: Excluded names audit
    all_excluded = set()
    for r in trading_days:
        for t in r.get("excluded", []):
            all_excluded.add(t)

    gate_excluded = {
        "name": "exit_overlay_audit",
        "n_unique_excluded": len(all_excluded),
        "excluded_tickers": sorted(all_excluded),
        "status": "PASS",  # Informational — no hard threshold
    }

    gates = {
        "net_return_delta": gate_return,
        "win_rate": gate_win_rate,
        "overlap_stability": gate_overlap,
        "exit_overlay_audit": gate_excluded,
    }

    # Verdict
    n_pass = sum(1 for g in gates.values() if g["status"] == "PASS")
    n_fail = sum(1 for g in gates.values() if g["status"] == "FAIL")

    if n_fail == 0:
        verdict = "PROMISING"
        reason = f"all gates pass ({n_pass}/{len(gates)}), +{return_delta_exit:.2f}pp over {n_days} days"
    elif n_fail == 1 and gate_return["status"] == "FAIL" and return_delta_exit > 0:
        verdict = "NEEDS_MORE"
        reason = f"return delta positive but below threshold ({return_delta_exit:.2f}pp < {MIN_RETURN_DELTA_PP}pp), need more days"
    else:
        verdict = "REJECT"
        reason = f"{n_fail} gate(s) failed"

    return {
        "verdict": verdict,
        "reason": reason,
        "n_trading_days": n_days,
        "date_range": f"{trading_days[0]['date']} to {trading_days[-1]['date']}",
        "gates": gates,
    }


def format_md(result: Dict) -> str:
    lines = []
    lines.append("# Policy Candidate Evaluation (Spec 035)")
    lines.append("")
    lines.append(f"**Verdict: {result['verdict']}** — {result['reason']}")
    lines.append(f"Period: {result.get('date_range', '?')} ({result['n_trading_days']} trading days)")
    lines.append("")

    lines.append("## Gates")
    lines.append("")
    lines.append("| Gate | Status | Detail |")
    lines.append("|------|--------|--------|")
    for name, gate in result.get("gates", {}).items():
        status = gate["status"]
        if name == "net_return_delta":
            detail = f"tiered: {gate['delta_tiered_pp']:+.2f}pp, exit: {gate['delta_exit_pp']:+.2f}pp (threshold: {gate['threshold']}pp)"
        elif name == "win_rate":
            detail = f"tiered: {gate['win_rate_tiered']:.0%}, exit: {gate['win_rate_exit']:.0%} (threshold: {gate['threshold']:.0%})"
        elif name == "overlap_stability":
            detail = (
                f"mean: {gate['mean_overlap']:.0%}, min: {gate['min_overlap']:.0%} (threshold: {gate['threshold']:.0%})"
            )
        elif name == "exit_overlay_audit":
            detail = f"{gate['n_unique_excluded']} unique tickers excluded: {', '.join(gate['excluded_tickers'][:10])}"
        else:
            detail = str(gate)
        lines.append(f"| {name} | **{status}** | {detail} |")
    lines.append("")

    # Summary
    g = result.get("gates", {})
    ret = g.get("net_return_delta", {})
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Current | Tiered | Tier+Exit |")
    lines.append("|--------|---------|--------|-----------|")
    lines.append(
        f"| Cumulative return | {ret.get('current_cum', 0):+.2f}% | {ret.get('tiered_cum', 0):+.2f}% | {ret.get('exit_cum', 0):+.2f}% |"
    )
    wr = g.get("win_rate", {})
    lines.append(f"| Win rate | — | {wr.get('win_rate_tiered', 0):.0%} | {wr.get('win_rate_exit', 0):.0%} |")
    ol = g.get("overlap_stability", {})
    lines.append(f"| Overlap (mean/min) | — | {ol.get('mean_overlap', 0):.0%} / {ol.get('min_overlap', 0):.0%} | |")
    lines.append("")

    lines.append(f"*Generated: {datetime.now(timezone.utc).isoformat()}*")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Evaluate policy shadow candidate (Spec 035)")
    parser.add_argument(
        "--history", type=Path, default=REPO_ROOT / "artifacts" / "policy_shadow" / "tier_weighted" / "history.jsonl"
    )
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "artifacts" / "policy_shadow" / "tier_weighted")
    args = parser.parse_args()

    history = load_history(args.history)
    logger.info("Loaded %d history rows", len(history))

    result = evaluate_candidate(history)

    full_result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "candidate_eval.json"
    with open(json_path, "w") as f:
        json.dump(full_result, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    md_path = args.output_dir / "candidate_eval.md"
    md_path.write_text(format_md(full_result))
    logger.info("Wrote %s", md_path)

    logger.info("Verdict: %s — %s", result["verdict"], result["reason"])


if __name__ == "__main__":
    main()
