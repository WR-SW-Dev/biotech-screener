"""Empirical AdCom posterior scoring from historical vote outcomes.

Loads adcom_outcomes.json and computes posterior favorable-vote
probabilities using a Beta-Binomial conjugate model:

    posterior = Beta(alpha_prior + yes_votes, beta_prior + no_votes)
    point estimate = E[posterior] = (alpha + yes) / (alpha + yes + beta + no)

Hierarchy (most specific → least specific):
    1. committee + question_type  (if n >= MIN_OBSERVATIONS)
    2. committee                  (if n >= MIN_OBSERVATIONS)
    3. COMMITTEE_BASE_RATES prior (hardcoded fallback)

PIT safety:
    Only outcomes with meeting_date < as_of_date are used.
    This prevents look-ahead: you cannot use a vote result
    before the meeting has occurred.

Provenance policy:
    Every record MUST have source_url, publication_date, and
    source_doc_type to be included in empirical scoring.
    Records without provenance are silently excluded.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Minimum observations to trust the empirical estimate over the prior
MIN_OBSERVATIONS = 3

# Prior strength (pseudo-counts for Beta distribution)
# alpha=7, beta=3 corresponds to a prior of 70% favorable (the default base rate)
# with strength equivalent to 10 observations
PRIOR_ALPHA = 7.0
PRIOR_BETA = 3.0

# Schema version for the outcomes file
OUTCOMES_SCHEMA = "adcom_outcomes.v3"
_ACCEPTED_SCHEMAS = frozenset({"adcom_outcomes.v2", "adcom_outcomes.v3"})

# Required provenance fields — records missing any of these are excluded
PROVENANCE_REQUIRED_FIELDS = ("source_url", "publication_date", "source_doc_type")

# Required data fields — records missing any of these are excluded
DATA_REQUIRED_FIELDS = (
    "meeting_date",
    "committee",
    "question_type",
    "vote_yes",
    "vote_no",
)

# All required fields for a valid record
ALL_REQUIRED_FIELDS = DATA_REQUIRED_FIELDS + PROVENANCE_REQUIRED_FIELDS

# Recognized source_doc_type values
VALID_SOURCE_DOC_TYPES = frozenset(
    {
        "fda_meeting_minutes",
        "federal_register_notice",
        "fda_briefing_document",
        "press_release",
        "published_article",
    }
)


# ---------------------------------------------------------------------------
# Provenance validation
# ---------------------------------------------------------------------------


def validate_record(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a single outcome record for required fields and provenance.

    Returns (is_valid, list_of_error_strings).
    """
    errors: List[str] = []

    if not isinstance(record, dict):
        return False, ["record is not a dict"]

    # Check required fields are present and non-empty
    for field in ALL_REQUIRED_FIELDS:
        val = record.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"missing or empty required field: {field}")

    # Validate source_url looks like a URL
    source_url = record.get("source_url", "")
    if isinstance(source_url, str) and source_url.strip():
        if not (source_url.startswith("http://") or source_url.startswith("https://")):
            errors.append(f"source_url must be http(s) URL, got: {source_url!r}")

    # Validate source_doc_type is recognized
    doc_type = record.get("source_doc_type", "")
    if isinstance(doc_type, str) and doc_type.strip():
        if doc_type not in VALID_SOURCE_DOC_TYPES:
            errors.append(
                f"unrecognized source_doc_type: {doc_type!r}; " f"valid types: {sorted(VALID_SOURCE_DOC_TYPES)}"
            )

    # Validate vote counts are non-negative integers
    for vote_field in ("vote_yes", "vote_no"):
        val = record.get(vote_field)
        if val is not None:
            try:
                iv = int(val)
                if iv < 0:
                    errors.append(f"{vote_field} must be non-negative, got {iv}")
            except (ValueError, TypeError):
                errors.append(f"{vote_field} must be an integer, got {val!r}")

    # Validate date formats (YYYY-MM-DD)
    for date_field in ("meeting_date", "publication_date"):
        val = record.get(date_field, "")
        if isinstance(val, str) and val.strip():
            parts = val.split("-")
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                errors.append(f"{date_field} must be YYYY-MM-DD, got {val!r}")

    return len(errors) == 0, errors


