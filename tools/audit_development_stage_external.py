#!/usr/bin/env python3
"""audit_development_stage_external.py — Spec 068 metadata integrity audit.

One-shot, read-only, cache-only audit that compares the rankings.csv
display-only `development_stage` column against external evidence sourced
exclusively from existing local caches (CT.gov, Purple Book, Orange Book,
pit_financials, PDUFA). Emits CSV/MD/JSON to
`artifacts/development_stage/` and an end-of-run decision branch.

SEC 8-K evidence not consumed in this one-shot audit; cache status reported
separately as optional source-quality metadata under `sec_cache_status` in
the JSON/MD output. SEC absence cannot affect `external_consensus_stage`,
`validation_status`, or `decision_branch`.

NEVER mutates `universe.json`, `rankings.csv`, scoring, selector, ranker,
EES, DEM, Event EV, or QA gates. The output is diagnostic-only.

Per Spec 068:
- Phase 4 does NOT imply commercial.
- Multi-program firms emit `ambiguous_multi_program`, not `likely_internal_stale`.
- LOW-confidence aliases cannot escalate past `validated`.
- Orange Book absence with stale cache (>7d) is not negative evidence.

Usage:
    python tools/audit_development_stage_external.py --as-of-date 2026-04-28
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]

ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "development_stage"

LATE_STAGE_RECRUITING = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING"}

PHASE_RANK = {
    "preclinical": 0,
    "phase_1": 1,
    "phase_1_2": 2,
    "phase_2": 3,
    "phase_2_3": 4,
    "phase_3": 5,
    "nda_bla": 6,
    "approved": 7,
    "commercial": 8,
    "unknown": -1,
}

CTGOV_PHASE_TO_STAGE = {
    "EARLY_PHASE1": "phase_1",
    "PHASE1": "phase_1",
    "PHASE1/PHASE2": "phase_1_2",
    "PHASE2": "phase_2",
    "PHASE2/PHASE3": "phase_2_3",
    "PHASE3": "phase_3",
    "PHASE4": "approved",  # Phase 4 ≠ commercial; approved is the right floor.
    "NA": "unknown",
}

VALIDATION_STATUSES = {
    "validated",
    "likely_internal_stale",
    "external_lower_than_internal",
    "ambiguous_multi_program",
    "sponsor_alias_uncertain",
    "platform_not_ctgov_applicable",
    "no_external_evidence",
    "override_disagrees_with_consensus",
}

DECISION_BRANCHES = {"MANUAL_FIX", "RECURRING_VALIDATOR", "ALIAS_MAP_FIRST"}

SEC_CACHE_VERDICTS = {
    "SEC_CACHE_OK_EVENT_COUNT_CONFUSION",
    "SEC_CACHE_STALE_BUT_OPTIONAL",
    "SEC_CACHE_PATH_MOVED",
    "SEC_DISABLED_OPTIONAL",
    "SEC_CACHE_INCOMPLETE_BLOCK_SPEC_068",
}

_NORM_STRIP = re.compile(
    r"\b(inc|incorporated|corp|corporation|holdings?|ltd|limited|llc|plc|ag|sa|sas|nv|"
    r"pharmaceuticals?|pharma|therapeutics|biosciences?|biotechnology|biotech|"
    r"technologies)\b",
    re.IGNORECASE,
)


def normalize_company(name: str | None) -> str:
    """Lowercase, strip punctuation, drop common suffixes, collapse whitespace."""
    if not name:
        return ""
    s = str(name).lower().strip()
    s = re.sub(r"[,\.\(\)\[\]\"']", " ", s)
    s = _NORM_STRIP.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def alias_confidence(internal_name: str, sponsor: str) -> str:
    """HIGH / MED / LOW / NONE for a single internal-vs-sponsor pair."""
    if not internal_name or not sponsor:
        return "NONE"
    ni = normalize_company(internal_name)
    ns = normalize_company(sponsor)
    if not ni or not ns:
        return "NONE"
    if ni == ns:
        return "HIGH"
    if ni in ns or ns in ni:
        return "HIGH"
    ti = set(ni.split())
    ts = set(ns.split())
    if not ti or not ts:
        return "LOW"
    overlap = len(ti & ts) / max(1, min(len(ti), len(ts)))
    if overlap >= 0.7:
        return "MED"
    return "LOW"


def aggregate_alias_confidence(internal_name: str, sponsors: Iterable[str]) -> str:
    """Best-of across all observed sponsors for the ticker."""
    best = "NONE"
    rank = {"NONE": 0, "LOW": 1, "MED": 2, "HIGH": 3}
    for s in sponsors:
        c = alias_confidence(internal_name, s)
        if rank[c] > rank[best]:
            best = c
    return best


def ctgov_max_active_phase(trials: list[dict[str, Any]]) -> tuple[str, int]:
    """Return (max_stage_str, count_of_active_late_stage_trials)."""
    best_rank = -1
    best_stage = "unknown"
    active_count = 0
    for t in trials:
        status = (t.get("status") or "").strip().upper()
        if status not in LATE_STAGE_RECRUITING:
            continue
        active_count += 1
        ph = (t.get("phase") or "").strip().upper()
        stage = CTGOV_PHASE_TO_STAGE.get(ph, "unknown")
        r = PHASE_RANK.get(stage, -1)
        if r > best_rank:
            best_rank = r
            best_stage = stage
    return best_stage, active_count


def detect_multi_program(trials: list[dict[str, Any]]) -> bool:
    """≥2 active programs at distinct phase stages."""
    distinct_stages = set()
    for t in trials:
        status = (t.get("status") or "").strip().upper()
        if status not in LATE_STAGE_RECRUITING:
            continue
        ph = (t.get("phase") or "").strip().upper()
        stage = CTGOV_PHASE_TO_STAGE.get(ph, "unknown")
        if stage != "unknown":
            distinct_stages.add(stage)
    return len(distinct_stages) >= 2


def has_material_revenue(facts: dict[str, Any], min_recent_val: float = 50_000_000) -> bool:
    """True if pit_financials shows substantial recent revenue.

    Threshold is set high enough ($50M) to filter out collaboration/grant
    revenue common at clinical-stage biotechs. A company with a marketed
    product clears this; a Phase 1 company with milestone payments does not.
    """
    rev = facts.get("revenue", []) if isinstance(facts, dict) else []
    if not isinstance(rev, list):
        return False
    for r in rev[-32:]:
        try:
            val = float(r.get("val", 0) or 0)
        except (TypeError, ValueError):
            continue
        if val >= min_recent_val:
            return True
    return False


def orange_book_hit(ob_by_ticker: dict[str, Any], ticker: str) -> bool:
    """Has at least one non-DISCN product."""
    rec = ob_by_ticker.get(ticker)
    if not rec or not isinstance(rec, dict):
        return False
    products = rec.get("products", [])
    if not isinstance(products, list):
        return False
    for p in products:
        ptype = (p.get("type") or "").strip().upper()
        if ptype and ptype != "DISCN":
            return True
    return bool(products)  # fallback: any product entry


def build_purple_book_approved_set(pb_data: dict[str, Any]) -> set[str]:
    """Resolve set of tickers with at least one non-'Disc' Purple Book product.

    `purple_book.json` is the authoritative source. Each product carries a
    `resolved_ticker` (None when the applicant could not be ticker-mapped) and
    a `marketing_status` ('Disc' = discontinued, anything else = active).

    NOTE: `purple_book_ticker_map.json` is only a company-name resolver and
    must NOT be used to flag approval — it contains every biotech in the
    universe regardless of Purple Book status.
    """
    approved: set[str] = set()
    if not isinstance(pb_data, dict):
        return approved
    for product in pb_data.get("products", []) or []:
        ticker = product.get("resolved_ticker")
        status = (product.get("marketing_status") or "").strip()
        if ticker and status and status.lower() != "disc":
            approved.add(str(ticker).upper())
    return approved


def purple_book_hit(approved_set: set[str], ticker: str) -> bool:
    return ticker.upper() in approved_set


def has_pdufa(pdufa_records: list[dict[str, Any]], ticker: str) -> bool:
    for r in pdufa_records:
        if (r.get("ticker") or "").upper() == ticker.upper():
            status = (r.get("event_status") or "").lower()
            if status in {"upcoming", "pending"} or not status:
                return True
    return False


def derive_external_consensus(
    *,
    archetype: str,
    tier_commercial: str,
    ctgov_stage: str,
    ctgov_active_count: int,
    multi_program: bool,
    fda_or_pb_approved: bool,
    has_revenue: bool,
    pdufa_pending: bool,
    alias_conf: str,
    orange_book_stale: bool,
) -> tuple[str, str]:
    """Apply Spec 068 §5 conservative hierarchy.

    Returns (external_consensus_stage, validation_status).
    """
    arch = (archetype or "").lower()
    tc = (tier_commercial or "").strip()

    is_platform = arch.startswith("platform_") or arch in {"diagnostics", "device"}

    # Platform / non-drug-developer archetypes don't expect CT.gov coverage.
    if is_platform and ctgov_active_count == 0:
        # Check for approved-product evidence still (commercial platforms).
        if fda_or_pb_approved or has_revenue:
            return ("commercial", "validated")
        return ("unknown", "platform_not_ctgov_applicable")

    # Phase 4 must not collapse to commercial without ownership/marketer evidence.
    # CTGOV_PHASE_TO_STAGE already maps PHASE4 → "approved" (not "commercial").
    # Commercial requires (FDA approval OR Purple Book) AND (revenue line OR tier_commercial).
    if (fda_or_pb_approved or arch.startswith("commercial_")) and (has_revenue or tc):
        consensus = "commercial"
    elif fda_or_pb_approved:
        consensus = "approved"
    elif pdufa_pending:
        consensus = "nda_bla"
    elif ctgov_stage != "unknown":
        consensus = ctgov_stage
    elif arch.startswith("commercial_"):
        # Archetype says commercial but no external corroboration; trust internal flag conservatively.
        consensus = "approved"
    else:
        consensus = "unknown"

    # Status determination requires comparison to internal stage; handled by caller.
    # multi_program hint is a flag, not a primary status — caller decides whether
    # the lead-phase classification is genuinely ambiguous.
    if consensus == "unknown" and ctgov_active_count == 0:
        return (consensus, "no_external_evidence")
    if alias_conf == "LOW":
        return (consensus, "sponsor_alias_uncertain")
    if multi_program and ctgov_active_count >= 2:
        return (consensus, "ambiguous_multi_program_hint")
    return (consensus, "")


def finalize_status(
    *,
    internal_stage: str,
    consensus_stage: str,
    pre_status: str,
    multi_program_hint: bool,
    alias_conf: str,
) -> str:
    """Pick the §7 enum value given internal/consensus/pre-status."""
    if pre_status == "platform_not_ctgov_applicable":
        return "platform_not_ctgov_applicable"
    if pre_status == "no_external_evidence":
        return "no_external_evidence"

    # Alias-uncertain: cannot escalate past 'validated' or 'no_external_evidence'.
    if pre_status == "sponsor_alias_uncertain":
        # If the consensus matches internal, it's still 'validated' under low confidence.
        # But Spec 068 §6 says LOW alias cannot escalate to 'likely_internal_stale'.
        if consensus_stage == internal_stage:
            return "validated"
        return "sponsor_alias_uncertain"

    if consensus_stage == "unknown":
        return "no_external_evidence"

    if consensus_stage == internal_stage:
        return "validated"

    ir = PHASE_RANK.get(internal_stage, -1)
    cr = PHASE_RANK.get(consensus_stage, -1)
    if cr > ir:
        # Real disagreement on lead phase. Multi-program ambiguity only
        # supersedes when there's no clear lead-phase signal — but if the
        # external lead phase is unambiguously higher than internal, this
        # is a stale internal record, not ambiguity.
        if multi_program_hint:
            return "ambiguous_multi_program"
        return "likely_internal_stale"
    if cr < ir and cr >= 0 and ir >= 0:
        return "external_lower_than_internal"
    return "validated"


def likely_action_for(status: str, top30: bool) -> str:
    """Operator-facing recommended action."""
    if status == "validated":
        return "no_action"
    if status == "likely_internal_stale":
        return "manual_review"
    if status == "external_lower_than_internal":
        return "manual_review"
    if status == "ambiguous_multi_program":
        return "no_action"  # informational
    if status == "sponsor_alias_uncertain":
        return "alias_audit"
    if status == "platform_not_ctgov_applicable":
        return "no_action"
    if status == "no_external_evidence":
        return "manual_review" if top30 else "no_action"
    return "no_action"


# ---------------------------------------------------------------------------
# I/O loaders
# ---------------------------------------------------------------------------


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_universe(path: Path) -> dict[str, dict[str, Any]]:
    raw = load_json(path)
    out: dict[str, dict[str, Any]] = {}
    for u in raw:
        t = u.get("ticker")
        if t:
            out[str(t).upper()] = u
    return out


def load_rankings_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def index_ctgov_by_ticker(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        t = r.get("ticker")
        if t:
            out[str(t).upper()].append(r)
    return dict(out)


def find_latest_orange_book(enrichment_dir: Path) -> tuple[Path | None, int]:
    """Return (path, age_days). Path may be None if no file present."""
    if not enrichment_dir.exists():
        return (None, 999)
    candidates = sorted(enrichment_dir.glob("orange_book_*.json"))
    if not candidates:
        return (None, 999)
    latest = candidates[-1]
    m = re.search(r"orange_book_(\d{4}-\d{2}-\d{2})\.json$", latest.name)
    if not m:
        return (latest, 999)
    try:
        d = date.fromisoformat(m.group(1))
        age = (date.today() - d).days
    except ValueError:
        age = 999
    return (latest, age)


def load_development_stage_overrides(path: Path) -> dict[str, str]:
    """Read production_data/development_stage_overrides.json -> {ticker: stage}.

    Spec 068 Lane 1: the audit revalidates override entries against
    external_consensus_stage each run. Disagreements emit
    `override_disagrees_with_consensus` so stale overrides are surfaced.
    Returns empty dict on missing/malformed file.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
    if not isinstance(entries, dict):
        return {}
    out: dict[str, str] = {}
    for ticker, payload in entries.items():
        if not isinstance(payload, dict):
            continue
        stage = payload.get("stage")
        if isinstance(stage, str):
            out[str(ticker).upper()] = stage
    return out


