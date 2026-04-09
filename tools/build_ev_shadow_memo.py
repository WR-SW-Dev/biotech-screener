#!/usr/bin/env python3
"""Daily Stage 1 shadow memo — 4 lines + EV coverage at cutoff.

Appends one entry per trading day to artifacts/event_ev/ev_shadow_memo.jsonl.
Designed to run after save_validation_snapshot produces rankings.csv and
after build_event_ev_scores.py produces the daily EV artifact.

Output per day:
  1. ties_at_cutoff: names within 0.001 of rank-30 score
  2. names_reordered: names that EV tiebreaker would swap
  3. top30_changed: whether any Top-30 membership changes
  4. ev_coverage_at_boundary: % of ranks 25-35 with EV data

Usage:
    python3 tools/build_ev_shadow_memo.py --as-of-date 2026-04-09
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ev_shadow_memo")

MEMO_PATH = REPO_ROOT / "artifacts" / "event_ev" / "ev_shadow_memo.jsonl"
SNAP_ROOT = REPO_ROOT / "data" / "snapshots"
EV_DIR = REPO_ROOT / "artifacts" / "event_ev"


def _safe_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def build_memo(as_of_date: str) -> dict:
    snap_dir = SNAP_ROOT / as_of_date
    csv_path = snap_dir / "rankings.csv"
    ev_path = EV_DIR / f"{as_of_date}_event_ev_scores.json"

    if not csv_path.exists():
        return {"date": as_of_date, "error": "no rankings.csv"}

    # Load rankings
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    eligible = [r for r in rows if r.get("eligible", "") in ("1", "True")]
    scored = []
    for r in eligible:
        fs = _safe_float(r.get("final_score", r.get("selector_score", "")))
        if fs is not None:
            scored.append(
                {
                    "ticker": r.get("ticker", ""),
                    "score": fs,
                    "straddle_price": r.get("straddle_price", "").strip(),
                }
            )
    scored.sort(key=lambda x: -x["score"])

    if len(scored) < 31:
        return {"date": as_of_date, "error": f"only {len(scored)} scored names"}

    # Load EV scores
    ev_lookup = {}
    if ev_path.exists():
        with open(ev_path) as f:
            ev_data = json.load(f)
        for e in ev_data.get("leaderboard", []):
            tk = e.get("ticker", "")
            ds = e.get("ds_adj_ev")
            if tk and ds is not None:
                ev_lookup[tk] = ds

    # 1. Ties at cutoff: names within 0.001 of rank-30 score
    rank30_score = scored[29]["score"]
    tied = [s["ticker"] for s in scored if abs(s["score"] - rank30_score) < 0.001]

    # 2. Names reordered by EV tiebreaker
    # Among tied names, would EV change the ordering?
    tied_with_ev = [(s["ticker"], ev_lookup.get(s["ticker"])) for s in scored if abs(s["score"] - rank30_score) < 0.001]
    # Current order (alphabetic tiebreak)
    current_order = [t for t, _ in tied_with_ev]
    # EV order (higher EV first, then alphabetic)
    ev_order = [t for t, _ in sorted(tied_with_ev, key=lambda x: (-(x[1] or -999), x[0]))]
    reordered = current_order != ev_order

    # 3. Top-30 change: would any name move in/out of Top-30?
    current_top30 = set(s["ticker"] for s in scored[:30])
    # Simulate EV tiebreaker: re-sort with (-score, -ev, ticker)
    ev_sorted = sorted(
        scored,
        key=lambda x: (-x["score"], -(ev_lookup.get(x["ticker"]) or -999), x["ticker"]),
    )
    ev_top30 = set(s["ticker"] for s in ev_sorted[:30])
    changed = current_top30 != ev_top30
    displaced = current_top30 - ev_top30
    promoted = ev_top30 - current_top30

    # 4. EV coverage at boundary (ranks 25-35)
    boundary = scored[24:35]
    boundary_with_ev = sum(1 for s in boundary if s["ticker"] in ev_lookup)
    boundary_with_opts = sum(1 for s in boundary if s["straddle_price"])

    gap_30_31 = scored[29]["score"] - scored[30]["score"]

    memo = {
        "date": as_of_date,
        "ties_at_cutoff": len(tied),
        "tied_names": tied,
        "gap_30_31": round(gap_30_31, 6),
        "names_reordered": reordered,
        "top30_changed": changed,
        "displaced": sorted(displaced) if displaced else [],
        "promoted": sorted(promoted) if promoted else [],
        "ev_coverage_boundary": f"{boundary_with_ev}/{len(boundary)}",
        "opts_coverage_boundary": f"{boundary_with_opts}/{len(boundary)}",
        "rank30": scored[29]["ticker"],
        "rank31": scored[30]["ticker"],
    }

    return memo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    memo = build_memo(args.as_of_date)

    # Append to ledger
    MEMO_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMO_PATH, "a") as f:
        f.write(json.dumps(memo, sort_keys=True, separators=(",", ":")) + "\n")

    # Print summary
    if "error" in memo:
        print(f"[{memo['date']}] ERROR: {memo['error']}")
        return

    print(f"[{memo['date']}] Stage 1 Shadow Memo:")
    print(f"  Ties at cutoff:     {memo['ties_at_cutoff']} names within 0.001")
    print(f"  Gap rank 30/31:     {memo['gap_30_31']:.4f} ({memo['rank30']} / {memo['rank31']})")
    print(f"  Names reordered:    {'YES' if memo['names_reordered'] else 'no'}")
    print(
        f"  Top-30 changed:     {'YES → ' + str(memo['promoted']) + ' in, ' + str(memo['displaced']) + ' out' if memo['top30_changed'] else 'no'}"
    )
    print(f"  EV coverage (25-35): {memo['ev_coverage_boundary']}")
    print(f"  Opts coverage (25-35): {memo['opts_coverage_boundary']}")


if __name__ == "__main__":
    main()
