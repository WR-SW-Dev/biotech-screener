#!/usr/bin/env python3
"""Event feedback metrics — weekly calibration from resolved events.

Reads all resolved event feedback records and computes:
  1. Alert precision by source class
  2. Herald confidence calibration (ECE)
  3. Herald outcome guess confusion matrix
  4. Regulatory p_hit calibration curve
  5. Post-event return buckets by predicted rank decile
  6. Exogenous exclusion counts

Read-only — produces evidence, never updates model priors.

Output:
    artifacts/event_feedback/metrics_{date}.json
    artifacts/event_feedback/metrics_{date}.md

Usage:
    python tools/build_event_feedback_metrics.py --as-of-date 2026-04-14
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("event_feedback_metrics")

SCHEMA_VERSION = "event_feedback_metrics.v1"
FEEDBACK_DIR = REPO_ROOT / "artifacts" / "event_feedback"

# Confidence calibration bins
CONFIDENCE_BINS = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]

MIN_BIN_SIZE = 5  # Minimum observations to report a bin


def _sf(val: Any) -> float:
    if val is None or val == "":
        return math.nan
    try:
        return float(val)
    except (ValueError, TypeError):
        return math.nan


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------


def load_all_resolved_events(as_of_date: str) -> List[Dict]:
    """Load all resolved event feedback records up to as_of_date."""
    records = []
    if not FEEDBACK_DIR.exists():
        return records

    for f in sorted(FEEDBACK_DIR.glob("*_resolved_events.jsonl")):
        file_date = f.stem.replace("_resolved_events", "")
        if file_date > as_of_date:
            continue
        try:
            for line in f.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("resolution_status") == "RESOLVED":
                    records.append(rec)
        except (json.JSONDecodeError, OSError):
            continue

    # Dedupe by (ticker, event_date) — keep latest adjudication
    seen: Dict[tuple, Dict] = {}
    for rec in records:
        key = (rec.get("ticker", ""), rec.get("event_date", ""))
        existing = seen.get(key)
        if existing is None or (rec.get("adjudication_timestamp", "") > existing.get("adjudication_timestamp", "")):
            seen[key] = rec
    return list(seen.values())


# ---------------------------------------------------------------------------
# 1. Alert precision by source class
# ---------------------------------------------------------------------------


def compute_precision_by_source(events: List[Dict]) -> Dict[str, Any]:
    """Precision (HIT rate) broken down by source_class."""
    by_source: Dict[str, List[str]] = defaultdict(list)
    for ev in events:
        src = ev.get("source_class", "UNKNOWN")
        by_source[src].append(ev.get("actual_outcome", ""))

    result = {}
    for src, outcomes in sorted(by_source.items()):
        n = len(outcomes)
        hits = sum(1 for o in outcomes if o == "HIT")
        misses = sum(1 for o in outcomes if o == "MISS")
        mixed = sum(1 for o in outcomes if o == "MIXED")
        result[src] = {
            "n": n,
            "hits": hits,
            "misses": misses,
            "mixed": mixed,
            "hit_rate": round(hits / max(n, 1), 3),
        }
    return result


# ---------------------------------------------------------------------------
# 2. Herald confidence calibration
# ---------------------------------------------------------------------------


def compute_confidence_calibration(events: List[Dict]) -> Dict[str, Any]:
    """Bin events by Herald confidence, compute actual HIT rate per bin + ECE."""
    # Filter to events with Herald match
    with_conf = [ev for ev in events if ev.get("herald_confidence") is not None]

    bins = {}
    weighted_error_sum = 0.0
    total_n = 0

    for lo, hi in CONFIDENCE_BINS:
        label = f"{lo:.1f}-{hi:.1f}"
        in_bin = [ev for ev in with_conf if lo <= (ev.get("herald_confidence") or 0) < hi]
        n = len(in_bin)
        if n < MIN_BIN_SIZE:
            bins[label] = {"n": n, "status": "insufficient_data"}
            continue

        actual_hits = sum(1 for ev in in_bin if ev["actual_outcome"] == "HIT")
        actual_hit_rate = actual_hits / n
        mean_conf = sum(ev.get("herald_confidence", 0) for ev in in_bin) / n

        bins[label] = {
            "n": n,
            "mean_confidence": round(mean_conf, 3),
            "actual_hit_rate": round(actual_hit_rate, 3),
            "calibration_error": round(abs(mean_conf - actual_hit_rate), 3),
        }

        weighted_error_sum += n * abs(mean_conf - actual_hit_rate)
        total_n += n

    ece = round(weighted_error_sum / max(total_n, 1), 3) if total_n > 0 else None

    return {
        "n_with_herald_match": len(with_conf),
        "n_total": len(events),
        "ece": ece,
        "bins": bins,
    }


# ---------------------------------------------------------------------------
# 3. Herald outcome guess confusion matrix
# ---------------------------------------------------------------------------


def compute_outcome_confusion(events: List[Dict]) -> Dict[str, Any]:
    """Confusion matrix: Herald outcome_guess vs actual CRT outcome."""
    with_guess = [ev for ev in events if ev.get("herald_outcome_guess") and ev.get("actual_outcome")]

    if not with_guess:
        return {"n": 0, "status": "no_data"}

    # Normalize labels
    def _norm(s: str) -> str:
        return (s or "unclear").upper()

    matrix: Dict[str, Counter] = defaultdict(Counter)
    for ev in with_guess:
        predicted = _norm(ev["herald_outcome_guess"])
        actual = _norm(ev["actual_outcome"])
        matrix[predicted][actual] += 1

    # Compute per-class metrics
    all_labels = sorted(set(list(matrix.keys()) + [lbl for c in matrix.values() for lbl in c]))
    per_class = {}
    total_correct = 0
    total_n = len(with_guess)

    for label in all_labels:
        tp = matrix.get(label, Counter()).get(label, 0)
        fp = sum(matrix.get(pred, Counter()).get(label, 0) for pred in all_labels if pred != label)
        fn = sum(matrix.get(label, Counter()).get(act, 0) for act in all_labels if act != label)
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9) if (precision + recall) > 0 else 0.0
        per_class[label] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }
        total_correct += tp

    return {
        "n": total_n,
        "accuracy": round(total_correct / max(total_n, 1), 3),
        "per_class": per_class,
        "raw_matrix": {k: dict(v) for k, v in matrix.items()},
    }


# ---------------------------------------------------------------------------
# 4. Regulatory p_hit calibration (placeholder — needs Event EV join)
# ---------------------------------------------------------------------------


def compute_regulatory_calibration(events: List[Dict]) -> Dict[str, Any]:
    """Calibration curve for regulatory events by outcome.

    NOTE: predicted_p_hit is not yet populated in the event feedback records
    (requires Event EV snapshot join, which is a future enhancement).
    For now, compute outcome distribution for regulatory events.
    """
    reg_events = [ev for ev in events if ev.get("event_family") == "REGULATORY"]
    if not reg_events:
        return {"n": 0, "status": "no_regulatory_events"}

    by_type: Dict[str, Counter] = defaultdict(Counter)
    for ev in reg_events:
        etype = ev.get("event_type", "UNKNOWN")
        by_type[etype][ev.get("actual_outcome", "UNKNOWN")] += 1

    result = {}
    for etype, outcomes in sorted(by_type.items()):
        n = sum(outcomes.values())
        hits = outcomes.get("HIT", 0)
        result[etype] = {
            "n": n,
            "hit_rate": round(hits / max(n, 1), 3),
            "outcomes": dict(outcomes),
        }

    total_hits = sum(1 for ev in reg_events if ev["actual_outcome"] == "HIT")
    return {
        "n": len(reg_events),
        "overall_hit_rate": round(total_hits / max(len(reg_events), 1), 3),
        "by_event_type": result,
    }


# ---------------------------------------------------------------------------
# 5. Post-event return buckets by rank decile
# ---------------------------------------------------------------------------


def compute_return_by_rank(events: List[Dict]) -> Dict[str, Any]:
    """Return distribution by DEM rank decile at T-1 snapshot."""
    decile_data: Dict[int, List[Dict]] = defaultdict(list)

    for ev in events:
        rank = ev.get("dem_rank_at_snapshot")
        if rank is None:
            continue
        try:
            rank_int = int(float(rank))
        except (ValueError, TypeError):
            continue

        decile = min(10, max(1, (rank_int - 1) // 10 + 1))

        price_t0 = _sf(ev.get("price_t_0"))
        price_tm1 = _sf(ev.get("price_t_minus_1"))
        ret_t5 = _sf(ev.get("return_t5"))

        # Compute T+0 return from prices if available
        ret_t0 = math.nan
        if not math.isnan(price_t0) and not math.isnan(price_tm1) and price_tm1 > 0:
            ret_t0 = (price_t0 - price_tm1) / price_tm1

        decile_data[decile].append(
            {
                "return_t0": ret_t0,
                "return_t5": ret_t5,
                "outcome": ev.get("actual_outcome", ""),
            }
        )

    result = {}
    for decile in sorted(decile_data):
        records = decile_data[decile]
        n = len(records)

        t0_rets = [r["return_t0"] for r in records if not math.isnan(r["return_t0"])]
        t5_rets = [r["return_t5"] for r in records if not math.isnan(r["return_t5"])]
        hits = sum(1 for r in records if r["outcome"] == "HIT")

        result[f"decile_{decile}"] = {
            "n": n,
            "hit_rate": round(hits / max(n, 1), 3),
            "return_t0_median": (round(sorted(t0_rets)[len(t0_rets) // 2], 4) if t0_rets else None),
            "return_t0_mean": (round(sum(t0_rets) / len(t0_rets), 4) if t0_rets else None),
            "return_t5_median": (round(sorted(t5_rets)[len(t5_rets) // 2], 4) if t5_rets else None),
            "return_t5_mean": (round(sum(t5_rets) / len(t5_rets), 4) if t5_rets else None),
            "n_with_t0": len(t0_rets),
            "n_with_t5": len(t5_rets),
        }
    return result


# ---------------------------------------------------------------------------
# 6. Exogenous exclusion counts
# ---------------------------------------------------------------------------


def compute_exogenous_counts(events: List[Dict]) -> Dict[str, Any]:
    """Count exogenous-flagged events by family."""
    exo = [ev for ev in events if ev.get("exogenous_flag")]
    by_family: Counter = Counter()
    for ev in exo:
        by_family[ev.get("event_family", "UNKNOWN")] += 1

    return {
        "n_total": len(events),
        "n_exogenous": len(exo),
        "exogenous_rate": round(len(exo) / max(len(events), 1), 3),
        "by_family": dict(by_family),
    }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_metrics(as_of_date: str) -> Dict[str, Any]:
    """Build all event feedback metrics."""
    events = load_all_resolved_events(as_of_date)
    logger.info("Loaded %d resolved events", len(events))

    if not events:
        result = {
            "schema": SCHEMA_VERSION,
            "as_of_date": as_of_date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_events": 0,
            "status": "NO_DATA",
        }
        _write_outputs(as_of_date, result)
        return result

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_events": len(events),
        "status": "OK",
        "precision_by_source": compute_precision_by_source(events),
        "confidence_calibration": compute_confidence_calibration(events),
        "outcome_confusion": compute_outcome_confusion(events),
        "regulatory_calibration": compute_regulatory_calibration(events),
        "return_by_rank": compute_return_by_rank(events),
        "exogenous_counts": compute_exogenous_counts(events),
    }

    _write_outputs(as_of_date, result)
    return result


def _write_outputs(as_of_date: str, result: Dict) -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

    json_path = FEEDBACK_DIR / f"metrics_{as_of_date}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    md_path = FEEDBACK_DIR / f"metrics_{as_of_date}.md"
    md_path.write_text(format_metrics_md(result), encoding="utf-8")
    logger.info("Wrote %s", md_path)


def format_metrics_md(d: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# Event Feedback Metrics — {d['as_of_date']}")
    lines.append("")

    if d.get("status") == "NO_DATA":
        lines.append("No resolved events found.")
        return "\n".join(lines)

    lines.append(f"**Resolved events**: {d['n_events']}")
    lines.append("")

    # 1. Precision by source
    pbs = d.get("precision_by_source", {})
    if pbs:
        lines.append("## Alert Precision by Source")
        lines.append("")
        lines.append("| Source | N | HITs | MISSes | Mixed | Hit Rate |")
        lines.append("|--------|---|------|--------|-------|----------|")
        for src, stats in sorted(pbs.items()):
            lines.append(
                f"| {src} | {stats['n']} | {stats['hits']} | "
                f"{stats['misses']} | {stats['mixed']} | "
                f"{stats['hit_rate']:.0%} |"
            )
        lines.append("")

    # 2. Confidence calibration
    cc = d.get("confidence_calibration", {})
    if cc and cc.get("n_with_herald_match", 0) > 0:
        lines.append("## Herald Confidence Calibration")
        lines.append("")
        ece = cc.get("ece")
        lines.append(
            f"Herald-matched: {cc['n_with_herald_match']}/{cc['n_total']} events. " f"ECE: {ece:.3f}"
            if ece is not None
            else "ECE: N/A"
        )
        lines.append("")
        lines.append("| Bin | N | Mean Conf | Actual Hit Rate | Cal Error |")
        lines.append("|-----|---|-----------|-----------------|-----------|")
        for label, stats in cc.get("bins", {}).items():
            if stats.get("status") == "insufficient_data":
                lines.append(f"| {label} | {stats['n']} | - | - | insufficient |")
            else:
                lines.append(
                    f"| {label} | {stats['n']} | "
                    f"{stats['mean_confidence']:.2f} | "
                    f"{stats['actual_hit_rate']:.0%} | "
                    f"{stats['calibration_error']:.3f} |"
                )
        lines.append("")

    # 3. Outcome confusion matrix
    oc = d.get("outcome_confusion", {})
    if oc and oc.get("n", 0) > 0:
        lines.append("## Herald Outcome Guess Accuracy")
        lines.append("")
        lines.append(f"N={oc['n']}, Overall accuracy: {oc['accuracy']:.0%}")
        lines.append("")
        lines.append("| Class | TP | FP | FN | Precision | Recall | F1 |")
        lines.append("|-------|----|----|-----|-----------|--------|-----|")
        for label, stats in sorted(oc.get("per_class", {}).items()):
            lines.append(
                f"| {label} | {stats['tp']} | {stats['fp']} | "
                f"{stats['fn']} | {stats['precision']:.2f} | "
                f"{stats['recall']:.2f} | {stats['f1']:.2f} |"
            )
        lines.append("")

    # 4. Regulatory calibration
    rc = d.get("regulatory_calibration", {})
    if rc and rc.get("n", 0) > 0:
        lines.append("## Regulatory Event Calibration")
        lines.append("")
        lines.append(f"N={rc['n']} regulatory events, " f"overall hit rate: {rc['overall_hit_rate']:.0%}")
        lines.append("")
        lines.append("| Event Type | N | Hit Rate | Outcomes |")
        lines.append("|------------|---|----------|----------|")
        for etype, stats in sorted(rc.get("by_event_type", {}).items()):
            outcomes_str = ", ".join(f"{k}={v}" for k, v in sorted(stats["outcomes"].items()))
            lines.append(f"| {etype} | {stats['n']} | " f"{stats['hit_rate']:.0%} | {outcomes_str} |")
        lines.append("")

    # 5. Return by rank
    rbr = d.get("return_by_rank", {})
    if rbr:
        lines.append("## Post-Event Returns by Rank Decile")
        lines.append("")
        lines.append("| Decile | N | Hit Rate | T+0 Med | T+0 Mean | T+5 Med | T+5 Mean |")
        lines.append("|--------|---|----------|---------|----------|---------|----------|")
        for decile, stats in sorted(rbr.items()):
            t0m = f"{stats['return_t0_median']:.1%}" if stats.get("return_t0_median") is not None else "-"
            t0a = f"{stats['return_t0_mean']:.1%}" if stats.get("return_t0_mean") is not None else "-"
            t5m = f"{stats['return_t5_median']:.1%}" if stats.get("return_t5_median") is not None else "-"
            t5a = f"{stats['return_t5_mean']:.1%}" if stats.get("return_t5_mean") is not None else "-"
            lines.append(f"| {decile} | {stats['n']} | {stats['hit_rate']:.0%} | " f"{t0m} | {t0a} | {t5m} | {t5a} |")
        lines.append("")

    # 6. Exogenous counts
    exo = d.get("exogenous_counts", {})
    if exo:
        lines.append("## Exogenous Exclusions")
        lines.append("")
        lines.append(f"Total: {exo['n_exogenous']}/{exo['n_total']} " f"({exo['exogenous_rate']:.0%})")
        if exo.get("by_family"):
            lines.append("")
            for fam, n in sorted(exo["by_family"].items()):
                lines.append(f"- {fam}: {n}")
        lines.append("")

    lines.append(f"*Generated: {d.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Event feedback metrics")
    parser.add_argument(
        "--as-of-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    args = parser.parse_args()

    result = build_metrics(args.as_of_date)
    if result.get("status") == "NO_DATA":
        logger.info("No resolved events found")
    else:
        logger.info(
            "Metrics: %d events, ECE=%.3f",
            result["n_events"],
            result.get("confidence_calibration", {}).get("ece") or 0,
        )


if __name__ == "__main__":
    main()
