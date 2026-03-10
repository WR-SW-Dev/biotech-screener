"""Loader + validator for the forward regulatory calendar (pdufa_dates.json).

Supports both old schema (pre-v2, curated_disclosed_at may be null) and new
schema (as_of_disclosed_at required for PIT safety).  Old-schema records with
no disclosed_at are treated as confidence=LOW and included only when
``include_undated=True``.

Schema v2 fields per record:
    ticker              str   required
    pdufa_date          str   required  YYYY-MM-DD
    event_type          str   optional  canonical: PDUFA, DUFA, AdCom, CHMP_OPINION, FDA_DECISION
    source              str   optional  MANUAL, COMPANY_GUIDANCE, SEC_8K, PRESS_RELEASE, ANALYST_ESTIMATE
    source_url          str   optional
    as_of_disclosed_at  str   optional  YYYY-MM-DD (PIT anchor)
    confidence          str   optional  HIGH, MED, LOW (default MED)
    notes               str   optional
    program             str   optional  drug name / indication
    drug_name           str   optional  (old schema compat)
    indication          str   optional  (old schema compat)
    submission_type     str   optional  (old schema compat: NDA, BLA, sNDA, sBLA)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Canonical event types (normalized from free-text)
CANONICAL_EVENT_TYPES = frozenset(
    {
        "PDUFA",
        "DUFA",
        "AdCom",
        "CHMP_OPINION",
        "FDA_DECISION",
        "EMA_DECISION",
        "FDA_APPROVAL",
        "FDA_CRL",
    }
)

# Old confidence values → new mapping
_CONFIDENCE_MAP = {
    "confirmed": "HIGH",
    "estimated": "MED",
    "high": "HIGH",
    "med": "MED",
    "low": "LOW",
    "HIGH": "HIGH",
    "MED": "MED",
    "LOW": "LOW",
}

# Old source values → new mapping
_SOURCE_MAP = {
    "company_guidance": "COMPANY_GUIDANCE",
    "analyst_estimate": "ANALYST_ESTIMATE",
    "manual": "MANUAL",
    "sec_8k": "SEC_8K",
    "press_release": "PRESS_RELEASE",
    "COMPANY_GUIDANCE": "COMPANY_GUIDANCE",
    "ANALYST_ESTIMATE": "ANALYST_ESTIMATE",
    "MANUAL": "MANUAL",
    "SEC_8K": "SEC_8K",
    "PRESS_RELEASE": "PRESS_RELEASE",
}


def load_regulatory_calendar(
    path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Load the regulatory calendar JSON file.

    Tries ``path`` first, then ``data_dir/pdufa_dates.json``, then the
    default ``production_data/pdufa_dates.json``.  Returns raw dicts.
    """
    candidates: List[Path] = []
    if path:
        candidates.append(Path(path))
    if data_dir:
        candidates.append(Path(data_dir) / "pdufa_dates.json")
    candidates.append(Path(__file__).resolve().parent.parent / "production_data" / "pdufa_dates.json")

    for p in candidates:
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    logger.info("MANUAL_REG_CAL: loaded %d records from %s", len(raw), p)
                    return raw
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("regulatory_calendar: failed to read %s: %s", p, exc)
    return []


