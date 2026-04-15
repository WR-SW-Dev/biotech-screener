"""Shared data loaders for the Event EV engine.

Extracted from scripts/research/run_event_ev_study.py for reuse by
both the research harness and the daily production scoring tool.

All loaders are PIT-safe: they only return data disclosed on or before as_of.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict

from common.feature_registry import get_context_keys, get_feature_keys

from .catalyst_graph import CatalystGraph
from .data_contracts import EventEvidenceSnapshot
from .evidence_snapshot import build_evidence_snapshots, enrich_literature_from_pubmed

logger = logging.getLogger(__name__)


def load_catalyst_graph(
    as_of: date,
    prod_data: Path,
    data_dir: Path,
) -> CatalystGraph:
    """Build catalyst graph from available repo data sources.

    Args:
        as_of: Evaluation date (PIT boundary).
        prod_data: Path to production_data/ directory.
        data_dir: Path to data/ directory.

    Returns:
        Populated CatalystGraph.
    """
    graph = CatalystGraph()

    # 1. PDUFA dates
    pdufa_path = prod_data / "pdufa_dates.json"
    if pdufa_path.exists():
        try:
            pdufa = json.loads(pdufa_path.read_text())
            entries = pdufa if isinstance(pdufa, list) else pdufa.get("entries", pdufa.get("dates", []))
            for e in entries:
                if "pdufa_date" in e and "date" not in e:
                    e["date"] = e["pdufa_date"]
                if "as_of_disclosed_at" in e and "disclosed_at" not in e:
                    e["disclosed_at"] = e["as_of_disclosed_at"]
            n = graph.load_from_pdufa(entries, as_of)
            logger.info("PDUFA: %d nodes", n)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load PDUFA dates: %s", exc)

    # 2. Catalyst events (most recent file <= as_of)
    cat_files = sorted(prod_data.glob("catalyst_events_*.json"))
    best_file = None
    for f in cat_files:
        try:
            fdate = f.stem.replace("catalyst_events_", "")
            if date.fromisoformat(fdate) <= as_of:
                best_file = f
        except (ValueError, TypeError):
            continue

    if best_file:
        try:
            data = json.loads(best_file.read_text())
            summaries = data.get("summaries", [])
            n = graph.load_from_catalyst_events(summaries, as_of)
            logger.info("Catalyst events (%s): %d nodes", best_file.name, n)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load catalyst events: %s", exc)

    # 3. Event ledger
    ledger_path = data_dir / "catalyst_history" / "catalyst_history_events.jsonl"
    if ledger_path.exists():
        try:
            entries = []
            for line in ledger_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "pit_available_at" in entry and "disclosed_at" not in entry:
                        entry["disclosed_at"] = entry["pit_available_at"]
                    if "source_uid" not in entry:
                        entry["source_uid"] = entry.get("event_id", entry.get("dedupe_key", ""))
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
            n = graph.load_from_ledger_entries(entries, as_of)
            logger.info("Event ledger: %d nodes", n)
        except OSError as exc:
            logger.warning("Failed to load event ledger: %s", exc)

    # 4. CRT resolutions
    resolutions_dir = data_dir / "snapshots" / "resolutions"
    if resolutions_dir.exists():
        recs = []
        for f in resolutions_dir.rglob("*.json"):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, dict) and "ticker" in data and "outcome" in data:
                    recs.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        if recs:
            n = graph.apply_resolutions(recs, as_of)
            logger.info("CRT resolutions: %d applied", n)

    # 5. Manual overrides
    overrides_path = prod_data / "crt_manual_overrides.json"
    if overrides_path.exists():
        try:
            overrides = json.loads(overrides_path.read_text())
            override_list = overrides if isinstance(overrides, list) else overrides.get("overrides", [])
            n = graph.apply_resolutions(override_list, as_of)
            logger.info("Manual overrides: %d applied", n)
        except (json.JSONDecodeError, OSError):
            pass

    # 5.5. Supplement from rankings.csv — create nodes for tickers with Module 3
    # catalysts but no graph node (bridges the M3 ↔ EV graph gap)
    snapshots_dir = data_dir / "snapshots"
    _n_supplemented = _supplement_from_rankings(graph, as_of, snapshots_dir)
    if _n_supplemented > 0:
        logger.info("Rankings supplement: %d nodes created from Module 3 catalysts", _n_supplemented)

    # 6. Enrich clinical nodes with phase from trial_records.json
    # Phase is critical for outcome model priors but the event ledger
    # and catalyst_events sources often lack it.
    trial_path = prod_data / "trial_records.json"
    if trial_path.exists():
        try:
            trials = json.loads(trial_path.read_text())
            ticker_phase = _build_ticker_phase_map(trials)
            n_enriched = graph.enrich_phases(ticker_phase)
            if n_enriched > 0:
                logger.info("Phase enrichment: %d nodes updated from trial_records", n_enriched)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to enrich phases: %s", exc)

    # 7. Fix range-marker date precision (SEC_8K nodes with synthetic dates)
    n_precision = graph.fix_range_marker_precision()
    if n_precision > 0:
        logger.info("Date precision: %d nodes updated (range markers)", n_precision)

    # 8. Tag overdue windowed nodes (days_to_event handles them natively now)
    n_overdue = graph.tag_overdue_windowed_nodes(as_of)
    if n_overdue > 0:
        logger.info("Overdue windows: %d nodes tagged (handled by window-aware days_to_event)", n_overdue)

    # 9. Dedup by (ticker, event_type, expected_date)
    n_dedup = graph.dedup_by_event()
    if n_dedup > 0:
        logger.info("Dedup: %d duplicate nodes removed", n_dedup)

    # 10. Archive stale entries (>180d past event_date, no resolution)
    n_archived = graph.archive_stale_entries(as_of, max_age_days=180)
    if n_archived > 0:
        logger.info("Archived: %d stale entries (>180d past event_date)", n_archived)

    logger.info("Catalyst graph: %d total nodes (%d active)", graph.node_count, graph.node_count - n_archived)
    return graph


def _build_ticker_phase_map(trials: list) -> Dict[str, str]:
    """Build {ticker: lead_phase} from trial records.

    Picks the most advanced active phase per ticker.
    """
    from event_ev.catalyst_graph import _infer_phase

    _PHASE_ORDER = {"1": 1, "1_2": 2, "2": 3, "2_3": 4, "3": 5, "4": 6}
    ticker_phase: Dict[str, str] = {}

    for t in trials:
        tk = (t.get("ticker") or t.get("lead_sponsor_ticker") or "").upper()
        raw_phase = t.get("phase", "")
        if not tk or not raw_phase:
            continue

        phase = _infer_phase(raw_phase)
        if phase == "unknown":
            continue

        existing = ticker_phase.get(tk, "unknown")
        if _PHASE_ORDER.get(phase, 0) > _PHASE_ORDER.get(existing, 0):
            ticker_phase[tk] = phase

    return ticker_phase


def _supplement_from_rankings(graph: CatalystGraph, as_of: date, snapshots_dir: Path) -> int:
    """Create EV graph nodes for tickers with Module 3 catalysts but no graph node.

    Reads catalyst_days, catalyst_event_type, catalyst_family from the latest
    rankings.csv and creates nodes for tickers that the event ledger missed.
    Only creates nodes for tickers with specific_days catalyst_mode.
    """
    from datetime import timedelta

    from event_ev.catalyst_graph import CatalystNode, NodeStatus, _infer_phase

    # Find latest snapshot
    if not snapshots_dir.exists():
        return 0
    snap_dates = []
    for d in snapshots_dir.iterdir():
        if d.is_dir() and len(d.name) == 10:
            try:
                sd = date.fromisoformat(d.name)
                if sd <= as_of:
                    snap_dates.append(sd)
            except (ValueError, TypeError):
                continue
    if not snap_dates:
        return 0

    latest = max(snap_dates)
    rankings_path = snapshots_dir / str(latest) / "rankings.csv"
    if not rankings_path.exists():
        return 0

    # Find tickers with M3 catalysts but no graph node
    existing_tickers = set()
    for nid, node in graph._nodes.items():
        existing_tickers.add(node.ticker)

    created = 0
    with open(rankings_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "")
            if not ticker or ticker in existing_tickers:
                continue

            mode = row.get("catalyst_mode", "")
            if mode != "specific_days":
                continue

            days_str = row.get("catalyst_days", "").strip()
            if not days_str:
                continue

            try:
                days = int(float(days_str))
            except (ValueError, TypeError):
                continue

            event_type = row.get("catalyst_event_type", "DATA_READOUT")
            family = row.get("catalyst_family", "CLINICAL")
            expected = (as_of + timedelta(days=days)).isoformat()

            node = CatalystNode(
                ticker=ticker,
                event_family=family,
                event_type=event_type,
                event_subtype="M3_SUPPLEMENT",
                expected_date=expected,
                date_range_start=expected,
                date_range_end=None,
                date_precision="MONTH" if days > 90 else "WEEK",
                date_confidence=0.40 if days <= 90 else 0.25,
                source="M3_RANKINGS_SUPPLEMENT",
                source_uid=f"m3_{ticker}_{as_of}",
                disclosed_at=str(as_of),
                phase=_infer_phase(row.get("phase", "")),
                indication="unknown",
                status=NodeStatus.PENDING.value,
            )
            graph.add_node(node)
            existing_tickers.add(ticker)
            created += 1

    return created


# Column aliases for feature extraction
_ALIASES = {
    "de_alpha_60d": "alpha_60d",
    "de_vol_60d": "vol_60d",
}

_BOOL_YES_NO = {"opt_event_premium"}

# Feature keys are now managed by the centralized registry.
# Legacy names kept as module-level aliases for backward compatibility.
_FEATURE_KEYS = get_feature_keys()
_CONTEXT_KEYS = get_context_keys()


def load_market_features(
    as_of: date,
    snapshots_dir: Path,
) -> Dict[str, Dict[str, Any]]:
    """Load market features from the most recent snapshot.

    Args:
        as_of: Evaluation date.
        snapshots_dir: Path to data/snapshots/ directory.

    Returns:
        {ticker: {feature: value}} dict.
    """
    features: Dict[str, Dict[str, Any]] = {}

    if not snapshots_dir.exists():
        return features

    # Find most recent snapshot <= as_of
    snap_dates = []
    for d in snapshots_dir.iterdir():
        if d.is_dir() and len(d.name) == 10:
            try:
                sd = date.fromisoformat(d.name)
                if sd <= as_of:
                    snap_dates.append(sd)
            except (ValueError, TypeError):
                continue

    if not snap_dates:
        return features

    latest = max(snap_dates)
    rankings_path = snapshots_dir / str(latest) / "rankings.csv"
    if not rankings_path.exists():
        return features

    with open(rankings_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "")
            if not ticker:
                continue

            feat: Dict[str, Any] = {}
            for key in _FEATURE_KEYS:
                v = row.get(key)
                if not v or v in ("", "NA", "None", "nan"):
                    continue
                canonical = _ALIASES.get(key, key)
                if canonical in feat:
                    continue
                if key in _BOOL_YES_NO:
                    feat[canonical] = 1.0 if v.upper() == "YES" else 0.0
                elif key in ("opt_liquidity_state", "opt_iv_regime", "catalyst_family"):
                    feat[canonical] = v.strip()
                else:
                    try:
                        feat[canonical] = float(v)
                    except (ValueError, TypeError):
                        pass

            # Compute event premium magnitude from term structure
            front = feat.get("opt_front_iv")
            back = feat.get("opt_back_iv")
            if front is not None and back is not None and isinstance(back, (int, float)) and back > 0:
                feat["event_premium_magnitude"] = max(0.0, front - back)

            # Underlying price alias
            close = feat.get("close_price")
            if close and isinstance(close, (int, float)):
                feat["underlying_price"] = close

            features[ticker] = feat

    if features:
        logger.info("Market features: %d tickers from %s", len(features), latest)
    else:
        logger.warning("Market features: 0 tickers loaded")

    return features


def split_context_features(
    market_features: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Extract context features (for outcome/payoff models) from market features."""
    context: Dict[str, Dict[str, Any]] = {}
    for ticker, feats in market_features.items():
        ctx = {}
        for key in _CONTEXT_KEYS:
            if key in feats:
                ctx[key] = feats[key]
        context[ticker] = ctx
    return context


