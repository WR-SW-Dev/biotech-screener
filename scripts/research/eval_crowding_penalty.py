#!/usr/bin/env python3
"""Crowding penalty alpha research study.

Tests whether pre-catalyst options activity (volume, breadth, concentration)
adds independent *negative* information after controlling for clinical quality.

This wraps the existing crowding_orthogonality_analysis.py infrastructure with
the standard alpha/overlay/abandon decision framework used by eval_options_alpha
and eval_pos_divergence.

Decision rule:
    - negative signed IC survives clinical quality control → negative_alpha_candidate
    - absolute IC survives controls → risk_overlay_candidate
    - signal present but wiped by quality control → signal_present_but_not_incremental
    - fails both → abandon

Usage:
    python scripts/research/eval_crowding_penalty.py \\
        --panel data/research/precatalyst_options_panel.csv \\
        --price-csv production_data/price_history.csv \\
        [--horizons 5,20,63] \\
        [--output-dir output/crowding_penalty]
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
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Ensure project root is importable
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

logger = logging.getLogger(__name__)

STUDY_SCHEMA = "crowding_penalty_study.v1"
IC_THRESHOLD = 0.05
DEFAULT_HORIZONS = [5, 20, 63]
DEFAULT_MIN_OBS = 20

# Crowding feature columns from the panel builder
CROWDING_FEATURES = [
    "pre_event_volume_mean",
    "pre_event_volume_surge",
    "pre_event_transactions_mean",
    "pre_event_contract_count_mean",
    "pre_event_put_call_ratio",
    "pre_event_volume_trend",
    "chain_breadth",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(v: Any) -> float:
    if v is None or v == "":
        return float("nan")
    try:
        return float(v)
    except (ValueError, TypeError):
        return float("nan")


def _insufficient(n: int, min_obs: int) -> Dict[str, Any]:
    return {"status": "insufficient_sample", "n": n, "min_required": min_obs}


def _mean(xs: List[float]) -> float:
    clean = [x for x in xs if not math.isnan(x)]
    return sum(clean) / len(clean) if clean else float("nan")


def _z_score(values: List[float]) -> List[float]:
    clean = [v for v in values if not math.isnan(v)]
    if len(clean) < 2:
        return [float("nan")] * len(values)
    mean = sum(clean) / len(clean)
    var = sum((v - mean) ** 2 for v in clean) / len(clean)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return [0.0 if not math.isnan(v) else float("nan") for v in values]
    return [(v - mean) / std if not math.isnan(v) else float("nan") for v in values]


# ---------------------------------------------------------------------------
# Dataset builder
# ---------------------------------------------------------------------------


def load_panel_dataset(
    panel_path: Path,
    price_csv: Path,
    horizons: List[int],
) -> List[Dict[str, Any]]:
    """Load the pre-catalyst options panel and attach forward returns."""
    if not panel_path.exists():
        logger.error("Panel not found: %s", panel_path)
        return []

    # Load panel
    with open(panel_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return []

    # Parse numeric features
    for r in rows:
        for feat in CROWDING_FEATURES:
            r[feat] = _safe_float(r.get(feat))
        r["composite_score"] = _safe_float(r.get("composite_score"))
        r["catalyst_days"] = _safe_float(r.get("catalyst_days"))

    # Load price history
    prices: Dict[str, Dict[str, float]] = {}
    if price_csv.exists():
        with open(price_csv, newline="", encoding="utf-8") as f:
            for pr in csv.DictReader(f):
                tk = pr.get("ticker", "")
                dt = pr.get("date", "")
                cl = pr.get("close", "")
                if tk and dt and cl:
                    try:
                        prices.setdefault(tk, {})[dt] = float(cl)
                    except ValueError:
                        pass

    # Compute forward returns
    from datetime import date, timedelta

    for r in rows:
        snap = r.get("snapshot_date", "")
        ticker = r.get("ticker", "")
        if not snap or not ticker:
            continue
        try:
            snap_date = date.fromisoformat(snap)
        except ValueError:
            continue
        ticker_prices = prices.get(ticker, {})
        for h in horizons:
            target = snap_date + timedelta(days=int(h * 7 / 5))
            p0 = _find_price(ticker_prices, snap_date)
            p1 = _find_price(ticker_prices, target)
            if p0 and p1 and p0 > 0:
                r[f"fwd_ret_{h}d"] = (p1 - p0) / p0
            else:
                r[f"fwd_ret_{h}d"] = None

    return rows


def _find_price(prices: Dict[str, float], target) -> Optional[float]:
    from datetime import timedelta

    for offset in range(4):
        for sign in (0, 1, -1):
            d = target + timedelta(days=offset * sign)
            if d.isoformat() in prices:
                return prices[d.isoformat()]
    return None


def compute_crowding_z(rows: List[Dict[str, Any]]) -> None:
    """Add crowding_z composite to each row (in-place).

    crowding_z = z(volume_mean) + z(near_term_share proxy via volume_surge)
    Positive crowding_z = more crowded.
    """
    vol_vals = [r.get("pre_event_volume_mean", float("nan")) for r in rows]
    surge_vals = [r.get("pre_event_volume_surge", float("nan")) for r in rows]

    vol_z = _z_score(vol_vals)
    surge_z = _z_score(surge_vals)

    for i, r in enumerate(rows):
        vz = vol_z[i]
        sz = surge_z[i]
        if not math.isnan(vz) and not math.isnan(sz):
            r["crowding_z"] = round(vz + sz, 4)
        elif not math.isnan(vz):
            r["crowding_z"] = round(vz, 4)
        else:
            r["crowding_z"] = float("nan")

        # Label
        cz = r["crowding_z"]
        if math.isnan(cz):
            r["crowding_label"] = ""
        elif cz >= 1.5:
            r["crowding_label"] = "high"
        elif cz >= 0.5:
            r["crowding_label"] = "medium"
        else:
            r["crowding_label"] = "low"


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


# ---------------------------------------------------------------------------
# Full test battery
# ---------------------------------------------------------------------------


def run_tests(
    dataset: List[Dict[str, Any]],
    horizons: List[int],
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Run all IC tests for crowding signals."""
    results: Dict[str, Any] = {"raw": {}, "incremental": {}, "double_sort": {}}

    signals = ["crowding_z", "pre_event_volume_mean", "chain_breadth", "pre_event_put_call_ratio"]
    targets = []
    for h in horizons:
        targets.append(f"fwd_ret_{h}d")

    # Raw IC
    for sig in signals:
        for ret in targets:
            results["raw"][f"ic_{sig}_vs_{ret}"] = compute_raw_ic(dataset, sig, ret, min_obs)

    # Incremental IC controlling for clinical quality (composite_score as proxy)
    for sig in signals:
        for ret in targets:
            results["incremental"][f"incr_{sig}_ctrl_composite_vs_{ret}"] = compute_incremental_ic(
                dataset, sig, "composite_score", ret, min_obs
            )

    # Double-sort: within composite_score terciles, does crowding discriminate?
    for ret in targets:
        triples = [
            (r.get("composite_score", float("nan")), r.get("crowding_z", float("nan")), r.get(ret))
            for r in dataset
            if not math.isnan(r.get("composite_score", float("nan")))
            and not math.isnan(r.get("crowding_z", float("nan")))
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
            results["double_sort"][f"crowding_z_within_quality_vs_{ret}"] = {
                "status": "ok",
                "n": len(triples),
                "spread": round(spread, 6),
            }
        else:
            results["double_sort"][f"crowding_z_within_quality_vs_{ret}"] = _insufficient(len(triples), min_obs)

    return results


# ---------------------------------------------------------------------------
# Decision rule
# ---------------------------------------------------------------------------


def evaluate_decision_rule(tests: Dict[str, Any], horizons: List[int]) -> Dict[str, Any]:
    """Classify crowding signal: negative_alpha / risk_overlay / not_incremental / abandon."""
    # Use first available horizon for the primary gate
    primary_h = horizons[0] if horizons else 5
    raw_key = f"ic_crowding_z_vs_fwd_ret_{primary_h}d"
    raw = tests["raw"].get(raw_key, {})
    raw_ic = raw.get("ic", 0.0) if raw.get("status") == "ok" else None

    incr_key = f"incr_crowding_z_ctrl_composite_vs_fwd_ret_{primary_h}d"
    incr = tests["incremental"].get(incr_key, {})
    incr_ic = incr.get("incremental_ic", 0.0) if incr.get("status") == "ok" else None

    classification = "insufficient_data"
    reasons: List[str] = []

    if raw_ic is not None:
        has_negative_alpha = raw_ic < -IC_THRESHOLD
        has_abs_signal = abs(raw_ic) >= IC_THRESHOLD
        survives = incr_ic is not None and abs(incr_ic) >= IC_THRESHOLD

        if has_negative_alpha and survives:
            classification = "negative_alpha_candidate"
            reasons.append(f"crowding_z raw IC={raw_ic:.4f} (negative), incremental IC={incr_ic:.4f}")
            reasons.append("Crowding predicts worse outcomes independently of quality")
        elif has_abs_signal and survives:
            classification = "risk_overlay_candidate"
            reasons.append(f"crowding_z |raw IC|={abs(raw_ic):.4f}, incremental IC={incr_ic:.4f}")
        elif has_abs_signal and not survives:
            classification = "signal_present_but_not_incremental"
            reasons.append(f"crowding_z raw IC={raw_ic:.4f} but incremental IC={incr_ic:.4f}")
            reasons.append("Signal wiped out by clinical quality control — crowding is proxy for quality")
        else:
            classification = "abandon"
            reasons.append(f"crowding_z raw IC={raw_ic:.4f} — below threshold")
    else:
        reasons.append("Insufficient data for IC computation")

    return {
        "classification": classification,
        "reasons": reasons,
        "raw_ic": raw_ic,
        "incremental_ic": incr_ic,
        "primary_horizon": primary_h,
        "ic_threshold": IC_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def generate_report(
    dataset: List[Dict[str, Any]],
    tests: Dict[str, Any],
    decision: Dict[str, Any],
    horizons: List[int],
) -> Dict[str, Any]:
    n = len(dataset)
    n_with_crowding = sum(1 for r in dataset if not math.isnan(r.get("crowding_z", float("nan"))))
    n_with_returns = {h: sum(1 for r in dataset if r.get(f"fwd_ret_{h}d") is not None) for h in horizons}
    label_dist = {}
    for r in dataset:
        lbl = r.get("crowding_label", "")
        if lbl:
            label_dist[lbl] = label_dist.get(lbl, 0) + 1

    return {
        "schema": STUDY_SCHEMA,
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": {"horizons": horizons, "ic_threshold": IC_THRESHOLD},
        "descriptive": {
            "n_total": n,
            "n_with_crowding_z": n_with_crowding,
            "n_with_returns": n_with_returns,
            "crowding_label_distribution": label_dist,
            "snap_dates": len({r.get("snapshot_date") for r in dataset}),
            "tickers": len({r.get("ticker") for r in dataset}),
        },
        "tests": tests,
        "decision": decision,
    }


def format_report_md(report: Dict[str, Any]) -> str:
    lines = [
        "# Crowding Penalty Study",
        "",
        f"Generated: {report['generated_at']}",
        "",
    ]

    d = report["decision"]
    lines.append(f"## Decision: **{d['classification'].upper()}**")
    lines.append("")
    for r in d["reasons"]:
        lines.append(f"- {r}")
    lines.append("")

    # Raw ICs
    lines.append("## Raw IC (crowding vs forward returns)")
    lines.append("")
    lines.append("| Signal vs Target | IC | n |")
    lines.append("|------------------|----|---|")
    for key, val in sorted(report["tests"]["raw"].items()):
        if val.get("status") == "ok":
            lines.append(f"| {key} | {val['ic']:.4f} | {val['n']} |")
        else:
            lines.append(f"| {key} | - | {val.get('n', '?')} |")
    lines.append("")

    # Incremental ICs
    lines.append("## Incremental IC (controlling for composite_score)")
    lines.append("")
    lines.append("| Test | Raw IC | Incremental IC | n |")
    lines.append("|------|--------|----------------|---|")
    for key, val in sorted(report["tests"]["incremental"].items()):
        if val.get("status") == "ok":
            lines.append(f"| {key} | {val['raw_ic']:.4f} | {val['incremental_ic']:.4f} | {val['n']} |")
        else:
            lines.append(f"| {key} | - | - | {val.get('n', '?')} |")
    lines.append("")

    # Double sort
    lines.append("## Double Sort (crowding within quality terciles)")
    lines.append("")
    for key, val in sorted(report["tests"]["double_sort"].items()):
        if val.get("status") == "ok":
            lines.append(f"- {key}: spread = {val['spread']:.4f} (n={val['n']})")
        else:
            lines.append(f"- {key}: insufficient data")
    lines.append("")

    # Descriptive
    desc = report["descriptive"]
    lines.append("## Dataset Summary")
    lines.append("")
    lines.append(f"- Panel rows: {desc['n_total']}")
    lines.append(f"- With crowding_z: {desc['n_with_crowding_z']}")
    lines.append(f"- Crowding distribution: {desc.get('crowding_label_distribution', {})}")
    lines.append(f"- Snapshot dates: {desc['snap_dates']}")
    lines.append(f"- Unique tickers: {desc['tickers']}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Crowding penalty alpha study.")
    p.add_argument("--panel", type=Path, default=Path("data/research/precatalyst_options_panel.csv"))
    p.add_argument("--price-csv", type=Path, default=Path("production_data/price_history.csv"))
    p.add_argument("--horizons", default="5,20,63")
    p.add_argument("--min-obs", type=int, default=DEFAULT_MIN_OBS)
    p.add_argument("--output-dir", type=Path, default=Path("output/crowding_penalty"))
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    logger.info("Loading panel from %s...", args.panel)
    dataset = load_panel_dataset(args.panel, args.price_csv, horizons)
    logger.info("Panel: %d rows", len(dataset))

    if not dataset:
        logger.error("No data — check panel path")
        return 1

    logger.info("Computing crowding_z composite...")
    compute_crowding_z(dataset)

    logger.info("Running IC tests...")
    tests = run_tests(dataset, horizons, args.min_obs)

    logger.info("Evaluating decision rule...")
    decision = evaluate_decision_rule(tests, horizons)

    report = generate_report(dataset, tests, decision, horizons)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "crowding_penalty_study.json"
    md_path = args.output_dir / "crowding_penalty_study.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
        f.write("\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(format_report_md(report))

    logger.info("Decision: %s", decision["classification"])
    for reason in decision["reasons"]:
        logger.info("  %s", reason)
    logger.info("Report: %s", json_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
