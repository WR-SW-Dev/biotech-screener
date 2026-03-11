#!/usr/bin/env python3
"""Provenance-enforced AdCom outcomes importer/normalizer.

Ingests source-backed historical FDA Advisory Committee vote outcome rows
into adcom_outcomes.json.  Does NOT change the live scoring basis — that
remains committee_prior until enough validated rows exist.

Modes:
  --validate   → validate an input candidates JSON against v2 provenance rules
  --ingest     → merge validated candidates into adcom_outcomes.json (dedup)
  --audit      → audit existing adcom_outcomes.json for provenance gaps
  --coverage   → show coverage breakdown by committee / year / question_type

Candidate JSON format (one record per vote question):
  [
    {
      "meeting_date": "2023-06-15",
      "committee": "Oncologic Drugs Advisory Committee",
      "question_type": "APPROVAL",
      "vote_yes": 10,
      "vote_no": 3,
      "vote_abstain": 0,
      "source_url": "https://www.fda.gov/advisory-committees/...",
      "publication_date": "2023-06-16",
      "source_doc_type": "fda_meeting_minutes",
      "drug_name": "TestDrug",
      "sponsor": "TestCo",
      "ticker": "TSTX",
      "indication": "cancer",
      "fda_outcome": "APPROVED",
      "fda_aligned_with_vote": true,
      "notes": "Voted 10-3 in favor of approval"
    }
  ]

Usage:
    python3 tools/import_adcom_outcomes.py --validate candidates.json
    python3 tools/import_adcom_outcomes.py --ingest candidates.json --dry-run
    python3 tools/import_adcom_outcomes.py --ingest candidates.json
    python3 tools/import_adcom_outcomes.py --audit
    python3 tools/import_adcom_outcomes.py --coverage
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.adcom_empirical import OUTCOMES_SCHEMA, validate_record

logger = logging.getLogger(__name__)

# Valid question_type values (standardized)
VALID_QUESTION_TYPES = frozenset(
    {
        "APPROVAL",
        "SAFETY",
        "EFFICACY",
        "RISK_BENEFIT",
        "LABELING",
        "PEDIATRIC",
        "OTHER",
    }
)

# Valid fda_outcome values
VALID_FDA_OUTCOMES = frozenset(
    {
        "APPROVED",
        "CRL",
        "PENDING",
        "WITHDRAWN",
        "NOT_APPLICABLE",
    }
)

# Recognized committee name prefixes (for normalization)
KNOWN_COMMITTEES = (
    "Oncologic Drugs Advisory Committee",
    "Cardiovascular and Renal Drugs Advisory Committee",
    "Psychopharmacologic Drugs Advisory Committee",
    "Pulmonary-Allergy Drugs Advisory Committee",
    "Endocrinologic and Metabolic Drugs Advisory Committee",
    "Dermatologic and Ophthalmic Drugs Advisory Committee",
    "Anti-Infective Drugs Advisory Committee",
    "Gastrointestinal Drugs Advisory Committee",
    "Peripheral and Central Nervous System Drugs Advisory Committee",
    "Arthritis Advisory Committee",
    "Anesthetic and Analgesic Drug Products Advisory Committee",
    "Drug Safety and Risk Management Advisory Committee",
    "Bone, Reproductive and Urologic Drugs Advisory Committee",
    "Antimicrobial Drugs Advisory Committee",
    "Cellular, Tissue, and Gene Therapies Advisory Committee",
    "Vaccines and Related Biological Products Advisory Committee",
)


# ---------------------------------------------------------------------------
# Extended validation (beyond adcom_empirical.validate_record)
# ---------------------------------------------------------------------------


def validate_candidate(rec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a candidate record with extended checks.

    Calls adcom_empirical.validate_record() for base validation, then adds:
      - question_type normalization check
      - fda_outcome validation (if present)
      - publication_date vs meeting_date PIT check
      - vote total sanity check (yes + no > 0)

    Returns (is_valid, list_of_error_strings).
    """
    # Base provenance + schema validation
    ok, errors = validate_record(rec)

    if not isinstance(rec, dict):
        return ok, errors

    # question_type normalization
    qtype = str(rec.get("question_type", "")).upper()
    if qtype and qtype not in VALID_QUESTION_TYPES:
        errors.append(f"unrecognized question_type: {qtype!r}; valid: {sorted(VALID_QUESTION_TYPES)}")

    # fda_outcome validation (optional field)
    fda_outcome = rec.get("fda_outcome", "")
    if fda_outcome:
        outcome_upper = str(fda_outcome).upper()
        if outcome_upper not in VALID_FDA_OUTCOMES:
            errors.append(f"unrecognized fda_outcome: {fda_outcome!r}; valid: {sorted(VALID_FDA_OUTCOMES)}")

    # PIT check: publication_date should be >= meeting_date
    pub_date = rec.get("publication_date", "")
    meeting_date = rec.get("meeting_date", "")
    if pub_date and meeting_date:
        try:
            if date.fromisoformat(pub_date) < date.fromisoformat(meeting_date):
                errors.append(f"publication_date ({pub_date}) is before meeting_date ({meeting_date})")
        except (ValueError, TypeError):
            pass  # date format errors caught by base validator

    # Vote total sanity
    try:
        yes = int(rec.get("vote_yes", 0))
        no = int(rec.get("vote_no", 0))
        if yes + no == 0 and rec.get("vote_yes") is not None:
            errors.append("vote_yes + vote_no = 0; at least one vote required")
    except (ValueError, TypeError):
        pass  # caught by base validator

    return len(errors) == 0, errors


