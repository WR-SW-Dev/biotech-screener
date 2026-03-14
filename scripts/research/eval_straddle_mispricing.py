#!/usr/bin/env python3
"""Straddle mispricing alpha research study.

Tests whether cheap_vol_score (historical fair move / implied event move)
predicts larger absolute event gaps or directional returns, using the
existing options alpha harness pattern.

Decision rule:
    - signed IC on signed_gap survives controls → alpha_candidate
    - abs IC on abs_gap survives controls → risk_overlay_candidate
    - neither survives → abandon

Usage:
    python scripts/research/eval_straddle_mispricing.py \\
        --snapshots-dir data/snapshots \\
        --price-csv production_data/price_history.csv \\
        --event-table data/research/event_move_table.json \\
        [--horizons 5,21] \\
        [--output-dir output/straddle_mispricing]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_SCRIPTS = PROJECT_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_RESEARCH = _SCRIPTS / "research"
if str(_RESEARCH) not in sys.path:
    sys.path.insert(0, str(_RESEARCH))

from backtest_signal_robustness import compute_double_sort_spread, residualize_ranks, spearman_rank_corr  # noqa: E402
from eval_options_alpha import load_enriched_dataset  # noqa: E402

from common.straddle_mispricing import compute_cheap_vol_score  # noqa: E402

logger = logging.getLogger(__name__)

STUDY_SCHEMA = "straddle_mispricing_study.v1"
IC_THRESHOLD = 0.05
DEFAULT_HORIZONS = [5, 21]
DEFAULT_MIN_OBS = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insufficient(n: int, min_obs: int) -> Dict[str, Any]:
    return {"status": "insufficient_sample", "n": n, "min_required": min_obs}


def _mean(xs: List[float]) -> float:
    clean = [x for x in xs if not math.isnan(x)]
    return sum(clean) / len(clean) if clean else float("nan")


# ---------------------------------------------------------------------------
# Dataset builder
# ---------------------------------------------------------------------------


def build_mispricing_dataset(
    snapshots_dir: Path,
    price_csv: Path,
    horizons: List[int],
    event_table: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Load enriched options dataset and add cheap_vol_score."""
    dataset = load_enriched_dataset(snapshots_dir, price_csv, horizons)
    if not dataset:
        return []

    table = event_table.get("table", {})

    # Enrich each row with rankings data for phase/indication
    _enrich_rankings(dataset, snapshots_dir)

    # Compute cheap_vol_score per row
    for row in dataset:
        result = compute_cheap_vol_score(
            opt_atm_iv=row.get("opt_atm_iv", float("nan")),
            catalyst_days=int(row.get("catalyst_days", 0)),
            catalyst_family=row.get("catalyst_family", ""),
            lead_program_phase=row.get("lead_program_phase", ""),
            therapeutic_area=row.get("therapeutic_area", ""),
            event_move_table=table,
        )
        row["cheap_vol_score"] = result["cheap_vol_score"] if result["cheap_vol_score"] is not None else float("nan")
        row["vol_classification"] = result["vol_classification"]
        row["historical_p50"] = result["historical_p50"] or float("nan")
        row["implied_event_move"] = result["implied_move"] or float("nan")
        row["table_confidence"] = result["table_confidence"]

    return dataset


def _enrich_rankings(dataset: List[Dict[str, Any]], snapshots_dir: Path) -> None:
    """Add lead_program_phase and therapeutic_area from rankings."""
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in dataset:
        by_date.setdefault(row["snap_date"], []).append(row)

    for snap_date, date_rows in by_date.items():
        csv_path = snapshots_dir / snap_date / "rankings.csv"
        rankings_map: Dict[str, Dict[str, str]] = {}
        if csv_path.exists():
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                for rr in csv.DictReader(f):
                    t = (rr.get("ticker") or "").strip().upper()
                    if t:
                        rankings_map[t] = rr

        for row in date_rows:
            rr = rankings_map.get(row["ticker"], {})
            row["lead_program_phase"] = rr.get("lead_program_phase", "")
            row["therapeutic_area"] = rr.get("therapeutic_area", "")


# ---------------------------------------------------------------------------
# IC tests
# ---------------------------------------------------------------------------


