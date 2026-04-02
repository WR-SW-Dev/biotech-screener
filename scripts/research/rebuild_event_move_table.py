#!/usr/bin/env python3
"""Rebuild event_move_table.json from CRT resolution outcomes.

Replaces the static historical move table with one derived from our own
CRT-tracked catalyst resolutions. This feeds into EPD's implied_vs_realized
computation, which is the missing EV term in the asymmetry score.

The table maps catalyst_type → {p25, p50, p75, p90, n, confidence} of
absolute realized 1d returns, using the same composite-key format as the
original event_move_table.json.

Also produces a supplementary CRT-keyed table using CRT's own catalyst
types (PHASE_3_READOUT, PDUFA_ACTION, etc.) for direct lookup.

Usage:
    python3 scripts/research/rebuild_event_move_table.py
    python3 scripts/research/rebuild_event_move_table.py --min-obs 3
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

CRT_JOIN_PATH = REPO_ROOT / "output" / "catalyst_ev" / "crt_options_join.json"
EMT_PATH = REPO_ROOT / "data" / "research" / "event_move_table.json"
OUTPUT_PATH = REPO_ROOT / "data" / "research" / "event_move_table.json"

# Map CRT catalyst types to composite-key families
CRT_TO_FAMILY = {
    "PHASE_1_READOUT": "CLINICAL",
    "PHASE_2_READOUT": "CLINICAL",
    "PHASE_3_READOUT": "CLINICAL",
    "DATA_READOUT": "CLINICAL",
    "INTERIM_ANALYSIS": "CLINICAL",
    "PDUFA_ACTION": "REGULATORY",
    "ADVISORY_COMMITTEE": "REGULATORY",
    "NDA_BLA_FILING": "REGULATORY",
    "APPROVAL_DECISION": "REGULATORY",
    "CORPORATE_UPDATE": "UNKNOWN",
    "PARTNERSHIP": "UNKNOWN",
    "LICENSING": "UNKNOWN",
}

# Map CRT types to phase bucket
CRT_TO_PHASE = {
    "PHASE_1_READOUT": "early",
    "PHASE_2_READOUT": "phase2",
    "PHASE_3_READOUT": "phase3",
    "DATA_READOUT": "any",
    "INTERIM_ANALYSIS": "any",
    "PDUFA_ACTION": "phase3",  # most PDUFAs are phase 3
    "ADVISORY_COMMITTEE": "phase3",
    "NDA_BLA_FILING": "phase3",
    "APPROVAL_DECISION": "phase3",
    "CORPORATE_UPDATE": "any",
    "PARTNERSHIP": "any",
    "LICENSING": "any",
}


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)

    def _pct(p):
        idx = p / 100.0 * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return round(s[lo] * (1 - frac) + s[hi] * frac, 6)

    return {
        "n": n,
        "p25": _pct(25),
        "p50": _pct(50),
        "p75": _pct(75),
        "p90": _pct(90),
        "mean": round(statistics.mean(values), 6),
    }


def _confidence(n: int) -> str:
    if n >= 20:
        return "ok"
    if n >= 10:
        return "moderate"
    if n >= 5:
        return "low_confidence"
    return "very_low"


def build_table(min_obs: int = 3) -> dict:
    """Build event move table from CRT resolutions."""
    if not CRT_JOIN_PATH.exists():
        print(f"CRT join not found at {CRT_JOIN_PATH}")
        print("Run: python scripts/research/build_crt_options_join.py")
        sys.exit(1)

    join = json.loads(CRT_JOIN_PATH.read_text())
    records = join.get("records", [])

    # Collect abs realized 1d returns by composite key
    composite_buckets: dict[str, list[float]] = defaultdict(list)
    crt_buckets: dict[str, list[float]] = defaultdict(list)

    for r in records:
        ret = r.get("realized_1d_return")
        if ret is None:
            continue
        abs_ret = abs(ret)
        crt_type = r.get("catalyst_type", "")

        # CRT-native bucket
        crt_buckets[crt_type].append(abs_ret)

        # Composite-key buckets
        family = CRT_TO_FAMILY.get(crt_type, "UNKNOWN")
        phase = CRT_TO_PHASE.get(crt_type, "any")

        composite_buckets[f"{family}|{phase}|any"].append(abs_ret)
        composite_buckets[f"{family}|any|any"].append(abs_ret)
        composite_buckets["any|any|any"].append(abs_ret)

    # Build table
    table = {}
    for key, values in sorted(composite_buckets.items()):
        if len(values) >= min_obs:
            entry = _percentiles(values)
            entry["confidence"] = _confidence(len(values))
            table[key] = entry

    # CRT-native supplementary table
    crt_table = {}
    for key, values in sorted(crt_buckets.items()):
        if len(values) >= min_obs:
            entry = _percentiles(values)
            entry["confidence"] = _confidence(len(values))
            crt_table[key] = entry

    return {
        "schema": "event_move_table.v1",
        "built_as_of": datetime.now(timezone.utc).isoformat(),
        "source": "crt_resolutions",
        "n_outcomes": sum(len(v) for v in crt_buckets.values()),
        "n_crt_types": len(crt_buckets),
        "min_obs": min_obs,
        "table": table,
        "crt_native_table": crt_table,
    }


def main():
    parser = argparse.ArgumentParser(description="Rebuild event move table from CRT outcomes")
    parser.add_argument("--min-obs", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="Print only, don't overwrite")
    args = parser.parse_args()

    result = build_table(args.min_obs)

    print("EVENT MOVE TABLE — rebuilt from CRT resolutions")
    print(f"  Outcomes: {result['n_outcomes']}")
    print(f"  CRT types: {result['n_crt_types']}")
    print(f"  Min obs: {args.min_obs}")

    print("\nComposite-key table:")
    for key, entry in result["table"].items():
        print(
            f"  {key:30s}  n={entry['n']:2d}  p50={entry['p50']:.3f}  "
            f"p75={entry['p75']:.3f}  conf={entry['confidence']}"
        )

    print("\nCRT-native table:")
    for key, entry in result["crt_native_table"].items():
        print(
            f"  {key:30s}  n={entry['n']:2d}  p50={entry['p50']:.3f}  "
            f"p75={entry['p75']:.3f}  conf={entry['confidence']}"
        )

    if args.dry_run:
        print("\nDry run — not overwriting event_move_table.json")
        return

    # Merge with existing table (preserve entries we can't rebuild yet)
    if EMT_PATH.exists():
        existing = json.loads(EMT_PATH.read_text())
        existing_table = existing.get("table", {})
        # CRT-derived entries override; keep existing entries not covered by CRT
        merged = dict(existing_table)
        merged.update(result["table"])
        result["table"] = merged
        result["merged_with_existing"] = True
        print(
            f"\nMerged: {len(result['table'])} entries "
            f"({len(existing_table)} existing + {len(result['table']) - len(existing_table)} new/updated)"
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2))
    print(f"\nWrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
