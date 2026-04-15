#!/usr/bin/env python3
"""CRT vs BioTradingArena Calibration — external benchmark comparison.

Compares our conditional model predictions against BioTradingArena's
655 labeled catalyst cases to assess:
  1. Base rate calibration by event type and phase
  2. Conditional model uplift (biomarker/mechanism vs BTA outcomes)
  3. Direction accuracy (our PoS → BTA actual impact)
  4. Distribution of mispricing signal vs realized outcomes

Usage:
    cd /mnt/c/Projects/biotech_screener/biotech-screener
    python -m scripts.research.crt_bta_calibration
"""

from __future__ import annotations

import json
import logging
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BTA_PATH = PROJECT_ROOT / "production_data" / "biotradingarena_benchmark.json"
TRIAL_RECORDS = PROJECT_ROOT / "production_data" / "trial_records.json"

# Map BTA impact → binary outcome
BTA_TO_BINARY = {
    "very_positive": "HIT",
    "positive": "HIT",
    "slightly_positive": "HIT",
    "neutral": "NEUTRAL",
    "slightly_negative": "MISS",
    "negative": "MISS",
    "very_negative": "MISS",
}

# Map BTA event type → our event_family
BTA_TYPE_TO_FAMILY = {
    "fda_approval": "REGULATORY",
    "fda_rejection": "REGULATORY",
    "phase2_positive": "CLINICAL",
    "phase2_negative": "CLINICAL",
    "phase3_positive": "CLINICAL",
    "phase3_negative": "CLINICAL",
    "topline_positive": "CLINICAL",
    "topline_negative": "CLINICAL",
}

# Map BTA event type → our phase bucket
BTA_TYPE_TO_PHASE = {
    "fda_approval": "phase3",
    "fda_rejection": "phase3",
    "phase2_positive": "phase2",
    "phase2_negative": "phase2",
    "phase3_positive": "phase3",
    "phase3_negative": "phase3",
    "topline_positive": "phase3",  # topline is usually Phase 3
    "topline_negative": "phase3",
}


def _load_bta() -> List[Dict[str, Any]]:
    with open(BTA_PATH, encoding="utf-8") as f:
        d = json.load(f)
    return d["cases"]