def compute_raw_ic(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    return_col: str,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    pairs = [
        (r[signal_col], r[return_col])
        for r in dataset
        if not math.isnan(r.get(signal_col, float("nan"))) and r.get(return_col) is not None
    ]
    n = len(pairs)
    if n < min_obs:
        return _insufficient(n, min_obs)
    ic = spearman_rank_corr([p[0] for p in pairs], [p[1] for p in pairs])
    return {"status": "ok", "n": n, "ic": round(ic, 6)}


def compute_incremental_ic(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    control_col: str,
    return_col: str,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    triples = [
        (r[signal_col], r[control_col], r[return_col])
        for r in dataset
        if not math.isnan(r.get(signal_col, float("nan")))
        and not math.isnan(r.get(control_col, float("nan")))
        and r.get(return_col) is not None
    ]
    n = len(triples)
    if n < min_obs:
        return _insufficient(n, min_obs)

    signals = [t[0] for t in triples]
    controls = [t[1] for t in triples]
    returns = [t[2] for t in triples]

    residuals = residualize_ranks(signals, controls)
    raw_ic = spearman_rank_corr(signals, returns)
    incr_ic = spearman_rank_corr(residuals, returns)
    return {"status": "ok", "n": n, "raw_ic": round(raw_ic, 6), "incremental_ic": round(incr_ic, 6)}


def compute_portfolio_slice(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    return_col: str,
    top_k: int = 10,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Sort by signal descending (cheapest first), top-K vs rest."""
    pairs = [
        (r[signal_col], r[return_col], r.get("ticker", ""))
        for r in dataset
        if not math.isnan(r.get(signal_col, float("nan"))) and r.get(return_col) is not None
    ]
    n = len(pairs)
    if n < min_obs or n < top_k + 1:
        return _insufficient(n, min_obs)

    pairs.sort(key=lambda p: (-p[0], p[2]))
    top_rets = [p[1] for p in pairs[:top_k]]
    rest_rets = [p[1] for p in pairs[top_k:]]

    return {
        "status": "ok",
        "n": n,
        "top_k": top_k,
        "top_mean": round(_mean(top_rets), 6),
        "rest_mean": round(_mean(rest_rets), 6),
        "spread": round(_mean(top_rets) - _mean(rest_rets), 6),
    }


# ---------------------------------------------------------------------------
# Full test battery
# ---------------------------------------------------------------------------


def run_all_tests(
    dataset: List[Dict[str, Any]],
    horizons: List[int],
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {"raw": {}, "incremental": {}, "portfolio": {}, "double_sort": {}}

    signals = ["cheap_vol_score"]
    targets = ["abs_gap", "signed_gap"]
    for h in horizons:
        targets.append(f"fwd_ret_{h}d")

    # Raw IC
    for sig in signals:
        for ret in targets:
            results["raw"][f"ic_{sig}_vs_{ret}"] = compute_raw_ic(dataset, sig, ret, min_obs)

    # Incremental IC controlling for catalyst timing
    for sig in signals:
        for ret in targets:
            results["incremental"][f"incr_{sig}_ctrl_decay_vs_{ret}"] = compute_incremental_ic(
                dataset, sig, "catalyst_decay_w", ret, min_obs
            )

    # Incremental IC controlling for raw IV (the key test: does historical comparison add beyond raw IV?)
    for sig in signals:
        for ret in targets:
            results["incremental"][f"incr_{sig}_ctrl_atm_iv_vs_{ret}"] = compute_incremental_ic(
                dataset, sig, "opt_atm_iv", ret, min_obs
            )

    # Portfolio slices
    for sig in signals:
        for ret in ["abs_gap", "signed_gap"]:
            results["portfolio"][f"{sig}_vs_{ret}"] = compute_portfolio_slice(dataset, sig, ret, 10, min_obs)

    # Double sort: within catalyst timing terciles, does cheap_vol_score discriminate?
    for ret in ["abs_gap", "signed_gap"]:
        triples = [
            (r.get("catalyst_decay_w", float("nan")), r.get("cheap_vol_score", float("nan")), r.get(ret))
            for r in dataset
            if not math.isnan(r.get("catalyst_decay_w", float("nan")))
            and not math.isnan(r.get("cheap_vol_score", float("nan")))
            and r.get(ret) is not None
        ]
        if len(triples) >= min_obs:
            spread = compute_double_sort_spread(
                [t[0] for t in triples],
                [t[1] for t in triples],
                [t[2] for t in triples],
                n_groups=3,
                min_per_group=5,
            )
            results["double_sort"][f"cheap_vol_within_timing_vs_{ret}"] = {
                "status": "ok",
                "n": len(triples),
                "spread": round(spread, 6),
            }
        else:
            results["double_sort"][f"cheap_vol_within_timing_vs_{ret}"] = _insufficient(len(triples), min_obs)

    return results


# ---------------------------------------------------------------------------
# Decision rule
# ---------------------------------------------------------------------------


def evaluate_decision(tests: Dict[str, Any]) -> Dict[str, Any]:
    abs_key = "ic_cheap_vol_score_vs_abs_gap"
    abs_r = tests["raw"].get(abs_key, {})
    abs_ic = abs_r.get("ic") if abs_r.get("status") == "ok" else None

    signed_key = "ic_cheap_vol_score_vs_signed_gap"
    signed_r = tests["raw"].get(signed_key, {})
    signed_ic = signed_r.get("ic") if signed_r.get("status") == "ok" else None

    incr_abs_key = "incr_cheap_vol_score_ctrl_decay_vs_abs_gap"
    incr_abs = tests["incremental"].get(incr_abs_key, {})
    incr_abs_ic = incr_abs.get("incremental_ic") if incr_abs.get("status") == "ok" else None

    incr_signed_key = "incr_cheap_vol_score_ctrl_decay_vs_signed_gap"
    incr_signed = tests["incremental"].get(incr_signed_key, {})
    incr_signed_ic = incr_signed.get("incremental_ic") if incr_signed.get("status") == "ok" else None

    # Also check the key question: does mispricing add beyond raw IV?
    incr_iv_key = "incr_cheap_vol_score_ctrl_atm_iv_vs_abs_gap"
    incr_iv = tests["incremental"].get(incr_iv_key, {})
    incr_iv_ic = incr_iv.get("incremental_ic") if incr_iv.get("status") == "ok" else None

    classification = "insufficient_data"
    reasons: List[str] = []

    if abs_ic is not None and signed_ic is not None:
        has_signed = abs(signed_ic) >= IC_THRESHOLD if signed_ic else False
        has_abs = abs(abs_ic) >= IC_THRESHOLD if abs_ic else False
        survives_signed = incr_signed_ic is not None and abs(incr_signed_ic) >= IC_THRESHOLD
        survives_abs = incr_abs_ic is not None and abs(incr_abs_ic) >= IC_THRESHOLD

        if has_signed and survives_signed:
            classification = "alpha_candidate"
            reasons.append(f"signed_gap IC={signed_ic:.4f}, incr IC={incr_signed_ic:.4f}")
        elif has_abs and survives_abs:
            classification = "risk_overlay_candidate"
            reasons.append(f"abs_gap IC={abs_ic:.4f}, incr IC={incr_abs_ic:.4f}")
        elif has_abs or has_signed:
            classification = "signal_present_but_not_incremental"
            reasons.append(f"abs IC={abs_ic:.4f}, signed IC={signed_ic:.4f}")
            reasons.append("Does not survive catalyst timing controls")
        else:
            classification = "abandon"
            reasons.append(f"abs IC={abs_ic:.4f}, signed IC={signed_ic:.4f} — below thresholds")

        if incr_iv_ic is not None:
            reasons.append(
                f"vs raw IV control: incr IC={incr_iv_ic:.4f} "
                f"({'survives' if abs(incr_iv_ic) >= IC_THRESHOLD else 'wiped'})"
            )
    else:
        reasons.append("Insufficient data for IC computation")

    return {
        "classification": classification,
        "reasons": reasons,
        "abs_gap_ic": abs_ic,
        "signed_gap_ic": signed_ic,
        "incr_abs_ic": incr_abs_ic,
        "incr_signed_ic": incr_signed_ic,
        "incr_vs_raw_iv_ic": incr_iv_ic,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def generate_report(
    dataset: List[Dict[str, Any]],
    tests: Dict[str, Any],
    decision: Dict[str, Any],
    horizons: List[int],
    event_table_meta: Dict[str, Any],
) -> Dict[str, Any]:
    n = len(dataset)
    n_with_score = sum(1 for r in dataset if not math.isnan(r.get("cheap_vol_score", float("nan"))))
    n_with_gap = sum(
        1 for r in dataset if r.get("abs_gap") is not None and not math.isnan(r.get("abs_gap", float("nan")))
    )

    from collections import Counter

    vol_dist = Counter(r.get("vol_classification", "") for r in dataset if r.get("vol_classification"))
    conf_dist = Counter(r.get("table_confidence", "") for r in dataset if r.get("table_confidence"))

    return {
        "schema": STUDY_SCHEMA,
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": {"horizons": horizons, "ic_threshold": IC_THRESHOLD},
        "event_table": {
            "built_as_of": event_table_meta.get("built_as_of"),
            "n_outcomes": event_table_meta.get("n_outcomes"),
            "input_hash": event_table_meta.get("input_hash"),
        },
        "descriptive": {
            "n_total": n,
            "n_with_cheap_vol_score": n_with_score,
            "n_with_abs_gap": n_with_gap,
            "vol_classification_dist": dict(vol_dist),
            "table_confidence_dist": dict(conf_dist),
            "snap_dates": len({r["snap_date"] for r in dataset}),
            "tickers": len({r["ticker"] for r in dataset}),
        },
        "tests": tests,
        "decision": decision,
    }


def format_report_md(report: Dict[str, Any]) -> str:
    lines = ["# Straddle Mispricing Study", ""]
    lines.append(f"Generated: {report['generated_at']}")
    et = report.get("event_table", {})
    lines.append(f"Event table: {et.get('n_outcomes', '?')} outcomes, built {et.get('built_as_of', '?')}")
    lines.append("")

    d = report["decision"]
    lines.append(f"## Decision: **{d['classification'].upper()}**")
    lines.append("")
    for r in d["reasons"]:
        lines.append(f"- {r}")
    lines.append("")

    # Raw ICs
    lines.append("## Raw IC")
    lines.append("")
    lines.append("| Test | IC | n |")
    lines.append("|------|----|---|")
    for key, val in sorted(report["tests"]["raw"].items()):
        if val.get("status") == "ok":
            lines.append(f"| {key} | {val['ic']:.4f} | {val['n']} |")
        else:
            lines.append(f"| {key} | - | {val.get('n', '?')} |")
    lines.append("")

    # Incremental ICs
    lines.append("## Incremental IC")
    lines.append("")
    lines.append("| Test | Raw IC | Incremental IC | n |")
    lines.append("|------|--------|----------------|---|")
    for key, val in sorted(report["tests"]["incremental"].items()):
        if val.get("status") == "ok":
            lines.append(f"| {key} | {val['raw_ic']:.4f} | {val['incremental_ic']:.4f} | {val['n']} |")
        else:
            lines.append(f"| {key} | - | - | {val.get('n', '?')} |")
    lines.append("")

    # Portfolio slices
    lines.append("## Portfolio Slices")
    lines.append("")
    for key, val in sorted(report["tests"]["portfolio"].items()):
        if val.get("status") == "ok":
            lines.append(
                f"- {key}: spread={val['spread']:.4f} (top={val['top_mean']:.4f}, rest={val['rest_mean']:.4f})"
            )
    lines.append("")

    # Descriptive
    desc = report["descriptive"]
    lines.append("## Dataset")
    lines.append("")
    lines.append(
        f"- Total: {desc['n_total']}, with score: {desc['n_with_cheap_vol_score']}, with gap: {desc['n_with_abs_gap']}"
    )
    lines.append(f"- Vol classification: {desc['vol_classification_dist']}")
    lines.append(f"- Table confidence: {desc['table_confidence_dist']}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Straddle mispricing alpha study.")
    p.add_argument("--snapshots-dir", type=Path, default=Path("data/snapshots"))
    p.add_argument("--price-csv", type=Path, default=Path("production_data/price_history.csv"))
    p.add_argument("--event-table", type=Path, default=Path("data/research/event_move_table.json"))
    p.add_argument("--horizons", default="5,21")
    p.add_argument("--min-obs", type=int, default=DEFAULT_MIN_OBS)
    p.add_argument("--output-dir", type=Path, default=Path("output/straddle_mispricing"))
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")
    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    if not args.event_table.exists():
        logger.error("Event table not found: %s — run build_event_move_table.py first", args.event_table)
        return 1

    event_table = json.loads(args.event_table.read_text())
    logger.info(
        "Event table: %d outcomes, built %s", event_table.get("n_outcomes", 0), event_table.get("built_as_of", "?")
    )

    logger.info("Loading dataset...")
    dataset = build_mispricing_dataset(args.snapshots_dir, args.price_csv, horizons, event_table)
    logger.info("Dataset: %d rows", len(dataset))

    if not dataset:
        logger.error("No data")
        return 1

    logger.info("Running tests...")
    tests = run_all_tests(dataset, horizons, args.min_obs)

    logger.info("Evaluating decision...")
    decision = evaluate_decision(tests)

    report = generate_report(dataset, tests, decision, horizons, event_table)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "straddle_mispricing_study.json"
    md_path = args.output_dir / "straddle_mispricing_study.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
        f.write("\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(format_report_md(report))

    logger.info("Decision: %s", decision["classification"])
    for r in decision["reasons"]:
        logger.info("  %s", r)
    logger.info("Report: %s", json_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
