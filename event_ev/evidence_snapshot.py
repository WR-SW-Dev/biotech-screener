"""Event Evidence Snapshot builder.

Materializes a PIT-anchored evidence snapshot per (node_id, as_of_date)
from trial_records.json, CatalystNode metadata, and CRT resolution history.

All evidence fields are nullable. Missing data is expected and non-blocking.

PIT safety:
  - Trial records are filtered by collected_at <= as_of_date
  - CRT resolutions are filtered by resolution_date <= as_of_date
  - Designation flags come from CatalystNode (already PIT-gated via disclosed_at)
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from .data_contracts import CatalystNode, EventEvidenceSnapshot

logger = logging.getLogger(__name__)

# Lazy import to avoid hard dependency on data_sources
_pubmed_client = None


def _get_pubmed_client():
    """Lazy-init PubMed client."""
    global _pubmed_client
    if _pubmed_client is None:
        try:
            from data_sources.pubmed_client import PubMedClient

            _pubmed_client = PubMedClient()
        except ImportError:
            logger.debug("PubMed client not available")
            _pubmed_client = False  # sentinel: tried and failed
    return _pubmed_client if _pubmed_client is not False else None


# Phase normalization: ClinicalTrials.gov uses "PHASE2", we use "2"
_CTGOV_PHASE_MAP: Dict[str, str] = {
    "PHASE1": "1",
    "PHASE1_PHASE2": "1_2",
    "PHASE2": "2",
    "PHASE2_PHASE3": "2_3",
    "PHASE3": "3",
    "PHASE4": "4",
    "EARLY_PHASE1": "1",
    "NA": "unknown",
}

# Endpoint type inference from endpoint text
_ENDPOINT_KEYWORDS: Dict[str, List[str]] = {
    "SAFETY": ["adverse event", "teae", "safety", "tolerability", "dose-limiting"],
    "BIOMARKER": ["biomarker", "ctdna", "mrd", "psa", "orr", "response rate"],
    "SURVIVAL": ["overall survival", "progression-free survival", "pfs", "os"],
    "COMPOSITE": ["composite", "co-primary"],
}


def _infer_endpoint_type(text: str) -> Optional[str]:
    """Infer endpoint type from primary endpoint text."""
    if not text:
        return None
    lower = text.lower()
    for etype, keywords in _ENDPOINT_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return etype
    return "EFFICACY"  # default for interventional trials


def _normalize_phase(raw: str) -> str:
    """Normalize ClinicalTrials.gov phase string to internal format."""
    if not raw:
        return "unknown"
    upper = raw.strip().upper().replace(" ", "_").replace("/", "_")
    return _CTGOV_PHASE_MAP.get(upper, "unknown")


def build_evidence_snapshot(
    node: CatalystNode,
    as_of: date,
    trial_records: Optional[List[Dict[str, Any]]] = None,
    crt_resolutions: Optional[List[Dict[str, Any]]] = None,
    literature_scores: Optional[Dict[str, float]] = None,
    pubmed_refs: Optional[Dict[str, List[str]]] = None,
) -> EventEvidenceSnapshot:
    """Build a PIT-safe evidence snapshot for a catalyst node.

    Args:
        node: CatalystNode to build evidence for.
        as_of: Evaluation date (PIT boundary).
        trial_records: List of trial dicts from trial_records.json.
        crt_resolutions: List of CRT resolution dicts.
        literature_scores: Pre-computed {ticker: score} from PubMed enrichment.
        pubmed_refs: Pre-computed {ticker: [pmid, ...]} from PubMed enrichment.

    Returns:
        Frozen EventEvidenceSnapshot.
    """
    trial_records = trial_records or []
    crt_resolutions = crt_resolutions or []
    literature_scores = literature_scores or {}
    pubmed_refs = pubmed_refs or {}

    # Match trial record to node by nct_id or ticker
    trial = _match_trial(node, trial_records, as_of)

    # Extract trial design fields
    phase = node.phase
    randomized_flag = None
    blinded_flag = None
    control_arm_flag = None
    enrollment_n = None
    primary_endpoint_text = None
    endpoint_type = None
    ctgov_study_id = node.nct_id
    source_refs: List[str] = []

    if trial:
        ctgov_study_id = trial.get("nct_id") or ctgov_study_id
        if ctgov_study_id:
            source_refs.append(f"ctgov:{ctgov_study_id}")

        alloc = trial.get("allocation", "")
        randomized_flag = alloc.upper() == "RANDOMIZED" if alloc else None

        masking = trial.get("masking", "")
        if masking:
            blinded_flag = masking.upper() in ("DOUBLE", "SINGLE", "TRIPLE", "QUADRUPLE")
        else:
            blinded_flag = None

        intervention_model = trial.get("intervention_model", "")
        if intervention_model:
            control_arm_flag = intervention_model.upper() not in ("SINGLE_GROUP",)
        else:
            control_arm_flag = None

        raw_enrollment = trial.get("enrollment")
        if raw_enrollment is not None:
            try:
                enrollment_n = int(raw_enrollment)
            except (ValueError, TypeError):
                pass

        endpoints = trial.get("primary_endpoints") or []
        if endpoints:
            primary_endpoint_text = endpoints[0][:500]  # cap length
            endpoint_type = _infer_endpoint_type(primary_endpoint_text)

        trial_phase = _normalize_phase(trial.get("phase", ""))
        if trial_phase != "unknown":
            phase = trial_phase

    # Regulatory designations from node (already PIT-gated via disclosed_at)
    designations = getattr(node, "designations", None) or []
    orphan_flag = "ODD" in designations if designations else None
    fast_track_flag = "FT" in designations if designations else None
    breakthrough_flag = "BTD" in designations if designations else None

    # AdCom flag from node
    adcom_outcome = getattr(node, "adcom_outcome", None)
    adcom_flag = adcom_outcome is not None if adcom_outcome else None

    # Safety signal: not currently wired, leave null
    safety_signal_flag = None

    # Prior readout counts from CRT (PIT-filtered)
    prior_pos, prior_neg = _count_prior_readouts(node.ticker, as_of, crt_resolutions)

    # PubMed literature enrichment
    lit_score = literature_scores.get(node.ticker)
    ticker_pmids = pubmed_refs.get(node.ticker, [])
    for pmid in ticker_pmids:
        source_refs.append(f"pubmed:{pmid}")

    # Evidence confidence: fraction of key fields populated
    has_literature = lit_score is not None and lit_score > 0
    confidence = _compute_confidence(
        trial is not None,
        bool(designations),
        prior_pos is not None,
        ctgov_study_id is not None,
        has_literature,
    )

    return EventEvidenceSnapshot(
        node_id=node.node_id,
        as_of_date=str(as_of),
        phase=phase,
        randomized_flag=randomized_flag,
        blinded_flag=blinded_flag,
        control_arm_flag=control_arm_flag,
        enrollment_n=enrollment_n,
        primary_endpoint_text=primary_endpoint_text,
        endpoint_type=endpoint_type,
        prior_positive_readouts_n=prior_pos,
        prior_negative_readouts_n=prior_neg,
        orphan_flag=orphan_flag,
        fast_track_flag=fast_track_flag,
        breakthrough_flag=breakthrough_flag,
        adcom_flag=adcom_flag,
        safety_signal_flag=safety_signal_flag,
        evidence_confidence=round(confidence, 4),
        ctgov_study_id=ctgov_study_id,
        source_refs=source_refs,
        literature_support_score=lit_score,
    )


def build_evidence_snapshots(
    nodes: List[CatalystNode],
    as_of: date,
    trial_records: Optional[List[Dict[str, Any]]] = None,
    crt_resolutions: Optional[List[Dict[str, Any]]] = None,
    literature_scores: Optional[Dict[str, float]] = None,
    pubmed_refs: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, EventEvidenceSnapshot]:
    """Build evidence snapshots for a batch of nodes.

    Returns:
        {node_id: EventEvidenceSnapshot}
    """
    literature_scores = literature_scores or {}
    pubmed_refs = pubmed_refs or {}
    result = {}
    for node in nodes:
        try:
            snap = build_evidence_snapshot(
                node,
                as_of,
                trial_records,
                crt_resolutions,
                literature_scores,
                pubmed_refs,
            )
            result[node.node_id] = snap
        except Exception:
            logger.exception("Failed to build evidence snapshot for %s (%s)", node.node_id, node.ticker)
    return result


def enrich_literature_from_pubmed(
    nodes: List[CatalystNode],
    trial_records: Optional[List[Dict[str, Any]]] = None,
) -> tuple[Dict[str, float], Dict[str, List[str]]]:
    """Fetch PubMed literature for a batch of nodes and compute scores.

    Searches by NCT ID (if available) and drug name/indication.
    Deduplicates articles per ticker. Caches results on disk.

    Returns:
        (literature_scores, pubmed_refs) where:
          literature_scores = {ticker: float [0, 1]}
          pubmed_refs = {ticker: [pmid, ...]}
    """
    client = _get_pubmed_client()
    if client is None:
        logger.info("PubMed client not available — skipping literature enrichment")
        return {}, {}

    from data_sources.pubmed_client import compute_literature_score

    scores: Dict[str, float] = {}
    refs: Dict[str, List[str]] = {}
    trial_records = trial_records or []

    # Build ticker → (drug_name, indication, nct_id) map
    ticker_context: Dict[str, Dict[str, str]] = {}
    for node in nodes:
        tk = node.ticker
        if tk in ticker_context:
            continue
        ctx: Dict[str, str] = {"indication": node.indication or ""}
        if node.nct_id:
            ctx["nct_id"] = node.nct_id
        # Try to get drug name from trial records
        for t in trial_records:
            t_ticker = (t.get("ticker") or "").upper()
            if t_ticker == tk:
                interventions = t.get("interventions") or []
                if interventions:
                    ctx["drug_name"] = interventions[0]
                break
        ticker_context[tk] = ctx

    for tk, ctx in ticker_context.items():
        try:
            all_articles = []
            seen_pmids: set = set()

            # Search by NCT ID first (most specific)
            nct_id = ctx.get("nct_id", "")
            if nct_id:
                for art in client.search_nct(nct_id, max_results=10):
                    if art.pmid not in seen_pmids:
                        all_articles.append(art)
                        seen_pmids.add(art.pmid)

            # Search by drug name + indication
            drug_name = ctx.get("drug_name", "")
            if drug_name:
                for art in client.search_drug(drug_name, ctx.get("indication", ""), max_results=15):
                    if art.pmid not in seen_pmids:
                        all_articles.append(art)
                        seen_pmids.add(art.pmid)

            scores[tk] = compute_literature_score(all_articles)
            refs[tk] = [a.pmid for a in all_articles]

        except Exception:
            logger.debug("PubMed enrichment failed for %s", tk, exc_info=True)
            continue

    if scores:
        enriched = sum(1 for s in scores.values() if s > 0)
        logger.info("PubMed enrichment: %d/%d tickers with literature", enriched, len(scores))

    return scores, refs


def _match_trial(
    node: CatalystNode,
    trial_records: List[Dict[str, Any]],
    as_of: date,
) -> Optional[Dict[str, Any]]:
    """Match a trial record to a node, PIT-safe.

    Priority:
      1. Exact nct_id match
      2. Ticker match (most advanced active trial)
    """
    as_of_str = str(as_of)

    # 1. Exact NCT match
    if node.nct_id:
        for t in trial_records:
            if t.get("nct_id") == node.nct_id:
                collected = t.get("collected_at", "")
                if collected and collected > as_of_str:
                    continue  # PIT violation
                return t

    # 2. Ticker match — pick most advanced active trial
    _PHASE_ORDER = {"1": 1, "1_2": 2, "2": 3, "2_3": 4, "3": 5, "4": 6}
    best: Optional[Dict[str, Any]] = None
    best_rank = 0

    ticker_upper = node.ticker.upper()
    for t in trial_records:
        tk = (t.get("ticker") or t.get("lead_sponsor_ticker") or "").upper()
        if tk != ticker_upper:
            continue
        collected = t.get("collected_at", "")
        if collected and collected > as_of_str:
            continue
        phase = _normalize_phase(t.get("phase", ""))
        rank = _PHASE_ORDER.get(phase, 0)
        if rank > best_rank:
            best = t
            best_rank = rank

    return best


def _count_prior_readouts(
    ticker: str,
    as_of: date,
    crt_resolutions: List[Dict[str, Any]],
) -> tuple[Optional[int], Optional[int]]:
    """Count prior HIT/MISS resolutions for a ticker, PIT-filtered.

    Returns (prior_positive, prior_negative) or (None, None) if no data.
    """
    if not crt_resolutions:
        return None, None

    as_of_str = str(as_of)
    pos = 0
    neg = 0
    found = False

    for rec in crt_resolutions:
        if (rec.get("ticker") or "").upper() != ticker.upper():
            continue
        resolved = rec.get("resolution_date") or rec.get("resolved_date", "")
        if resolved and resolved > as_of_str:
            continue
        outcome = rec.get("outcome", "")
        if outcome == "HIT":
            pos += 1
            found = True
        elif outcome == "MISS":
            neg += 1
            found = True

    return (pos, neg) if found else (None, None)


def _compute_confidence(
    has_trial: bool,
    has_designations: bool,
    has_crt_history: bool,
    has_nct_id: bool,
    has_literature: bool = False,
) -> float:
    """Compute evidence confidence as weighted fraction of available sources."""
    weights = {
        "trial": (0.35, has_trial),
        "nct_id": (0.10, has_nct_id),
        "designations": (0.20, has_designations),
        "crt_history": (0.20, has_crt_history),
        "literature": (0.15, has_literature),
    }
    score = sum(w for w, present in weights.values() if present)
    return min(score, 1.0)
