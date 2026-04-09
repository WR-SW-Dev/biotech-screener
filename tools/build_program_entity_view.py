#!/usr/bin/env python3
"""Program entity view — unified per-program join across enrichment layers.

Joins drug_master, indication_master, ctgov_endpoints, label_regulatory,
biomarker_context, and open_targets into one program-native view keyed by
ticker × canonical drug × normalized indication.

This is the derived artifact that competitive_intel and other downstream
tools should consume instead of raw source-native enrichments.

Output:
    data/enrichment/program_entity_view_{date}.json

Usage:
    python tools/build_program_entity_view.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("program_entity_view")

SCHEMA_VERSION = "program_entity_view.v1"
DATA_DIR = REPO_ROOT / "data"


def _load_condition_aliases() -> Dict[str, str]:
    """Load condition alias map (variant → canonical)."""
    path = DATA_DIR / "condition_aliases.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    # Keys are already lowercased in the file; filter out metadata keys
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _load_ta_rollup() -> Dict[str, Any]:
    """Load therapeutic area rollup config."""
    path = DATA_DIR / "therapeutic_area_rollup.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_simplified_ta(
    raw_condition: str,
    efo_therapeutic_areas: List[str],
    ta_rollup: Dict[str, Any],
) -> Optional[str]:
    """Resolve a single simplified therapeutic area from EFO TAs + overrides."""
    # Direct condition override takes priority
    overrides = ta_rollup.get("condition_to_ta_override", {})
    if raw_condition in overrides:
        return overrides[raw_condition]

    # Map from EFO therapeutic_areas via rollup, first non-null wins by priority
    efo_map = ta_rollup.get("efo_to_ta", {})
    ta_priority = ta_rollup.get("ta_priority", [])
    mapped = set()
    for efo_ta in efo_therapeutic_areas:
        ta = efo_map.get(efo_ta)
        if ta:
            mapped.add(ta)
    if mapped:
        for ta in ta_priority:
            if ta in mapped:
                return ta
        return next(iter(mapped))

    return None


def _load_latest(enrichment_dir: Path, prefix: str) -> Optional[Dict]:
    candidates = sorted(enrichment_dir.glob(f"{prefix}_*.json"))
    if not candidates:
        return None
    with open(candidates[-1], encoding="utf-8") as f:
        return json.load(f)


def _match_confidence(has_rxcui: bool, has_chembl: bool, has_inxight: bool) -> str:
    n = sum([has_rxcui, has_chembl, has_inxight])
    if n >= 2:
        return "high"
    if n == 1:
        return "medium"
    return "low"


def _disease_confidence(has_efo: bool, has_medgen: bool) -> str:
    if has_efo and has_medgen:
        return "high"
    if has_efo or has_medgen:
        return "medium"
    return "low"


def build_program_entity_view(
    *,
    enrichment_dir: Path = REPO_ROOT / "data" / "enrichment",
    cache_dir: Path = REPO_ROOT / "cache" / "ctgov",
) -> Dict[str, Any]:
    """Build unified program entity view from enrichment layers."""

    # Load alias and TA rollup maps
    condition_aliases = _load_condition_aliases()
    ta_rollup = _load_ta_rollup()
    if condition_aliases:
        logger.info("Loaded %d condition aliases", len(condition_aliases))
    if ta_rollup:
        logger.info(
            "Loaded TA rollup (%d EFO mappings, %d condition overrides)",
            len(ta_rollup.get("efo_to_ta", {})),
            len(ta_rollup.get("condition_to_ta_override", {})),
        )

    # Load all enrichment sources
    drug_master = _load_latest(enrichment_dir, "drug_master")
    indication_master = _load_latest(enrichment_dir, "indication_master")
    endpoints = _load_latest(enrichment_dir, "ctgov_endpoints")
    label_reg = _load_latest(enrichment_dir, "label_regulatory")
    biomarker = _load_latest(enrichment_dir, "biomarker_context")
    open_targets = _load_latest(enrichment_dir, "open_targets")

    source_versions = {}
    for name, data in [
        ("drug_master", drug_master),
        ("indication_master", indication_master),
        ("ctgov_endpoints", endpoints),
        ("label_regulatory", label_reg),
        ("biomarker_context", biomarker),
        ("open_targets", open_targets),
    ]:
        if data:
            source_versions[name] = data.get("schema", "unknown")

    logger.info("Source versions: %s", source_versions)

    # Load CTgov trials as the backbone
    ctgov_candidates = sorted(p for p in cache_dir.glob("trial_records_*.json") if not p.name.endswith(".meta.json"))
    if not ctgov_candidates:
        return {"error": "no CTgov cache"}

    with open(ctgov_candidates[-1], encoding="utf-8") as f:
        trials = json.load(f)

    # Build drug index from drug_master
    drug_index: Dict[str, Dict] = {}  # raw_name → drug entry
    if drug_master:
        for ticker, entries in drug_master.get("entries", {}).items():
            for entry in entries:
                raw = entry.get("raw_name", "")
                if raw:
                    drug_index[raw.lower()] = entry

    # Build indication index from indication_master
    indication_index: Dict[str, Dict] = {}  # raw_condition → indication entry
    if indication_master:
        for cond, entry in indication_master.get("entries", {}).items():
            indication_index[cond.lower()] = entry

    # Build endpoint index from ctgov_endpoints
    endpoint_index: Dict[str, Dict] = {}  # nct_id → endpoint entry
    if endpoints:
        for entry in endpoints.get("enrichments", []):
            nct = entry.get("nct_id", "")
            if nct:
                endpoint_index[nct] = entry

    # Build label index from label_regulatory
    label_index: Dict[str, List[Dict]] = {}  # ticker → label entries
    if label_reg:
        label_index = label_reg.get("entries", {})

    # Build biomarker index
    biomarker_index: Dict[str, Dict] = {}  # ticker → biomarker entry
    if biomarker:
        biomarker_index = biomarker.get("entries", {})

    # Build programs: group trials by ticker
    ticker_programs: Dict[str, List[Dict]] = defaultdict(list)

    for trial in trials:
        ticker = trial.get("ticker", "")
        if not ticker:
            continue

        nct_id = trial.get("nct_id", "")
        raw_interventions = trial.get("interventions", [])
        raw_conditions = trial.get("conditions", [])

        # Resolve drug entity
        drug_entity = None
        for intervention in raw_interventions[:3]:
            if not intervention:
                continue
            match = drug_index.get(intervention.lower())
            if match:
                drug_entity = {
                    "raw_name": intervention,
                    "canonical_name": (match.get("rxnorm", {}) or {}).get("rxnorm_name")
                    or (match.get("inxight", {}) or {}).get("inxight_name")
                    or (match.get("chembl", {}) or {}).get("pref_name")
                    or intervention,
                    "rxcui": (match.get("rxnorm", {}) or {}).get("rxcui"),
                    "chembl_id": (match.get("chembl", {}) or {}).get("chembl_id"),
                    "inxight_uuid": (match.get("inxight", {}) or {}).get("inxight_uuid"),
                    "molecule_type": (match.get("chembl", {}) or {}).get("molecule_type"),
                    "max_phase": (match.get("chembl", {}) or {}).get("max_phase"),
                    "mechanisms": (match.get("chembl", {}) or {}).get("mechanisms", []),
                    "synonyms": (match.get("inxight", {}) or {}).get("synonyms", []),
                }
                break
        if not drug_entity and raw_interventions:
            drug_entity = {"raw_name": raw_interventions[0], "canonical_name": raw_interventions[0]}

        # Resolve indication entity (use first non-noise condition)
        # Try alias-resolved lookup before exact match
        indication_entity = None
        for cond in raw_conditions[:3]:
            cond_lower = cond.lower()
            # Alias resolution: map variant → canonical, then look up canonical
            canonical = condition_aliases.get(cond_lower)
            match = None
            if canonical:
                match = indication_index.get(canonical.lower())
            if not match:
                match = indication_index.get(cond_lower)
            if match and not match.get("excluded"):
                efo = match.get("efo", {}) or {}
                medgen = match.get("medgen", {}) or {}
                efo_tas = efo.get("therapeutic_areas", [])
                raw_cond_display = canonical or cond
                simplified_ta = _resolve_simplified_ta(raw_cond_display, efo_tas, ta_rollup)
                indication_entity = {
                    "raw_condition": cond,
                    "canonical_condition": canonical or cond,
                    "efo_id": efo.get("efo_id"),
                    "efo_name": efo.get("efo_name"),
                    "medgen_uid": medgen.get("medgen_uid"),
                    "therapeutic_areas": efo_tas,
                    "simplified_therapeutic_area": simplified_ta,
                    "is_rare": match.get("is_rare", False),
                }
                break
        if not indication_entity and raw_conditions:
            raw_cond = raw_conditions[0]
            canonical = condition_aliases.get(raw_cond.lower())
            simplified_ta = _resolve_simplified_ta(canonical or raw_cond, [], ta_rollup)
            indication_entity = {
                "raw_condition": raw_cond,
                "canonical_condition": canonical or raw_cond,
                "simplified_therapeutic_area": simplified_ta,
            }

        # Attach trial context
        trial_context = endpoint_index.get(nct_id, {})

        # Build program key
        drug_key = (drug_entity or {}).get("canonical_name", "unknown")
        disease_key = (indication_entity or {}).get("efo_id") or (indication_entity or {}).get(
            "raw_condition", "unknown"
        )
        program_key = f"{ticker}|{drug_key}|{disease_key}"

        # Join quality
        de = drug_entity or {}
        ie = indication_entity or {}
        join_quality = {
            "drug_match_confidence": _match_confidence(
                bool(de.get("rxcui")), bool(de.get("chembl_id")), bool(de.get("inxight_uuid"))
            ),
            "disease_match_confidence": _disease_confidence(bool(ie.get("efo_id")), bool(ie.get("medgen_uid"))),
            "has_trial_context": bool(trial_context),
            "has_label_context": ticker in label_index,
            "has_biomarker_context": ticker in biomarker_index,
        }

        program = {
            "program_key": program_key,
            "nct_id": nct_id,
            "phase": trial.get("phase", ""),
            "status": trial.get("status", ""),
            "drug": drug_entity,
            "indication": indication_entity,
            "trial_context": (
                {
                    k: trial_context.get(k)
                    for k in ["planned_enrollment", "primary_outcomes", "allocation", "masking", "primary_purpose"]
                    if trial_context.get(k) is not None
                }
                if trial_context
                else {}
            ),
            "join_quality": join_quality,
        }
        ticker_programs[ticker].append(program)

    # Add label and biomarker overlays at ticker level
    entries = []
    for ticker in sorted(ticker_programs):
        programs = ticker_programs[ticker]

        # Deduplicate by program_key (keep first = most data)
        seen_keys = set()
        deduped = []
        for p in programs:
            pk = p["program_key"]
            if pk not in seen_keys:
                seen_keys.add(pk)
                deduped.append(p)

        entry = {
            "ticker": ticker,
            "n_programs": len(deduped),
            "programs": deduped[:20],  # Cap per ticker
            "label_regulatory": label_index.get(ticker, [])[:3],
            "biomarker_context": biomarker_index.get(ticker, {}),
        }
        entries.append(entry)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_versions": source_versions,
        "n_tickers": len(entries),
        "n_programs_total": sum(e["n_programs"] for e in entries),
        "entries": entries,
    }

    out_path = enrichment_dir / f"program_entity_view_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s (%d tickers, %d programs)", out_path, len(entries), result["n_programs_total"])

    return result


def main():
    argparse.ArgumentParser(description="Program entity view builder").parse_args()
    result = build_program_entity_view()
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