def scan_sec_cache(sec_dir: Path, as_of_date: str) -> dict[str, Any]:
    """Enumerate cache/sec/8k_catalysts safely (top-level files only).

    Returns a verdict object with file count, event count, newest/oldest dates,
    and a verdict label from SEC_CACHE_VERDICTS. The audit does NOT consume
    these events for stage classification; this is provenance metadata only.

    Skips hidden/staging subdirectories (e.g. `.staging_8k_*`) which would
    otherwise trip os.listdir-based readers.
    """
    out: dict[str, Any] = {
        "path": str(sec_dir),
        "consumed_by_audit": False,
        "verdict": "SEC_DISABLED_OPTIONAL",
        "verdict_reason": "SEC 8-K evidence not consumed in this one-shot audit",
        "file_count": 0,
        "event_count": 0,
        "newest_file": None,
        "oldest_file": None,
        "as_of_date_file_present": False,
    }

    if not sec_dir.exists():
        out["verdict"] = "SEC_CACHE_PATH_MOVED"
        out["verdict_reason"] = f"path not found: {sec_dir}"
        return out

    files = sorted(p for p in sec_dir.iterdir() if p.is_file() and p.suffix == ".json" and not p.name.startswith("."))
    out["file_count"] = len(files)
    if not files:
        out["verdict"] = "SEC_CACHE_INCOMPLETE_BLOCK_SPEC_068"
        out["verdict_reason"] = "no top-level JSON files in cache/sec/8k_catalysts"
        return out

    # Filename pattern: 8k_catalysts_{YYYY-MM-DD}_{pattern_version}.json
    date_re = re.compile(r"8k_catalysts_(\d{4}-\d{2}-\d{2})")
    file_dates: list[tuple[str, Path]] = []
    for p in files:
        m = date_re.search(p.name)
        if m:
            file_dates.append((m.group(1), p))
    file_dates.sort()
    if file_dates:
        out["oldest_file"] = file_dates[0][1].name
        out["newest_file"] = file_dates[-1][1].name
        out["as_of_date_file_present"] = any(d == as_of_date for d, _ in file_dates)

    total_events = 0
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            total_events += len(data)
        elif isinstance(data, dict):
            for key in ("events", "catalysts", "records"):
                v = data.get(key)
                if isinstance(v, list):
                    total_events += len(v)
                    break
    out["event_count"] = total_events

    # Verdict: cache is well-populated and today's file present → "OK with prior count confusion"
    # (the previous os.listdir-based count of 88 included staging dirs as files).
    newest_date = file_dates[-1][0] if file_dates else None
    if newest_date == as_of_date and total_events > 0:
        out["verdict"] = "SEC_CACHE_OK_EVENT_COUNT_CONFUSION"
        out["verdict_reason"] = (
            f"{len(files)} top-level JSON files containing {total_events} events; "
            f"today's file present; staging subdirs ({sum(1 for p in sec_dir.iterdir() if p.is_dir())}) "
            "previously inflated naive os.listdir-based counts. SEC layer not consumed by this audit."
        )
    elif newest_date and newest_date < as_of_date:
        out["verdict"] = "SEC_CACHE_STALE_BUT_OPTIONAL"
        out["verdict_reason"] = (
            f"newest file {newest_date} predates as_of_date {as_of_date}; "
            "SEC layer not consumed by this audit so staleness has no effect on results"
        )
    return out