def validate_candidates(
    records: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate a batch of candidate records.

    Returns (valid, invalid_with_errors).
    """
    valid = []
    invalid = []
    for rec in records:
        ok, errs = validate_candidate(rec)
        if ok:
            valid.append(rec)
        else:
            inv = dict(rec) if isinstance(rec, dict) else {"_raw": rec}
            inv["_errors"] = errs
            invalid.append(inv)
    return valid, invalid


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a validated record to canonical form.

    - Uppercases question_type
    - Casts vote counts to int
    - Strips whitespace from string fields
    - Removes internal/review fields (_prefixed)
    """
    out: Dict[str, Any] = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, str):
            v = v.strip()
        out[k] = v

    # Standardize types
    if "question_type" in out:
        out["question_type"] = str(out["question_type"]).upper()
    for vote_field in ("vote_yes", "vote_no", "vote_abstain"):
        if vote_field in out and out[vote_field] is not None:
            try:
                out[vote_field] = int(out[vote_field])
            except (ValueError, TypeError):
                pass
    if "fda_outcome" in out and out["fda_outcome"]:
        out["fda_outcome"] = str(out["fda_outcome"]).upper()
    if "fda_aligned_with_vote" in out:
        out["fda_aligned_with_vote"] = bool(out["fda_aligned_with_vote"])

    return out


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def _dedup_key(rec: Dict[str, Any]) -> Tuple[str, str, str]:
    """Dedup key: (meeting_date, committee, question_type)."""
    return (
        rec.get("meeting_date", ""),
        rec.get("committee", ""),
        str(rec.get("question_type", "")).upper(),
    )


