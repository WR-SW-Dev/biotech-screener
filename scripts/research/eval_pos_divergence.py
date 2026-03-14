#!/usr/bin/env python3
"""PoS divergence alpha research study.

Evaluates whether the divergence between the model's clinical quality
signal and the options market's implied event move has predictive value
for forward returns — specifically whether it adds alpha beyond what
catalyst timing alone explains.

Decision rule (same as eval_options_alpha.py):
    - signed-move IC survives controls → alpha candidate
    - absolute-move IC survives controls → risk overlay candidate
    - neither → abandon

Signals tested:
    pos_divergence_z: z-scored (model_quality_z - implied_move_z)
    implied_event_move: ATM IV × sqrt(T) — market's expected magnitude

Usage:
    python scripts/research/eval_pos_divergence.py \\
        --snapshots-dir data/snapshots \\
        --price-csv production_data/price_history.csv \\
        [--model-signal composite_score] \\
        [--horizons 5,21,63] \\
        [--min-obs 20] \\
        [--output-dir output/pos_divergence_study]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Ensure project root + scripts dirs are importable
# ---------------------------------------------------------------------------
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
from eval_options_alpha import _safe_float, load_enriched_dataset  # noqa: E402

from common.pos_divergence import compute_pos_divergence_panel  # noqa: E402

logger = logging.getLogger(__name__)

# Schema version for the output report
STUDY_SCHEMA = "pos_divergence_study.v1"

# IC thresholds for decision rule
IC_THRESHOLD_OVERLAY = 0.05
IC_THRESHOLD_ALPHA = 0.05

DEFAULT_HORIZONS = [5, 21, 63]
DEFAULT_MIN_OBS = 20
DEFAULT_MODEL_SIGNAL = "composite_score"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insufficient(n: int, min_obs: int) -> Dict[str, Any]:
    return {"status": "insufficient_sample", "n": n, "min_required": min_obs}


def _mean(xs: List[float]) -> float:
    clean = [x for x in xs if not math.isnan(x)]
    return sum(clean) / len(clean) if clean else float("nan")


def _median(xs: List[float]) -> float:
    clean = sorted(x for x in xs if not math.isnan(x))
    if not clean:
        return float("nan")
    mid = len(clean) // 2
    if len(clean) % 2 == 0:
        return (clean[mid - 1] + clean[mid]) / 2
    return clean[mid]


def _std(xs: List[float]) -> float:
    clean = [x for x in xs if not math.isnan(x)]
    if len(clean) < 2:
        return float("nan")
    m = sum(clean) / len(clean)
    return math.sqrt(sum((v - m) ** 2 for v in clean) / (len(clean) - 1))


def _dist(values: List[float]) -> Dict[str, Any]:
    clean = [v for v in values if not math.isnan(v)]
    if not clean:
        return {"n": 0}
    return {
        "n": len(clean),
        "mean": round(_mean(clean), 6),
        "median": round(_median(clean), 6),
        "std": round(_std(clean), 6),
        "min": round(min(clean), 6),
        "max": round(max(clean), 6),
    }


# ---------------------------------------------------------------------------
# Section A: Dataset enrichment
# ---------------------------------------------------------------------------


def build_pos_divergence_dataset(
    snapshots_dir: Path,
    price_csv: Path,
    horizons: List[int],
    model_signal: str,
) -> List[Dict[str, Any]]:
    """Load the options-enriched dataset and add PoS divergence columns.

    Reuses the eval_options_alpha dataset loader (which filters to
    opt_has_data=1 and catalyst_days <= 90), then enriches with
    pos_divergence signals.
    """
    dataset = load_enriched_dataset(snapshots_dir, price_csv, horizons)
    if not dataset:
        return []

    # The enriched dataset has opt_atm_iv and catalyst_days already.
    # We need the model signal from rankings — reload for each snap_date.
    _enrich_model_signal(dataset, snapshots_dir, model_signal)

    # Compute PoS divergence per cross-section (snapshot date)
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in dataset:
        by_date.setdefault(row["snap_date"], []).append(row)

    enriched = []
    for snap_date, date_rows in sorted(by_date.items()):
        compute_pos_divergence_panel(
            date_rows,
            model_signal_col="model_signal",
            atm_iv_col="opt_atm_iv",
            catalyst_days_col="catalyst_days",
        )
        enriched.extend(date_rows)

    return enriched


def _enrich_model_signal(
    dataset: List[Dict[str, Any]],
    snapshots_dir: Path,
    model_signal_col: str,
) -> None:
    """Add the model signal from rankings.csv into each dataset row."""
    import csv

    # Group by snap_date to batch load rankings
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in dataset:
        by_date.setdefault(row["snap_date"], []).append(row)

    for snap_date, date_rows in by_date.items():
        csv_path = snapshots_dir / snap_date / "rankings.csv"
        rankings_map: Dict[str, str] = {}
        if csv_path.exists():
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                for rr in csv.DictReader(f):
                    t = (rr.get("ticker") or "").strip().upper()
                    if t:
                        rankings_map[t] = rr.get(model_signal_col, "")

        for row in date_rows:
            row["model_signal"] = _safe_float(rankings_map.get(row["ticker"], ""))


# ---------------------------------------------------------------------------
# Section B: Descriptive analysis
# ---------------------------------------------------------------------------


def compute_descriptive(dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Coverage and distribution of PoS divergence signals."""
    n = len(dataset)
    if n == 0:
        return {"n_total": 0, "status": "no_data"}

    n_with_divergence = sum(1 for r in dataset if not math.isnan(r.get("pos_divergence", float("nan"))))

    return {
        "n_total": n,
        "n_with_divergence": n_with_divergence,
        "coverage_pct": round(n_with_divergence / n * 100, 1),
        "snap_dates": len({r["snap_date"] for r in dataset}),
        "tickers": len({r["ticker"] for r in dataset}),
        "distributions": {
            "implied_event_move": _dist([r.get("implied_event_move", float("nan")) for r in dataset]),
            "model_signal_z": _dist([r.get("model_signal_z", float("nan")) for r in dataset]),
            "implied_move_z": _dist([r.get("implied_move_z", float("nan")) for r in dataset]),
            "pos_divergence": _dist([r.get("pos_divergence", float("nan")) for r in dataset]),
            "pos_divergence_z": _dist([r.get("pos_divergence_z", float("nan")) for r in dataset]),
            "opt_atm_iv": _dist([r.get("opt_atm_iv", float("nan")) for r in dataset]),
        },
    }


