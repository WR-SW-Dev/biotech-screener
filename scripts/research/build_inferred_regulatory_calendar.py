#!/usr/bin/env python3
"""Build inferred regulatory calendar from SEC 8-K submission/acceptance language.

Scans 8-K cache for NDA/BLA submission, filing acceptance, priority/standard
review designation, and CRL resubmission language. Infers approximate PDUFA
dates using statutory review timelines.

Does NOT modify production_data/pdufa_dates.json (confirmed calendar).
Writes a separate inferred_regulatory_dates.json artifact.

Usage:
    python scripts/research/build_inferred_regulatory_calendar.py
    python scripts/research/build_inferred_regulatory_calendar.py --as-of-date 2026-03-15
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from dateutil.relativedelta import relativedelta

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Inference patterns
# ---------------------------------------------------------------------------

# Submission language (NDA/BLA filed or submitted)
_SUBMISSION_RE = re.compile(
    r"(?i)(?:"
    r"(?:submitted|filed|submission of|filing of).{0,60}(?:NDA|BLA|sNDA|sBLA)"
    r"|(?:NDA|BLA|sNDA|sBLA).{0,60}(?:submitted|filed|submission)"
    r"|(?:accepted|acceptance).{0,80}(?:for filing|for review)"
    r"|(?:filing|review)\s+(?:accepted|acceptance)"
    r")"
)

# Review type
_PRIORITY_RE = re.compile(r"(?i)priority\s+review")
_STANDARD_RE = re.compile(r"(?i)standard\s+review")

# CRL / resubmission
_CRL_RE = re.compile(r"(?i)(?:complete\s+response\s+letter|(?:received|issued)\s+a?\s*CRL)")
_RESUB_RE = re.compile(r"(?i)(?:resubmi(?:tted|ssion)|plan(?:s|ned)?\s+to\s+resubmit)")

# Submission type extraction
_SUBTYPE_RE = re.compile(r"\b(sNDA|sBLA|NDA|BLA)\b", re.IGNORECASE)
_SUBTYPE_CANONICAL = {"nda": "NDA", "bla": "BLA", "snda": "sNDA", "sbla": "sBLA"}

# Drug name extraction (simple heuristic)
_DRUG_RE = re.compile(
    r"(?:for|of)\s+([A-Z][a-z]+(?:umab|izumab|ximab|zumab|nib|tinib|sertib|mab|cept|tide|lone|vir|stat|pril|olol|idol|amine|fentanil|lukast)\b)",
    re.IGNORECASE,
)

# Review timeline defaults (months from submission/acceptance to decision)
# FDA statutory review timelines (from FDA.gov):
# Priority Review: 6 months from filing acceptance
# Standard Review: 10 months from filing acceptance
# https://www.fda.gov/patients/fast-track-breakthrough-therapy-accelerated-approval-priority-review/priority-review
REVIEW_MONTHS = {
    "priority": 6,
    "standard": 10,
    "unknown": 10,  # conservative default (standard review)
    "resubmission": 6,  # Class 2 resubmission default
}

# Confidence by inference quality
CONFIDENCE = {
    "acceptance_with_review_type": 0.75,
    "submission_without_acceptance": 0.65,
    "crl_resubmission": 0.60,
    "unknown_review_type": 0.55,
}

STALENESS_DAYS = 90
STALENESS_DOWNGRADE_CONFIDENCE = 0.40


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def load_universe(data_dir: Path) -> Set[str]:
    universe_path = data_dir / "universe.json"
    if not universe_path.exists():
        return set()
    data = json.loads(universe_path.read_text())
    if isinstance(data, list):
        return {(e.get("ticker", e) if isinstance(e, dict) else e).upper() for e in data}
    return set()


def load_confirmed_pdufa(data_dir: Path) -> Set[Tuple[str, str]]:
    """Load confirmed PDUFA entries → set of (ticker, date) for dedup."""
    path = data_dir / "pdufa_dates.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    entries = data if isinstance(data, list) else data.get("events", [])
    return {(e.get("ticker", "").upper(), e.get("pdufa_date", "")) for e in entries}


def scan_8k_cache_for_submissions(
    cache_dir: Path,
    universe: Set[str],
    as_of_date: date,
) -> List[Dict[str, Any]]:
    """Scan 8-K cache for submission/acceptance/CRL language."""
    cache_files = sorted(cache_dir.glob("8k_catalysts_*.json"), reverse=True)
    inferred: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()  # (ticker, event_type) dedup

    for cache_file in cache_files:
        try:
            events = json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        for ev in events:
            ticker = (ev.get("ticker") or "").upper()
            if not ticker or ticker not in universe:
                continue

            event_name = ev.get("event_name", "")
            event_type = ev.get("event_type", "")
            filing_date = ev.get("disclosed_at") or ev.get("event_date", "")

            # Skip if already has an explicit PDUFA date (belongs in confirmed path)
            if event_type == "FDA_PDUFA_DATE":
                continue

            # Check for submission/acceptance language
            has_submission = bool(_SUBMISSION_RE.search(event_name))
            has_crl = bool(_CRL_RE.search(event_name))
            has_resub = bool(_RESUB_RE.search(event_name))

            if not has_submission and not has_crl and not has_resub:
                continue

            # Extract review type
            is_priority = bool(_PRIORITY_RE.search(event_name))
            is_standard = bool(_STANDARD_RE.search(event_name))
            review_type = "priority" if is_priority else ("standard" if is_standard else "unknown")

            # Extract submission type
            sub_match = _SUBTYPE_RE.search(event_name)
            submission_type = _SUBTYPE_CANONICAL.get(sub_match.group(1).lower(), "NDA") if sub_match else "unknown"

            # Extract drug name
            drug_match = _DRUG_RE.search(event_name)
            drug_name = drug_match.group(1) if drug_match else ""

            # Determine inference type and confidence
            if has_resub:
                infer_type = "PDUFA_INFERRED_RESUBMISSION"
                months = REVIEW_MONTHS["resubmission"]
                confidence = CONFIDENCE["crl_resubmission"]
            elif has_submission:
                if is_priority or is_standard:
                    infer_type = "PDUFA_INFERRED"
                    months = REVIEW_MONTHS[review_type]
                    confidence = CONFIDENCE["acceptance_with_review_type"]
                else:
                    infer_type = "PDUFA_INFERRED"
                    months = REVIEW_MONTHS["unknown"]
                    confidence = CONFIDENCE["submission_without_acceptance"]
            elif has_crl:
                # CRL detected but no resubmission yet — just flag it
                infer_type = "CRL_DETECTED"
                months = 0
                confidence = 0.50
            else:
                continue

            # Compute inferred date
            try:
                disclosed = date.fromisoformat(filing_date[:10])
            except (ValueError, TypeError):
                continue

            if months > 0:
                inferred_date = disclosed + relativedelta(months=months)
            else:
                inferred_date = None

            # Staleness check
            stale = False
            if inferred_date and (as_of_date - disclosed).days > STALENESS_DAYS:
                confidence = min(confidence, STALENESS_DOWNGRADE_CONFIDENCE)
                stale = True

            # Skip if inferred date has passed
            if inferred_date and inferred_date < as_of_date:
                continue

            # Dedup
            dedup_key = (ticker, infer_type)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            entry = {
                "ticker": ticker,
                "drug_name": drug_name,
                "pdufa_date": inferred_date.isoformat() if inferred_date else "",
                "event_type": infer_type,
                "submission_type": submission_type,
                "review_type": review_type,
                "confidence_numeric": round(confidence, 2),
                "confidence_label": "HIGH" if confidence >= 0.75 else ("MED" if confidence >= 0.60 else "LOW"),
                "source": "SEC_8K_INFERRED",
                "source_file": cache_file.name,
                "as_of_disclosed_at": filing_date[:10] if filing_date else "",
                "uncertainty_window_days": 45 if review_type != "unknown" else 60,
                "stale": stale,
                "notes": f"Inferred from 8-K: {event_name[:100]}",
            }
            inferred.append(entry)

    return inferred


def compute_treatment_impact(
    snapshots_dir: Path,
    inferred: List[Dict[str, Any]],
    as_of_date: date,
) -> Dict[str, Any]:
    """Measure how much inferred entries expand the 61-210d treatment set."""
    # Build inferred lookup: ticker → inferred days from as_of
    inferred_lookup: Dict[str, int] = {}
    for e in inferred:
        if not e["pdufa_date"]:
            continue
        try:
            idate = date.fromisoformat(e["pdufa_date"])
            days = (idate - as_of_date).days
            if 61 <= days <= 210:
                inferred_lookup[e["ticker"]] = days
        except (ValueError, TypeError):
            pass

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    impact_by_date = []

    for d in sorted(snapshots_dir.iterdir()):
        if not d.is_dir() or not date_re.match(d.name):
            continue
        csv_path = d / "rankings.csv"
        if not csv_path.exists():
            continue

        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except (OSError, csv.Error):
            continue

        confirmed_reg = set()
        for r in rows:
            tk = (r.get("ticker") or "").upper()
            has_reg = str(r.get("has_regulatory_upcoming_180d", "")).strip() == "1"
            try:
                rd = float(r.get("regulatory_days", ""))
            except (ValueError, TypeError):
                rd = 0
            if has_reg and 61 <= rd <= 210:
                confirmed_reg.add(tk)

        # Add inferred names not already in confirmed
        combined = confirmed_reg | set(inferred_lookup.keys())

        impact_by_date.append(
            {
                "date": d.name,
                "confirmed_only": len(confirmed_reg),
                "inferred_only": len(set(inferred_lookup.keys()) - confirmed_reg),
                "combined": len(combined),
            }
        )

    return {
        "n_dates": len(impact_by_date),
        "n_inferred_in_window": len(inferred_lookup),
        "inferred_tickers_in_window": sorted(inferred_lookup.keys()),
        "by_date": impact_by_date,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build inferred regulatory calendar")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "production_data")
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_ROOT / "cache" / "sec" / "8k_catalysts")
    parser.add_argument("--snapshots-dir", type=Path, default=PROJECT_ROOT / "data" / "snapshots")
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "production_data" / "inferred_regulatory_dates.json"
    )
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output" / "inferred_regulatory_calendar")
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of_date)

    logger.info("Loading universe ...")
    universe = load_universe(args.data_dir)
    logger.info("Universe: %d tickers", len(universe))

    logger.info("Loading confirmed PDUFA entries ...")
    confirmed = load_confirmed_pdufa(args.data_dir)
    logger.info("Confirmed entries: %d", len(confirmed))

    logger.info("Scanning 8-K cache for submission/acceptance language ...")
    inferred = scan_8k_cache_for_submissions(args.cache_dir, universe, as_of)
    logger.info("Inferred entries: %d", len(inferred))

    # Remove entries that overlap with confirmed PDUFAs
    before = len(inferred)
    inferred = [e for e in inferred if (e["ticker"], e["pdufa_date"]) not in confirmed]
    if before != len(inferred):
        logger.info("Removed %d entries overlapping with confirmed PDUFA", before - len(inferred))

    # Write inferred calendar
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_data = {
        "schema": "inferred_regulatory_dates.v1",
        "built_as_of": args.as_of_date,
        "n_entries": len(inferred),
        "entries": inferred,
    }
    args.output.write_text(json.dumps(output_data, indent=2) + "\n")
    logger.info("Inferred calendar → %s", args.output)

    # Treatment set impact
    logger.info("Computing treatment set impact ...")
    impact = compute_treatment_impact(args.snapshots_dir, inferred, as_of)

    # Diagnostics output
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Summary
    from collections import Counter

    by_type = Counter(e["event_type"] for e in inferred)
    by_subtype = Counter(e["submission_type"] for e in inferred)
    by_review = Counter(e["review_type"] for e in inferred)
    by_conf = Counter(e["confidence_label"] for e in inferred)
    in_window = [
        e for e in inferred if e["pdufa_date"] and 61 <= (date.fromisoformat(e["pdufa_date"]) - as_of).days <= 210
    ]

    summary = {
        "n_inferred": len(inferred),
        "by_event_type": dict(by_type),
        "by_submission_type": dict(by_subtype),
        "by_review_type": dict(by_review),
        "by_confidence": dict(by_conf),
        "n_in_61_210d_window": len(in_window),
        "tickers_in_window": [e["ticker"] for e in in_window],
        "overlap_with_confirmed": before - len(inferred),
        "treatment_set_impact": {
            "n_inferred_in_window": impact["n_inferred_in_window"],
            "inferred_tickers": impact["inferred_tickers_in_window"],
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    # Markdown
    md = [
        "# Inferred Regulatory Calendar",
        "",
        f"**As-of date**: {args.as_of_date}",
        f"**Total inferred entries**: {len(inferred)}",
        f"**In 61-210d window**: {len(in_window)}",
        "",
        "## By Event Type",
        "",
    ]
    for t, c in sorted(by_type.items()):
        md.append(f"- {t}: {c}")
    md += ["", "## By Review Type", ""]
    for t, c in sorted(by_review.items()):
        md.append(f"- {t}: {c}")
    md += ["", "## By Confidence", ""]
    for t, c in sorted(by_conf.items()):
        md.append(f"- {t}: {c}")

    if in_window:
        md += [
            "",
            "## Names in 61-210d Window",
            "",
            "| Ticker | Drug | Inferred Date | Type | Review | Confidence | Source |",
            "|--------|------|---------------|------|--------|-----------|--------|",
        ]
        for e in sorted(in_window, key=lambda x: x["pdufa_date"]):
            md.append(
                f"| {e['ticker']} | {e['drug_name']} | {e['pdufa_date']} | {e['event_type']} | {e['review_type']} | {e['confidence_numeric']} | {e['source']} |"
            )

    if inferred:
        md += [
            "",
            "## All Inferred Entries",
            "",
            "| Ticker | Drug | Inferred Date | Type | Review | Confidence | Stale |",
            "|--------|------|---------------|------|--------|-----------|-------|",
        ]
        for e in sorted(inferred, key=lambda x: x.get("pdufa_date", "")):
            md.append(
                f"| {e['ticker']} | {e['drug_name']} | {e['pdufa_date']} | {e['event_type']} | {e['review_type']} | {e['confidence_numeric']} | {'Y' if e['stale'] else ''} |"
            )

    md.append("")
    (args.output_dir / "summary.md").write_text("\n".join(md))
    logger.info("Summary → %s", args.output_dir / "summary.md")

    # Print key results
    logger.info("  Inferred entries: %d", len(inferred))
    logger.info("  In 61-210d window: %d", len(in_window))
    logger.info("  By type: %s", dict(by_type))
    if in_window:
        logger.info("  Window tickers: %s", [e["ticker"] for e in in_window])

    return 0


if __name__ == "__main__":
    sys.exit(main())
