"""Herald → CRT shadow intake — resolution candidate extraction.

Reads Herald classified output and produces CRT intake candidates.
Shadow-only: does NOT write CRT resolution records. Produces an
artifact that reports what CRT records WOULD be created.

Intake filter (all must pass):
  1. classification not informational
  2. event_category in whitelist (clinical, regulatory, safety)
  3. confidence >= threshold
  4. ticker matches a DEM-ranked name with catalyst in detection window
  5. no existing CRT record for this (ticker, catalyst_date) key

Output:
    artifacts/herald_crt_intake/{date}_candidates.json

Usage:
    python tools/herald_crt_intake.py --as-of-date 2026-04-01
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CLASSIFIED_DIR = PROJECT_ROOT / "data" / "press_releases" / "classified"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots"
RESOLUTION_DIR = SNAPSHOT_DIR / "resolutions"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "herald_crt_intake"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("herald_crt_intake")

# --- Intake filter config ---
CATEGORY_WHITELIST = frozenset({"clinical", "regulatory", "safety"})
MIN_CONFIDENCE = 0.5
CATALYST_WINDOW_DAYS = 14  # herald event must be within ±14d of a DEM catalyst


# --- Herald → CRT catalyst_type mapping ---
_SUBTYPE_TO_CATALYST_TYPE = {
    "clinical_data": "PHASE_3_READOUT",  # default; refined by headline keywords
    "regulatory_update": "PDUFA_ACTION",
    "safety_signal": "CORPORATE_UPDATE",
    "mna_announcement": "CORPORATE_UPDATE",
    "capital_raise": "CORPORATE_UPDATE",
}


def _map_catalyst_type(herald_record: dict) -> str:
    """Map Herald event to CRT catalyst_type."""
    subtype = herald_record.get("event_subtype", "")
    headline = (herald_record.get("headline") or "").lower()

    base = _SUBTYPE_TO_CATALYST_TYPE.get(subtype, "CORPORATE_UPDATE")

    # Refine clinical by phase
    if base == "PHASE_3_READOUT":
        if "phase 1" in headline:
            return "PHASE_1_DATA"
        if "phase 2" in headline:
            return "PHASE_2_READOUT"
    # Refine regulatory
    if herald_record.get("event_category") == "regulatory":
        if any(kw in headline for kw in ["nda", "bla", "submission", "filing"]):
            return "NDA_BLA_FILING"
        if "breakthrough" in headline or "designation" in headline:
            return "REGULATORY_DESIGNATION"
        if "advisory" in headline or "adcom" in headline:
            return "ADVISORY_COMMITTEE"

    return base


def _map_outcome(herald_record: dict) -> str:
    """Map Herald outcome guess to CRT outcome."""
    guess = herald_record.get("event_outcome_guess", "unclear")
    return {
        "hit": "HIT",
        "miss": "MISS",
        "mixed": "MIXED",
    }.get(guess, "NEEDS_REVIEW")


def load_classified(as_of_date: str) -> List[Dict]:
    """Load Herald classified records for a date."""
    path = CLASSIFIED_DIR / f"classified_{as_of_date}.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text().strip().split("\n"):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def load_dem_catalysts(as_of_date: str) -> Dict[str, Dict]:
    """Load DEM catalyst context from rankings.csv.

    Returns {ticker: {catalyst_date_approx, catalyst_days, catalyst_type, rank}}.
    """
    rpath = SNAPSHOT_DIR / as_of_date / "rankings.csv"
    if not rpath.exists():
        return {}

    result = {}
    with open(rpath, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").upper()
            ar = row.get("actionable_rank", "").strip()
            if not ticker or not ar:
                continue

            cat_days = row.get("catalyst_days", "").strip()
            if not cat_days:
                continue
            try:
                cd = int(float(cat_days))
            except (ValueError, TypeError):
                continue

            # Approximate catalyst date from snapshot date + catalyst_days
            try:
                snap = date.fromisoformat(as_of_date)
                approx_cat_date = (snap + timedelta(days=cd)).isoformat()
            except (ValueError, TypeError):
                continue

            result[ticker] = {
                "catalyst_date_approx": approx_cat_date,
                "catalyst_days": cd,
                "catalyst_event_type": row.get("catalyst_event_type", ""),
                "rank": int(ar) if ar else 9999,
                "is_hard_catalyst": row.get("is_hard_catalyst", "") == "1",
            }
    return result


def load_existing_resolutions() -> Set[Tuple[str, str]]:
    """Load all existing CRT resolution keys (ticker, catalyst_date)."""
    keys: Set[Tuple[str, str]] = set()
    if not RESOLUTION_DIR.exists():
        return keys
    for month_dir in RESOLUTION_DIR.iterdir():
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob("*.json"):
            try:
                rec = json.loads(f.read_text())
                keys.add((rec.get("ticker", ""), rec.get("catalyst_date", "")))
            except (json.JSONDecodeError, OSError):
                pass
    return keys


def build_intake_candidates(as_of_date: str) -> Dict[str, Any]:
    """Build CRT intake candidates from Herald classified output."""
    classified = load_classified(as_of_date)
    log.info("Loaded %d classified records for %s", len(classified), as_of_date)

    dem_catalysts = load_dem_catalysts(as_of_date)
    log.info("DEM catalyst context: %d tickers", len(dem_catalysts))

    existing = load_existing_resolutions()
    log.info("Existing CRT resolutions: %d", len(existing))

    candidates = []
    rejected = {
        "informational": 0,
        "wrong_category": 0,
        "low_confidence": 0,
        "no_dem_match": 0,
        "already_resolved": 0,
        "noise": 0,
    }

    for rec in classified:
        ticker = (rec.get("ticker") or "").upper()
        headline = rec.get("headline", "")

        # Filter 1: not informational AND not ticker-collision
        # (collision_severity=soft items have informational_only=False but are
        # still flagged ticker_collision_flag=True so they don't enter CRT;
        # they stay cache-visible for escalation review.)
        if rec.get("informational_only") or rec.get("ticker_collision_flag"):
            rejected["informational"] += 1
            continue

        # Filter 2: category whitelist
        cat = rec.get("event_category", "other")
        if cat not in CATEGORY_WHITELIST:
            rejected["wrong_category"] += 1
            continue

        # Filter 3: confidence threshold
        conf = rec.get("confidence", 0)
        if conf < MIN_CONFIDENCE:
            rejected["low_confidence"] += 1
            continue

        # Filter 4: DEM match — ticker must have a catalyst in the DEM
        dem = dem_catalysts.get(ticker)
        if not dem:
            rejected["no_dem_match"] += 1
            continue

        # Use the DEM's approximate catalyst date
        approx_cat_date = dem["catalyst_date_approx"]

        # Filter 5: no existing resolution for this key
        if (ticker, approx_cat_date) in existing:
            rejected["already_resolved"] += 1
            continue

        # Build candidate
        catalyst_type = _map_catalyst_type(rec)
        outcome = _map_outcome(rec)

        candidates.append(
            {
                "ticker": ticker,
                "catalyst_date": approx_cat_date,
                "catalyst_type": catalyst_type,
                "headline": headline,
                "herald_category": cat,
                "herald_subtype": rec.get("event_subtype", ""),
                "herald_confidence": conf,
                "herald_outcome_guess": rec.get("event_outcome_guess", "unclear"),
                "mapped_outcome": outcome,
                "source_url": rec.get("source_url", ""),
                "source_type": rec.get("source_type", ""),
                "dem_rank": dem["rank"],
                "dem_catalyst_days": dem["catalyst_days"],
                "is_hard_catalyst": dem["is_hard_catalyst"],
                "thesis_change_flag": rec.get("thesis_change_flag", False),
                "safety_signal_flag": rec.get("safety_signal_flag", False),
                "mna_signal_flag": rec.get("mna_signal_flag", False),
                "financing_signal_flag": rec.get("financing_signal_flag", False),
                "would_create_crt": True,
            }
        )

    # Deduplicate by (ticker, catalyst_type) — keep highest confidence
    seen: Dict[Tuple[str, str], int] = {}
    deduped = []
    for i, c in enumerate(candidates):
        key = (c["ticker"], c["catalyst_type"])
        if key in seen:
            existing_idx = seen[key]
            if c["herald_confidence"] > deduped[existing_idx]["herald_confidence"]:
                deduped[existing_idx] = c
        else:
            seen[key] = len(deduped)
            deduped.append(c)

    return {
        "schema": "herald_crt_intake.v1",
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_classified": len(classified),
        "n_candidates": len(deduped),
        "n_rejected": sum(rejected.values()),
        "rejection_reasons": rejected,
        "candidates": deduped,
    }


def print_report(result: dict):
    print(f"\n{'='*60}")
    print("HERALD → CRT INTAKE CANDIDATES (shadow)")
    print(f"{'='*60}")
    print(f"  Classified: {result['n_classified']}")
    print(f"  Candidates: {result['n_candidates']}")
    print(f"  Rejected:   {result['n_rejected']}")

    rej = result["rejection_reasons"]
    print("\n  Rejection breakdown:")
    for reason, n in sorted(rej.items(), key=lambda x: -x[1]):
        if n > 0:
            print(f"    {reason}: {n}")

    if result["candidates"]:
        print(f"\n  {'Ticker':<8} {'Type':<20} {'Outcome':<8} {'Conf':>5} {'Rank':>5} {'Hard':>5}  Headline")
        print(f"  {'-'*90}")
        for c in result["candidates"]:
            hard = "Y" if c["is_hard_catalyst"] else "N"
            print(
                f"  {c['ticker']:<8} {c['catalyst_type']:<20} {c['mapped_outcome']:<8} "
                f"{c['herald_confidence']:>4.1f} {c['dem_rank']:>5} {hard:>5}  {c['headline'][:50]}"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    result = build_intake_candidates(args.as_of_date)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{args.as_of_date}_candidates.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", out_path)

    print_report(result)


if __name__ == "__main__":
    main()
