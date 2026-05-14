#!/usr/bin/env python3
"""Catalyst source validation report — quality metrics by source and precision.

Produces artifacts/catalyst_source_report.json with per-source accuracy,
precision distribution, confidence calibration, and CRT match rates.

Usage:
    python3 tools/build_catalyst_source_report.py
    python3 tools/build_catalyst_source_report.py --as-of-date 2026-04-10
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("catalyst_source_report")


def build_report(as_of_date: str) -> dict:
    from event_ev.loaders import load_catalyst_graph

    as_of = date.fromisoformat(as_of_date)
    graph = load_catalyst_graph(as_of, REPO_ROOT / "production_data", REPO_ROOT / "data")

    active = [n for n in graph.get_all_nodes(as_of) if not n.is_resolved()]

    # Load CRT resolutions
    resolutions = []
    res_dir = REPO_ROOT / "data" / "snapshots" / "resolutions"
    if res_dir.exists():
        for md in res_dir.iterdir():
            if not md.is_dir():
                continue
            for f in md.glob("*.json"):
                if f.name.startswith(("calibration", "manual", "watchlist")):
                    continue
                try:
                    r = json.loads(f.read_text())
                    if r.get("outcome") in ("HIT", "MISS", "MIXED"):
                        resolutions.append(r)
                except (json.JSONDecodeError, OSError):
                    pass

    # Build per-source stats
    by_source = defaultdict(
        lambda: {
            "total": 0,
            "by_precision": Counter(),
            "by_type": Counter(),
            "confidence_sum": 0.0,
            "matched": 0,
            "hit": 0,
            "miss": 0,
        }
    )

    for n in active:
        src = n.source
        by_source[src]["total"] += 1
        by_source[src]["by_precision"][n.date_precision] += 1
        by_source[src]["by_type"][n.event_type] += 1
        by_source[src]["confidence_sum"] += n.date_confidence

    # Match resolutions to nodes
    for res in resolutions:
        tk = res.get("ticker", "")
        cd = res.get("catalyst_date", "")
        outcome = res.get("outcome", "")
        if not (tk and cd):
            continue

        best_node = None
        best_gap = 999
        for n in graph.get_ticker_nodes(tk):
            if not n.expected_date:
                continue
            try:
                gap = abs((date.fromisoformat(n.expected_date) - date.fromisoformat(cd)).days)
                if gap < best_gap:
                    best_gap = gap
                    best_node = n
            except (ValueError, TypeError):
                pass

        if best_node and best_gap <= 30:
            src = best_node.source
            by_source[src]["matched"] += 1
            if outcome == "HIT":
                by_source[src]["hit"] += 1
            elif outcome == "MISS":
                by_source[src]["miss"] += 1

    # Build report
    sources = {}
    for src, stats in sorted(by_source.items(), key=lambda x: -x[1]["total"]):
        total = stats["total"]
        matched = stats["matched"]
        hit = stats["hit"]
        miss = stats["miss"]
        sources[src] = {
            "total_nodes": total,
            "avg_confidence": round(stats["confidence_sum"] / total, 4) if total else 0,
            "precision_distribution": dict(stats["by_precision"]),
            "event_type_distribution": dict(stats["by_type"].most_common(5)),
            "crt_matched": matched,
            "crt_hit": hit,
            "crt_miss": miss,
            "crt_hit_rate": round(hit / (hit + miss), 4) if hit + miss > 0 else None,
        }

    report = {
        "as_of_date": as_of_date,
        "total_active_nodes": len(active),
        "total_resolutions": len(resolutions),
        "sources": sources,
    }

    # Write
    out_path = REPO_ROOT / "artifacts" / "catalyst_source_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)

    # Print
    print(f"\n{'Source':25s} {'Nodes':>6s} {'Conf':>6s} {'Match':>6s} {'Hit%':>6s}")
    print("-" * 55)
    for src, s in sources.items():
        hit_pct = f"{100*s['crt_hit_rate']:.0f}%" if s["crt_hit_rate"] is not None else "—"
        print(f"{src:25s} {s['total_nodes']:6d} {s['avg_confidence']:6.3f} {s['crt_matched']:6d} {hit_pct:>6s}")

    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()
    build_report(args.as_of_date)


if __name__ == "__main__":
    main()