def validate_outcomes_file(
    records: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate all records in an outcomes dataset.

    Returns (valid_records, invalid_records_with_errors).
    Invalid records have an '_errors' key appended.
    """
    valid = []
    invalid = []
    for r in records:
        ok, errs = validate_record(r)
        if ok:
            valid.append(r)
        else:
            inv = dict(r) if isinstance(r, dict) else {"_raw": r}
            inv["_errors"] = errs
            invalid.append(inv)
    return valid, invalid


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_outcomes(
    outcomes_path: Path,
) -> List[Dict[str, Any]]:
    """Load adcom_outcomes.json records.

    Returns only provenance-validated records.  Records that fail
    validation are logged and excluded.
    """
    if not outcomes_path.exists():
        logger.debug("AdCom outcomes file not found: %s", outcomes_path)
        return []
    try:
        data = json.loads(outcomes_path.read_text(encoding="utf-8"))
        if data.get("schema") not in _ACCEPTED_SCHEMAS:
            logger.warning(
                "AdCom outcomes schema mismatch: expected one of %s, got %s",
                sorted(_ACCEPTED_SCHEMAS),
                data.get("schema"),
            )
            return []
        raw_records = data.get("records", [])
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load adcom outcomes: %s", exc)
        return []

    if not raw_records:
        return []

    valid, invalid = validate_outcomes_file(raw_records)
    if invalid:
        logger.warning(
            "AdCom outcomes: %d/%d records failed provenance validation (excluded)",
            len(invalid),
            len(raw_records),
        )
        for inv in invalid[:5]:  # log first 5
            logger.debug("  Invalid record: %s", inv.get("_errors"))
    if valid:
        logger.info(
            "AdCom outcomes: %d provenance-validated records loaded",
            len(valid),
        )
    return valid


# ---------------------------------------------------------------------------
# PIT filtering
# ---------------------------------------------------------------------------


def _filter_pit_safe(
    records: List[Dict[str, Any]],
    as_of_date: str,
) -> List[Dict[str, Any]]:
    """Filter to records with meeting_date strictly before as_of_date (PIT-safe)."""
    return [
        r
        for r in records
        if r.get("meeting_date", "") < as_of_date and r.get("vote_yes") is not None and r.get("vote_no") is not None
    ]


# ---------------------------------------------------------------------------
# Posterior table
# ---------------------------------------------------------------------------


def build_posterior_table(
    records: List[Dict[str, Any]],
    as_of_date: str,
) -> Dict[str, Dict[str, Any]]:
    """Build posterior scoring table from PIT-safe historical records.

    Only provenance-validated records should be passed in (load_outcomes
    handles this).

    Returns a nested dict:
        {
            "committee|question_type": {score, n, basis},
            "committee|*":             {score, n, basis},
        }
    """
    pit_records = _filter_pit_safe(records, as_of_date)

    # Aggregate vote counts
    by_cq: Dict[Tuple[str, str], List[int]] = {}  # [favorable, unfavorable, n]
    by_c: Dict[str, List[int]] = {}

    for r in pit_records:
        committee = r.get("committee", "")
        qtype = r.get("question_type", "")
        yes = int(r.get("vote_yes", 0))
        no = int(r.get("vote_no", 0))
        if yes + no == 0:
            continue

        favorable = 1 if yes > no else 0

        # Committee + question_type level
        key = (committee, qtype)
        if key not in by_cq:
            by_cq[key] = [0, 0, 0]
        by_cq[key][0] += favorable
        by_cq[key][1] += 1 - favorable
        by_cq[key][2] += 1

        # Committee level (all question types)
        if committee not in by_c:
            by_c[committee] = [0, 0, 0]
        by_c[committee][0] += favorable
        by_c[committee][1] += 1 - favorable
        by_c[committee][2] += 1

    table: Dict[str, Dict[str, Any]] = {}

    # Committee + question_type posteriors
    for (committee, qtype), (yes, no, n) in by_cq.items():
        if n >= MIN_OBSERVATIONS:
            alpha = PRIOR_ALPHA + yes
            beta = PRIOR_BETA + no
            score = alpha / (alpha + beta)
            table[f"{committee}|{qtype}"] = {
                "score": round(score, 4),
                "n": n,
                "basis": "empirical_committee_question",
            }

    # Committee-level posteriors
    for committee, (yes, no, n) in by_c.items():
        if n >= MIN_OBSERVATIONS:
            alpha = PRIOR_ALPHA + yes
            beta = PRIOR_BETA + no
            score = alpha / (alpha + beta)
            table[f"{committee}|*"] = {
                "score": round(score, 4),
                "n": n,
                "basis": "empirical_committee",
            }

    return table


def score_empirical(
    committee: str,
    question_type: str,
    posterior_table: Dict[str, Dict[str, Any]],
    fallback_score: float,
) -> Tuple[float, int, str]:
    """Score using the posterior hierarchy.

    Returns (score, n, basis).

    Hierarchy:
        1. committee + question_type (if in table)
        2. committee only (if in table)
        3. fallback_score (committee base rate prior)
    """
    # Level 1: committee + question_type
    key_cq = f"{committee}|{question_type}"
    if key_cq in posterior_table:
        entry = posterior_table[key_cq]
        return entry["score"], entry["n"], entry["basis"]

    # Level 2: committee only
    key_c = f"{committee}|*"
    if key_c in posterior_table:
        entry = posterior_table[key_c]
        return entry["score"], entry["n"], entry["basis"]

    # Level 3: prior
    return fallback_score, 0, "committee_prior"