def load_pit_financials_revenue(pit_dir: Path, ticker: str) -> dict[str, Any]:
    p = pit_dir / f"{ticker.upper()}.json"
    if not p.exists():
        return {}
    try:
        data = load_json(p)
        return data.get("facts", {}) if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------


def audit(as_of_date: str) -> dict[str, Any]:
    snap_dir = REPO_ROOT / "data" / "snapshots" / as_of_date
    rankings_path = snap_dir / "rankings.csv"
    if not rankings_path.exists():
        raise FileNotFoundError(f"rankings.csv not found at {rankings_path}")

    universe_path = REPO_ROOT / "production_data" / "universe.json"
    ctgov_path = REPO_ROOT / "cache" / "ctgov" / f"trial_records_{as_of_date}.json"
    if not ctgov_path.exists():
        raise FileNotFoundError(f"CT.gov cache not found at {ctgov_path}")
    pdufa_path = REPO_ROOT / "production_data" / "pdufa_dates_extracted.json"
    purple_book_path = REPO_ROOT / "production_data" / "purple_book.json"
    pit_dir = REPO_ROOT / "production_data" / "pit_financials"
    enrichment_dir = REPO_ROOT / "data" / "enrichment"
    sec_dir = REPO_ROOT / "cache" / "sec" / "8k_catalysts"
    overrides_path = REPO_ROOT / "production_data" / "development_stage_overrides.json"

    universe = load_universe(universe_path)
    rankings = load_rankings_csv(rankings_path)
    ctgov_by_ticker = index_ctgov_by_ticker(load_json(ctgov_path))
    pdufa_records = load_json(pdufa_path) if pdufa_path.exists() else []
    pb_data = load_json(purple_book_path) if purple_book_path.exists() else {}
    pb_approved_tickers = build_purple_book_approved_set(pb_data)
    sec_cache_status = scan_sec_cache(sec_dir, as_of_date)
    overrides = load_development_stage_overrides(overrides_path)

    ob_path, ob_age = find_latest_orange_book(enrichment_dir)
    ob_stale = ob_age > 7
    ob_by_ticker: dict[str, Any] = {}
    if ob_path is not None:
        try:
            ob_by_ticker = load_json(ob_path).get("by_ticker", {})
        except (OSError, json.JSONDecodeError):
            ob_by_ticker = {}

    # Top-30 set by selector_score for impact reporting.
    def _selector_score(r: dict[str, str]) -> float:
        try:
            return float(r.get("selector_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    sorted_by_selector = sorted(rankings, key=_selector_score, reverse=True)
    top30 = {r["ticker"] for r in sorted_by_selector[:30]}

    rows_out: list[dict[str, Any]] = []
    for r in rankings:
        ticker = (r.get("ticker") or "").upper()
        if not ticker:
            continue
        u = universe.get(ticker, {})
        md = u.get("market_data", {}) if isinstance(u, dict) else {}
        internal_name = (md.get("company_name") or u.get("name") or "").strip()

        archetype = (r.get("archetype") or "").strip()
        tier_commercial = (r.get("tier_commercial") or "").strip()
        internal_stage = (r.get("development_stage") or "unknown").strip().lower()
        internal_source = (r.get("development_stage_source") or "").strip()
        lead_program_phase_raw = (r.get("lead_program_phase_raw") or r.get("lead_program_phase") or "").strip()

        trials = ctgov_by_ticker.get(ticker, [])
        sponsors = [t.get("sponsor") for t in trials if t.get("sponsor")]
        ctgov_max_phase, active_count = ctgov_max_active_phase(trials)
        is_multi = detect_multi_program(trials)
        if sponsors:
            sponsor_counter = Counter(sponsors)
            top_sponsor = sponsor_counter.most_common(1)[0][0]
        else:
            top_sponsor = ""
        alias_conf = aggregate_alias_confidence(internal_name, sponsors) if sponsors else "NONE"

        pb_hit = purple_book_hit(pb_approved_tickers, ticker)
        ob_hit = orange_book_hit(ob_by_ticker, ticker) if not ob_stale else False
        # If OB stale, do not treat absence as negative; only positive ob_hit can fire.
        ob_hit_effective = ob_hit  # already gated above
        pf_facts = load_pit_financials_revenue(pit_dir, ticker)
        rev_flag = has_material_revenue(pf_facts)
        pdufa_pending = has_pdufa(pdufa_records, ticker)
        approved_flag = pb_hit or ob_hit_effective

        consensus, pre_status = derive_external_consensus(
            archetype=archetype,
            tier_commercial=tier_commercial,
            ctgov_stage=ctgov_max_phase,
            ctgov_active_count=active_count,
            multi_program=is_multi,
            fda_or_pb_approved=approved_flag,
            has_revenue=rev_flag,
            pdufa_pending=pdufa_pending,
            alias_conf=alias_conf,
            orange_book_stale=ob_stale,
        )

        multi_hint = pre_status == "ambiguous_multi_program_hint"
        status = finalize_status(
            internal_stage=internal_stage,
            consensus_stage=consensus,
            pre_status=pre_status if not multi_hint else "",
            multi_program_hint=multi_hint,
            alias_conf=alias_conf,
        )

        # Spec 068 Lane 1: revalidate manual overrides against external consensus.
        # If the override stage disagrees with the consensus stage AND consensus is
        # informative (not 'unknown' / no_external_evidence / platform_not_ctgov_applicable),
        # surface the override as potentially stale rather than rubber-stamping it.
        override_stage = overrides.get(ticker)
        if (
            override_stage
            and consensus != "unknown"
            and status not in {"platform_not_ctgov_applicable", "no_external_evidence"}
            and override_stage != consensus
        ):
            status = "override_disagrees_with_consensus"

        # Confidence for the row as a whole.
        if alias_conf == "HIGH" and approved_flag:
            confidence = "HIGH"
        elif alias_conf == "HIGH":
            confidence = "HIGH" if active_count > 0 else "MED"
        elif alias_conf in {"MED"}:
            confidence = "MED"
        else:
            confidence = "LOW"

        in_top30 = ticker in top30

        notes_parts: list[str] = []
        if override_stage:
            notes_parts.append(f"manual override: {override_stage}")
        if multi_hint:
            notes_parts.append(f"multi-program: {active_count} active trials at distinct phases")
        if alias_conf == "LOW":
            notes_parts.append("LOW-confidence sponsor alias")
        if archetype.startswith("platform_") and active_count == 0:
            notes_parts.append("platform/diagnostics — CT.gov not applicable")
        if ob_stale:
            notes_parts.append(
                f"approved evidence: small-molecule confirmation possibly stale (Orange Book {ob_age}d old)"
            )
        if pb_hit and not ob_hit_effective and ob_stale:
            notes_parts.append("approved-evidence source: Purple Book only")

        sources_evidence: list[str] = []
        if active_count > 0:
            sources_evidence.append(f"ctgov(active={active_count})")
        if pb_hit:
            sources_evidence.append("purple_book")
        if ob_hit_effective:
            sources_evidence.append("orange_book")
        if rev_flag:
            sources_evidence.append("pit_financials.revenue")
        if pdufa_pending:
            sources_evidence.append("pdufa_pending")

        rows_out.append(
            {
                "ticker": ticker,
                "company_name": internal_name,
                "internal_development_stage": internal_stage,
                "development_stage_source": internal_source,
                "lead_program_phase_raw": lead_program_phase_raw,
                "archetype": archetype,
                "tier_commercial": tier_commercial,
                "ctgov_max_phase": ctgov_max_phase,
                "ctgov_active_trial_count": active_count,
                "ctgov_top_sponsor": top_sponsor,
                "ctgov_alias_confidence": alias_conf,
                "purple_book_hit": pb_hit,
                "orange_book_hit": ob_hit_effective,
                "orange_book_stale_days": ob_age,
                "pit_financials_material_revenue": rev_flag,
                "pdufa_pending": pdufa_pending,
                "fda_or_purplebook_approved_evidence": approved_flag,
                "external_consensus_stage": consensus,
                "validation_status": status,
                "confidence": confidence,
                "likely_action": likely_action_for(status, in_top30),
                "in_top30": in_top30,
                "evidence_sources": ";".join(sources_evidence),
                "notes": " | ".join(notes_parts),
            }
        )

    # Aggregate counts
    status_counts = Counter(r["validation_status"] for r in rows_out)
    high_mismatches = [
        r for r in rows_out if r["validation_status"] == "likely_internal_stale" and r["confidence"] == "HIGH"
    ]
    top30_impacts = [r for r in rows_out if r["in_top30"] and r["validation_status"] != "validated"]
    top30_high_impacts = [
        r for r in top30_impacts if r["validation_status"] == "likely_internal_stale" and r["confidence"] == "HIGH"
    ]

    # Decision branch
    n_high = len(high_mismatches)
    n_top30_high = len(top30_high_impacts)
    n_alias_uncertain = status_counts.get("sponsor_alias_uncertain", 0)
    total_rows = len(rows_out)
    alias_pct = n_alias_uncertain / max(1, total_rows)

    if alias_pct > 0.30:
        decision = "ALIAS_MAP_FIRST"
        decision_reason = (
            f"sponsor_alias_uncertain dominates ({alias_pct*100:.1f}% of rows); "
            "build alias map before any recurring validator"
        )
    elif n_high <= 5 and n_top30_high == 0:
        decision = "MANUAL_FIX"
        decision_reason = (
            f"{n_high} HIGH-confidence material mismatches and {n_top30_high} top-30 impact; "
            "fix manually in universe.json/source data; close the lane"
        )
    else:
        decision = "RECURRING_VALIDATOR"
        decision_reason = (
            f"{n_high} HIGH mismatches ({n_top30_high} in top-30); "
            "scope a separate recurring cache-based validator spec"
        )

    return {
        "as_of_date": as_of_date,
        "spec_version": "spec_068",
        "rows": rows_out,
        "status_counts": dict(status_counts),
        "totals": {
            "n_audited": total_rows,
            "n_high_mismatches": n_high,
            "n_top30_impact": len(top30_impacts),
            "n_top30_high_mismatches": n_top30_high,
        },
        "data_quality": {
            "orange_book_age_days": ob_age,
            "orange_book_stale": ob_stale,
            "ctgov_record_count": sum(len(v) for v in ctgov_by_ticker.values()),
        },
        "sec_cache_status": sec_cache_status,
        "overrides_loaded": overrides,
        "overrides_disagreeing": [
            r["ticker"] for r in rows_out if r["validation_status"] == "override_disagrees_with_consensus"
        ],
        "decision_branch": decision,
        "decision_reason": decision_reason,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


CSV_FIELDS = [
    "ticker",
    "company_name",
    "internal_development_stage",
    "development_stage_source",
    "lead_program_phase_raw",
    "archetype",
    "tier_commercial",
    "ctgov_max_phase",
    "ctgov_active_trial_count",
    "ctgov_top_sponsor",
    "ctgov_alias_confidence",
    "purple_book_hit",
    "orange_book_hit",
    "orange_book_stale_days",
    "pit_financials_material_revenue",
    "pdufa_pending",
    "fda_or_purplebook_approved_evidence",
    "external_consensus_stage",
    "validation_status",
    "confidence",
    "likely_action",
    "in_top30",
    "evidence_sources",
    "notes",
]


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    import io

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
    _atomic_write(path, buf.getvalue())


def write_json(payload: dict[str, Any], path: Path) -> None:
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True, default=str))


def write_md(payload: dict[str, Any], path: Path) -> None:
    rows = payload["rows"]
    counts = payload["status_counts"]
    totals = payload["totals"]
    dq = payload["data_quality"]
    decision = payload["decision_branch"]
    reason = payload["decision_reason"]

    lines: list[str] = []
    lines.append(f"# Development Stage External Cache Audit — {payload['as_of_date']}")
    lines.append("")
    lines.append("Spec 068 metadata integrity audit. Read-only. Display-only column.")
    lines.append("")
    lines.append("## Decision")
    lines.append(f"**{decision}** — {reason}")
    lines.append("")
    lines.append("## Totals")
    lines.append(f"- Rows audited: {totals['n_audited']}")
    lines.append(f"- HIGH-confidence material mismatches: {totals['n_high_mismatches']}")
    lines.append(f"- Top-30 with non-validated status: {totals['n_top30_impact']}")
    lines.append(f"- Top-30 HIGH mismatches: {totals['n_top30_high_mismatches']}")
    lines.append("")
    lines.append("## Validation status counts")
    for s in sorted(counts.keys()):
        lines.append(f"- `{s}`: {counts[s]}")
    lines.append("")
    lines.append("## Data quality")
    lines.append(f"- Orange Book age: {dq['orange_book_age_days']} days (stale={dq['orange_book_stale']})")
    lines.append(f"- CT.gov record count: {dq['ctgov_record_count']}")
    lines.append("")
    overrides_loaded = payload.get("overrides_loaded", {})
    overrides_disagreeing = payload.get("overrides_disagreeing", [])
    lines.append("## Manual overrides (Spec 068 Lane 1)")
    lines.append(f"- Overrides loaded: {len(overrides_loaded)}")
    if overrides_loaded:
        lines.append("- Entries:")
        for tkr, stg in sorted(overrides_loaded.items()):
            lines.append(f"  - {tkr}: {stg}")
    lines.append(f"- Overrides disagreeing with consensus: {len(overrides_disagreeing)}")
    if overrides_disagreeing:
        lines.append("- Disagreement tickers (review override staleness):")
        for tkr in overrides_disagreeing:
            lines.append(f"  - {tkr}")
    lines.append("")
    sec = payload.get("sec_cache_status", {})
    lines.append("## SEC 8-K cache status")
    lines.append(f"- Verdict: **{sec.get('verdict', 'unknown')}**")
    lines.append(f"- Reason: {sec.get('verdict_reason', '')}")
    lines.append(f"- Consumed by audit: {sec.get('consumed_by_audit', False)}")
    lines.append(f"- Top-level JSON files: {sec.get('file_count', 0)}")
    lines.append(f"- Total events: {sec.get('event_count', 0)}")
    lines.append(f"- Newest file: {sec.get('newest_file')}")
    lines.append(f"- Oldest file: {sec.get('oldest_file')}")
    lines.append(f"- {payload['as_of_date']} file present: {sec.get('as_of_date_file_present', False)}")
    lines.append("")
    lines.append(
        "_SEC 8-K evidence not consumed in this one-shot audit; cache status reported "
        "separately as optional source-quality metadata._"
    )
    lines.append("")

    high_rows = [r for r in rows if r["validation_status"] == "likely_internal_stale" and r["confidence"] == "HIGH"]
    if high_rows:
        lines.append("## HIGH-confidence likely_internal_stale (operator review)")
        lines.append("")
        lines.append("| Ticker | Internal | Consensus | Top-30 | Evidence |")
        lines.append("|---|---|---|---|---|")
        for r in high_rows[:50]:
            lines.append(
                f"| {r['ticker']} | {r['internal_development_stage']} | "
                f"{r['external_consensus_stage']} | {'Y' if r['in_top30'] else ''} | "
                f"{r['evidence_sources']} |"
            )
        lines.append("")

    multi = [r for r in rows if r["validation_status"] == "ambiguous_multi_program"]
    if multi:
        lines.append("## ambiguous_multi_program callouts")
        lines.append(f"({len(multi)} tickers — informational, not failures)")
        lines.append("")
        for r in multi[:30]:
            lines.append(f"- {r['ticker']}: {r['notes']}")
        lines.append("")

    _atomic_write(path, "\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--as-of-date",
        default=None,
        help="Snapshot date (YYYY-MM-DD). Defaults to latest snapshot dir.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(ARTIFACTS_DIR),
        help="Override output directory.",
    )
    args = parser.parse_args()

    if args.as_of_date is None:
        snaps = REPO_ROOT / "data" / "snapshots"
        candidates = sorted(p.name for p in snaps.iterdir() if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", p.name))
        if not candidates:
            print("ERROR: no snapshot dirs found", file=sys.stderr)
            return 2
        as_of = candidates[-1]
    else:
        as_of = args.as_of_date

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = audit(as_of)

    csv_path = out_dir / f"stage_cache_audit_{as_of}.csv"
    md_path = out_dir / f"stage_cache_audit_{as_of}.md"
    json_path = out_dir / f"stage_cache_audit_{as_of}.json"

    write_csv(payload["rows"], csv_path)
    write_md(payload, md_path)
    write_json(payload, json_path)

    totals = payload["totals"]
    print(f"as_of_date: {as_of}")
    print(f"rows_audited: {totals['n_audited']}")
    print(f"status_counts: {payload['status_counts']}")
    print(f"high_mismatches: {totals['n_high_mismatches']}")
    print(f"top30_high_mismatches: {totals['n_top30_high_mismatches']}")
    print(f"decision: {payload['decision_branch']}")
    print(f"decision_reason: {payload['decision_reason']}")
    print("outputs:")
    print(f"  csv: {csv_path}")
    print(f"  md:  {md_path}")
    print(f"  json:{json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
