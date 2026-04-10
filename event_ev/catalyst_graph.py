"""Layer 1 — Catalyst Graph.

Builds unified CatalystNode objects from existing repo data sources:
- event_ledger.py LedgerEntry
- event_detector.py CatalystEvent
- CRT ResolutionRecord
- PDUFA dates
- Herald/NewsEvent classified output

The graph tracks dependencies between events (e.g., Phase 2 → Phase 3)
and revision history for timing models.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .data_contracts import CatalystNode, CatalystRevision, DatePrecision, EventFamily, NodeStatus

logger = logging.getLogger(__name__)

# Event type → family mapping (mirrors event_ledger.CATALYST_FAMILY_MAP)
_FAMILY_MAP: Dict[str, str] = {
    "PDUFA": "REGULATORY",
    "FDA_PDUFA_DATE": "REGULATORY",
    "FDA_ADCOM": "REGULATORY",
    "FDA_APPROVAL": "REGULATORY",
    "FDA_SUBMISSION": "REGULATORY",
    "FDA_DESIGNATION": "REGULATORY",
    "FDA_CRL": "REGULATORY",
    "FDA_RTF": "REGULATORY",
    "FDA_DECISION": "REGULATORY",
    "EMA_AGENDA": "REGULATORY",
    "EMA_OUTCOME": "REGULATORY",
    "CLINICAL_PCD": "CLINICAL",
    "CLINICAL_CD": "CLINICAL",
    "CT_PRIMARY_COMPLETION": "CLINICAL",
    "CT_STUDY_COMPLETION": "CLINICAL",
    "CT_RESULTS_POSTED": "CLINICAL",
    "CT_DATE_CONFIRMED_ACTUAL": "CLINICAL",
    "DATA_READOUT": "CLINICAL",
    "DATA_PRESENTATION": "CLINICAL",
    "DATA_PUBLICATION": "CLINICAL",
    "CT_STATUS_UPGRADE": "CLINICAL",
    "CT_STATUS_DOWNGRADE": "SAFETY",
    "CLINICAL_HOLD": "SAFETY",
    "SAFETY_SIGNAL": "SAFETY",
    "FDA_WARNING_LETTER": "SAFETY",
    "CT_TRIAL_TERMINATED": "SAFETY",
    "CT_TRIAL_WITHDRAWN": "SAFETY",
    "CT_TRIAL_SUSPENDED": "SAFETY",
    "CT_STATUS_SEVERE_NEG": "SAFETY",
    "CT_TIMELINE_PULLIN": "CLINICAL",
    "CT_TIMELINE_PUSHOUT": "CLINICAL",
    "CT_ACTIVITY_PROXY": "CLINICAL",
}

# Event type → subtype heuristic
_SUBTYPE_MAP: Dict[str, str] = {
    "PDUFA": "FDA_ACTION",
    "FDA_ADCOM": "ADCOM",
    "DATA_READOUT": "TOPLINE",
    "DATA_PRESENTATION": "CONFERENCE",
    "CT_PRIMARY_COMPLETION": "PCD",
    "CT_STUDY_COMPLETION": "SCD",
    "CT_RESULTS_POSTED": "RESULTS",
}


# CRT catalyst_type → graph event_type mapping (for resolution matching)
_CRT_TYPE_TO_GRAPH: Dict[str, str] = {
    "PDUFA_ACTION": "PDUFA",
    "NDA_BLA_FILING": "FDA_SUBMISSION",
    "REGULATORY_DESIGNATION": "FDA_DESIGNATION",
    "ADCOM_VOTE": "FDA_ADCOM",
    "PHASE_3_READOUT": "DATA_READOUT",
    "PHASE_2_READOUT": "DATA_READOUT",
    "PHASE_1_READOUT": "DATA_READOUT",
    "PHASE_1_DATA": "DATA_READOUT",
    "PHASE_2_DATA": "DATA_READOUT",
    "FDA_PDUFA_DATE": "PDUFA",
}


def _infer_phase(raw: Optional[str]) -> str:
    """Normalize phase string to canonical form."""
    if not raw:
        return "unknown"
    s = str(raw).lower().strip()
    for canon in ("1_2", "2_3", "1", "2", "3", "4"):
        if canon in s.replace("/", "_").replace(" ", ""):
            return canon
    try:
        p = float(s)
        if p >= 3:
            return "3"
        if p >= 2:
            return "2"
        return "1"
    except (ValueError, TypeError):
        return "unknown"


def _infer_indication(raw: Optional[str]) -> str:
    """Normalize indication string."""
    if not raw:
        return "unknown"
    return raw.strip().lower()


class CatalystGraph:
    """Registry of CatalystNode objects with PIT-aware querying.

    Usage:
        graph = CatalystGraph()
        graph.load_from_ledger_entries(entries, as_of_date)
        graph.load_from_pdufa(pdufa_entries, as_of_date)
        graph.apply_resolutions(resolution_records, as_of_date)
        nodes = graph.get_active_nodes("ACAD", as_of_date)
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, CatalystNode] = {}
        self._by_ticker: Dict[str, List[str]] = {}

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    def add_node(self, node: CatalystNode) -> None:
        """Add a node to the graph. Deduplicates by node_id."""
        self._nodes[node.node_id] = node
        self._by_ticker.setdefault(node.ticker, [])
        if node.node_id not in self._by_ticker[node.ticker]:
            self._by_ticker[node.ticker].append(node.node_id)

    def get_node(self, node_id: str) -> Optional[CatalystNode]:
        return self._nodes.get(node_id)

    def archive_stale_entries(self, as_of: date, max_age_days: int = 180) -> int:
        """Mark nodes with event date > max_age_days in the past as STALE.

        For windowed events, uses date_range_end instead of expected_date
        to avoid archiving events whose window hasn't closed yet.
        """
        cutoff = as_of - timedelta(days=max_age_days)
        archived = 0
        for node in self._nodes.values():
            if node.is_resolved():
                continue
            if not node.expected_date:
                continue
            try:
                # Use range end for windowed events (window may extend beyond expected_date)
                effective_date = node.expected_date
                if node.date_range_end and node.date_precision in ("HALF_YEAR", "QUARTER", "MONTH"):
                    effective_date = node.date_range_end

                ed = date.fromisoformat(effective_date)
                if ed < cutoff:
                    node.status = NodeStatus.RESOLVED.value
                    node.resolution = "STALE_ARCHIVED"
                    archived += 1
            except (ValueError, TypeError):
                continue
        return archived

    def dedup_by_event(self) -> int:
        """Remove duplicate nodes with same (ticker, event_type, expected_date).

        Keeps the node with the most recent disclosed_at date.
        Returns count of nodes removed.
        """
        seen: Dict[str, str] = {}  # key → best node_id
        to_remove = []
        for node in sorted(self._nodes.values(), key=lambda n: n.disclosed_at or "", reverse=True):
            key = f"{node.ticker}|{node.event_type}|{node.expected_date}"
            if key in seen:
                to_remove.append(node.node_id)
            else:
                seen[key] = node.node_id
        for nid in to_remove:
            if nid in self._nodes:
                ticker = self._nodes[nid].ticker
                del self._nodes[nid]
                if ticker in self._by_ticker:
                    self._by_ticker[ticker] = [n for n in self._by_ticker[ticker] if n != nid]
        return len(to_remove)

    def fix_range_marker_precision(self) -> int:
        """Set date_precision and compute date_range_end for range-marker nodes.

        Nodes with expected_date ending in -01 or -31/-30 from SEC_8K sources
        are typically range markers (H1 2024, Q3 2025) — not exact dates.
        Sets precision AND computes the range end so window-aware scoring works.
        """
        fixed = 0
        for node in self._nodes.values():
            if not node.expected_date or node.date_precision != "UNKNOWN":
                continue
            if node.source not in ("SEC_8K_FILING", "SEC_8K"):
                continue
            try:
                ed = date.fromisoformat(node.expected_date)
                if ed.day == 1 and ed.month in (1, 7):
                    node.date_precision = "HALF_YEAR"
                    node.date_confidence = 0.20
                    # Range: 6 months from start
                    node.date_range_start = node.expected_date
                    node.date_range_end = (
                        (date(ed.year, ed.month + 6, 1) - timedelta(days=1)).isoformat()
                        if ed.month <= 6
                        else (date(ed.year + 1, 1, 1) - timedelta(days=1)).isoformat()
                    )
                    fixed += 1
                elif ed.day in (1, 28, 29, 30, 31) and ed.month in (1, 4, 7, 10):
                    node.date_precision = "QUARTER"
                    node.date_confidence = 0.25
                    # Range: 3 months from quarter start
                    q_start = date(ed.year, ed.month, 1)
                    q_end_month = ed.month + 3 if ed.month <= 9 else 1
                    q_end_year = ed.year if ed.month <= 9 else ed.year + 1
                    node.date_range_start = q_start.isoformat()
                    node.date_range_end = (date(q_end_year, q_end_month, 1) - timedelta(days=1)).isoformat()
                    fixed += 1
                elif ed.day == 1:
                    node.date_precision = "MONTH"
                    node.date_confidence = 0.30
                    # Range: 1 month
                    node.date_range_start = node.expected_date
                    next_month = ed.month + 1 if ed.month < 12 else 1
                    next_year = ed.year if ed.month < 12 else ed.year + 1
                    node.date_range_end = (date(next_year, next_month, 1) - timedelta(days=1)).isoformat()
                    fixed += 1
            except (ValueError, TypeError):
                continue
        return fixed

    def tag_overdue_windowed_nodes(self, as_of: date) -> int:
        """Tag overdue windowed nodes for downstream identification.

        Nodes with HALF_YEAR/QUARTER/MONTH precision and expected_date in the
        past are 'overdue' — the event should have happened but wasn't resolved.

        Instead of mutating dates (the old roll-forward approach), these nodes
        are now handled by days_to_event() which returns a positive number for
        overdue windows. This method just tags them and caps confidence.
        """
        tagged = 0
        for node in self._nodes.values():
            if node.is_resolved():
                continue
            if node.date_precision not in ("HALF_YEAR", "QUARTER", "MONTH"):
                continue
            if not node.expected_date:
                continue
            try:
                ed = date.fromisoformat(node.expected_date)
                if ed >= as_of:
                    continue  # Not overdue
                node.date_confidence = min(node.date_confidence, 0.15)
                node.event_subtype = (node.event_subtype or "") + "|OVERDUE_WINDOW"
                tagged += 1
            except (ValueError, TypeError):
                continue
        return tagged

    def enrich_phases(self, ticker_phase: Dict[str, str]) -> int:
        """Update phase for nodes with phase="unknown" using a ticker→phase map.

        Only updates clinical/safety events — regulatory events keep their
        existing phase. Returns count of nodes updated.
        """
        count = 0
        for node in self._nodes.values():
            if node.phase != "unknown":
                continue
            if node.event_family == "REGULATORY":
                continue
            phase = ticker_phase.get(node.ticker)
            if phase and phase != "unknown":
                node.phase = phase
                count += 1
        return count

    def get_ticker_nodes(
        self,
        ticker: str,
        as_of: Optional[date] = None,
        status_filter: Optional[List[str]] = None,
    ) -> List[CatalystNode]:
        """Get all nodes for a ticker, optionally filtered by PIT and status."""
        node_ids = self._by_ticker.get(ticker, [])
        nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]

        if as_of is not None:
            nodes = [n for n in nodes if n.is_visible(as_of)]

        if status_filter is not None:
            nodes = [n for n in nodes if n.status in status_filter]

        return nodes

    def get_active_nodes(self, ticker: str, as_of: date) -> List[CatalystNode]:
        """Get pending/active (unresolved) nodes for a ticker."""
        return self.get_ticker_nodes(
            ticker,
            as_of=as_of,
            status_filter=[NodeStatus.PENDING.value, NodeStatus.ACTIVE.value],
        )

    def get_nearest_node(self, ticker: str, as_of: date) -> Optional[CatalystNode]:
        """Get the nearest future active catalyst for a ticker."""
        active = self.get_active_nodes(ticker, as_of)
        future = []
        for n in active:
            days = n.days_to_event(as_of)
            if days is not None and days > 0:
                future.append((days, n))
        if not future:
            return None
        future.sort(key=lambda x: x[0])
        return future[0][1]

    def get_all_nodes(self, as_of: Optional[date] = None) -> List[CatalystNode]:
        """Get all nodes, optionally PIT-filtered."""
        nodes = list(self._nodes.values())
        if as_of is not None:
            nodes = [n for n in nodes if n.is_visible(as_of)]
        return nodes

    def get_event_cohort(
        self,
        as_of: date,
        max_days: int = 180,
        min_days: int = 0,
        families: Optional[List[str]] = None,
    ) -> List[CatalystNode]:
        """Get the actionable event cohort within a time window."""
        result = []
        for node in self.get_all_nodes(as_of):
            if node.is_resolved():
                continue
            days = node.days_to_event(as_of)
            if days is None:
                continue
            if not (min_days <= days <= max_days):
                continue
            if families and node.event_family not in families:
                continue
            result.append(node)
        result.sort(key=lambda n: n.days_to_event(as_of) or 999)
        return result

    # =========================================================================
    # Loaders — from existing repo data sources
    # =========================================================================

    def load_from_ledger_entries(
        self,
        entries: List[Dict[str, Any]],
        as_of: date,
    ) -> int:
        """Load from event_ledger LedgerEntry dicts.

        Args:
            entries: list of LedgerEntry.to_dict() outputs
            as_of: PIT filter date

        Returns:
            Number of nodes added
        """
        count = 0
        for e in entries:
            disclosed = e.get("disclosed_at", "")
            try:
                if date.fromisoformat(disclosed) > as_of:
                    continue
            except (ValueError, TypeError):
                continue

            event_type = e.get("event_type", "UNKNOWN")
            family = _FAMILY_MAP.get(event_type, "CLINICAL")
            subtype = _SUBTYPE_MAP.get(event_type, event_type)

            node = CatalystNode(
                ticker=e.get("ticker", ""),
                event_family=family,
                event_type=event_type,
                event_subtype=subtype,
                expected_date=e.get("event_date"),
                date_range_start=e.get("event_date"),
                date_range_end=e.get("event_date_end"),
                date_precision=_normalize_precision(e.get("date_precision", "UNKNOWN"), e.get("source", "")),
                date_confidence=_precision_to_confidence(
                    e.get("confidence", "LOW"),
                    _normalize_precision(e.get("date_precision", "UNKNOWN"), e.get("source", "")),
                    source=e.get("source", "UNKNOWN"),
                    event_type=event_type,
                ),
                source=e.get("source", "UNKNOWN"),
                source_uid=e.get("source_uid", ""),
                disclosed_at=disclosed,
                phase=_infer_phase(e.get("tags", [None])[0] if e.get("tags") else None),
                indication="unknown",
                nct_id=e.get("source_uid") if e.get("source") == "CTGOV" else None,
                status=NodeStatus.PENDING.value,
            )
            self.add_node(node)
            count += 1

        logger.info("Loaded %d nodes from ledger entries (as_of=%s)", count, as_of)
        return count

    def load_from_pdufa(
        self,
        pdufa_entries: List[Dict[str, Any]],
        as_of: date,
    ) -> int:
        """Load from pdufa_dates.json entries.

        Expected keys: ticker, date, drug_name, indication, source
        """
        count = 0
        for p in pdufa_entries:
            pdufa_date = p.get("date", "")
            ticker = p.get("ticker", "")
            if not pdufa_date or not ticker:
                continue

            node = CatalystNode(
                ticker=ticker,
                event_family=EventFamily.REGULATORY.value,
                event_type="PDUFA",
                event_subtype="FDA_ACTION",
                expected_date=pdufa_date,
                date_range_start=pdufa_date,
                date_range_end=pdufa_date,
                date_precision=DatePrecision.DAY.value,
                date_confidence=0.90,
                source="PDUFA_MANUAL",
                source_uid=f"pdufa_{ticker}_{pdufa_date}",
                disclosed_at=p.get("disclosed_at", pdufa_date),
                phase=_infer_phase(p.get("phase")),
                indication=_infer_indication(p.get("indication")),
                modality=p.get("modality"),
                status=NodeStatus.ACTIVE.value,
            )
            self.add_node(node)
            count += 1

        logger.info("Loaded %d PDUFA nodes (as_of=%s)", count, as_of)
        return count

    def enrich_with_fda_designations(
        self,
        designations: List[Dict[str, Any]],
    ) -> int:
        """Enrich PDUFA/regulatory nodes with FDA designation data.

        Matches designations to nodes by ticker, adds review_type,
        designations list, and other regulatory context.

        Args:
            designations: list of dicts with keys: ticker, designation_type,
                         drug_name, indication, grant_date

        Returns:
            Number of nodes enriched.
        """
        # Build ticker → designations lookup
        by_ticker: Dict[str, List[str]] = {}
        for d in designations:
            tk = d.get("ticker", "")
            dtype = d.get("designation_type", "")
            if tk and dtype:
                by_ticker.setdefault(tk, []).append(dtype)

        enriched = 0
        for node in self._nodes.values():
            if node.event_family != EventFamily.REGULATORY.value:
                continue
            desigs = by_ticker.get(node.ticker, [])
            if desigs:
                node.designations = list(set(desigs))
                # Infer review type from designations
                if "BTD" in desigs or "PR" in desigs:
                    node.review_type = "PRIORITY"
                elif not node.review_type:
                    node.review_type = "STANDARD"
                enriched += 1

        if enriched:
            logger.info("Enriched %d regulatory nodes with FDA designations", enriched)
        return enriched

    def enrich_with_adcom_outcomes(
        self,
        adcom_records: List[Dict[str, Any]],
    ) -> int:
        """Enrich PDUFA nodes with advisory committee vote outcomes.

        Matches AdCom records to PDUFA nodes by ticker. When a matching
        AdCom record exists, sets adcom_outcome on the node, which the
        outcome model uses to adjust the PDUFA approval probability.

        Args:
            adcom_records: list of dicts with keys: ticker, vote_yes, vote_no,
                          vote_favorable, fda_outcome, meeting_date

        Returns:
            Number of nodes enriched.
        """
        from .fda_outcome_priors import classify_adcom_outcome

        # Build ticker → adcom outcome lookup (most recent per ticker)
        by_ticker: Dict[str, Dict] = {}
        for r in sorted(adcom_records, key=lambda x: x.get("meeting_date", "")):
            tk = r.get("ticker", "")
            if tk:
                by_ticker[tk] = r

        enriched = 0
        for node in self._nodes.values():
            if node.event_type != "PDUFA":
                continue
            adcom = by_ticker.get(node.ticker)
            if not adcom:
                continue
            yes = adcom.get("vote_yes", 0) or 0
            no = adcom.get("vote_no", 0) or 0
            total = yes + no
            if total > 0:
                node.adcom_outcome = classify_adcom_outcome(yes, total)
                enriched += 1

        # Also check for prior CRL history (resubmission indicator)
        crl_tickers = {r.get("ticker") for r in adcom_records if r.get("fda_outcome") == "CRL"}
        crl_enriched = 0
        for node in self._nodes.values():
            if node.event_type == "PDUFA" and node.ticker in crl_tickers:
                node.has_prior_crl = True
                crl_enriched += 1

        if enriched or crl_enriched:
            logger.info(
                "Enriched %d PDUFA nodes with AdCom outcomes, %d with CRL history",
                enriched,
                crl_enriched,
            )
        return enriched + crl_enriched

    def load_from_catalyst_events(
        self,
        summaries: List[Dict[str, Any]],
        as_of: date,
    ) -> int:
        """Load from catalyst_events_*.json summaries.

        Each summary has: ticker, events: [{event_type, event_date, ...}]
        """
        count = 0
        for summary in summaries:
            ticker = summary.get("ticker", "")
            for evt in summary.get("events", []):
                event_type = evt.get("event_type", "UNKNOWN")
                event_date = evt.get("event_date")
                disclosed = evt.get("disclosed_at", evt.get("pit_available_at", ""))

                if not event_date or not ticker:
                    continue
                try:
                    if disclosed and date.fromisoformat(disclosed) > as_of:
                        continue
                except (ValueError, TypeError):
                    pass

                family = _FAMILY_MAP.get(event_type, "CLINICAL")
                subtype = _SUBTYPE_MAP.get(event_type, event_type)

                node = CatalystNode(
                    ticker=ticker,
                    event_family=family,
                    event_type=event_type,
                    event_subtype=subtype,
                    expected_date=event_date,
                    date_range_start=event_date,
                    date_range_end=evt.get("event_date_end"),
                    date_precision=evt.get("date_precision", "UNKNOWN"),
                    date_confidence=_precision_to_confidence(
                        evt.get("confidence", "LOW"),
                        evt.get("date_precision", "UNKNOWN"),
                        source=evt.get("source", "UNKNOWN"),
                        event_type=event_type,
                    ),
                    source=evt.get("source", "UNKNOWN"),
                    source_uid=evt.get("source_uid", evt.get("nct_id", "")),
                    disclosed_at=disclosed or str(as_of),
                    phase=_infer_phase(evt.get("phase")),
                    indication=_infer_indication(evt.get("indication")),
                    nct_id=evt.get("nct_id"),
                    status=NodeStatus.PENDING.value,
                )
                self.add_node(node)
                count += 1

        logger.info("Loaded %d nodes from catalyst events (as_of=%s)", count, as_of)
        return count

    def apply_resolutions(
        self,
        resolution_records: List[Dict[str, Any]],
        as_of: date,
    ) -> int:
        """Apply CRT resolution outcomes to matching nodes.

        Matches by (ticker, catalyst_date) within ±7 day window.
        Prefers event_type match when available to avoid cross-type
        false matches. Only applies if resolution_date <= as_of.
        """
        applied = 0
        for rec in resolution_records:
            res_date = rec.get("resolution_date", "")
            try:
                if date.fromisoformat(res_date) > as_of:
                    continue
            except (ValueError, TypeError):
                continue

            ticker = rec.get("ticker", "")
            cat_date = rec.get("catalyst_date", "")
            outcome = rec.get("outcome", "")
            crt_type = rec.get("catalyst_type", "")

            if not ticker or not cat_date or not outcome:
                continue
            if outcome == "INFORMATIONAL":
                continue

            # Map CRT type to graph event type for matching
            crt_event_type = _CRT_TYPE_TO_GRAPH.get(crt_type)

            # Find matching node — prefer type+date match, fall back to date-only
            best_node = None
            best_gap = 999
            for node in self.get_ticker_nodes(ticker):
                if not node.expected_date:
                    continue
                try:
                    nd = date.fromisoformat(node.expected_date)
                    cd = date.fromisoformat(cat_date)
                    gap = abs((nd - cd).days)
                    if gap > 7:
                        continue
                    # Prefer type match (gap penalty 0) over type mismatch (gap penalty 1)
                    type_match = crt_event_type and node.event_type == crt_event_type
                    effective_gap = gap if type_match else gap + 100
                    if effective_gap < best_gap:
                        best_gap = effective_gap
                        best_node = node
                except (ValueError, TypeError):
                    continue

            if best_node is not None:
                best_node.status = NodeStatus.RESOLVED.value
                best_node.resolution = outcome
                best_node.resolved_date = res_date
                applied += 1

        logger.info("Applied %d resolutions (as_of=%s)", applied, as_of)
        return applied

    def build_revision_history(
        self,
        ledger_snapshots: List[Dict[str, Any]],
    ) -> int:
        """Build revision history from multiple ledger snapshots over time.

        Each snapshot: {"as_of_date": "YYYY-MM-DD", "entries": [...]}

        Compares expected_date across snapshots to detect pushouts/pullins.
        """
        revisions_added = 0
        # Group entries by (ticker, source_uid) across snapshots
        history: Dict[str, List[Dict[str, Any]]] = {}
        for snap in sorted(ledger_snapshots, key=lambda s: s.get("as_of_date", "")):
            snap_date = snap.get("as_of_date", "")
            for entry in snap.get("entries", []):
                key = f"{entry.get('ticker', '')}|{entry.get('source_uid', '')}"
                history.setdefault(key, []).append({"date": snap_date, "event_date": entry.get("event_date")})

        # Detect changes
        for key, timeline in history.items():
            for i in range(1, len(timeline)):
                prev = timeline[i - 1]
                curr = timeline[i]
                if prev["event_date"] != curr["event_date"] and curr["event_date"]:
                    # Find matching node
                    parts = key.split("|", 1)
                    if len(parts) != 2:
                        continue
                    ticker, source_uid = parts
                    for node in self.get_ticker_nodes(ticker):
                        if node.source_uid == source_uid:
                            rev = CatalystRevision(
                                revision_date=curr["date"],
                                field_name="expected_date",
                                old_value=prev["event_date"] or "",
                                new_value=curr["event_date"] or "",
                                source="ledger_diff",
                            )
                            node.revisions.append(rev)
                            revisions_added += 1
                            break

        logger.info("Built %d revision entries from snapshot history", revisions_added)
        return revisions_added


