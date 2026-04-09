#!/usr/bin/env python3
"""Options IV/skew alpha research study.

Evaluates whether options-implied vol/skew measures add predictive value for
catalyst names beyond existing catalyst timing/type information.

Decision rule:
    - absolute-move-only → risk overlay candidate
    - signed-move/drift  → alpha candidate
    - nothing survives controls → abandon

Reuses dataset builders from options_prospective_analysis.py and statistical
primitives from backtest_signal_robustness.py.

Usage:
    python scripts/research/eval_options_alpha.py \\
        --snapshots-dir data/snapshots \\
        --price-csv production_data/price_history.csv \\
        [--horizons 5,21,63] \\
        [--min-obs 20] \\
        [--output-dir output/options_alpha_study]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
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
from options_prospective_analysis import (  # noqa: E402
    _mean,
    _median,
    _std,
    compute_forward_return,
    load_options_snapshots,
    load_price_series,
    resolve_event_outcome,
)

logger = logging.getLogger(__name__)

# Schema version for the output report
STUDY_SCHEMA = "options_alpha_study.v1"

# Catalyst window: only include observations with catalyst_days <= this
CATALYST_WINDOW_MAX = 90

# IC thresholds for decision rule
IC_THRESHOLD_OVERLAY = 0.05  # abs-gap IC to qualify as risk overlay
IC_THRESHOLD_ALPHA = 0.05  # signed-gap IC to qualify as alpha candidate

DEFAULT_HORIZONS = [5, 21, 63]
DEFAULT_MIN_OBS = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(v: Any, default: float = float("nan")) -> float:
    """Parse a value to float, returning *default* on failure."""
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _insufficient(n: int, min_obs: int) -> Dict[str, Any]:
    """Return standard insufficient-sample dict."""
    return {"status": "insufficient_sample", "n": n, "min_required": min_obs}


# ---------------------------------------------------------------------------
# Section A: Dataset builder
# ---------------------------------------------------------------------------


def _load_rankings_for_date(
    snapshots_dir: Path,
    snap_date: str,
) -> Dict[str, Dict[str, str]]:
    """Load rankings.csv for a single snap_date → {ticker: row_dict}."""
    csv_path = snapshots_dir / snap_date / "rankings.csv"
    result: Dict[str, Dict[str, str]] = {}
    if not csv_path.exists():
        return result
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip().upper()
            if ticker:
                result[ticker] = row
    return result


def load_enriched_dataset(
    snapshots_dir: Path,
    price_csv: Path,
    horizons: List[int],
) -> List[Dict[str, Any]]:
    """Load options sidecars, join to rankings for catalyst context,
    compute forward returns and event outcomes.

    Returns flat list of enriched row dicts filtered to:
        - opt_has_data == "1"
        - catalyst_days present and <= CATALYST_WINDOW_MAX
    """
    opt_rows = load_options_snapshots(snapshots_dir)
    if not opt_rows:
        return []

    prices = load_price_series(price_csv) if price_csv.exists() else {}

    # Build sorted dates from all prices
    all_dates_set: set = set()
    for td in prices.values():
        all_dates_set.update(td.keys())
    sorted_dates = sorted(all_dates_set)

    # Group sidecar rows by snap_date for batch rankings load
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in opt_rows:
        sd = row.get("snap_date", "")
        if sd:
            by_date.setdefault(sd, []).append(row)

    result: List[Dict[str, Any]] = []

    for snap_date, date_rows in sorted(by_date.items()):
        rankings_map = _load_rankings_for_date(snapshots_dir, snap_date)

        for row in date_rows:
            # Filter: must have options data
            if row.get("opt_has_data") != "1":
                continue

            ticker = (row.get("ticker") or "").upper()
            if not ticker:
                continue

            # Join to rankings
            rank_row = rankings_map.get(ticker)
            if rank_row is None:
                continue

            # Extract catalyst_days from rankings (preferred) or sidecar
            cat_days_str = rank_row.get("catalyst_days", "") or row.get("catalyst_days", "")
            cat_days = _safe_float(cat_days_str)
            if math.isnan(cat_days):
                continue
            cat_days_int = int(cat_days)
            if cat_days_int < 0 or cat_days_int > CATALYST_WINDOW_MAX:
                continue

            # Build enriched row
            out: Dict[str, Any] = {
                "ticker": ticker,
                "snap_date": snap_date,
                # Options columns
                "opt_term_slope": _safe_float(row.get("opt_term_slope", "")),
                "opt_atm_iv": _safe_float(row.get("opt_atm_iv", "")),
                "opt_front_iv": _safe_float(row.get("opt_front_iv", "")),
                "opt_back_iv": _safe_float(row.get("opt_back_iv", "")),
                "opt_event_premium": row.get("opt_event_premium", ""),
                "opt_iv_regime": row.get("opt_iv_regime", ""),
                "opt_use_for_judgment": row.get("opt_use_for_judgment", ""),
                # Catalyst context from rankings
                "catalyst_days": cat_days_int,
                "catalyst_decay_w": _safe_float(rank_row.get("catalyst_decay_w", "")),
                "catalyst_mode": rank_row.get("catalyst_mode", ""),
                "catalyst_family": rank_row.get("catalyst_family", ""),
                "catalyst_event_type": rank_row.get("catalyst_event_type", ""),
                "catalyst_source": rank_row.get("catalyst_source", ""),
                "eligible": rank_row.get("eligible", ""),
            }

            # Forward returns
            ticker_prices = prices.get(ticker, {})
            for h in horizons:
                ret = compute_forward_return(
                    ticker_prices,
                    sorted_dates,
                    snap_date,
                    h,
                )
                out[f"fwd_ret_{h}d"] = ret

            # Event outcome
            event = resolve_event_outcome(
                ticker_prices,
                sorted_dates,
                snap_date,
                cat_days_int,
            )
            out.update(event)

            # Hard catalyst flag (for filtering PCD noise)
            out["is_hard_catalyst"] = _is_hard_catalyst(out)

            result.append(out)

    return result


# Hard catalyst event types and sources for filtering calendar noise
_HARD_CATALYST_SOURCES = frozenset(
    {
        "FDA_PDUFA_DATE",
        "SEC_8K_FILING",
        "DATA_READOUT",
        "COMPANY_GUIDANCE",
    }
)


def _is_hard_catalyst(row: dict) -> bool:
    """Determine if a row represents a genuine binary catalyst event.

    Excludes calendar-inferred completion dates (CT_PRIMARY_COMPLETION,
    CT_STUDY_COMPLETION from CTGOV_CALENDAR) which typically produce
    < 5% abs_gap and are not meaningful for mispricing or PoS studies.

    Returns True for hard sources, hard event types, or large abs_gap
    as a backstop for miscategorized events.
    """
    event_type = (row.get("catalyst_event_type") or "").lower()
    source = row.get("catalyst_source") or ""
    abs_gap = row.get("abs_gap")

    # Rows without outcomes: unknown, not False
    if abs_gap is None or (isinstance(abs_gap, float) and math.isnan(abs_gap)):
        # For rows without outcomes, classify based on source/type alone
        if source in _HARD_CATALYST_SOURCES:
            return True
        if source == "CTGOV_CALENDAR":
            return False
        return False  # conservative default

    abs_gap_val = float(abs_gap)

    # Exclude calendar-inferred completions with small moves
    if source == "CTGOV_CALENDAR":
        return False
    if "completion" in event_type and abs_gap_val < 0.08:
        return False

    # Include hard sources regardless of event type
    if source in _HARD_CATALYST_SOURCES:
        return True

    # Include hard event type keywords
    hard_keywords = {
        "pdufa",
        "nda_bla",
        "snda",
        "sbla",
        "top_line",
        "data_readout",
        "interim_analysis",
        "phase3_completion",
        "advisory_committee",
    }
    if any(h in event_type for h in hard_keywords):
        return True

    # Backstop: any row with abs_gap >= 10% is a real move
    if abs_gap_val >= 0.10:
        return True

    return False


# ---------------------------------------------------------------------------
# Section B: Descriptive analysis
# ---------------------------------------------------------------------------


def compute_descriptive(dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Coverage counts and feature distributions."""
    n = len(dataset)
    if n == 0:
        return {"n_total": 0, "status": "no_data"}

    # Feature distributions
    def _dist(values: List[float]) -> Dict[str, Any]:
        clean = [v for v in values if not math.isnan(v)]
        if not clean:
            return {"n": 0}
        return {
            "n": len(clean),
            "mean": round(_mean(clean), 6),
            "median": round(_median(clean), 6),
            "std": round(_std(clean), 6),
        }

    features = {}
    for col in ["opt_term_slope", "opt_atm_iv", "opt_front_iv", "opt_back_iv"]:
        features[col] = _dist([r[col] for r in dataset])

    # Liquidity split
    liquid = [r for r in dataset if r.get("opt_use_for_judgment") == "YES"]
    illiquid = [r for r in dataset if r.get("opt_use_for_judgment") != "YES"]

    # Event-type split
    reg = [r for r in dataset if r.get("catalyst_family") == "REGULATORY"]
    clin = [r for r in dataset if r.get("catalyst_family") == "CLINICAL"]

    # Catalyst days terciles
    cat_days_vals = sorted(r["catalyst_days"] for r in dataset)
    t1 = cat_days_vals[len(cat_days_vals) // 3] if cat_days_vals else None
    t2 = cat_days_vals[2 * len(cat_days_vals) // 3] if cat_days_vals else None

    # Event premium split
    ep_yes = sum(1 for r in dataset if r.get("opt_event_premium") == "YES")
    ep_no = sum(1 for r in dataset if r.get("opt_event_premium") == "NO")

    return {
        "n_total": n,
        "n_liquid": len(liquid),
        "n_illiquid": len(illiquid),
        "n_regulatory": len(reg),
        "n_clinical": len(clin),
        "n_event_premium_yes": ep_yes,
        "n_event_premium_no": ep_no,
        "catalyst_days_terciles": [t1, t2],
        "features": features,
    }


# ---------------------------------------------------------------------------
# Section C: Simple predictive tests
# ---------------------------------------------------------------------------


def compute_raw_ic(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    return_col: str,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Raw Spearman IC: signal vs return."""
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


def compute_binned_comparison(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    return_col: str,
    n_bins: int = 3,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Tercile-binned comparison: mean return per signal bin."""
    pairs = [
        (r[signal_col], r[return_col], r.get("ticker", ""))
        for r in dataset
        if not math.isnan(r.get(signal_col, float("nan"))) and r.get(return_col) is not None
    ]
    n = len(pairs)
    if n < min_obs:
        return _insufficient(n, min_obs)

    # Deterministic sort: by (signal, ticker) for tie-breaking
    pairs.sort(key=lambda p: (p[0], p[2]))
    bin_size = n // n_bins
    if bin_size < 1:
        return _insufficient(n, min_obs)

    bins: List[Dict[str, Any]] = []
    for b in range(n_bins):
        start = b * bin_size
        end = start + bin_size if b < n_bins - 1 else n
        bin_rets = [p[1] for p in pairs[start:end]]
        bin_sigs = [p[0] for p in pairs[start:end]]
        bins.append(
            {
                "bin": b + 1,
                "n": len(bin_rets),
                "signal_range": [round(min(bin_sigs), 6), round(max(bin_sigs), 6)],
                "mean_return": round(_mean(bin_rets), 6),
            }
        )

    effect_size = bins[-1]["mean_return"] - bins[0]["mean_return"]
    return {
        "status": "ok",
        "n": n,
        "bins": bins,
        "effect_size": round(effect_size, 6),
    }


def compute_premium_split(
    dataset: List[Dict[str, Any]],
    return_col: str,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Event premium YES vs NO → mean return comparison."""
    yes = [r[return_col] for r in dataset if r.get("opt_event_premium") == "YES" and r.get(return_col) is not None]
    no = [r[return_col] for r in dataset if r.get("opt_event_premium") == "NO" and r.get(return_col) is not None]

    n = len(yes) + len(no)
    if len(yes) < min_obs // 2 or len(no) < min_obs // 2:
        return _insufficient(n, min_obs)

    mean_yes = _mean(yes)
    mean_no = _mean(no)
    return {
        "status": "ok",
        "n_yes": len(yes),
        "n_no": len(no),
        "mean_yes": round(mean_yes, 6),
        "mean_no": round(mean_no, 6),
        "effect_size": round(mean_yes - mean_no, 6),
    }


def compute_simple_tests(
    dataset: List[Dict[str, Any]],
    horizons: List[int],
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Run all simple predictive tests."""
    results: Dict[str, Any] = {}

    signal_cols = ["opt_term_slope", "opt_atm_iv"]
    return_targets = ["abs_gap", "signed_gap"]
    for h in horizons:
        return_targets.append(f"fwd_ret_{h}d")

    for sig in signal_cols:
        for ret in return_targets:
            key = f"{sig}_vs_{ret}"
            results[f"ic_{key}"] = compute_raw_ic(dataset, sig, ret, min_obs)
            results[f"bins_{key}"] = compute_binned_comparison(dataset, sig, ret, 3, min_obs)

    # Event premium splits
    for ret in return_targets:
        results[f"premium_split_{ret}"] = compute_premium_split(dataset, ret, min_obs)

    return results


# ---------------------------------------------------------------------------
# Section D: Incremental alpha tests
# ---------------------------------------------------------------------------


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


def compute_double_sort(
    dataset: List[Dict[str, Any]],
    control_col: str,
    signal_col: str,
    return_col: str,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Double-sort: within control terciles, does signal still discriminate?"""
    triples = [
        (r[control_col], r[signal_col], r[return_col])
        for r in dataset
        if not math.isnan(r.get(control_col, float("nan")))
        and not math.isnan(r.get(signal_col, float("nan")))
        and r.get(return_col) is not None
    ]
    n = len(triples)
    if n < min_obs:
        return _insufficient(n, min_obs)

    sort1 = [t[0] for t in triples]
    sort2 = [t[1] for t in triples]
    rets = [t[2] for t in triples]

    spread = compute_double_sort_spread(sort1, sort2, rets, n_groups=3, min_per_group=3)
    return {"status": "ok", "n": n, "spread": round(spread, 6)}


def compute_incremental_tests(
    dataset: List[Dict[str, Any]],
    horizons: List[int],
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Run all incremental alpha tests."""
    results: Dict[str, Any] = {}

    signal_cols = ["opt_term_slope", "opt_atm_iv"]
    control_cols = ["catalyst_decay_w"]
    return_targets = ["abs_gap", "signed_gap"]
    for h in horizons:
        return_targets.append(f"fwd_ret_{h}d")

    for sig in signal_cols:
        for ctrl in control_cols:
            for ret in return_targets:
                key = f"{sig}_ctrl_{ctrl}_vs_{ret}"
                results[f"incr_ic_{key}"] = compute_incremental_ic(
                    dataset,
                    sig,
                    ctrl,
                    ret,
                    min_obs,
                )
                results[f"double_sort_{key}"] = compute_double_sort(
                    dataset,
                    ctrl,
                    sig,
                    ret,
                    min_obs,
                )

    # Subgroup splits: by catalyst_family
    for family in ["REGULATORY", "CLINICAL"]:
        sub = [r for r in dataset if r.get("catalyst_family") == family]
        if len(sub) < min_obs:
            results[f"family_{family}"] = _insufficient(len(sub), min_obs)
            continue
        family_results: Dict[str, Any] = {"n": len(sub)}
        for sig in signal_cols:
            for ret in ["abs_gap", "signed_gap"]:
                key = f"{sig}_vs_{ret}"
                family_results[f"ic_{key}"] = compute_raw_ic(sub, sig, ret, min_obs)
        results[f"family_{family}"] = family_results

    # Subgroup splits: by IV regime
    for regime in ["NORMAL", "ELEVATED"]:
        sub = [r for r in dataset if r.get("opt_iv_regime") == regime]
        if len(sub) < min_obs:
            results[f"regime_{regime}"] = _insufficient(len(sub), min_obs)
            continue
        regime_results: Dict[str, Any] = {"n": len(sub)}
        for sig in signal_cols:
            for ret in ["abs_gap", "signed_gap"]:
                key = f"{sig}_vs_{ret}"
                regime_results[f"ic_{key}"] = compute_raw_ic(sub, sig, ret, min_obs)
        results[f"regime_{regime}"] = regime_results

    return results


# ---------------------------------------------------------------------------
# Section E: Portfolio-realistic slice
# ---------------------------------------------------------------------------


def compute_portfolio_slice(
    dataset: List[Dict[str, Any]],
    signal_col: str,
    return_col: str,
    top_k: int = 10,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Sort catalyst-subset by signal, compare top-K vs rest."""
    pairs = [
        (r[signal_col], r[return_col], r.get("ticker", ""))
        for r in dataset
        if not math.isnan(r.get(signal_col, float("nan"))) and r.get(return_col) is not None
    ]
    n = len(pairs)
    if n < min_obs or n < top_k + 1:
        return _insufficient(n, min_obs)

    # For opt_term_slope: most negative = strongest backwardation = most event premium
    # Sort ascending so most negative is first
    pairs.sort(key=lambda p: (p[0], p[2]))

    top_rets = [p[1] for p in pairs[:top_k]]
    rest_rets = [p[1] for p in pairs[top_k:]]

    # Baseline: sort by catalyst_decay_w descending (highest = nearest catalyst)
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


def compute_portfolio_slices(
    dataset: List[Dict[str, Any]],
    horizons: List[int],
    top_k: int = 10,
    min_obs: int = DEFAULT_MIN_OBS,
) -> Dict[str, Any]:
    """Run portfolio slices for each signal x return target."""
    results: Dict[str, Any] = {}
    for sig in ["opt_term_slope", "opt_atm_iv"]:
        for ret in ["abs_gap", "signed_gap"]:
            results[f"{sig}_vs_{ret}"] = compute_portfolio_slice(
                dataset,
                sig,
                ret,
                top_k,
                min_obs,
            )
        for h in horizons:
            results[f"{sig}_vs_fwd_ret_{h}d"] = compute_portfolio_slice(
                dataset,
                sig,
                f"fwd_ret_{h}d",
                top_k,
                min_obs,
            )
    return results


# ---------------------------------------------------------------------------
# Section F: Report assembly
# ---------------------------------------------------------------------------


def _evaluate_decision_rule(
    simple_tests: Dict[str, Any],
    incremental_tests: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply decision rule: risk overlay / alpha candidate / abandon."""
    # Check absolute-move IC for risk overlay
    abs_ic_key = "ic_opt_term_slope_vs_abs_gap"
    abs_result = simple_tests.get(abs_ic_key, {})
    abs_ic = abs_result.get("ic", 0.0) if abs_result.get("status") == "ok" else None

    # Check signed-move IC for alpha
    signed_ic_key = "ic_opt_term_slope_vs_signed_gap"
    signed_result = simple_tests.get(signed_ic_key, {})
    signed_ic = signed_result.get("ic", 0.0) if signed_result.get("status") == "ok" else None

    # Check incremental IC (controls catalyst timing)
    incr_key = "incr_ic_opt_term_slope_ctrl_catalyst_decay_w_vs_abs_gap"
    incr_result = incremental_tests.get(incr_key, {})
    incr_ic = incr_result.get("incremental_ic", 0.0) if incr_result.get("status") == "ok" else None

    incr_signed_key = "incr_ic_opt_term_slope_ctrl_catalyst_decay_w_vs_signed_gap"
    incr_signed_result = incremental_tests.get(incr_signed_key, {})
    incr_signed_ic = incr_signed_result.get("incremental_ic", 0.0) if incr_signed_result.get("status") == "ok" else None

    # Decision
    classification = "insufficient_data"
    reasons: List[str] = []

    if abs_ic is not None and signed_ic is not None:
        has_abs = abs(abs_ic) >= IC_THRESHOLD_OVERLAY
        has_signed = abs(signed_ic) >= IC_THRESHOLD_ALPHA
        survives_abs_ctrl = incr_ic is not None and abs(incr_ic) >= IC_THRESHOLD_OVERLAY
        survives_signed_ctrl = incr_signed_ic is not None and abs(incr_signed_ic) >= IC_THRESHOLD_ALPHA

        if has_signed and survives_signed_ctrl:
            classification = "alpha_candidate"
            reasons.append(f"signed_gap IC={signed_ic:.4f}, incremental IC={incr_signed_ic:.4f}")
        elif has_abs and survives_abs_ctrl:
            classification = "risk_overlay_candidate"
            reasons.append(f"abs_gap IC={abs_ic:.4f}, incremental IC={incr_ic:.4f}")
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
        "incremental_abs_ic": incr_ic,
        "incremental_signed_ic": incr_signed_ic,
        "ic_threshold_overlay": IC_THRESHOLD_OVERLAY,
        "ic_threshold_alpha": IC_THRESHOLD_ALPHA,
    }


def generate_alpha_report(
    dataset: List[Dict[str, Any]],
    descriptive: Dict[str, Any],
    simple_tests: Dict[str, Any],
    incremental_tests: Dict[str, Any],
    portfolio_slices: Dict[str, Any],
    horizons: List[int],
    min_obs: int,
) -> Dict[str, Any]:
    """Assemble full JSON report."""
    n = len(dataset)
    snap_dates = sorted(set(r.get("snap_date", "") for r in dataset if r.get("snap_date")))

    if n == 0:
        return {
            "schema": STUDY_SCHEMA,
            "status": "insufficient_sample",
            "n_observations": 0,
            "n_snapshots": 0,
            "message": "No options observations with catalyst context found. "
            "Continue accumulating weekly snapshots with tastytrade credentials active.",
        }

    decision = _evaluate_decision_rule(simple_tests, incremental_tests)

    return {
        "schema": STUDY_SCHEMA,
        "status": "ok" if n >= min_obs else "insufficient_sample",
        "n_observations": n,
        "n_snapshots": len(snap_dates),
        "snap_dates": snap_dates,
        "horizons": horizons,
        "min_obs": min_obs,
        "catalyst_window_max": CATALYST_WINDOW_MAX,
        "decision": decision,
        "descriptive": descriptive,
        "simple_tests": simple_tests,
        "incremental_tests": incremental_tests,
        "portfolio_slices": portfolio_slices,
    }


def format_alpha_report_md(report: Dict[str, Any]) -> str:
    """Render report as compact markdown."""
    lines = [
        "# Options IV/Skew Alpha Study",
        "",
        f"**Schema**: {report.get('schema', '?')}  ",
        f"**Status**: {report.get('status', '?')}  ",
        f"**Observations**: {report.get('n_observations', 0)}  ",
        f"**Snapshots**: {report.get('n_snapshots', 0)}  ",
        "",
    ]

    if report.get("status") == "insufficient_sample":
        lines.append(f"> {report.get('message', 'Insufficient data.')}")
        lines.append("")
        return "\n".join(lines) + "\n"

    # Decision
    decision = report.get("decision", {})
    lines.append("## Decision")
    lines.append("")
    lines.append(f"**Classification**: {decision.get('classification', '?')}  ")
    for reason in decision.get("reasons", []):
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    for key in ["abs_gap_ic", "signed_gap_ic", "incremental_abs_ic", "incremental_signed_ic"]:
        val = decision.get(key)
        val_str = f"{val:.4f}" if isinstance(val, float) else "\u2014"
        lines.append(f"| {key} | {val_str} |")
    lines.append("")

    # Descriptive
    desc = report.get("descriptive", {})
    if desc:
        lines.append("## Descriptive")
        lines.append("")
        lines.append("| Stat | Value |")
        lines.append("|------|-------|")
        for k in ["n_total", "n_liquid", "n_regulatory", "n_clinical", "n_event_premium_yes", "n_event_premium_no"]:
            lines.append(f"| {k} | {desc.get(k, '—')} |")
        lines.append("")

    # Simple test ICs
    simple = report.get("simple_tests", {})
    ic_entries = {k: v for k, v in simple.items() if k.startswith("ic_") and isinstance(v, dict)}
    if ic_entries:
        lines.append("## Raw ICs")
        lines.append("")
        lines.append("| Test | N | IC |")
        lines.append("|------|---|-----|")
        for k, v in sorted(ic_entries.items()):
            if v.get("status") == "ok":
                lines.append(f"| {k} | {v['n']} | {v['ic']:.4f} |")
            else:
                lines.append(f"| {k} | {v.get('n', '—')} | insufficient |")
        lines.append("")

    # Portfolio slices
    slices = report.get("portfolio_slices", {})
    if slices:
        lines.append("## Portfolio Slices")
        lines.append("")
        lines.append("| Slice | N | Top Mean | Rest Mean | Spread |")
        lines.append("|-------|---|----------|-----------|--------|")
        for k, v in sorted(slices.items()):
            if v.get("status") == "ok":
                lines.append(f"| {k} | {v['n']} | {v['top_mean']:.4f} | " f"{v['rest_mean']:.4f} | {v['spread']:.4f} |")
            else:
                lines.append(f"| {k} | {v.get('n', '—')} | — | — | insufficient |")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Options IV/skew alpha research study")
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=Path("data/snapshots"),
        help="Base snapshot directory",
    )
    parser.add_argument(
        "--price-csv",
        type=Path,
        default=Path("production_data/price_history.csv"),
        help="Price history CSV",
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default="5,21,63",
        help="Comma-separated forward return horizons (trading days)",
    )
    parser.add_argument(
        "--min-obs",
        type=int,
        default=DEFAULT_MIN_OBS,
        help="Minimum observations for statistical tests",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Portfolio slice size",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: stdout)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    logger.info("Loading enriched dataset from %s ...", args.snapshots_dir)
    dataset = load_enriched_dataset(args.snapshots_dir, args.price_csv, horizons)
    logger.info("Enriched dataset: %d observations", len(dataset))

    # Run analysis sections
    descriptive = compute_descriptive(dataset)
    simple_tests = compute_simple_tests(dataset, horizons, args.min_obs)
    incremental_tests = compute_incremental_tests(dataset, horizons, args.min_obs)
    portfolio_slices = compute_portfolio_slices(dataset, horizons, args.top_k, args.min_obs)

    report = generate_alpha_report(
        dataset,
        descriptive,
        simple_tests,
        incremental_tests,
        portfolio_slices,
        horizons,
        args.min_obs,
    )

    report_json = json.dumps(report, indent=2, default=str)
    report_md = format_alpha_report_md(report)

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with open(args.output_dir / "options_alpha_report.json", "w") as f:
            f.write(report_json + "\n")
        with open(args.output_dir / "options_alpha_report.md", "w") as f:
            f.write(report_md)
        logger.info("Report written to %s", args.output_dir)
    else:
        print(report_md)
        print("---")
        print(report_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