# ---------------------------------------------------------------------------
# Section C: Predictive tests
# ---------------------------------------------------------------------------


def compute_raw_ic(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    return_col: str,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Spearman IC: signal vs return."""
    pairs = [
        (r[signal_col], r[return_col])
        for r in dataset
        if not math.isnan(r.get(signal_col, float("nan"))) and r.get(return_col) is not None
    ]
    n = len(pairs)
    if n < min_obs:
        return _insufficient(n, min_obs)
    signals = [p[0] for p in pairs]
    returns = [p[1] for p in pairs]
    ic = spearman_rank_corr(signals, returns)
    return {"status": "ok", "n": n, "ic": round(ic, 6)}


def compute_incremental_ic(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    control_col: str,
    return_col: str,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Residualize signal vs control, then IC against return."""
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
    ic = spearman_rank_corr(residuals, returns)
    raw_ic = spearman_rank_corr(signals, returns)

    return {
        "status": "ok",
        "n": n,
        "raw_ic": round(raw_ic, 6),
        "incremental_ic": round(ic, 6),
    }


def compute_binned_comparison(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    return_col: str,
    n_bins: int = 3,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Bin by signal tercile, compare mean returns."""
    pairs = [
        (r[signal_col], r[return_col])
        for r in dataset
        if not math.isnan(r.get(signal_col, float("nan"))) and r.get(return_col) is not None
    ]
    n = len(pairs)
    if n < min_obs:
        return _insufficient(n, min_obs)

    pairs.sort(key=lambda p: p[0])
    bin_size = n // n_bins
    if bin_size < 3:
        return _insufficient(n, min_obs)

    bins = []
    for i in range(n_bins):
        start = i * bin_size
        end = n if i == n_bins - 1 else (i + 1) * bin_size
        chunk = pairs[start:end]
        rets = [p[1] for p in chunk]
        bins.append(
            {
                "bin": i + 1,
                "n": len(chunk),
                "signal_range": [round(chunk[0][0], 4), round(chunk[-1][0], 4)],
                "mean_return": round(_mean(rets), 6),
            }
        )

    spread = bins[-1]["mean_return"] - bins[0]["mean_return"]
    return {"status": "ok", "n": n, "bins": bins, "top_minus_bottom_spread": round(spread, 6)}


def compute_portfolio_slice(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    return_col: str,
    top_k: int = 10,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Sort by signal descending (highest divergence first), top-K vs rest."""
    pairs = [
        (r[signal_col], r[return_col], r.get("ticker", ""))
        for r in dataset
        if not math.isnan(r.get(signal_col, float("nan"))) and r.get(return_col) is not None
    ]
    n = len(pairs)
    if n < min_obs or n < top_k + 1:
        return _insufficient(n, min_obs)

    # Sort descending: highest pos_divergence = model most bullish vs market
    pairs.sort(key=lambda p: (-p[0], p[2]))

    top_rets = [p[1] for p in pairs[:top_k]]
    rest_rets = [p[1] for p in pairs[top_k:]]

    # Baseline: sort by catalyst_decay_w descending
    decay_pairs = [
        (r.get("catalyst_decay_w", float("nan")), r.get(return_col))
        for r in dataset
        if not math.isnan(r.get("catalyst_decay_w", float("nan"))) and r.get(return_col) is not None
    ]
    decay_pairs.sort(key=lambda p: p[0], reverse=True)
    baseline_rets = [p[1] for p in decay_pairs[:top_k]] if len(decay_pairs) >= top_k else []

    return {
        "status": "ok",
        "n": n,
        "top_k": top_k,
        "top_mean": round(_mean(top_rets), 6),
        "rest_mean": round(_mean(rest_rets), 6),
        "spread": round(_mean(top_rets) - _mean(rest_rets), 6),
        "baseline_mean": round(_mean(baseline_rets), 6) if baseline_rets else None,
    }


# ---------------------------------------------------------------------------
# Section D: Full test battery
# ---------------------------------------------------------------------------


def run_simple_tests(
    dataset: List[Dict[str, Any]],
    horizons: List[int],
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Run all simple predictive tests for PoS divergence signals."""
    results: Dict[str, Any] = {}

    signal_cols = ["pos_divergence_z", "implied_event_move", "pos_divergence"]
    return_targets = ["abs_gap", "signed_gap"]
    for h in horizons:
        return_targets.append(f"fwd_ret_{h}d")

    for sig in signal_cols:
        for ret in return_targets:
            key = f"{sig}_vs_{ret}"
            results[f"ic_{key}"] = compute_raw_ic(dataset, sig, ret, min_obs)
            results[f"bins_{key}"] = compute_binned_comparison(dataset, sig, ret, 3, min_obs)

    return results


def run_incremental_tests(
    dataset: List[Dict[str, Any]],
    horizons: List[int],
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Run incremental IC tests controlling for catalyst timing."""
    results: Dict[str, Any] = {}

    signal_cols = ["pos_divergence_z", "pos_divergence"]
    control = "catalyst_decay_w"
    return_targets = ["abs_gap", "signed_gap"]
    for h in horizons:
        return_targets.append(f"fwd_ret_{h}d")

    for sig in signal_cols:
        for ret in return_targets:
            key = f"incr_ic_{sig}_ctrl_{control}_vs_{ret}"
            results[key] = compute_incremental_ic(dataset, sig, control, ret, min_obs)

    # Double-sort spread: within catalyst-timing terciles, does divergence discriminate?
    for ret in ["abs_gap", "signed_gap"]:
        triples = [
            (r.get("catalyst_decay_w", float("nan")), r.get("pos_divergence_z", float("nan")), r.get(ret))
            for r in dataset
            if not math.isnan(r.get("catalyst_decay_w", float("nan")))
            and not math.isnan(r.get("pos_divergence_z", float("nan")))
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
            results[f"double_sort_pos_divergence_z_vs_{ret}"] = {
                "status": "ok",
                "n": len(triples),
                "spread": round(spread, 6),
            }
        else:
            results[f"double_sort_pos_divergence_z_vs_{ret}"] = _insufficient(len(triples), min_obs)

    return results


def run_portfolio_slices(
    dataset: List[Dict[str, Any]],
    horizons: List[int],
    top_k: int = 10,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Portfolio slice tests for pos_divergence signals."""
    results: Dict[str, Any] = {}
    for sig in ["pos_divergence_z", "pos_divergence"]:
        for ret in ["abs_gap", "signed_gap"]:
            results[f"{sig}_vs_{ret}"] = compute_portfolio_slice(dataset, sig, ret, top_k, min_obs)
        for h in horizons:
            results[f"{sig}_vs_fwd_ret_{h}d"] = compute_portfolio_slice(dataset, sig, f"fwd_ret_{h}d", top_k, min_obs)
    return results


# ---------------------------------------------------------------------------
# Section E: Decision rule
# ---------------------------------------------------------------------------


def evaluate_decision_rule(
    simple_tests: Dict[str, Any],
    incremental_tests: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply decision rule: risk overlay / alpha candidate / abandon."""
    # Primary signal: pos_divergence_z
    abs_key = "ic_pos_divergence_z_vs_abs_gap"
    abs_result = simple_tests.get(abs_key, {})
    abs_ic = abs_result.get("ic", 0.0) if abs_result.get("status") == "ok" else None

    signed_key = "ic_pos_divergence_z_vs_signed_gap"
    signed_result = simple_tests.get(signed_key, {})
    signed_ic = signed_result.get("ic", 0.0) if signed_result.get("status") == "ok" else None

    incr_abs_key = "incr_ic_pos_divergence_z_ctrl_catalyst_decay_w_vs_abs_gap"
    incr_abs = incremental_tests.get(incr_abs_key, {})
    incr_abs_ic = incr_abs.get("incremental_ic", 0.0) if incr_abs.get("status") == "ok" else None

    incr_signed_key = "incr_ic_pos_divergence_z_ctrl_catalyst_decay_w_vs_signed_gap"
    incr_signed = incremental_tests.get(incr_signed_key, {})
    incr_signed_ic = incr_signed.get("incremental_ic", 0.0) if incr_signed.get("status") == "ok" else None

    classification = "insufficient_data"
    reasons: List[str] = []

    if abs_ic is not None and signed_ic is not None:
        has_abs = abs(abs_ic) >= IC_THRESHOLD_OVERLAY
        has_signed = abs(signed_ic) >= IC_THRESHOLD_ALPHA
        survives_abs = incr_abs_ic is not None and abs(incr_abs_ic) >= IC_THRESHOLD_OVERLAY
        survives_signed = incr_signed_ic is not None and abs(incr_signed_ic) >= IC_THRESHOLD_ALPHA

        if has_signed and survives_signed:
            classification = "alpha_candidate"
            reasons.append(f"signed_gap IC={signed_ic:.4f}, incremental IC={incr_signed_ic:.4f}")
        elif has_abs and survives_abs:
            classification = "risk_overlay_candidate"
            reasons.append(f"abs_gap IC={abs_ic:.4f}, incremental IC={incr_abs_ic:.4f}")
        elif has_abs or has_signed:
            classification = "signal_present_but_not_incremental"
            reasons.append(f"abs_gap IC={abs_ic:.4f}, signed IC={signed_ic:.4f}")
            reasons.append("Does not survive catalyst timing controls")
        else:
            classification = "abandon"
            reasons.append(f"abs_gap IC={abs_ic:.4f}, signed IC={signed_ic:.4f}")
            reasons.append("Below IC thresholds")
    else:
        reasons.append("Insufficient data for IC computation")

    return {
        "classification": classification,
        "reasons": reasons,
        "abs_gap_ic": abs_ic,
        "signed_gap_ic": signed_ic,
        "incremental_abs_ic": incr_abs_ic,
        "incremental_signed_ic": incr_signed_ic,
        "ic_threshold_overlay": IC_THRESHOLD_OVERLAY,
        "ic_threshold_alpha": IC_THRESHOLD_ALPHA,
    }


# ---------------------------------------------------------------------------
# Section F: Report assembly
# ---------------------------------------------------------------------------


def generate_report(
    dataset: List[Dict[str, Any]],
    descriptive: Dict[str, Any],
    simple_tests: Dict[str, Any],
    incremental_tests: Dict[str, Any],
    portfolio_slices: Dict[str, Any],
    decision: Dict[str, Any],
    model_signal: str,
    horizons: List[int],
) -> Dict[str, Any]:
    """Assemble full JSON report."""
    return {
        "schema": STUDY_SCHEMA,
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": {
            "model_signal": model_signal,
            "horizons": horizons,
            "ic_threshold_overlay": IC_THRESHOLD_OVERLAY,
            "ic_threshold_alpha": IC_THRESHOLD_ALPHA,
        },
        "descriptive": descriptive,
        "simple_tests": simple_tests,
        "incremental_tests": incremental_tests,
        "portfolio_slices": portfolio_slices,
        "decision": decision,
    }


def format_report_md(report: Dict[str, Any]) -> str:
    """Format the report as human-readable Markdown."""
    lines = [
        "# PoS Divergence Alpha Study",
        "",
        f"Generated: {report['generated_at']}",
        f"Model signal: `{report['config']['model_signal']}`",
        "",
    ]

    # Decision
    d = report["decision"]
    lines.append(f"## Decision: **{d['classification'].upper()}**")
    lines.append("")
    for r in d["reasons"]:
        lines.append(f"- {r}")
    lines.append("")

    # Key ICs
    lines.append("## Key Information Coefficients")
    lines.append("")
    lines.append("| Signal | Target | IC | Status |")
    lines.append("|--------|--------|----|--------|")
    for key, val in sorted(report["simple_tests"].items()):
        if not key.startswith("ic_"):
            continue
        sig_target = key[3:]  # strip "ic_"
        if val.get("status") == "ok":
            lines.append(f"| {sig_target} | | {val['ic']:.4f} | n={val['n']} |")
        else:
            lines.append(f"| {sig_target} | | - | {val.get('status', '?')} |")
    lines.append("")

    # Incremental ICs
    lines.append("## Incremental ICs (controlling for catalyst timing)")
    lines.append("")
    lines.append("| Test | Raw IC | Incremental IC | n |")
    lines.append("|------|--------|----------------|---|")
    for key, val in sorted(report["incremental_tests"].items()):
        if not key.startswith("incr_ic_"):
            continue
        if val.get("status") == "ok":
            lines.append(f"| {key} | {val['raw_ic']:.4f} | {val['incremental_ic']:.4f} | {val['n']} |")
        else:
            lines.append(f"| {key} | - | - | {val.get('n', '?')} |")
    lines.append("")

    # Portfolio slices
    lines.append("## Portfolio Slices")
    lines.append("")
    lines.append("| Signal vs Target | Top-K Mean | Rest Mean | Spread | Baseline |")
    lines.append("|------------------|-----------|-----------|--------|----------|")
    for key, val in sorted(report["portfolio_slices"].items()):
        if val.get("status") == "ok":
            bl = f"{val['baseline_mean']:.4f}" if val.get("baseline_mean") is not None else "-"
            lines.append(f"| {key} | {val['top_mean']:.4f} | {val['rest_mean']:.4f} | " f"{val['spread']:.4f} | {bl} |")
    lines.append("")

    # Descriptive
    desc = report["descriptive"]
    lines.append("## Dataset Summary")
    lines.append("")
    lines.append(f"- Observations: {desc.get('n_total', 0)}")
    lines.append(f"- With divergence: {desc.get('n_with_divergence', 0)} ({desc.get('coverage_pct', 0)}%)")
    lines.append(f"- Snapshot dates: {desc.get('snap_dates', 0)}")
    lines.append(f"- Unique tickers: {desc.get('tickers', 0)}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="PoS divergence alpha research study.")
    p.add_argument("--snapshots-dir", type=Path, default=Path("data/snapshots"))
    p.add_argument("--price-csv", type=Path, default=Path("production_data/price_history.csv"))
    p.add_argument("--model-signal", default=DEFAULT_MODEL_SIGNAL, help="Model signal column from rankings.csv")
    p.add_argument("--horizons", default="5,21,63", help="Comma-separated forward-return horizons")
    p.add_argument("--min-obs", type=int, default=DEFAULT_MIN_OBS)
    p.add_argument("--top-k", type=int, default=10, help="Top-K for portfolio slice tests")
    p.add_argument("--output-dir", type=Path, default=Path("output/pos_divergence_study"))
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    logger.info("Loading dataset (model_signal=%s)...", args.model_signal)
    dataset = build_pos_divergence_dataset(args.snapshots_dir, args.price_csv, horizons, args.model_signal)
    logger.info("Dataset: %d observations", len(dataset))

    if not dataset:
        logger.error("No data — check snapshots dir and options_diagnostics.csv sidecars")
        return 1

    logger.info("Computing descriptive statistics...")
    descriptive = compute_descriptive(dataset)

    logger.info("Running simple predictive tests...")
    simple_tests = run_simple_tests(dataset, horizons, args.min_obs)

    logger.info("Running incremental tests (controlling for catalyst timing)...")
    incremental_tests = run_incremental_tests(dataset, horizons, args.min_obs)

    logger.info("Running portfolio slice tests...")
    portfolio_slices = run_portfolio_slices(dataset, horizons, args.top_k, args.min_obs)

    logger.info("Evaluating decision rule...")
    decision = evaluate_decision_rule(simple_tests, incremental_tests)

    report = generate_report(
        dataset,
        descriptive,
        simple_tests,
        incremental_tests,
        portfolio_slices,
        decision,
        args.model_signal,
        horizons,
    )

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "pos_divergence_study.json"
    md_path = args.output_dir / "pos_divergence_study.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
        f.write("\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(format_report_md(report))

    logger.info("Decision: %s", decision["classification"])
    for reason in decision["reasons"]:
        logger.info("  %s", reason)
    logger.info("Report: %s", json_path)
    logger.info("Report: %s", md_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