def dedup_candidates(
    candidates: List[Dict[str, Any]],
    existing: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split candidates into new vs duplicate (already in existing).

    Dedup key: (meeting_date, committee, question_type).
    """
    existing_keys: Set[Tuple[str, str, str]] = set()
    for rec in existing:
        existing_keys.add(_dedup_key(rec))

    new = []
    dupes = []
    for rec in candidates:
        key = _dedup_key(rec)
        if key in existing_keys:
            dupes.append(rec)
        else:
            new.append(rec)
            existing_keys.add(key)  # prevent intra-batch dupes

    return new, dupes


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_existing_outcomes(outcomes_path: Path) -> List[Dict[str, Any]]:
    """Load existing records from adcom_outcomes.json."""
    if not outcomes_path.exists():
        return []
    try:
        data = json.loads(outcomes_path.read_text(encoding="utf-8"))
        if data.get("schema") != OUTCOMES_SCHEMA:
            return []
        return data.get("records", [])
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def ingest_candidates(
    candidates: List[Dict[str, Any]],
    outcomes_path: Path,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Validate, normalize, dedup, and ingest candidates.

    Returns report dict with accepted/rejected/duplicate counts.
    """
    existing = load_existing_outcomes(outcomes_path)
    new_candidates, dupes = dedup_candidates(candidates, existing)

    accepted = []
    rejected = []

    for rec in new_candidates:
        ok, errs = validate_candidate(rec)
        if ok:
            clean = normalize_record(rec)
            accepted.append(clean)
        else:
            rejected.append({"record": rec, "errors": errs})

    report: Dict[str, Any] = {
        "total_candidates": len(candidates),
        "duplicates_skipped": len(dupes),
        "validated_new": len(new_candidates),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "rejection_details": rejected[:10],
        "dry_run": dry_run,
    }

    if accepted and not dry_run:
        merged = existing + accepted
        # Write back to file preserving schema envelope
        data = _read_full_file(outcomes_path)
        data["records"] = merged
        outcomes_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        report["written_to"] = str(outcomes_path)
        report["total_after_ingest"] = len(merged)
        logger.info(
            "Ingested %d new AdCom outcome records → %s (total: %d)",
            len(accepted),
            outcomes_path,
            len(merged),
        )
    elif accepted:
        logger.info("DRY RUN: would ingest %d new AdCom outcome records", len(accepted))
        report["would_ingest"] = [
            {
                "meeting_date": r.get("meeting_date"),
                "committee": r.get("committee"),
                "question_type": r.get("question_type"),
                "vote_yes": r.get("vote_yes"),
                "vote_no": r.get("vote_no"),
                "drug_name": r.get("drug_name", ""),
            }
            for r in accepted
        ]

    return report


def _read_full_file(outcomes_path: Path) -> Dict[str, Any]:
    """Read the full adcom_outcomes.json envelope."""
    if outcomes_path.exists():
        try:
            return json.loads(outcomes_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "schema": OUTCOMES_SCHEMA,
        "description": "Historical FDA Advisory Committee drug-related vote outcomes.",
        "records": [],
    }


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def audit_existing(outcomes_path: Path) -> Dict[str, Any]:
    """Audit existing adcom_outcomes.json for provenance and quality.

    Returns a report with per-record provenance status and gap analysis.
    """
    records = load_existing_outcomes(outcomes_path)
    results: Dict[str, Any] = {
        "total": len(records),
        "with_source_url": 0,
        "with_publication_date": 0,
        "with_source_doc_type": 0,
        "with_full_provenance": 0,
        "with_fda_outcome": 0,
        "with_ticker": 0,
        "gaps": [],
    }

    for rec in records:
        meeting = rec.get("meeting_date", "?")
        committee = rec.get("committee", "?")
        has_url = bool(rec.get("source_url"))
        has_pub = bool(rec.get("publication_date"))
        has_doc_type = bool(rec.get("source_doc_type"))
        has_outcome = bool(rec.get("fda_outcome"))
        has_ticker = bool(rec.get("ticker"))

        if has_url:
            results["with_source_url"] += 1
        if has_pub:
            results["with_publication_date"] += 1
        if has_doc_type:
            results["with_source_doc_type"] += 1
        if has_outcome:
            results["with_fda_outcome"] += 1
        if has_ticker:
            results["with_ticker"] += 1
        if has_url and has_pub and has_doc_type:
            results["with_full_provenance"] += 1
        else:
            gap = {
                "meeting_date": meeting,
                "committee": committee[:50],
                "missing": [],
            }
            if not has_url:
                gap["missing"].append("source_url")
            if not has_pub:
                gap["missing"].append("publication_date")
            if not has_doc_type:
                gap["missing"].append("source_doc_type")
            results["gaps"].append(gap)

    return results


# ---------------------------------------------------------------------------
# Coverage summary
# ---------------------------------------------------------------------------


def coverage_summary(outcomes_path: Path) -> Dict[str, Any]:
    """Compute coverage breakdown by committee, year, and question_type.

    Returns structured summary for evaluating whether enough validated
    rows exist to support empirical posterior scoring.
    """
    records = load_existing_outcomes(outcomes_path)

    by_committee: Counter = Counter()
    by_year: Counter = Counter()
    by_question_type: Counter = Counter()
    by_committee_year: Counter = Counter()
    by_committee_qtype: Counter = Counter()

    favorable_count = 0
    total_votes = 0

    for rec in records:
        committee = rec.get("committee", "UNKNOWN")
        meeting_date = rec.get("meeting_date", "")
        qtype = str(rec.get("question_type", "UNKNOWN")).upper()
        yes = int(rec.get("vote_yes", 0))
        no = int(rec.get("vote_no", 0))

        year = meeting_date[:4] if len(meeting_date) >= 4 else "UNKNOWN"

        by_committee[committee] += 1
        by_year[year] += 1
        by_question_type[qtype] += 1
        by_committee_year[(committee, year)] += 1
        by_committee_qtype[(committee, qtype)] += 1

        if yes + no > 0:
            total_votes += 1
            if yes > no:
                favorable_count += 1

    # Identify cells that meet MIN_OBSERVATIONS for empirical scoring
    from common.adcom_empirical import MIN_OBSERVATIONS

    empirical_ready_cq = {f"{c}|{q}": n for (c, q), n in by_committee_qtype.items() if n >= MIN_OBSERVATIONS}
    empirical_ready_c = {c: n for c, n in by_committee.items() if n >= MIN_OBSERVATIONS}

    return {
        "total_records": len(records),
        "total_with_votes": total_votes,
        "favorable_rate": round(favorable_count / max(total_votes, 1), 3),
        "by_committee": dict(by_committee.most_common()),
        "by_year": dict(sorted(by_year.items())),
        "by_question_type": dict(by_question_type.most_common()),
        "empirical_ready": {
            "committee_question_cells": empirical_ready_cq,
            "committee_cells": empirical_ready_c,
            "n_committee_question_cells": len(empirical_ready_cq),
            "n_committee_cells": len(empirical_ready_c),
            "min_observations": MIN_OBSERVATIONS,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    p = argparse.ArgumentParser(
        description="Provenance-enforced AdCom outcomes importer/normalizer",
    )
    p.add_argument(
        "--outcomes-path",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "adcom_outcomes.json",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "adcom_importer",
    )

    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--validate",
        type=Path,
        metavar="CANDIDATES_JSON",
        help="Validate a candidates JSON file",
    )
    mode.add_argument(
        "--ingest",
        type=Path,
        metavar="CANDIDATES_JSON",
        help="Ingest validated candidates into adcom_outcomes.json",
    )
    mode.add_argument(
        "--audit",
        action="store_true",
        help="Audit existing adcom_outcomes.json for provenance gaps",
    )
    mode.add_argument(
        "--coverage",
        action="store_true",
        help="Show coverage breakdown by committee/year/question_type",
    )

    p.add_argument(
        "--dry-run",
        action="store_true",
        help="With --ingest: validate but don't write",
    )

    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.validate:
        candidates = json.loads(args.validate.read_text(encoding="utf-8"))
        valid, invalid = validate_candidates(candidates)
        print(f"Validated {len(candidates)} candidates:")
        print(f"  Valid:   {len(valid)}")
        print(f"  Invalid: {len(invalid)}")
        if invalid:
            print("\nRejections:")
            for inv in invalid[:10]:
                meeting = inv.get("meeting_date", "?")
                committee = inv.get("committee", "?")[:40]
                errs = inv.get("_errors", [])
                print(f"  {meeting} {committee}: {'; '.join(errs)}")

        report_path = args.output_dir / "validation_report.json"
        report_path.write_text(
            json.dumps({"valid": valid, "invalid": invalid}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nFull report: {report_path}")

    elif args.ingest:
        candidates = json.loads(args.ingest.read_text(encoding="utf-8"))
        report = ingest_candidates(candidates, args.outcomes_path, dry_run=args.dry_run)

        report_path = args.output_dir / "ingest_report.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Ingest report: {report_path}")
        print(f"  Total candidates: {report['total_candidates']}")
        print(f"  Duplicates skipped: {report['duplicates_skipped']}")
        print(f"  Accepted: {report['accepted']}")
        print(f"  Rejected: {report['rejected']}")
        if report.get("dry_run"):
            print("  (DRY RUN — nothing written)")

    elif args.audit:
        report = audit_existing(args.outcomes_path)
        print(f"AdCom Outcomes Audit ({report['total']} records):")
        print(f"  With source_url:          {report['with_source_url']}")
        print(f"  With publication_date:    {report['with_publication_date']}")
        print(f"  With source_doc_type:     {report['with_source_doc_type']}")
        print(f"  Full provenance:          {report['with_full_provenance']}")
        print(f"  With FDA outcome:         {report['with_fda_outcome']}")
        print(f"  With ticker:              {report['with_ticker']}")
        if report["gaps"]:
            print(f"\n  Provenance gaps ({len(report['gaps'])} records):")
            for gap in report["gaps"][:10]:
                print(f"    {gap['meeting_date']} {gap['committee']}: " f"missing {gap['missing']}")

        report_path = args.output_dir / "audit_report.json"
        report_path.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nFull report: {report_path}")

    elif args.coverage:
        summary = coverage_summary(args.outcomes_path)
        print(f"AdCom Outcomes Coverage ({summary['total_records']} records):")
        print(f"  Records with votes: {summary['total_with_votes']}")
        print(f"  Overall favorable rate: {summary['favorable_rate']:.1%}")

        print("\n  By committee:")
        for c, n in summary["by_committee"].items():
            print(f"    {c[:55]:55s} {n:3d}")

        print("\n  By year:")
        for y, n in summary["by_year"].items():
            print(f"    {y}: {n}")

        print("\n  By question type:")
        for q, n in summary["by_question_type"].items():
            print(f"    {q}: {n}")

        emp = summary["empirical_ready"]
        print(f"\n  Empirical scoring readiness (min_observations={emp['min_observations']}):")
        print(f"    Committee+question cells ready: {emp['n_committee_question_cells']}")
        print(f"    Committee cells ready:          {emp['n_committee_cells']}")
        if emp["committee_cells"]:
            print("    Ready committees:")
            for c, n in emp["committee_cells"].items():
                print(f"      {c[:55]:55s} {n:3d} meetings")

        report_path = args.output_dir / "coverage_report.json"
        report_path.write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nFull report: {report_path}")


if __name__ == "__main__":
    main()
