#!/usr/bin/env python3
"""Build clinical PoS prior table from high-confidence outcome labels (Spec 023).

Creates production_data/clinical_pos_priors_v2.json with universe-specific
phase priors, endpoint modifiers, and shrinkage toward reference rates.

Usage:
    python scripts/research/build_clinical_pos_priors.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA = "clinical_pos_priors.v2"

# Wong et al. / industry reference priors (approximate)
REFERENCE_PRIORS = {
    "phase1": 0.066,
    "phase1_2": 0.15,
    "phase2": 0.305,
    "phase2_3": 0.40,
    "phase3": 0.580,
    "phase4": 0.650,
    "global": 0.115,  # overall clinical success from Phase 1
}

# Shrinkage constants
K_STRONG = 25  # n >= 200
K_MODERATE = 50  # 75 <= n < 200
K_SPARSE = 100  # n < 75

# Minimum support thresholds
MIN_N_DIRECT = 200
MIN_N_SHRUNK = 75


def shrink(raw_rate: float, n: int, reference_rate: float) -> float:
    """Apply deterministic shrinkage toward reference prior."""
    if n >= MIN_N_DIRECT:
        k = K_STRONG
    elif n >= MIN_N_SHRUNK:
        k = K_MODERATE
    else:
        k = K_SPARSE
    return round((n * raw_rate + k * reference_rate) / (n + k), 4)


def support_confidence(n: int) -> str:
    if n >= MIN_N_DIRECT:
        return "high"
    if n >= MIN_N_SHRUNK:
        return "medium"
    return "low"


def build_priors(labels: List[Dict], catalog: Dict[str, Dict]) -> Dict[str, Any]:
    """Build the prior table from high-confidence labels + catalog."""
    # Join labels to catalog for features
    rows = []
    for label in labels:
        nct = label.get("nct_id", "")
        cat = catalog.get(nct, {})
        phase = cat.get("phase", "")
        ep = cat.get("design", {}).get("endpoint_class", "other")
        bio = cat.get("design", {}).get("biomarker_selected", False)

        rows.append(
            {
                "binary_outcome": label["binary_outcome"],
                "phase": phase,
                "endpoint_class": ep,
                "biomarker_selected": bio,
            }
        )

    n_total = len(rows)
    n_success = sum(r["binary_outcome"] for r in rows)
    global_rate = round(n_success / n_total, 4) if n_total else 0

    # By phase
    by_phase = {}
    phase_groups = {}
    for r in rows:
        p = r["phase"]
        if p not in phase_groups:
            phase_groups[p] = []
        phase_groups[p].append(r["binary_outcome"])

    for phase, outcomes in sorted(phase_groups.items()):
        if not phase or phase in ("n/a", "na", "unknown"):
            continue
        n = len(outcomes)
        raw = round(sum(outcomes) / n, 4)
        ref = REFERENCE_PRIORS.get(phase, global_rate)
        by_phase[phase] = {
            "n": n,
            "raw_rate": raw,
            "shrunk_rate": shrink(raw, n, ref),
            "reference_rate": ref,
            "support_confidence": support_confidence(n),
        }

    # Endpoint modifiers (delta vs global)
    endpoint_mods = {}
    ep_groups = {}
    for r in rows:
        ep = r["endpoint_class"]
        if ep not in ep_groups:
            ep_groups[ep] = []
        ep_groups[ep].append(r["binary_outcome"])

    for ep, outcomes in sorted(ep_groups.items()):
        n = len(outcomes)
        if n < 20:
            continue
        raw = round(sum(outcomes) / n, 4)
        delta = round(raw - global_rate, 4)
        # Shrink delta toward zero
        shrunk_delta = round(delta * min(n, 500) / (min(n, 500) + K_STRONG), 4)
        endpoint_mods[ep] = {
            "n": n,
            "raw_rate": raw,
            "raw_delta_vs_global": delta,
            "shrunk_delta": shrunk_delta,
            "support_confidence": support_confidence(n),
        }

    # Biomarker modifiers
    bio_groups = {True: [], False: []}
    for r in rows:
        bio_groups[r["biomarker_selected"]].append(r["binary_outcome"])

    biomarker_mods = {}
    for bio_val, outcomes in bio_groups.items():
        n = len(outcomes)
        if n < 10:
            continue
        raw = round(sum(outcomes) / n, 4)
        delta = round(raw - global_rate, 4)
        label = "yes" if bio_val else "no"

        if bio_val and n < MIN_N_SHRUNK:
            # Low support — do not apply
            biomarker_mods[label] = {
                "n": n,
                "raw_rate": raw,
                "raw_delta_vs_global": delta,
                "shrunk_delta": 0.0,
                "support_confidence": "low",
                "policy": "do_not_apply_directly",
            }
        else:
            shrunk_delta = round(delta * min(n, 500) / (min(n, 500) + K_MODERATE), 4)
            biomarker_mods[label] = {
                "n": n,
                "raw_rate": raw,
                "raw_delta_vs_global": delta,
                "shrunk_delta": shrunk_delta,
                "support_confidence": support_confidence(n),
            }

    return {
        "schema": SCHEMA,
        "built_as_of": date.today().isoformat(),
        "label_policy": {
            "allowed_sources": ["CT_GOV_RESULTS_API"],
            "allowed_confidence": ["high"],
            "excluded_sources": ["completion_proxy"],
        },
        "global": {
            "n": n_total,
            "success_rate": global_rate,
        },
        "by_phase": by_phase,
        "endpoint_modifiers": endpoint_mods,
        "biomarker_modifiers": biomarker_mods,
        "fallback_policy": {
            "min_n_for_direct_use": MIN_N_DIRECT,
            "min_n_for_shrunk_use": MIN_N_SHRUNK,
            "otherwise": "reference_prior_only",
        },
    }


def main() -> int:
    labels_path = PROJECT_ROOT / "data" / "clinical" / "clinical_outcome_labels_v2.json"
    catalog_path = PROJECT_ROOT / "data" / "clinical" / "clinical_history_catalog.json"

    logger.info("Loading labels ...")
    labels_data = json.loads(labels_path.read_text())
    labels = [
        r
        for r in labels_data.get("labels", [])
        if r.get("confidence") == "high" and r.get("binary_outcome") is not None
    ]
    logger.info("High-confidence labels: %d", len(labels))

    logger.info("Loading catalog ...")
    cat_data = json.loads(catalog_path.read_text())
    catalog = {r["nct_id"]: r for r in cat_data.get("records", [])}

    logger.info("Building priors ...")
    priors = build_priors(labels, catalog)

    # Write artifact
    out_path = PROJECT_ROOT / "production_data" / "clinical_pos_priors_v2.json"
    out_path.write_text(json.dumps(priors, indent=2) + "\n")
    logger.info("Priors → %s", out_path)

    # Summary
    logger.info("  Global: %.1f%% (n=%d)", priors["global"]["success_rate"] * 100, priors["global"]["n"])
    for phase, p in sorted(priors["by_phase"].items()):
        logger.info(
            "  %s: raw=%.1f%% shrunk=%.1f%% ref=%.1f%% (n=%d, %s)",
            phase,
            p["raw_rate"] * 100,
            p["shrunk_rate"] * 100,
            p["reference_rate"] * 100,
            p["n"],
            p["support_confidence"],
        )
    for ep, m in sorted(priors["endpoint_modifiers"].items()):
        logger.info(
            "  EP %s: delta=%.1f%% shrunk_delta=%.1f%% (n=%d)",
            ep,
            m["raw_delta_vs_global"] * 100,
            m["shrunk_delta"] * 100,
            m["n"],
        )

    # Markdown summary
    md = [
        "# Clinical PoS Priors v2",
        "",
        f"**Built**: {priors['built_as_of']}",
        f"**Labels**: {priors['global']['n']} high-confidence",
        f"**Global success rate**: {priors['global']['success_rate']:.1%}",
        "",
        "## Phase Priors",
        "",
        "| Phase | N | Raw | Shrunk | Reference | Confidence |",
        "|-------|---|-----|--------|-----------|-----------|",
    ]
    for phase, p in sorted(priors["by_phase"].items()):
        md.append(
            f"| {phase} | {p['n']} | {p['raw_rate']:.1%} | {p['shrunk_rate']:.1%} | {p['reference_rate']:.1%} | {p['support_confidence']} |"
        )

    md += [
        "",
        "## Endpoint Modifiers",
        "",
        "| Endpoint | N | Raw Delta | Shrunk Delta | Confidence |",
        "|----------|---|-----------|-------------|-----------|",
    ]
    for ep, m in sorted(priors["endpoint_modifiers"].items()):
        md.append(
            f"| {ep} | {m['n']} | {m['raw_delta_vs_global']:+.1%} | {m['shrunk_delta']:+.1%} | {m['support_confidence']} |"
        )

    md += [
        "",
        "## Biomarker Modifiers",
        "",
        "| Biomarker | N | Raw Delta | Shrunk Delta | Policy |",
        "|-----------|---|-----------|-------------|--------|",
    ]
    for label, m in sorted(priors["biomarker_modifiers"].items()):
        policy = m.get("policy", "apply")
        md.append(f"| {label} | {m['n']} | {m['raw_delta_vs_global']:+.1%} | {m['shrunk_delta']:+.1%} | {policy} |")

    md.append("")
    out_md = PROJECT_ROOT / "output" / "clinical_pos_priors_v2_summary.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md))
    logger.info("Summary → %s", out_md)

    return 0


if __name__ == "__main__":
    sys.exit(main())
