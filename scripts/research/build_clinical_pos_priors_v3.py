#!/usr/bin/env python3
"""Build survivorship-adjusted clinical PoS priors v3.

Constructs production_data/clinical_pos_priors_v3.json from:
- data/clinical/clinical_history_catalog.json
- data/clinical/clinical_outcome_labels_v2.json

Design goals:
- deterministic
- PIT-safe inputs only
- explicit survivorship assumptions
- conservative shrinkage toward Wong reference rates
- output suitable for diagnostic / loader use

Usage:
    python scripts/research/build_clinical_pos_priors_v3.py
    python scripts/research/build_clinical_pos_priors_v3.py --terminated-fail-prob 0.75
    python scripts/research/build_clinical_pos_priors_v3.py --completed-no-results-fail-prob 0.20
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA = "clinical_pos_priors.v3"

# Wong-style population references used as shrink anchor.
# These are anchors, not truth for this universe.
WONG_REFERENCE = {
    "phase1": 0.066,
    "phase1_2": 0.186,
    "phase2": 0.305,
    "phase2_3": 0.443,
    "phase3": 0.580,
    "phase4": 0.650,
    "approved": 0.950,
    "preclinical": 0.030,
    "unknown": 0.305,
}

# Endpoint modifiers are learned as deltas vs overall adjusted rate,
# then bounded for production safety.
ENDPOINT_MODIFIER_CAP = 0.10

PHASE_ORDER = [
    "preclinical",
    "phase1",
    "phase1_2",
    "phase2",
    "phase2_3",
    "phase3",
    "phase4",
    "approved",
    "unknown",
]


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _phase_key(raw: str) -> str:
    s = (raw or "").strip().lower().replace("/", "_").replace(" ", "")
    mapping = {
        "phase1": "phase1",
        "phase2": "phase2",
        "phase3": "phase3",
        "phase4": "phase4",
        "phase1_2": "phase1_2",
        "phase2_3": "phase2_3",
        "phase1phase2": "phase1_2",
        "phase2phase3": "phase2_3",
        "approved": "approved",
        "preclinical": "preclinical",
        "unknown": "unknown",
    }
    return mapping.get(s, s if s in WONG_REFERENCE else "unknown")


def _endpoint_key(raw: str) -> str:
    s = (raw or "").strip().lower()
    mapping = {
        "overall_survival": "overall_survival",
        "progression_free_survival": "progression_free_survival",
        "objective_response_rate": "objective_response_rate",
        "surrogate": "surrogate",
        "other": "other",
    }
    return mapping.get(s, "other")


def _status_key(raw: str) -> str:
    return (raw or "").strip().upper()


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        if math.isnan(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _label_records(labels_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Support either {"labels": [...]} or {"records": [...]}.
    if isinstance(labels_obj.get("labels"), list):
        return labels_obj["labels"]
    if isinstance(labels_obj.get("records"), list):
        return labels_obj["records"]
    return []


def _effective_sample_size(n_labeled: int, n_unlabeled: int) -> float:
    # Conservative ESS: unlabeled observations count at half weight.
    return float(n_labeled) + 0.5 * float(n_unlabeled)


def _shrink_rate(
    empirical: Optional[float],
    reference: float,
    n_labeled: int,
    n_unlabeled: int,
    min_support: int,
    prior_strength: float,
) -> Tuple[float, str]:
    """Shrink empirical toward reference with explicit support logic."""
    if empirical is None:
        return reference, "reference_no_empirical"

    ess = _effective_sample_size(n_labeled, n_unlabeled)
    if ess < min_support:
        return reference, "reference_thin_support"

    weight_emp = ess / (ess + prior_strength)
    shrunk = weight_emp * empirical + (1.0 - weight_emp) * reference
    return shrunk, "shrunk_empirical"


def _bounded_endpoint_delta(
    endpoint_rate: Optional[float],
    overall_rate: Optional[float],
) -> float:
    if endpoint_rate is None or overall_rate is None:
        return 0.0
    delta = endpoint_rate - overall_rate
    return max(-ENDPOINT_MODIFIER_CAP, min(ENDPOINT_MODIFIER_CAP, delta))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build survivorship-adjusted clinical PoS priors v3.")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=PROJECT_ROOT / "data" / "clinical" / "clinical_history_catalog.json",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=PROJECT_ROOT / "data" / "clinical" / "clinical_outcome_labels_v2.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "clinical_pos_priors_v3.json",
    )
    parser.add_argument(
        "--terminated-fail-prob",
        type=float,
        default=0.75,
        help="Assumed failure probability for TERMINATED unlabeled trials.",
    )
    parser.add_argument(
        "--withdrawn-fail-prob",
        type=float,
        default=0.60,
        help="Assumed failure probability for WITHDRAWN unlabeled trials.",
    )
    parser.add_argument(
        "--completed-no-results-fail-prob",
        type=float,
        default=0.15,
        help="Assumed failure probability for COMPLETED unlabeled trials with no posted results.",
    )
    parser.add_argument(
        "--min-support",
        type=int,
        default=50,
        help="Minimum effective support before using shrunk empirical instead of pure reference.",
    )
    parser.add_argument(
        "--prior-strength",
        type=float,
        default=150.0,
        help="Shrinkage strength toward Wong reference.",
    )
    parser.add_argument(
        "--min-label-confidence",
        default="high",
        choices=["high", "medium", "low"],
        help="Minimum label confidence to admit from labels_v2.",
    )
    args = parser.parse_args(argv)

    conf_rank = {"low": 0, "medium": 1, "high": 2}
    min_conf_rank = conf_rank[args.min_label_confidence.lower()]

    if not args.catalog.exists():
        logger.error("Missing catalog: %s", args.catalog)
        return 1
    if not args.labels.exists():
        logger.error("Missing labels: %s", args.labels)
        return 1

    catalog_obj = _load_json(args.catalog)
    labels_obj = _load_json(args.labels)

    records = catalog_obj.get("records", [])
    label_records = _label_records(labels_obj)

    logger.info("Catalog records: %d", len(records))
    logger.info("Raw labels: %d", len(label_records))

    # Keep highest-confidence label per NCT ID.
    labels_by_nct: Dict[str, Dict[str, Any]] = {}
    for rec in label_records:
        nct_id = (rec.get("nct_id") or "").strip()
        if not nct_id:
            continue

        conf = str(rec.get("confidence", "")).lower()
        if conf_rank.get(conf, -1) < min_conf_rank:
            continue

        outcome = rec.get("binary_outcome")
        if outcome not in (0, 1):
            continue

        prev = labels_by_nct.get(nct_id)
        if prev is None or conf_rank.get(conf, -1) > conf_rank.get(str(prev.get("confidence", "")).lower(), -1):
            labels_by_nct[nct_id] = rec

    logger.info("Admitted labels after confidence filter: %d", len(labels_by_nct))

    # Phase / endpoint buckets
    phase_stats: Dict[str, Dict[str, float]] = {
        p: {
            "labeled_success": 0.0,
            "labeled_failure": 0.0,
            "terminated_unlabeled": 0.0,
            "withdrawn_unlabeled": 0.0,
            "completed_no_results_unlabeled": 0.0,
            "other_unlabeled": 0.0,
            "n_catalog": 0.0,
        }
        for p in PHASE_ORDER
    }

    endpoint_label_stats: Dict[str, Dict[str, float]] = {}
    overall = {
        "labeled_success": 0.0,
        "labeled_failure": 0.0,
        "terminated_unlabeled": 0.0,
        "withdrawn_unlabeled": 0.0,
        "completed_no_results_unlabeled": 0.0,
        "other_unlabeled": 0.0,
        "n_catalog": 0.0,
    }

    for rec in records:
        nct_id = (rec.get("nct_id") or "").strip()
        phase = _phase_key(rec.get("phase", "unknown"))
        endpoint = _endpoint_key((rec.get("design") or {}).get("endpoint_class"))
        lifecycle = rec.get("lifecycle") or {}
        status = _status_key(rec.get("status"))
        has_posted_results = bool(lifecycle.get("has_posted_results"))
        is_terminated = bool(lifecycle.get("is_terminated"))

        phase_stats.setdefault(phase, phase_stats["unknown"])
        phase_stats[phase]["n_catalog"] += 1.0
        overall["n_catalog"] += 1.0

        endpoint_label_stats.setdefault(
            endpoint,
            {"labeled_success": 0.0, "labeled_failure": 0.0, "n_labeled": 0.0},
        )

        label = labels_by_nct.get(nct_id)
        if label is not None:
            if int(label["binary_outcome"]) == 1:
                phase_stats[phase]["labeled_success"] += 1.0
                overall["labeled_success"] += 1.0
                endpoint_label_stats[endpoint]["labeled_success"] += 1.0
            else:
                phase_stats[phase]["labeled_failure"] += 1.0
                overall["labeled_failure"] += 1.0
                endpoint_label_stats[endpoint]["labeled_failure"] += 1.0
            endpoint_label_stats[endpoint]["n_labeled"] += 1.0
            continue

        # Unlabeled survivorship buckets.
        if status == "TERMINATED":
            phase_stats[phase]["terminated_unlabeled"] += 1.0
            overall["terminated_unlabeled"] += 1.0
        elif status == "WITHDRAWN":
            phase_stats[phase]["withdrawn_unlabeled"] += 1.0
            overall["withdrawn_unlabeled"] += 1.0
        elif status == "COMPLETED" and not has_posted_results:
            phase_stats[phase]["completed_no_results_unlabeled"] += 1.0
            overall["completed_no_results_unlabeled"] += 1.0
        elif is_terminated:
            phase_stats[phase]["terminated_unlabeled"] += 1.0
            overall["terminated_unlabeled"] += 1.0
        else:
            phase_stats[phase]["other_unlabeled"] += 1.0
            overall["other_unlabeled"] += 1.0

    def summarize_bucket(stats: Dict[str, float], phase_key: str) -> Dict[str, Any]:
        s = stats["labeled_success"]
        f = stats["labeled_failure"]
        t = stats["terminated_unlabeled"]
        w = stats["withdrawn_unlabeled"]
        c = stats["completed_no_results_unlabeled"]

        labeled_n = s + f
        observed_rate = (s / labeled_n) if labeled_n > 0 else None

        worst_total = labeled_n + t + w + c
        worst_case_rate = (s / worst_total) if worst_total > 0 else None

        adjusted_failures = (
            f + t * args.terminated_fail_prob + w * args.withdrawn_fail_prob + c * args.completed_no_results_fail_prob
        )
        adjusted_total = s + adjusted_failures
        adjusted_rate = (s / adjusted_total) if adjusted_total > 0 else None

        unlabeled_n = t + w + c + stats["other_unlabeled"]
        reference = WONG_REFERENCE.get(phase_key, WONG_REFERENCE["unknown"])
        shrunk_rate, source = _shrink_rate(
            empirical=adjusted_rate,
            reference=reference,
            n_labeled=int(labeled_n),
            n_unlabeled=int(unlabeled_n),
            min_support=args.min_support,
            prior_strength=args.prior_strength,
        )

        return {
            "phase": phase_key,
            "reference_rate_wong": round(reference, 6),
            "observed_rate_posted_results_only": round(observed_rate, 6) if observed_rate is not None else None,
            "worst_case_rate_all_unlabeled_fail": round(worst_case_rate, 6) if worst_case_rate is not None else None,
            "survivorship_adjusted_rate": round(adjusted_rate, 6) if adjusted_rate is not None else None,
            "shrunk_rate": round(shrunk_rate, 6),
            "source": source,
            "counts": {
                "n_catalog": int(stats["n_catalog"]),
                "n_labeled_success": int(s),
                "n_labeled_failure": int(f),
                "n_labeled_total": int(labeled_n),
                "n_terminated_unlabeled": int(t),
                "n_withdrawn_unlabeled": int(w),
                "n_completed_no_results_unlabeled": int(c),
                "n_other_unlabeled": int(stats["other_unlabeled"]),
                "n_unlabeled_total": int(unlabeled_n),
            },
            "assumption_applied": {
                "terminated_fail_prob": args.terminated_fail_prob,
                "withdrawn_fail_prob": args.withdrawn_fail_prob,
                "completed_no_results_fail_prob": args.completed_no_results_fail_prob,
            },
            "uncertainty_bounds": {
                "lower_worst_case": round(worst_case_rate, 6) if worst_case_rate is not None else None,
                "upper_observed": round(observed_rate, 6) if observed_rate is not None else None,
            },
        }

    overall_summary = summarize_bucket(overall, "phase2")  # reference placeholder overwritten below
    # For overall, use simple weighted reference from phase2/phase3 anchor.
    overall_reference = 0.415
    overall_summary["phase"] = "overall"
    overall_summary["reference_rate_wong"] = overall_reference
    overall_shrunk, overall_source = _shrink_rate(
        empirical=overall_summary["survivorship_adjusted_rate"],
        reference=overall_reference,
        n_labeled=overall_summary["counts"]["n_labeled_total"],
        n_unlabeled=overall_summary["counts"]["n_unlabeled_total"],
        min_support=args.min_support,
        prior_strength=args.prior_strength,
    )
    overall_summary["shrunk_rate"] = round(overall_shrunk, 6)
    overall_summary["source"] = overall_source

    by_phase = {}
    for phase in PHASE_ORDER:
        by_phase[phase] = summarize_bucket(phase_stats[phase], phase)

    # Endpoint modifiers relative to overall adjusted rate.
    overall_adj = overall_summary["survivorship_adjusted_rate"]
    endpoint_modifiers = {}
    for endpoint, stats in sorted(endpoint_label_stats.items()):
        n_labeled = int(stats["n_labeled"])
        if n_labeled == 0:
            endpoint_rate = None
        else:
            endpoint_rate = stats["labeled_success"] / n_labeled
        delta = _bounded_endpoint_delta(endpoint_rate, overall_adj)
        endpoint_modifiers[endpoint] = {
            "endpoint": endpoint,
            "observed_rate": round(endpoint_rate, 6) if endpoint_rate is not None else None,
            "modifier_delta": round(delta, 6),
            "n_labeled": n_labeled,
            "source": "observed_labeled_only",
            "bounded_cap": ENDPOINT_MODIFIER_CAP,
        }

    # Biomarker neutrality preserved unless evidence is large enough.
    biomarker_modifier = {
        "modifier_delta": 0.0,
        "source": "neutral_due_to_confounding_and_thin_support",
        "note": "Keep neutral until survivorship-adjusted biomarker cell has materially larger support.",
    }

    def _rel_path(p: Path) -> str:
        try:
            return str(p.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(p)

    out_obj = {
        "schema_version": SCHEMA,
        "built_as_of": date.today().isoformat(),
        "source_artifacts": {
            "clinical_history_catalog": {
                "path": _rel_path(args.catalog),
                "sha256": _sha256_bytes(args.catalog.read_bytes()),
            },
            "clinical_outcome_labels_v2": {
                "path": _rel_path(args.labels),
                "sha256": _sha256_bytes(args.labels.read_bytes()),
            },
        },
        "assumptions": {
            "terminated_fail_prob": args.terminated_fail_prob,
            "withdrawn_fail_prob": args.withdrawn_fail_prob,
            "completed_no_results_fail_prob": args.completed_no_results_fail_prob,
            "min_support": args.min_support,
            "prior_strength": args.prior_strength,
            "min_label_confidence": args.min_label_confidence,
            "notes": [
                "Observed posted-results rates are upward-biased by survivorship.",
                "Survivorship-adjusted rate is the working empirical anchor.",
                "Shrunk rate is the production-facing rate.",
                "Endpoint modifiers are bounded and biomarker stays neutral in v3.",
            ],
        },
        "overall": overall_summary,
        "phase_priors": by_phase,
        "endpoint_modifiers": endpoint_modifiers,
        "biomarker_modifier": biomarker_modifier,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Wrote %s", args.out)

    # Human-readable summary
    logger.info(
        "Overall observed=%.3f adjusted=%.3f shrunk=%.3f",
        overall_summary["observed_rate_posted_results_only"] or float("nan"),
        overall_summary["survivorship_adjusted_rate"] or float("nan"),
        overall_summary["shrunk_rate"],
    )
    for phase in ["phase2", "phase3", "phase4"]:
        row = by_phase[phase]
        logger.info(
            "%s observed=%.3f adjusted=%.3f shrunk=%.3f labeled=%d unlabeled=%d",
            phase,
            row["observed_rate_posted_results_only"] or float("nan"),
            row["survivorship_adjusted_rate"] or float("nan"),
            row["shrunk_rate"],
            row["counts"]["n_labeled_total"],
            row["counts"]["n_unlabeled_total"],
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