def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a single record to v2 schema.

    Preserves all original fields; adds/overwrites canonical fields.
    """
    out = dict(rec)

    # Normalize confidence
    raw_conf = str(rec.get("confidence", "MED")).strip()
    out["confidence"] = _CONFIDENCE_MAP.get(raw_conf, "MED")

    # Normalize source
    raw_src = str(rec.get("source", "MANUAL")).strip()
    out["source"] = _SOURCE_MAP.get(raw_src, raw_src.upper())

    # Normalize event_type (default PDUFA for old schema)
    raw_et = rec.get("event_type", "")
    if not raw_et:
        out["event_type"] = "PDUFA"
    else:
        out["event_type"] = raw_et

    # Resolve disclosed_at: prefer as_of_disclosed_at, fall back to curated_disclosed_at
    disclosed = rec.get("as_of_disclosed_at") or rec.get("curated_disclosed_at") or ""
    out["as_of_disclosed_at"] = disclosed if disclosed else ""

    # Build program from drug_name + indication if not set
    if not out.get("program"):
        parts = []
        if rec.get("drug_name"):
            parts.append(rec["drug_name"])
        if rec.get("indication"):
            parts.append(rec["indication"])
        if parts:
            out["program"] = " — ".join(parts)

    return out


def validate_record(rec: Dict[str, Any]) -> List[str]:
    """Validate a single normalized record.  Returns list of error strings."""
    errors: List[str] = []
    ticker = rec.get("ticker", "")
    if not ticker:
        errors.append("missing ticker")
    pdufa_date = rec.get("pdufa_date", "")
    if not pdufa_date:
        errors.append(f"{ticker}: missing pdufa_date")
    elif not _DATE_RE.match(pdufa_date):
        errors.append(f"{ticker}: invalid pdufa_date format '{pdufa_date}'")
    disclosed = rec.get("as_of_disclosed_at", "")
    if disclosed and not _DATE_RE.match(disclosed):
        errors.append(f"{ticker}: invalid as_of_disclosed_at format '{disclosed}'")
    return errors


def load_and_validate(
    path: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    as_of_date: Optional[str] = None,
    include_undated: bool = True,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Load, normalize, validate, PIT-filter, and dedupe.

    Parameters
    ----------
    path : optional explicit path to JSON file
    data_dir : optional directory containing pdufa_dates.json
    as_of_date : YYYY-MM-DD for PIT filtering.  If set, only records with
        as_of_disclosed_at <= as_of_date (or undated if include_undated) pass.
    include_undated : whether to include records missing as_of_disclosed_at
        (old schema).  Default True for backward compat.

    Returns
    -------
    (records, errors) — records are normalized + filtered; errors are
    validation issues (non-fatal, reported for audit).
    """
    raw = load_regulatory_calendar(path=path, data_dir=data_dir)
    all_errors: List[str] = []
    normalized: List[Dict[str, Any]] = []

    for i, rec in enumerate(raw):
        if not isinstance(rec, dict):
            all_errors.append(f"record {i}: not a dict")
            continue
        norm = normalize_record(rec)
        errs = validate_record(norm)
        if errs:
            all_errors.extend(errs)
            continue
        normalized.append(norm)

    # PIT filter
    if as_of_date:
        pit_filtered: List[Dict[str, Any]] = []
        for rec in normalized:
            disclosed = rec.get("as_of_disclosed_at", "")
            if disclosed:
                if disclosed <= as_of_date:
                    pit_filtered.append(rec)
            elif include_undated:
                pit_filtered.append(rec)
        normalized = pit_filtered

    # Dedupe by (ticker, pdufa_date, event_type) — keep first occurrence
    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    dupes: List[str] = []
    for rec in normalized:
        key = (rec["ticker"], rec["pdufa_date"], rec.get("event_type", "PDUFA"))
        if key in seen:
            dupes.append(f"duplicate: {key}")
            continue
        seen.add(key)
        deduped.append(rec)

    if dupes:
        all_errors.extend(dupes)

    pit_label = f" (PIT <= {as_of_date})" if as_of_date else ""
    logger.info(
        "MANUAL_REG_CAL: loaded=%d pit_eligible=%d flagged_eligible=%d%s",
        len(raw),
        len(deduped),
        len(deduped),
        pit_label,
    )

    return deduped, all_errors


def get_calendar_telemetry(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build telemetry dict for snapshot metadata."""
    type_counts: Dict[str, int] = {}
    conf_counts: Dict[str, int] = {}
    source_counts: Dict[str, int] = {}
    for rec in records:
        et = rec.get("event_type", "PDUFA")
        type_counts[et] = type_counts.get(et, 0) + 1
        conf = rec.get("confidence", "MED")
        conf_counts[conf] = conf_counts.get(conf, 0) + 1
        src = rec.get("source", "MANUAL")
        source_counts[src] = source_counts.get(src, 0) + 1
    return {
        "manual_calendar_loaded": len(records) > 0,
        "manual_calendar_n_records": len(records),
        "manual_calendar_by_event_type": type_counts,
        "manual_calendar_by_confidence": conf_counts,
        "manual_calendar_by_source": source_counts,
    }