def load_trial_records(prod_data: Path, as_of: date) -> list:
    """Load trial records from trial_records.json (PIT-filtered by collected_at).

    Returns a list of trial dicts with collected_at <= as_of.
    """
    trial_path = prod_data / "trial_records.json"
    if not trial_path.exists():
        return []
    try:
        trials = json.loads(trial_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load trial records: %s", exc)
        return []
    as_of_str = str(as_of)
    return [t for t in trials if (t.get("collected_at", "") or "") <= as_of_str or not t.get("collected_at")]


def load_crt_resolutions(data_dir: Path, as_of: date) -> list:
    """Load CRT resolution records (PIT-filtered by resolution_date).

    Returns a list of resolution dicts with resolution_date <= as_of.
    """
    resolutions_dir = data_dir / "snapshots" / "resolutions"
    if not resolutions_dir.exists():
        return []
    as_of_str = str(as_of)
    recs = []
    for f in resolutions_dir.rglob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict) or "ticker" not in data:
            continue
        resolved = data.get("resolution_date") or data.get("resolved_date", "")
        if resolved and resolved > as_of_str:
            continue
        recs.append(data)
    return recs


def load_evidence_snapshots(
    nodes: list,
    as_of: date,
    prod_data: Path,
    data_dir: Path,
    enrich_pubmed: bool = False,
) -> Dict[str, "EventEvidenceSnapshot"]:
    """Build evidence snapshots for a batch of CatalystNodes.

    Loads trial records and CRT resolutions, then delegates to
    build_evidence_snapshots() for the actual construction.

    Args:
        nodes: List of CatalystNode objects.
        as_of: Evaluation date (PIT boundary).
        prod_data: Path to production_data/ directory.
        data_dir: Path to data/ directory.
        enrich_pubmed: If True, fetch PubMed literature scores via NCBI API.
            Adds ~0.3s per ticker (cached after first call). Default False
            to avoid API calls during fast production runs.

    Returns:
        {node_id: EventEvidenceSnapshot}
    """
    trials = load_trial_records(prod_data, as_of)
    resolutions = load_crt_resolutions(data_dir, as_of)

    literature_scores: Dict[str, float] = {}
    pubmed_refs: Dict[str, list] = {}
    if enrich_pubmed:
        literature_scores, pubmed_refs = enrich_literature_from_pubmed(nodes, trials)

    snapshots = build_evidence_snapshots(
        nodes,
        as_of,
        trials,
        resolutions,
        literature_scores,
        pubmed_refs,
    )
    if snapshots:
        lit_count = sum(1 for s in snapshots.values() if s.literature_support_score and s.literature_support_score > 0)
        logger.info(
            "Evidence snapshots: %d built (%d with trial match, %d with literature)",
            len(snapshots),
            sum(1 for s in snapshots.values() if s.ctgov_study_id),
            lit_count,
        )
    return snapshots
