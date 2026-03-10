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
from dataclasses import dataclass
from datetime import date as _date
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

# Priority scores for selection (higher = preferred)
_CONFIDENCE_PRIORITY = {"HIGH": 3, "MED": 2, "LOW": 1}
_SOURCE_PRIORITY = {
    "COMPANY_GUIDANCE": 3,
    "SEC_8K": 3,
    "SEC_8K_FILING": 3,
    "FEDERAL_REGISTER": 2,
    "MANUAL": 2,
    "PRESS_RELEASE": 2,
    "ANALYST_ESTIMATE": 1,
    "CTGOV_ESTIMATE": 1,
}


@dataclass(frozen=True)
class CalendarPolicy:
    """Configurable thresholds for calendar quality pruning."""

    max_entries: int = 25
    """Hard cap on entries after pruning."""

    max_coverage_pct: float = 10.0
    """Auto-prune lowest priority entries if coverage exceeds this % of eligible."""

    min_coverage_pct: float = 3.0
    """Below this %, keep all HIGH + best MED (advisory only, no fabrication)."""

    require_disclosed_within_days: int = 90
    """Drop entries missing as_of_disclosed_at if pdufa_date <= as_of_date + this many days."""

    min_proximity_days: int = 0
    """Minimum days to event (entries closer than this get deprioritized)."""

    max_proximity_days: int = 210
    """Maximum days to event considered (entries farther get deprioritized)."""

    preferred_band_lo: int = 15
    """Lower bound of preferred proximity band (bonus priority)."""

    preferred_band_hi: int = 180
    """Upper bound of preferred proximity band (bonus priority)."""


def _compute_entry_priority(rec: Dict[str, Any], as_of_date: str) -> float:
    """Compute a priority score for a calendar entry (higher = keep).

    Components:
    - Confidence: HIGH=3, MED=2, LOW=1
    - Source: COMPANY_GUIDANCE/SEC_8K=3, FEDREG=2, ANALYST/CTGOV=1
    - Proximity band bonus: +2 if in 15-180d sweet spot, +1 if 0-14d, +0 if >180d
    """
    conf = _CONFIDENCE_PRIORITY.get(rec.get("confidence", "MED"), 1)
    src = _SOURCE_PRIORITY.get(rec.get("source", "MANUAL"), 1)

    # Proximity bonus
    proximity_bonus = 0.0
    pdufa = rec.get("pdufa_date", "")
    if pdufa and as_of_date:
        try:
            days = (_date.fromisoformat(pdufa) - _date.fromisoformat(as_of_date)).days
            if 15 <= days <= 180:
                proximity_bonus = 2.0
            elif 0 <= days <= 14:
                proximity_bonus = 1.0
            # >180d or past: 0
        except ValueError:
            pass

    # Tiebreaker: prefer sooner events (smaller date = higher priority)
    # Use small fraction so it only breaks ties
    date_tiebreak = 0.0
    if pdufa:
        try:
            days = (_date.fromisoformat(pdufa) - _date.fromisoformat(as_of_date)).days
            # Normalize: 0 days → 0.9, 365 days → 0.0
            date_tiebreak = max(0.0, (365 - days) / 365.0) * 0.9
        except ValueError:
            pass

    return conf + src + proximity_bonus + date_tiebreak


def select_quality_entries(
    records: List[Dict[str, Any]],
    as_of_date: str,
    n_eligible: int = 0,
    policy: Optional[CalendarPolicy] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Apply quality pruning and priority selection to calendar entries.

    Call AFTER load_and_validate() on PIT-filtered records.

    Parameters
    ----------
    records : PIT-filtered, normalized calendar entries
    as_of_date : YYYY-MM-DD reference date
    n_eligible : number of eligible tickers in universe (for coverage calc).
        If 0, coverage-based pruning is skipped.
    policy : pruning thresholds (defaults to CalendarPolicy())

    Returns
    -------
    (selected, diagnostics) — selected entries sorted by priority desc,
    plus diagnostics dict with pruning counts.
    """
    if policy is None:
        policy = CalendarPolicy()

    diag: Dict[str, Any] = {
        "input_count": len(records),
        "pruned_past_dated": 0,
        "pruned_missing_disclosed": 0,
        "pruned_max_entries": 0,
        "pruned_coverage_cap": 0,
        "output_count": 0,
    }

    try:
        ref = _date.fromisoformat(as_of_date)
    except ValueError:
        diag["output_count"] = len(records)
        return list(records), diag

    # 1. Drop past-dated entries (pdufa_date < as_of_date)
    active: List[Dict[str, Any]] = []
    for rec in records:
        pdufa = rec.get("pdufa_date", "")
        if pdufa and pdufa < as_of_date:
            diag["pruned_past_dated"] += 1
            continue
        active.append(rec)

    # 2. Drop entries missing as_of_disclosed_at if event is within N days
    threshold_date = str(ref + __import__("datetime").timedelta(days=policy.require_disclosed_within_days))
    vetted: List[Dict[str, Any]] = []
    for rec in active:
        disclosed = rec.get("as_of_disclosed_at", "")
        pdufa = rec.get("pdufa_date", "")
        if not disclosed and pdufa and pdufa <= threshold_date:
            diag["pruned_missing_disclosed"] += 1
            continue
        vetted.append(rec)

    # 3. Score and sort by priority (descending)
    scored = [(rec, _compute_entry_priority(rec, as_of_date)) for rec in vetted]
    scored.sort(key=lambda x: x[1], reverse=True)

    # 4. Coverage cap: if n_eligible provided and coverage > max_coverage_pct
    selected = [rec for rec, _ in scored]
    if n_eligible > 0 and policy.max_coverage_pct > 0:
        # Count unique tickers
        max_tickers = int(n_eligible * policy.max_coverage_pct / 100.0)
        if max_tickers < 1:
            max_tickers = 1
        tickers_seen: set = set()
        coverage_capped: List[Dict[str, Any]] = []
        for rec in selected:
            t = rec["ticker"]
            if t not in tickers_seen:
                if len(tickers_seen) >= max_tickers:
                    diag["pruned_coverage_cap"] += 1
                    continue
                tickers_seen.add(t)
            coverage_capped.append(rec)
        selected = coverage_capped

    # 5. max_entries hard cap
    if len(selected) > policy.max_entries:
        diag["pruned_max_entries"] = len(selected) - policy.max_entries
        selected = selected[: policy.max_entries]

    diag["output_count"] = len(selected)
    diag["unique_tickers"] = len({r["ticker"] for r in selected})
    if n_eligible > 0:
        diag["coverage_pct"] = round(diag["unique_tickers"] / max(n_eligible, 1) * 100, 1)

    return selected, diag


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


def get_calendar_telemetry(
    records: List[Dict[str, Any]],
    selection_diag: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build telemetry dict for snapshot metadata.

    Parameters
    ----------
    records : the final used calendar entries
    selection_diag : optional diagnostics from select_quality_entries()
    """
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
    result = {
        "manual_calendar_loaded": len(records) > 0,
        "manual_calendar_n_records": len(records),
        "manual_calendar_by_event_type": type_counts,
        "manual_calendar_by_confidence": conf_counts,
        "manual_calendar_by_source": source_counts,
    }
    if selection_diag:
        result["quality_selection"] = selection_diag
    return result
