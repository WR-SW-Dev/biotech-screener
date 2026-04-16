#!/usr/bin/env python3
"""Clinical Transmission Shadow — forward validation of clinical stack v2.

Captures old-default vs transmission-enabled rankings side by side,
logs the divergence, and sets up monitoring fields so realized outcomes
can be compared prospectively.

Designed to run daily alongside production (Step 5k after EV scoring).
Appends to a JSONL ledger for time-series comparison.

Usage:
    python tools/clinical_transmission_shadow.py
    python tools/clinical_transmission_shadow.py --as-of 2026-04-16
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("clinical_shadow")

LEDGER_PATH = REPO_ROOT / "artifacts" / "clinical_transmission_shadow.jsonl"
SNAPSHOT_DIR = REPO_ROOT / "artifacts" / "clinical_shadow_snapshots"


def _run_variant(
    trials: list,
    as_of: date,
    inject_clinical: bool,
) -> List[Dict[str, Any]]:
    """Run EV scoring with or without clinical transmission."""
    from event_ev.ev_calculator import EventEVCalculator
    from event_ev.loaders import load_catalyst_graph, load_market_features, split_context_features
    from event_ev.outcome_model import OutcomeModel

    prod = REPO_ROOT / "production_data"
    data = REPO_ROOT / "data"

    graph = load_catalyst_graph(as_of, prod, data)
    mf = load_market_features(as_of, data / "snapshots")
    cf = split_context_features(mf)

    if inject_clinical:
        from common.biomarker_context import compute_biomarker_context_score
        from common.endpoint_quality import compute_endpoint_quality
        from common.protocol_quality import compute_protocol_quality

        pq = compute_protocol_quality(trials, str(as_of))
        bm = compute_biomarker_context_score(trials, str(as_of), protocol_quality=pq)
        ep = compute_endpoint_quality(trials, str(as_of))
        for tk in cf:
            if tk in pq:
                cf[tk]["protocol_quality_score"] = pq[tk]["protocol_quality_score"]
            if tk in bm:
                cf[tk]["biomarker_context_score"] = bm[tk]["biomarker_context_score"]
            if tk in ep:
                cf[tk]["endpoint_quality_score"] = ep[tk]["endpoint_quality_score"]

    calc = EventEVCalculator(as_of_date=as_of, outcome_model=OutcomeModel(), max_days=180, min_days=0)
    results = calc.run_from_graph(graph, market_features=mf, context_features=cf)

    rows = []
    for rank, ev in enumerate(results, 1):
        tx = ev.outcome.features_used.get("clinical_transmission", {})
        rows.append(
            {
                "rank": rank,
                "ticker": ev.node.ticker,
                "event_type": ev.node.event_type,
                "phase": ev.node.phase,
                "p_hit": round(ev.outcome.p_hit, 4),
                "scenario_ev": round(ev.scenario_ev, 4),
                "ds_adj_ev": round(ev.payoff.downside_adjusted_ev, 4),
                "actionable": ev.actionable,
                "days_to_event": ev.node.days_to_event(as_of),
                "tx_clamped": round(tx.get("tx_clamped", 0), 4),
                "tx_protocol": round(tx.get("tx_protocol", 0), 4),
                "tx_endpoint": round(tx.get("tx_endpoint", 0), 4),
                "tx_biomarker": round(tx.get("tx_biomarker", 0), 4),
            }
        )
    return rows


def run_shadow(as_of_str: str) -> Dict[str, Any]:
    """Run side-by-side comparison and log divergence."""
    as_of = date.fromisoformat(as_of_str)
    logger.info("Clinical transmission shadow — %s", as_of_str)

    trials = json.loads((REPO_ROOT / "production_data" / "trial_records.json").read_text())

    # Run both variants
    logger.info("  Running default (no transmission)...")
    default_rows = _run_variant(trials, as_of, inject_clinical=False)
    logger.info("  Running transmission-enabled...")
    tx_rows = _run_variant(trials, as_of, inject_clinical=True)

    # Compare
    def_actionable = {r["ticker"] for r in default_rows if r["actionable"]}
    tx_actionable = {r["ticker"] for r in tx_rows if r["actionable"]}
    def_top10 = {r["ticker"] for r in default_rows[:10]}
    tx_top10 = {r["ticker"] for r in tx_rows[:10]}
    def_top20 = {r["ticker"] for r in default_rows[:20]}
    tx_top20 = {r["ticker"] for r in tx_rows[:20]}

    dropped = def_actionable - tx_actionable
    gained = tx_actionable - def_actionable

    # Build per-name divergence for changed names
    def_by_tk = {f"{r['ticker']}_{r['event_type']}": r for r in default_rows}
    tx_by_tk = {f"{r['ticker']}_{r['event_type']}": r for r in tx_rows}

    changed_names = []
    for key, tx_r in tx_by_tk.items():
        def_r = def_by_tk.get(key)
        if not def_r:
            continue
        rank_delta = def_r["rank"] - tx_r["rank"]
        if abs(rank_delta) >= 3 or tx_r["ticker"] in dropped or tx_r["ticker"] in gained:
            changed_names.append(
                {
                    "ticker": tx_r["ticker"],
                    "phase": tx_r["phase"],
                    "event_type": tx_r["event_type"],
                    "default_rank": def_r["rank"],
                    "tx_rank": tx_r["rank"],
                    "rank_delta": rank_delta,
                    "default_p_hit": def_r["p_hit"],
                    "tx_p_hit": tx_r["p_hit"],
                    "default_ev": def_r["scenario_ev"],
                    "tx_ev": tx_r["scenario_ev"],
                    "default_actionable": def_r["actionable"],
                    "tx_actionable": tx_r["actionable"],
                    "tx_clamped": tx_r["tx_clamped"],
                    "tx_protocol": tx_r["tx_protocol"],
                    "tx_endpoint": tx_r["tx_endpoint"],
                    "tx_biomarker": tx_r["tx_biomarker"],
                    "days_to_event": tx_r["days_to_event"],
                    # Forward monitoring fields
                    "realized_outcome": None,
                    "realized_return": None,
                    "resolution_date": None,
                }
            )
    changed_names.sort(key=lambda x: -abs(x["rank_delta"]))

    entry = {
        "as_of_date": as_of_str,
        "default_actionable_n": len(def_actionable),
        "tx_actionable_n": len(tx_actionable),
        "dropped_from_actionable": sorted(dropped),
        "gained_actionable": sorted(gained),
        "top10_overlap": len(def_top10 & tx_top10),
        "top20_overlap": len(def_top20 & tx_top20),
        "n_changed_names": len(changed_names),
        "changed_names": changed_names[:30],
    }

    # Append to ledger
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")

    # Write daily snapshot
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = SNAPSHOT_DIR / f"{as_of_str}_shadow.json"
    snap_path.write_text(
        json.dumps(
            {
                "as_of_date": as_of_str,
                "summary": entry,
                "default_top20": [r for r in default_rows[:20]],
                "tx_top20": [r for r in tx_rows[:20]],
            },
            indent=2,
        )
    )

    # Print summary
    print(f"\n{'='*60}")
    print(f"Clinical Transmission Shadow — {as_of_str}")
    print(f"{'='*60}")
    print(f"Default actionable: {len(def_actionable)}")
    print(f"TX actionable:      {len(tx_actionable)}")
    print(f"Dropped:            {sorted(dropped)}")
    print(f"Gained:             {sorted(gained)}")
    print(f"Top-10 overlap:     {entry['top10_overlap']}/10")
    print(f"Top-20 overlap:     {entry['top20_overlap']}/20")
    print(f"Changed names:      {len(changed_names)}")

    if changed_names:
        print("\nTop changed names:")
        for c in changed_names[:10]:
            act_change = ""
            if c["default_actionable"] and not c["tx_actionable"]:
                act_change = " [DROPPED]"
            elif not c["default_actionable"] and c["tx_actionable"]:
                act_change = " [GAINED]"
            print(
                f"  {c['ticker']:>6s} ph={c['phase']} "
                f"rank {c['default_rank']}→{c['tx_rank']} "
                f"(Δ={c['rank_delta']:+d}) "
                f"p_hit {c['default_p_hit']:.3f}→{c['tx_p_hit']:.3f} "
                f"tx={c['tx_clamped']:+.3f}{act_change}"
            )

    print(f"\nLedger: {LEDGER_PATH}")
    print(f"Snapshot: {snap_path}")

    return entry


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clinical Transmission Shadow (forward validation)")
    parser.add_argument("--as-of", default=str(date.today()), help="Evaluation date")
    args = parser.parse_args()
    run_shadow(args.as_of)
