#!/usr/bin/env python3
"""Competitive intelligence — cross-reference trial outcomes by therapeutic area.

Builds an indication → tickers mapping from CTgov trial conditions, then
surfaces when a competitor in the same indication has a material event
(from catalyst_delta, ctgov_daily, or price_action_watch).

Read-only — does not affect rankings, scoring, or execution.

Output:
    artifacts/competitive_intel/{date}_intel.json
    artifacts/competitive_intel/{date}_intel.md

Usage:
    python tools/build_competitive_intel.py --as-of-date 2026-03-27
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("competitive_intel")

SCHEMA_VERSION = "competitive_intel.v1"

# Filter out generic/noisy conditions
NOISE_CONDITIONS = frozenset(
    {
        "Healthy",
        "Healthy Volunteers",
        "Healthy Volunteer",
        "COVID-19",
        "Solid Tumor",
        "Advanced Solid Tumors",
        "Neoplasms",
        "Cancer",
        "Safety",
        "Pharmacokinetics",
        "Drug Interaction",
    }
)

MIN_SHARED_TICKERS = 2  # minimum tickers per indication to form a competitive group


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _build_enriched_indication_map(
    enrichment_dir: Path,
) -> tuple:
    """Build indication → tickers using normalized EFO/MedGen entities.

    Reads program_entity_view to get per-program indication entities, then
    groups tickers by normalized disease ID (efo_id preferred, medgen_uid
    fallback). Returns (empty, empty) if enrichment data is insufficient.
    """
    pev_candidates = sorted(enrichment_dir.glob("program_entity_view_*.json"))
    if not pev_candidates:
        return {}, {}

    pev = _load_json(pev_candidates[-1])
    if not pev or not pev.get("entries"):
        return {}, {}

    ind_tickers: Dict[str, Set[str]] = defaultdict(set)
    ind_ta: Dict[str, str] = {}  # indication_key → simplified_therapeutic_area
    n_mapped = 0
    n_total = 0

    for entry in pev["entries"]:
        ticker = entry.get("ticker", "")
        if not ticker:
            continue
        for prog in entry.get("programs", []):
            n_total += 1
            ind = prog.get("indication", {})
            # Prefer EFO ID, fall back to MedGen UID, then raw condition
            efo_id = ind.get("efo_id", "")
            efo_name = ind.get("efo_name", "")
            medgen_uid = ind.get("medgen_uid", "")
            sta = ind.get("simplified_therapeutic_area")

            if efo_id and efo_name:
                key = f"efo:{efo_id}|{efo_name}"
                ind_tickers[key].add(ticker)
                if sta and key not in ind_ta:
                    ind_ta[key] = sta
                n_mapped += 1
            elif medgen_uid:
                key = f"medgen:{medgen_uid}|{ind.get('raw_condition', '')}"
                ind_tickers[key].add(ticker)
                if sta and key not in ind_ta:
                    ind_ta[key] = sta
                n_mapped += 1

    if n_total == 0 or n_mapped / n_total < 0.10:
        logger.info(
            "Enriched indication map too sparse (%d/%d mapped), falling back to raw",
            n_mapped,
            n_total,
        )
        return {}, {}

    logger.info(
        "Enriched indication map: %d indications, %d/%d programs mapped (%.0f%%)",
        len(ind_tickers),
        n_mapped,
        n_total,
        100 * n_mapped / max(n_total, 1),
    )

    # Filter to conditions with multiple tickers
    filtered = {c: ts for c, ts in ind_tickers.items() if len(ts) >= MIN_SHARED_TICKERS}
    return filtered, {k: v for k, v in ind_ta.items() if k in filtered}


def build_indication_map(
    cache_dir: Path,
    enrichment_dir: Path = REPO_ROOT / "data" / "enrichment",
) -> tuple:
    """Build indication → tickers mapping.

    Prefers enriched program_entity_view (normalized EFO/MedGen IDs) when
    available and sufficiently populated. Falls back to raw CTgov conditions.

    Returns (ind_tickers, ind_ta) where ind_ta maps indication keys to
    simplified therapeutic areas (may be empty for raw fallback).
    """
    # Try enriched first
    enriched = _build_enriched_indication_map(enrichment_dir)
    if enriched:
        return enriched

    # Fallback: raw CTgov conditions
    candidates = sorted(p for p in cache_dir.glob("trial_records_*.json") if not p.name.endswith(".meta.json"))
    if not candidates:
        return {}, {}

    with open(candidates[-1], encoding="utf-8") as f:
        records = json.load(f)

    ind_tickers: Dict[str, Set[str]] = defaultdict(set)
    for r in records:
        ticker = r.get("ticker", "")
        conditions = r.get("conditions", [])
        if not ticker or not isinstance(conditions, list):
            continue
        for cond in conditions:
            if cond and cond not in NOISE_CONDITIONS:
                ind_tickers[cond].add(ticker)

    # Filter to conditions with multiple tickers (no TA info in raw fallback)
    return {c: ts for c, ts in ind_tickers.items() if len(ts) >= MIN_SHARED_TICKERS}, {}


def _display_indication(key: str) -> str:
    """Extract human-readable name from indication key.

    Enriched keys look like 'efo:MONDO_0007254|breast cancer' or
    'medgen:1866696|Breast Cancer'. Raw keys are plain condition strings.
    """
    if "|" in key:
        return key.split("|", 1)[1]
    return key


def find_portfolio_competitive_groups(
    indication_map: Dict[str, Set[str]],
    portfolio_tickers: Set[str],
    indication_ta: Dict[str, str] | None = None,
) -> Dict[str, Dict[str, Any]]:
    """For each portfolio ticker, find indications where competitors exist."""
    ta_map = indication_ta or {}
    groups: Dict[str, Dict[str, Any]] = {}

    for ticker in sorted(portfolio_tickers):
        ticker_indications = []
        for indication, tickers in indication_map.items():
            if ticker in tickers:
                competitors = tickers - {ticker}
                portfolio_competitors = competitors & portfolio_tickers
                entry = {
                    "indication": _display_indication(indication),
                    "indication_key": indication,
                    "n_competitors": len(competitors),
                    "n_portfolio_competitors": len(portfolio_competitors),
                    "competitors": sorted(competitors)[:10],
                    "portfolio_competitors": sorted(portfolio_competitors),
                }
                ta = ta_map.get(indication)
                if ta:
                    entry["therapeutic_area"] = ta
                ticker_indications.append(entry)

        if ticker_indications:
            # Sort by number of competitors descending
            ticker_indications.sort(key=lambda x: -x["n_competitors"])
            groups[ticker] = {
                "n_indications": len(ticker_indications),
                "top_indications": ticker_indications[:5],
            }

    return groups


def find_competitive_events(
    indication_map: Dict[str, Set[str]],
    portfolio_tickers: Set[str],
    event_sources: Dict[str, List[Dict]],
) -> List[Dict[str, Any]]:
    """Find events in competitor tickers that affect portfolio names."""
    # Build reverse map: ticker → indications
    ticker_indications: Dict[str, Set[str]] = defaultdict(set)
    for indication, tickers in indication_map.items():
        for t in tickers:
            ticker_indications[t].add(indication)

    alerts = []
    for source_name, events in event_sources.items():
        for event in events:
            event_ticker = event.get("ticker", "")
            if not event_ticker or event_ticker in portfolio_tickers:
                continue  # Skip portfolio names — they have their own monitors

            # Find which portfolio names share an indication with this event ticker
            shared_indications = ticker_indications.get(event_ticker, set())
            affected_portfolio = set()
            affected_indications = []

            for indication in shared_indications:
                portfolio_in_indication = indication_map.get(indication, set()) & portfolio_tickers
                if portfolio_in_indication:
                    affected_portfolio |= portfolio_in_indication
                    affected_indications.append(indication)

            if affected_portfolio:
                alerts.append(
                    {
                        "source": source_name,
                        "event_ticker": event_ticker,
                        "event_codes": event.get("codes", event.get("alerts", [])),
                        "shared_indications": [_display_indication(i) for i in affected_indications[:3]],
                        "affected_portfolio_tickers": sorted(affected_portfolio),
                        "n_affected": len(affected_portfolio),
                    }
                )

    # Sort by number of affected portfolio names
    alerts.sort(key=lambda x: -x["n_affected"])
    return alerts


def build_competitive_intel(
    as_of_date: str,
    *,
    artifacts_dir: Path = REPO_ROOT / "artifacts",
    cache_dir: Path = REPO_ROOT / "cache" / "ctgov",
    snapshots_dir: Path = REPO_ROOT / "data" / "snapshots",
) -> Dict[str, Any]:
    """Build competitive intelligence artifact."""
    # Build indication map
    indication_map, indication_ta = build_indication_map(cache_dir)
    if not indication_map:
        return {"error": "no CTgov cache for indication mapping"}

    logger.info("Indication map: %d indications (%d with TA)", len(indication_map), len(indication_ta))

    # Load portfolio tickers
    portfolio_tickers: Set[str] = set()
    pos_data = _load_json(artifacts_dir / "live_shadow" / "positions" / f"{as_of_date}.json")
    if pos_data:
        portfolio_tickers = {p["ticker"] for p in pos_data.get("positions", []) if p.get("ticker")}

    if not portfolio_tickers:
        # Fallback to rankings top-60
        rankings_path = snapshots_dir / as_of_date / "rankings.csv"
        if rankings_path.exists():
            with open(rankings_path, encoding="utf-8") as f:
                rows = sorted(csv.DictReader(f), key=lambda r: float(r.get("actionable_rank", "9999")))
            portfolio_tickers = {r["ticker"] for r in rows[:60] if r.get("ticker")}

    # Competitive groups
    groups = find_portfolio_competitive_groups(indication_map, portfolio_tickers, indication_ta)

    # Load event sources for cross-referencing
    event_sources: Dict[str, List[Dict]] = {}

    # Catalyst delta
    cd = _load_json(artifacts_dir / "catalyst_delta" / f"{as_of_date}_delta.json")
    if cd:
        event_sources["catalyst_delta"] = cd.get("deltas", [])

    # CTgov daily diff
    ctgov = _load_json(artifacts_dir / "ctgov_daily" / f"{as_of_date}_diff.json")
    if ctgov:
        event_sources["ctgov_daily"] = ctgov.get("changes", [])

    # Price action watch
    paw = _load_json(artifacts_dir / "price_action_watch" / f"{as_of_date}_watch.json")
    if paw:
        alerted = [r for r in paw.get("rows", []) if r.get("alerts")]
        event_sources["price_action"] = alerted

    # Surface delta (covers ~190 names, much broader than price_action's 40)
    sd = _load_json(snapshots_dir / as_of_date / "surface_delta.json")
    if sd:
        sd_events = [
            {"ticker": d["ticker"], "codes": d.get("flags", []), "severity": d.get("severity", "")}
            for d in sd.get("deltas", [])
            if d.get("severity") in ("alert", "watch")
        ]
        event_sources["surface_delta"] = sd_events

    # Universe-wide big movers: scan rankings for 1d returns > 5%
    # This catches non-portfolio names that price_action_watch doesn't cover
    rankings_path = snapshots_dir / as_of_date / "rankings.csv"
    if rankings_path.exists():
        universe_movers = []
        with open(rankings_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ticker = row.get("ticker", "")
                if not ticker or ticker in portfolio_tickers:
                    continue
                # Check momentum state as a proxy for big recent move
                mom = row.get("mom_state", "")
                tier = row.get("tier_dev", "")
                if mom in ("tailwind", "headwind") and tier in ("A", "B"):
                    universe_movers.append({"ticker": ticker, "codes": [f"MOMENTUM_{mom.upper()}"]})
        if universe_movers:
            event_sources["universe_momentum"] = universe_movers

    # Filing watch
    fw = _load_json(artifacts_dir / "filing_watch" / f"{as_of_date}_watch.json")
    if fw:
        # Dilution and material agreements are most competitively relevant
        filing_events = [
            {"ticker": f["ticker"], "codes": f.get("categories", [])}
            for f in fw.get("recent_filings", [])
            if any(c in ("DILUTION", "MATERIAL_AGREEMENT", "EARNINGS") for c in f.get("categories", []))
        ]
        if filing_events:
            event_sources["filing_watch"] = filing_events

    # Find competitive events
    competitive_events = find_competitive_events(indication_map, portfolio_tickers, event_sources)

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_indications": len(indication_map),
        "n_portfolio_tickers": len(portfolio_tickers),
        "n_competitive_groups": len(groups),
        "n_competitive_events": len(competitive_events),
        "competitive_events": competitive_events[:20],
        "portfolio_groups": groups,
    }

    # Write
    out_dir = artifacts_dir / "competitive_intel"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{as_of_date}_intel.json"
    md_path = out_dir / f"{as_of_date}_intel.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    md_path.write_text(format_intel_md(result), encoding="utf-8")
    logger.info("Wrote %s", md_path)

    result["_json_path"] = str(json_path)
    return result


def format_intel_md(d: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# Competitive Intelligence — {d['as_of_date']}")
    lines.append("")
    lines.append(
        f"Indications: {d['n_indications']} | Portfolio: {d['n_portfolio_tickers']} | "
        f"Groups: {d['n_competitive_groups']} | Events: {d['n_competitive_events']}"
    )
    lines.append("")

    events = d.get("competitive_events", [])
    if events:
        lines.append("## Competitive Events Affecting Portfolio")
        lines.append("")
        lines.append("| Event Ticker | Codes | Shared Indication | Affected Portfolio | N |")
        lines.append("|-------------|-------|-------------------|-------------------|---|")
        for e in events[:15]:
            codes = ", ".join(str(c) for c in e.get("event_codes", [])[:3])
            indications = ", ".join(e.get("shared_indications", [])[:2])
            affected = ", ".join(e.get("affected_portfolio_tickers", [])[:5])
            lines.append(f"| {e['event_ticker']} | {codes} | {indications} | {affected} | {e['n_affected']} |")
        lines.append("")

    lines.append(f"*Generated: {d.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Competitive intelligence")
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    result = build_competitive_intel(args.as_of_date)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)
    logger.info("Intel: %d groups, %d events", result["n_competitive_groups"], result["n_competitive_events"])


if __name__ == "__main__":
    main()
