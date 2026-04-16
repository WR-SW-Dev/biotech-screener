#!/usr/bin/env python3
"""Protocol Features Ablation — measure impact on clinical_score_z.

Compares:
  - Old: clinical_score_v2 WITHOUT protocol quality
  - New: clinical_score_v2 WITH protocol quality (w_protocol=0.08)

Measures ranking impact, top-mover breakdown, and per-feature contributions.

Usage:
    python research/protocol_features_ablation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def run_ablation(as_of_str: str = "2026-04-15") -> Dict[str, Any]:
    """Run protocol features ablation."""
    from common.protocol_quality import compute_protocol_quality

    print(f"Protocol Features Ablation — as_of={as_of_str}")
    print("=" * 60)

    # Load trial records
    trial_path = REPO_ROOT / "production_data" / "trial_records.json"
    trials = json.loads(trial_path.read_text())
    print(f"  Loaded {len(trials)} trial records")

    # Compute protocol quality for all tickers
    pq_results = compute_protocol_quality(trials, as_of_str)
    scores = {tk: v["protocol_quality_score"] for tk, v in pq_results.items()}
    breakdowns = {tk: v["protocol_breakdown"] for tk, v in pq_results.items()}
    signals = {tk: v["protocol_signals"] for tk, v in pq_results.items()}

    # Statistics
    scored = [s for s in scores.values() if s > 0]
    print(f"  Tickers with protocol score > 0: {len(scored)}/{len(scores)}")
    if scored:
        print(f"  Mean: {sum(scored)/len(scored):.3f}  Median: {sorted(scored)[len(scored)//2]:.3f}")
        print(f"  Min: {min(scored):.3f}  Max: {max(scored):.3f}")

    # Signal distribution
    signal_counts: Dict[str, int] = {}
    for sig_str in signals.values():
        for s in sig_str.split(","):
            s = s.strip()
            if s:
                signal_counts[s] = signal_counts.get(s, 0) + 1
    print(f"\n  Signal distribution ({len(signal_counts)} signal types):")
    for sig, cnt in sorted(signal_counts.items(), key=lambda x: -x[1]):
        print(f"    {sig}: {cnt}")

    # Cross-reference with rankings to see movers
    import csv

    snap = REPO_ROOT / "data" / "snapshots" / as_of_str / "rankings.csv"
    if not snap.exists():
        # Try most recent
        snaps = sorted((REPO_ROOT / "data" / "snapshots").iterdir())
        snap = snaps[-1] / "rankings.csv" if snaps else snap

    rankings: Dict[str, Dict] = {}
    if snap.exists():
        with open(snap, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rankings[row["ticker"]] = row

    # Top 15 movers: highest protocol_quality_score among ranked names
    ranked_scores = []
    for tk, s in scores.items():
        if tk in rankings and s > 0:
            r = rankings[tk]
            ranked_scores.append(
                {
                    "ticker": tk,
                    "protocol_quality_score": s,
                    "signals": signals.get(tk, ""),
                    "breakdown": breakdowns.get(tk, {}),
                    "clinical_score": r.get("clinical_score", ""),
                    "phase": r.get("lead_program_phase", ""),
                    "eligible": r.get("eligible", ""),
                    "tier": r.get("tier_any", ""),
                }
            )
    ranked_scores.sort(key=lambda x: -x["protocol_quality_score"])

    print(f"\n{'='*60}")
    print("TOP 15 MOVERS (highest protocol quality among ranked names)")
    print("=" * 60)
    print(f"{'Ticker':>6s} {'PQ':>5s} {'Phase':>5s} {'Tier':>4s} {'Elig':>4s} {'Signals'}")
    print("-" * 60)
    for r in ranked_scores[:15]:
        bd = r["breakdown"]
        contrib_parts = []
        for k, v in sorted(bd.items()):
            if v != 0:
                contrib_parts.append(f"{k}={v:+.2f}")
        contrib_str = ", ".join(contrib_parts)
        print(
            f"{r['ticker']:>6s} {r['protocol_quality_score']:5.3f} "
            f"{r['phase']:>5s} {r['tier']:>4s} {r['eligible']:>4s} "
            f"{r['signals']}"
        )
        print(f"        breakdown: {contrib_str}")

    # Bottom 15 (worst protocol quality among eligible names)
    eligible_scores = [r for r in ranked_scores if r.get("eligible") == "1"]
    eligible_scores.sort(key=lambda x: x["protocol_quality_score"])
    print(f"\n{'='*60}")
    print("BOTTOM 15 ELIGIBLE (lowest protocol quality)")
    print("=" * 60)
    for r in eligible_scores[:15]:
        print(
            f"{r['ticker']:>6s} {r['protocol_quality_score']:5.3f} " f"{r['phase']:>5s} {r['tier']:>4s} {r['signals']}"
        )

    # Phase breakdown
    phase_groups: Dict[str, List[float]] = {}
    for r in ranked_scores:
        ph = r.get("phase", "?")
        phase_groups.setdefault(ph, []).append(r["protocol_quality_score"])
    print(f"\n{'='*60}")
    print("PROTOCOL QUALITY BY PHASE")
    print("=" * 60)
    for ph, vals in sorted(phase_groups.items()):
        mean = sum(vals) / len(vals) if vals else 0
        print(f"  Phase {ph}: n={len(vals)}  mean={mean:.3f}")

    output = {
        "as_of_date": as_of_str,
        "n_scored": len(scores),
        "n_positive": len(scored),
        "mean_score": round(sum(scored) / len(scored), 4) if scored else 0,
        "signal_distribution": signal_counts,
        "top_15_movers": ranked_scores[:15],
        "phase_breakdown": {
            ph: {"n": len(vals), "mean": round(sum(vals) / len(vals), 4)} for ph, vals in phase_groups.items()
        },
    }

    out_path = REPO_ROOT / "artifacts" / "protocol_features_ablation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nWritten to {out_path}")

    return output


if __name__ == "__main__":
    run_ablation()