def _normalize_precision(raw_precision: str, source: str = "") -> str:
    """Normalize date precision string, using source-aware defaults.

    CTGOV entries often have precision="?" but carry real specific dates
    from trial status changes — default to MONTH (conservative).
    """
    p = (raw_precision or "UNKNOWN").upper().strip()
    if p in ("DAY", "WEEK", "MONTH", "QUARTER", "HALF_YEAR", "YEAR", "UNKNOWN"):
        return p
    # Invalid precision — use source-aware default
    if source == "CTGOV":
        return "DAY"  # CTgov dates are real specific dates (from trial status change timestamps)
    return "UNKNOWN"


def _precision_to_confidence(confidence_str: str, precision_str: str, source: str = "", event_type: str = "") -> float:
    """Convert ledger confidence + precision into a [0, 1] date-confidence score.

    Source-aware: SEC 8-K PDUFA dates with DAY precision are upgraded to HIGH
    confidence because the SEC filing is a reliable disclosure of the exact date.
    """
    # Handle both string labels (HIGH/MED/LOW) and numeric confidence values
    try:
        numeric_conf = float(confidence_str)
        if numeric_conf >= 0.7:
            conf_upper = "HIGH"
        elif numeric_conf >= 0.4:
            conf_upper = "MED"
        else:
            conf_upper = "LOW"
    except (ValueError, TypeError):
        conf_upper = confidence_str.upper()

    # Source-aware confidence upgrade
    if source in ("SEC_8K_FILING", "SEC_8K") and precision_str.upper() == "DAY":
        if "PDUFA" in event_type or "FDA" in event_type:
            conf_upper = "HIGH"  # SEC filing with exact PDUFA date = reliable
        else:
            conf_upper = "MED"  # SEC filing with exact readout date = moderate

    # CTGOV nodes: upgrade from LOW to MED — trial registry is a reliable source
    # for primary completion dates even when confidence field says LOW
    if source == "CTGOV" and conf_upper == "LOW":
        conf_upper = "MED"  # CTgov PCD/CD dates are registry-sourced, not rumors

    base = {"HIGH": 0.85, "MED": 0.60, "LOW": 0.30}.get(conf_upper, 0.30)
    precision_mult = {
        "DAY": 1.0,
        "WEEK": 0.90,
        "MONTH": 0.70,
        "QUARTER": 0.50,
        "HALF_YEAR": 0.35,
        "YEAR": 0.20,
        "UNKNOWN": 0.15,
    }.get(precision_str.upper(), 0.15)
    return round(min(base * precision_mult, 1.0), 4)