def run_calibration() -> Dict[str, Any]:
    sys.path.insert(0, str(PROJECT_ROOT))
    from event_ev.conditional_model import ConditionalModel

    cases = _load_bta()
    cond_model = ConditionalModel(trial_records_path=TRIAL_RECORDS)
    logger.info("Loaded %d BTA cases, conditional model ready", len(cases))

    # ═════════════════════════════════════════════════════════════════
    # 1. BASE RATE CALIBRATION BY EVENT TYPE
    # ═════════════════════════════════════════════════════════════════

    type_outcomes: Dict[str, Dict[str, int]] = defaultdict(lambda: Counter())
    for c in cases:
        binary = BTA_TO_BINARY.get(c["ground_truth"]["actual_impact"], "NEUTRAL")
        type_outcomes[c["type"]][binary] += 1

    base_rate_table = {}
    for etype, counts in sorted(type_outcomes.items()):
        total = sum(counts.values())
        hit = counts.get("HIT", 0)
        miss = counts.get("MISS", 0)
        neutral = counts.get("NEUTRAL", 0)
        hit_rate = hit / total if total else 0
        base_rate_table[etype] = {
            "n": total,
            "hit": hit,
            "miss": miss,
            "neutral": neutral,
            "hit_rate": round(hit_rate, 3),
        }

    # ═════════════════════════════════════════════════════════════════
    # 2. OUR CONDITIONAL MODEL vs BTA OUTCOMES
    # ═════════════════════════════════════════════════════════════════

    # Score each BTA case with our conditional model
    scored_cases = []
    for c in cases:
        ticker = c["id"].split("_")[0]
        event_type = c["type"]
        family = BTA_TYPE_TO_FAMILY.get(event_type, "CLINICAL")
        phase = BTA_TYPE_TO_PHASE.get(event_type, "phase3")
        binary = BTA_TO_BINARY.get(c["ground_truth"]["actual_impact"], "NEUTRAL")
        pct_change = c["ground_truth"].get("percent_change", 0)

        # Build a fake CSV row for the conditional model
        row = {
            "ticker": ticker,
            "catalyst_family": family,
            "lead_program_phase": "3.0" if phase == "phase3" else "2.0" if phase == "phase2" else "1.0",
            "priced_move_pct": None,  # not available from BTA
        }

        cond = cond_model.score_row(row, c["date"])

        scored_cases.append(
            {
                "id": c["id"],
                "ticker": ticker,
                "date": c["date"],
                "type": event_type,
                "family": family,
                "phase": phase,
                "binary_outcome": binary,
                "pct_change": pct_change,
                "bta_impact": c["ground_truth"]["actual_impact"],
                "our_base_rate": cond.conditional_base_rate,
                "our_expected_move": cond.conditional_expected_move,
                "our_bucket": cond.conditional_bucket,
                "our_confidence": cond.conditional_confidence,
                "selection_status": (
                    cond.conditional_bucket.split("|")[2] if len(cond.conditional_bucket.split("|")) > 2 else "unknown"
                ),
                "mechanism_class": (
                    cond.conditional_bucket.split("|")[3] if len(cond.conditional_bucket.split("|")) > 3 else "unknown"
                ),
            }
        )

    # ═════════════════════════════════════════════════════════════════
    # 3. CALIBRATION: predicted base rate vs realized hit rate
    # ═════════════════════════════════════════════════════════════════

    # Bin by predicted base rate quintiles
    scored_with_outcome = [s for s in scored_cases if s["binary_outcome"] != "NEUTRAL"]
    scored_with_outcome.sort(key=lambda s: s["our_base_rate"])

    n = len(scored_with_outcome)
    quintile_size = max(1, n // 5)
    calibration_quintiles = []
    for q in range(5):
        start = q * quintile_size
        end = start + quintile_size if q < 4 else n
        chunk = scored_with_outcome[start:end]
        if not chunk:
            continue
        predicted_avg = statistics.mean(s["our_base_rate"] for s in chunk)
        realized_hit = sum(1 for s in chunk if s["binary_outcome"] == "HIT") / len(chunk)
        calibration_quintiles.append(
            {
                "quintile": q + 1,
                "n": len(chunk),
                "predicted_hit_rate": round(predicted_avg, 3),
                "realized_hit_rate": round(realized_hit, 3),
                "gap": round(realized_hit - predicted_avg, 3),
            }
        )

    # Overall calibration
    if scored_with_outcome:
        pred_all = statistics.mean(s["our_base_rate"] for s in scored_with_outcome)
        real_all = sum(1 for s in scored_with_outcome if s["binary_outcome"] == "HIT") / len(scored_with_outcome)
        overall_calibration = {
            "predicted_hit_rate": round(pred_all, 3),
            "realized_hit_rate": round(real_all, 3),
            "gap": round(real_all - pred_all, 3),
            "n": len(scored_with_outcome),
        }
    else:
        overall_calibration = {}

    # ═════════════════════════════════════════════════════════════════
    # 4. CONDITIONAL UPLIFT: selected vs unselected outcomes
    # ═════════════════════════════════════════════════════════════════

    selection_outcomes: Dict[str, Dict[str, int]] = defaultdict(lambda: Counter())
    for s in scored_cases:
        sel = s["selection_status"]
        selection_outcomes[sel][s["binary_outcome"]] += 1

    selection_table = {}
    for sel, counts in sorted(selection_outcomes.items()):
        non_neutral = counts.get("HIT", 0) + counts.get("MISS", 0)
        hit_rate = counts["HIT"] / non_neutral if non_neutral > 0 else None
        selection_table[sel] = {
            "n_total": sum(counts.values()),
            "n_non_neutral": non_neutral,
            "hit": counts.get("HIT", 0),
            "miss": counts.get("MISS", 0),
            "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
        }

    # Mechanism class outcomes
    mechanism_outcomes: Dict[str, Dict[str, int]] = defaultdict(lambda: Counter())
    for s in scored_cases:
        mech = s["mechanism_class"]
        mechanism_outcomes[mech][s["binary_outcome"]] += 1

    mechanism_table = {}
    for mech, counts in sorted(mechanism_outcomes.items()):
        non_neutral = counts.get("HIT", 0) + counts.get("MISS", 0)
        hit_rate = counts["HIT"] / non_neutral if non_neutral > 0 else None
        mechanism_table[mech] = {
            "n_total": sum(counts.values()),
            "n_non_neutral": non_neutral,
            "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
        }

    # ═════════════════════════════════════════════════════════════════
    # 5. RETURN DISTRIBUTION BY PREDICTED BASE RATE
    # ═════════════════════════════════════════════════════════════════

    return_by_quintile = []
    for q in range(5):
        start = q * quintile_size
        end = start + quintile_size if q < 4 else n
        chunk = scored_with_outcome[start:end]
        if not chunk:
            continue
        rets = [s["pct_change"] for s in chunk]
        return_by_quintile.append(
            {
                "quintile": q + 1,
                "n": len(chunk),
                "mean_return_pct": round(statistics.mean(rets), 2),
                "median_return_pct": round(statistics.median(rets), 2),
                "hit_rate": round(sum(1 for r in rets if r > 0) / len(rets), 3),
            }
        )

    # ═════════════════════════════════════════════════════════════════
    # 6. BY EVENT TYPE: our base rate vs BTA realized
    # ═════════════════════════════════════════════════════════════════

    type_calibration = {}
    type_groups: Dict[str, List] = defaultdict(list)
    for s in scored_cases:
        type_groups[s["type"]].append(s)

    for etype, group in sorted(type_groups.items()):
        non_neutral = [s for s in group if s["binary_outcome"] != "NEUTRAL"]
        if not non_neutral:
            continue
        pred = statistics.mean(s["our_base_rate"] for s in non_neutral)
        real = sum(1 for s in non_neutral if s["binary_outcome"] == "HIT") / len(non_neutral)
        type_calibration[etype] = {
            "n": len(non_neutral),
            "predicted": round(pred, 3),
            "realized": round(real, 3),
            "gap": round(real - pred, 3),
        }

    # ═════════════════════════════════════════════════════════════════
    # Assemble report
    # ═════════════════════════════════════════════════════════════════

    report = {
        "schema": "crt_bta_calibration.v1",
        "bta_cases": len(cases),
        "scored_cases": len(scored_cases),
        "non_neutral_cases": len(scored_with_outcome),
        "base_rate_by_event_type": base_rate_table,
        "overall_calibration": overall_calibration,
        "calibration_by_quintile": calibration_quintiles,
        "return_by_predicted_quintile": return_by_quintile,
        "selection_status_outcomes": selection_table,
        "mechanism_class_outcomes": mechanism_table,
        "type_calibration": type_calibration,
    }

    return report


def _print_summary(report: Dict[str, Any]) -> None:
    print(f"\n{'=' * 70}")
    print("CRT vs BioTradingArena CALIBRATION")
    print(f"{'=' * 70}")
    print(
        f"BTA cases: {report['bta_cases']} | Scored: {report['scored_cases']} | Non-neutral: {report['non_neutral_cases']}"
    )

    print("\n--- BTA Base Rates by Event Type ---")
    print(f"  {'Type':<22} {'N':>5} {'HIT':>5} {'MISS':>5} {'NEUT':>5} {'HitRate':>8}")
    for etype, d in report["base_rate_by_event_type"].items():
        print(f"  {etype:<22} {d['n']:>5} {d['hit']:>5} {d['miss']:>5} {d['neutral']:>5} {d['hit_rate']:>8.1%}")

    oc = report["overall_calibration"]
    if oc:
        print(f"\n--- Overall Calibration (non-neutral only, n={oc['n']}) ---")
        print(f"  Our predicted hit rate: {oc['predicted_hit_rate']:.1%}")
        print(f"  BTA realized hit rate:  {oc['realized_hit_rate']:.1%}")
        print(f"  Gap:                    {oc['gap']:+.1%}")

    print("\n--- Calibration by Predicted Base Rate Quintile ---")
    print(f"  {'Q':>2} {'N':>5} {'Predicted':>10} {'Realized':>10} {'Gap':>7}")
    for q in report["calibration_by_quintile"]:
        print(
            f"  {q['quintile']:>2} {q['n']:>5} {q['predicted_hit_rate']:>10.1%} {q['realized_hit_rate']:>10.1%} {q['gap']:>+7.1%}"
        )

    print("\n--- Returns by Predicted Base Rate Quintile ---")
    print(f"  {'Q':>2} {'N':>5} {'Mean Ret':>9} {'Med Ret':>9} {'HitRate':>8}")
    for q in report["return_by_predicted_quintile"]:
        print(
            f"  {q['quintile']:>2} {q['n']:>5} {q['mean_return_pct']:>+8.1f}% {q['median_return_pct']:>+8.1f}% {q['hit_rate']:>8.1%}"
        )

    print("\n--- Selection Status → HIT Rate ---")
    print(f"  {'Status':<15} {'N':>5} {'NonNeut':>8} {'HitRate':>8}")
    for sel, d in report["selection_status_outcomes"].items():
        hr = f"{d['hit_rate']:.1%}" if d["hit_rate"] is not None else "---"
        print(f"  {sel:<15} {d['n_total']:>5} {d['n_non_neutral']:>8} {hr:>8}")

    print("\n--- Mechanism Class → HIT Rate ---")
    print(f"  {'Mechanism':<18} {'N':>5} {'NonNeut':>8} {'HitRate':>8}")
    for mech, d in report["mechanism_class_outcomes"].items():
        hr = f"{d['hit_rate']:.1%}" if d["hit_rate"] is not None else "---"
        print(f"  {mech:<18} {d['n_total']:>5} {d['n_non_neutral']:>8} {hr:>8}")

    print("\n--- Type Calibration (our predicted vs BTA realized) ---")
    print(f"  {'Type':<22} {'N':>5} {'Predicted':>10} {'Realized':>10} {'Gap':>7}")
    for etype, d in report["type_calibration"].items():
        print(f"  {etype:<22} {d['n']:>5} {d['predicted']:>10.1%} {d['realized']:>10.1%} {d['gap']:>+7.1%}")

    print(f"\n{'=' * 70}")


def main() -> None:
    report = run_calibration()
    _print_summary(report)

    out = PROJECT_ROOT / "artifacts" / "crt_bta_calibration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Full report: %s", out)


if __name__ == "__main__":
    main()
