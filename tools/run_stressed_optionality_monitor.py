"""
STRESSED_OPTIONALITY_FORWARD_MONITOR_NO_MODEL_CHANGE

Forward-validation ledger for the stressed-optionality confirmation shadow rule.
Writes per-date records, appends to a longitudinal JSONL ledger, fills T+5 forward
returns when prices become available, and produces weekly calibration memos.

Governance (HARD — do not remove):
  NO_MODEL_CHANGE  NO_RANKER_CHANGE  NO_SELECTOR_CHANGE  NO_SIZING_CHANGE
  NO_PRODUCTION_WIRING  NO_CRON  SHADOW_ONLY
  Do not alter rankings.csv or any production output.

Artifact paths:
  artifacts/shadow_monitor/stressed_optionality/
    daily/   YYYY-MM-DD_stressed_optionality_shadow.{json,md}
    jsonl/   stressed_optionality_daily.jsonl
    weekly/  YYYY-MM-DD_stressed_optionality_weekly_calibration.{json,md}
    pending_forward/  YYYY-MM-DD_pending_t5.json

Usage:
  python tools/run_stressed_optionality_monitor.py --date YYYY-MM-DD
  python tools/run_stressed_optionality_monitor.py --fill-forward
  python tools/run_stressed_optionality_monitor.py --weekly [--end-date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_v2_pairwise import RankerV2Config, filter_cohort

# Reuse the rule from the shadow test tool (same constants, same logic)
from tools.run_stressed_optionality_shadow_test import (
    EES_SUPPRESS_THRESHOLD,
    EXTREME_STRESS_FI_Z_THRESHOLD,
    MOMENTUM_CONFIRM_THRESHOLD,
    apply_shadow_rule,
    build_shadow_basket,
    compute_basket_return,
    get_fwd_date,
    get_trading_dates,
    load_canonical_rankings,
    load_price_history,
    load_ranker_v2_model,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLASSIFICATION = "STRESSED_OPTIONALITY_FORWARD_MONITOR_NO_MODEL_CHANGE"
SCHEMA = "stressed_optionality_shadow_daily_v1"
WEEKLY_SCHEMA = "stressed_optionality_weekly_calibration_v1"

SUPPRESSION_REVIEW_THRESHOLD: int = 8  # >= 8 of 30 → REVIEW_REQUIRED
N_BASKET: int = 30

PRODUCTION_RANKER_V2_CONFIG = RankerV2Config(feature_set="minimal_v2")

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_HISTORY_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"

OUTPUT_BASE = PROJECT_ROOT / "artifacts" / "shadow_monitor" / "stressed_optionality"
DAILY_DIR = OUTPUT_BASE / "daily"
JSONL_DIR = OUTPUT_BASE / "jsonl"
WEEKLY_DIR = OUTPUT_BASE / "weekly"
PENDING_DIR = OUTPUT_BASE / "pending_forward"
DAILY_JSONL = JSONL_DIR / "stressed_optionality_daily.jsonl"

GOVERNANCE = {
    "model_change": False,
    "ranker_change": False,
    "selector_change": False,
    "sizing_change": False,
    "production_wiring": False,
}

PARAMETERS = {
    "ees_cutoff": EES_SUPPRESS_THRESHOLD,
    "extreme_fi_z": EXTREME_STRESS_FI_Z_THRESHOLD,
    "momentum_threshold": MOMENTUM_CONFIRM_THRESHOLD,
    "suppression_rate_review_threshold": SUPPRESSION_REVIEW_THRESHOLD,
}


# ---------------------------------------------------------------------------
# Cohort stats (local — avoid importing private internals)
# ---------------------------------------------------------------------------

import math as _math


def _cohort_stats(cohort: list[dict]) -> dict:
    def _stats(vals):
        n = len(vals)
        if n == 0:
            return 0.0, 1.0
        mu = sum(vals) / n
        std = _math.sqrt(sum((x - mu) ** 2 for x in vals) / n) or 1.0
        return mu, std

    ci_vals = [float(r.get("coinvest_score_z") or 0) for r in cohort]
    fi_vals = [float(r.get("financial_score") or 0) for r in cohort]
    ci_mean, ci_std = _stats(ci_vals)
    fi_mean, fi_std = _stats(fi_vals)
    return {"ci_mean": ci_mean, "ci_std": ci_std, "fi_mean": fi_mean, "fi_std": fi_std}


def _float_or_none(row: dict, key: str) -> Optional[float]:
    val = row.get(key, "")
    if val in ("", "None", "nan", None):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Guard status
# ---------------------------------------------------------------------------


def compute_guard_status(n_suppressed: int) -> str:
    return "REVIEW_REQUIRED" if n_suppressed >= SUPPRESSION_REVIEW_THRESHOLD else "CLEAN"


# ---------------------------------------------------------------------------
# Suppression and replacement detail
# ---------------------------------------------------------------------------


def build_suppression_detail(
    original_top30: list[str],
    shadow_top30: list[str],
    rows: list[dict],
    shadow_by_ticker: dict,
) -> tuple[list[dict], list[dict]]:
    """
    Returns (suppressed_list, replacement_list).

    suppressed_list: one entry per name in original_top30 but not shadow_top30.
    replacement_list: one entry per name in shadow_top30 but not original_top30.
    Paired 1-to-1 by position; replacement_ticker is None if no corresponding replacement.
    """
    original_set = set(original_top30)
    shadow_set = set(shadow_top30)

    suppressed_tickers = [t for t in original_top30 if t not in shadow_set]
    replacement_tickers = [t for t in shadow_top30 if t not in original_set]

    # Build row lookup
    row_lookup = {r["ticker"]: r for r in rows}

    def _rank(r: dict) -> int:
        try:
            return int(r.get("actionable_rank") or 9999)
        except ValueError:
            return 9999

    suppressed_list = []
    for i, ticker in enumerate(suppressed_tickers):
        r = row_lookup.get(ticker, {})
        sr = shadow_by_ticker.get(ticker, {})
        replacement = replacement_tickers[i] if i < len(replacement_tickers) else None
        suppressed_list.append(
            {
                "ticker": ticker,
                "original_rank": _rank(r),
                "reason_code": sr.get("suppression_type") or "UNKNOWN",
                "fi_z": sr.get("fi_z"),
                "ees": sr.get("ees_v3_score"),
                "momentum": sr.get("momentum_score"),
                "clinical": _float_or_none(r, "clinical_score"),
                "coinvest_z": sr.get("ci_z"),
                "replacement_ticker": replacement,
            }
        )

    replacement_list = []
    for ticker in replacement_tickers:
        r = row_lookup.get(ticker, {})
        replacement_list.append(
            {
                "ticker": ticker,
                "rank_in_original_rankings": _rank(r),
            }
        )

    return suppressed_list, replacement_list


# ---------------------------------------------------------------------------
# Daily shadow record
# ---------------------------------------------------------------------------


def run_daily_shadow(
    snap_date: str,
    write_output: bool = True,
    _model=None,
    _prices: Optional[dict] = None,
    _trading_dates: Optional[list] = None,
) -> dict:
    """
    Run the stressed-optionality shadow rule for a single snapshot date.

    Returns the full daily record dict.
    If write_output=True: writes daily JSON, daily MD, appends to JSONL, writes pending T+5.
    """
    if _model is None:
        _model = load_ranker_v2_model()
    if _prices is None:
        _prices = load_price_history()
    if _trading_dates is None:
        _trading_dates = get_trading_dates(_prices)

    snap_path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    if not snap_path.exists():
        return {"error": f"snapshot not found: {snap_path}", "as_of_date": snap_date}

    rows = load_canonical_rankings(snap_date)
    cohort = filter_cohort(copy.deepcopy(rows), PRODUCTION_RANKER_V2_CONFIG)
    stats = _cohort_stats(cohort)

    def _rank(r):
        try:
            return int(r.get("actionable_rank") or 9999)
        except ValueError:
            return 9999

    top30_rows = [r for r in sorted(rows, key=_rank) if _rank(r) <= N_BASKET]
    original_top30 = [r["ticker"] for r in top30_rows]

    # Apply shadow rule to top-30 + extension (ranks 31–60) for basket replacement
    shadow_by_ticker: dict = {}
    for r in sorted(rows, key=_rank):
        if _rank(r) <= 60:
            shadow_by_ticker[r["ticker"]] = apply_shadow_rule(r, stats, _model)

    shadow_top30 = build_shadow_basket(rows, shadow_by_ticker, n=N_BASKET)

    n_suppressed = sum(1 for t in original_top30 if shadow_by_ticker.get(t, {}).get("shadow_status") == "SUPPRESSED")

    guard_status = compute_guard_status(n_suppressed)
    suppressed_list, replacement_list = build_suppression_detail(original_top30, shadow_top30, rows, shadow_by_ticker)

    # T+5 forward return
    fwd_date = get_fwd_date(snap_date, _trading_dates)
    if fwd_date is None:
        fwd_status = "UNOBSERVABLE"
        original_ret = None
        shadow_ret = None
    else:
        # Try to compute returns (may be PENDING if fwd prices not yet available)
        original_ret = compute_basket_return(original_top30, snap_date, fwd_date, _prices)
        shadow_ret = compute_basket_return(shadow_top30, snap_date, fwd_date, _prices)
        # If ANY ticker in fwd_date exists in prices, fwd prices are available
        has_fwd_prices = any(fwd_date in _prices.get(t, {}) for t in original_top30)
        if not has_fwd_prices:
            fwd_status = "PENDING"
            original_ret = None
            shadow_ret = None
        else:
            fwd_status = "OBSERVED"

    delta = (shadow_ret - original_ret) if (shadow_ret is not None and original_ret is not None) else None

    record = {
        "schema": SCHEMA,
        "classification": CLASSIFICATION,
        "as_of_date": snap_date,
        "parameters": PARAMETERS,
        "original_top30": original_top30,
        "shadow_top30": shadow_top30,
        "suppressed": suppressed_list,
        "replacements": replacement_list,
        "suppression_summary": {
            "n_suppressed": n_suppressed,
            "suppression_rate": n_suppressed / N_BASKET,
            "guard_status": guard_status,
        },
        "forward_return": {
            "t5_due_date": fwd_date,
            "status": fwd_status,
            "original_top30_return": original_ret,
            "shadow_top30_return": shadow_ret,
            "delta": delta,
        },
        "governance": GOVERNANCE,
    }

    if write_output:
        _write_daily(record, _prices, _trading_dates)

    return record


def _write_daily(record: dict, prices: dict, trading_dates: list) -> None:
    snap_date = record["as_of_date"]
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    JSONL_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    # Daily JSON
    daily_json = DAILY_DIR / f"{snap_date}_stressed_optionality_shadow.json"
    with open(daily_json, "w") as f:
        json.dump(record, f, indent=2, default=str)

    # Daily MD
    daily_md = DAILY_DIR / f"{snap_date}_stressed_optionality_shadow.md"
    with open(daily_md, "w") as f:
        f.write(_format_daily_md(record))

    # Append to JSONL (summary only)
    jsonl_record = {
        "as_of_date": snap_date,
        "n_suppressed": record["suppression_summary"]["n_suppressed"],
        "suppression_rate": record["suppression_summary"]["suppression_rate"],
        "guard_status": record["suppression_summary"]["guard_status"],
        "suppressed_tickers": [s["ticker"] for s in record["suppressed"]],
        "reason_codes": [s["reason_code"] for s in record["suppressed"]],
        "fwd_status": record["forward_return"]["status"],
        "t5_due_date": record["forward_return"]["t5_due_date"],
        "delta": record["forward_return"]["delta"],
    }
    with open(DAILY_JSONL, "a") as f:
        f.write(json.dumps(jsonl_record, default=str) + "\n")

    # Pending forward record (only if PENDING)
    if record["forward_return"]["status"] == "PENDING":
        pending_json = PENDING_DIR / f"{snap_date}_pending_t5.json"
        pending = {
            "snap_date": snap_date,
            "t5_due_date": record["forward_return"]["t5_due_date"],
            "original_top30": record["original_top30"],
            "shadow_top30": record["shadow_top30"],
        }
        with open(pending_json, "w") as f:
            json.dump(pending, f, indent=2)


def _format_daily_md(record: dict) -> str:
    sd = record["as_of_date"]
    ss = record["suppression_summary"]
    fr = record["forward_return"]
    lines = [
        f"# Stressed Optionality Shadow — {sd}",
        "",
        f"> Classification: `{CLASSIFICATION}`",
        f"> Guard status: **{ss['guard_status']}**",
        "",
        "## Suppression Summary",
        "",
        f"- Names suppressed: **{ss['n_suppressed']} / {N_BASKET}** ({ss['suppression_rate']:.0%})",
        f"- Guard: {ss['guard_status']}",
        "",
    ]
    if record["suppressed"]:
        lines += [
            "| Ticker | Rank | Reason | fi_z | EES | Momentum | Replacement |",
            "|--------|-----:|--------|-----:|----:|---------:|-------------|",
        ]
        for s in record["suppressed"]:
            fi = f"{s['fi_z']:.3f}" if s["fi_z"] is not None else "N/A"
            ees = f"{s['ees']:.3f}" if s["ees"] is not None else "N/A"
            mom = f"{s['momentum']:.1f}" if s["momentum"] is not None else "N/A"
            repl = s["replacement_ticker"] or "—"
            lines.append(
                f"| {s['ticker']} | {s['original_rank']} | {s['reason_code']} | {fi} | {ees} | {mom} | {repl} |"
            )
        lines.append("")
    else:
        lines += ["*No suppressions.*", ""]

    lines += [
        "## Forward Return",
        "",
        f"- T+5 due date: {fr['t5_due_date'] or 'N/A'}",
        f"- Status: **{fr['status']}**",
    ]
    if fr["status"] == "OBSERVED":
        lines += [
            (
                f"- Original top-30: {fr['original_top30_return']:+.4f}"
                if fr["original_top30_return"] is not None
                else "- Original top-30: N/A"
            ),
            (
                f"- Shadow top-30:   {fr['shadow_top30_return']:+.4f}"
                if fr["shadow_top30_return"] is not None
                else "- Shadow top-30: N/A"
            ),
            f"- Delta:           {fr['delta']:+.4f}" if fr["delta"] is not None else "- Delta: N/A",
        ]
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fill pending forward returns
# ---------------------------------------------------------------------------


def fill_pending_forward(
    snap_date: str,
    write_output: bool = True,
    _prices: Optional[dict] = None,
    _trading_dates: Optional[list] = None,
) -> dict:
    """
    Attempt to fill T+5 forward returns for a previously-pending daily record.
    Updates the daily JSON in-place. Removes pending file if successful.
    """
    pending_path = PENDING_DIR / f"{snap_date}_pending_t5.json"
    daily_path = DAILY_DIR / f"{snap_date}_stressed_optionality_shadow.json"

    if not pending_path.exists():
        return {"snap_date": snap_date, "status": "NO_PENDING_RECORD"}
    if not daily_path.exists():
        return {"snap_date": snap_date, "status": "DAILY_RECORD_MISSING"}

    if _prices is None:
        _prices = load_price_history()
    if _trading_dates is None:
        _trading_dates = get_trading_dates(_prices)

    with open(pending_path) as f:
        pending = json.load(f)
    with open(daily_path) as f:
        daily = json.load(f)

    fwd_date = pending.get("t5_due_date")
    original_top30 = pending["original_top30"]
    shadow_top30 = pending["shadow_top30"]

    if fwd_date is None:
        return {"snap_date": snap_date, "status": "UNOBSERVABLE_NO_FWD_DATE"}

    has_fwd_prices = any(fwd_date in _prices.get(t, {}) for t in original_top30)
    if not has_fwd_prices:
        return {"snap_date": snap_date, "status": "PENDING_PRICES_NOT_YET_AVAILABLE", "t5_due_date": fwd_date}

    original_ret = compute_basket_return(original_top30, snap_date, fwd_date, _prices)
    shadow_ret = compute_basket_return(shadow_top30, snap_date, fwd_date, _prices)
    delta = (shadow_ret - original_ret) if (shadow_ret is not None and original_ret is not None) else None

    daily["forward_return"]["status"] = "OBSERVED"
    daily["forward_return"]["original_top30_return"] = original_ret
    daily["forward_return"]["shadow_top30_return"] = shadow_ret
    daily["forward_return"]["delta"] = delta

    if write_output:
        with open(daily_path, "w") as f:
            json.dump(daily, f, indent=2, default=str)
        # Rewrite the daily MD
        daily_md = DAILY_DIR / f"{snap_date}_stressed_optionality_shadow.md"
        with open(daily_md, "w") as f:
            f.write(_format_daily_md(daily))
        # Remove pending file
        pending_path.unlink()

    return {
        "snap_date": snap_date,
        "status": "FILLED",
        "t5_due_date": fwd_date,
        "original_top30_return": original_ret,
        "shadow_top30_return": shadow_ret,
        "delta": delta,
    }


def fill_all_pending(
    write_output: bool = True,
    _prices: Optional[dict] = None,
    _trading_dates: Optional[list] = None,
) -> list[dict]:
    """Scan pending_forward/ and attempt to fill all outstanding T+5 records."""
    if not PENDING_DIR.exists():
        return []
    if _prices is None:
        _prices = load_price_history()
    if _trading_dates is None:
        _trading_dates = get_trading_dates(_prices)

    results = []
    for pending_file in sorted(PENDING_DIR.glob("*_pending_t5.json")):
        snap_date = pending_file.stem.replace("_pending_t5", "")
        result = fill_pending_forward(
            snap_date, write_output=write_output, _prices=_prices, _trading_dates=_trading_dates
        )
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Weekly calibration memo
# ---------------------------------------------------------------------------


def run_weekly_memo(
    end_date: Optional[str] = None,
    n_days: int = 5,
    write_output: bool = True,
) -> dict:
    """
    Aggregate the last n_days daily records into a weekly calibration memo.
    Reads from DAILY_DIR. Does not modify daily records.
    """
    if not DAILY_DIR.exists():
        return {"error": "DAILY_DIR does not exist — run daily monitor first"}

    daily_files = sorted(DAILY_DIR.glob("*_stressed_optionality_shadow.json"), reverse=True)
    if end_date:
        daily_files = [f for f in daily_files if f.name[:10] <= end_date]

    loaded = []
    for f in daily_files[:n_days]:
        with open(f) as fh:
            loaded.append(json.load(fh))
    loaded = sorted(loaded, key=lambda r: r["as_of_date"])

    if not loaded:
        return {"error": "No daily records found"}

    window_start = loaded[0]["as_of_date"]
    window_end = loaded[-1]["as_of_date"]

    n_dates = len(loaded)
    suppression_counts = [r["suppression_summary"]["n_suppressed"] for r in loaded]
    guard_statuses = [r["suppression_summary"]["guard_status"] for r in loaded]

    # Reason code counts
    reason_counts: dict[str, int] = {}
    for r in loaded:
        for s in r.get("suppressed", []):
            rc = s.get("reason_code", "UNKNOWN")
            reason_counts[rc] = reason_counts.get(rc, 0) + 1

    # Observed T+5 outcomes
    observed = [r for r in loaded if r["forward_return"]["status"] == "OBSERVED"]
    pending = [r for r in loaded if r["forward_return"]["status"] == "PENDING"]
    deltas = [r["forward_return"]["delta"] for r in observed if r["forward_return"]["delta"] is not None]
    original_rets = [
        r["forward_return"]["original_top30_return"]
        for r in observed
        if r["forward_return"]["original_top30_return"] is not None
    ]
    shadow_rets = [
        r["forward_return"]["shadow_top30_return"]
        for r in observed
        if r["forward_return"]["shadow_top30_return"] is not None
    ]

    mean_delta = sum(deltas) / len(deltas) if deltas else None
    mean_original = sum(original_rets) / len(original_rets) if original_rets else None
    mean_shadow = sum(shadow_rets) / len(shadow_rets) if shadow_rets else None

    # Gate status
    n_observed = len(observed)
    if n_observed < 3:
        gate_status = "INSUFFICIENT_DATA"
    elif mean_delta is not None and mean_delta > 0:
        gate_status = "PROMISING"
    elif mean_delta is not None and mean_delta < -0.001:
        gate_status = "DEGRADED"
    else:
        gate_status = "NEUTRAL"

    n_review = sum(1 for g in guard_statuses if g == "REVIEW_REQUIRED")

    memo = {
        "schema": WEEKLY_SCHEMA,
        "classification": CLASSIFICATION,
        "window_start": window_start,
        "window_end": window_end,
        "n_dates": n_dates,
        "parameters": PARAMETERS,
        "suppression_stats": {
            "mean_suppressed_per_date": sum(suppression_counts) / n_dates if n_dates else None,
            "max_suppressed_per_date": max(suppression_counts) if suppression_counts else None,
            "n_dates_review_required": n_review,
            "reason_code_counts": reason_counts,
        },
        "forward_return_stats": {
            "n_observed": n_observed,
            "n_pending": len(pending),
            "mean_original_ret": mean_original,
            "mean_shadow_ret": mean_shadow,
            "mean_delta": mean_delta,
        },
        "gate_status": gate_status,
        "governance": GOVERNANCE,
    }

    if write_output:
        WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
        memo_date = end_date or window_end
        weekly_json = WEEKLY_DIR / f"{memo_date}_stressed_optionality_weekly_calibration.json"
        weekly_md = WEEKLY_DIR / f"{memo_date}_stressed_optionality_weekly_calibration.md"
        with open(weekly_json, "w") as f:
            json.dump(memo, f, indent=2, default=str)
        with open(weekly_md, "w") as f:
            f.write(_format_weekly_md(memo))

    return memo


def _format_weekly_md(memo: dict) -> str:
    sup = memo["suppression_stats"]
    fwd = memo["forward_return_stats"]
    lines = [
        f"# Stressed Optionality Weekly Calibration — {memo['window_end']}",
        "",
        f"> Classification: `{CLASSIFICATION}`",
        f"> Gate status: **{memo['gate_status']}**",
        f"> Window: {memo['window_start']} → {memo['window_end']} ({memo['n_dates']} dates)",
        "",
        "## Suppression Activity",
        "",
        "| Metric | Value |",
        "|--------|------:|",
    ]
    mspd = sup.get("mean_suppressed_per_date")
    lines.append(f"| Mean suppressed per date | {mspd:.1f} |" if mspd else "| Mean suppressed per date | N/A |")
    mxspd = sup.get("max_suppressed_per_date")
    lines.append(f"| Max suppressed in a day | {mxspd} |" if mxspd is not None else "| Max suppressed in a day | N/A |")
    lines.append(f"| Dates with REVIEW_REQUIRED | {sup['n_dates_review_required']} |")
    lines.append("")
    lines.append("**Reason codes:**")
    for rc, count in sorted(sup["reason_code_counts"].items(), key=lambda x: -x[1]):
        lines.append(f"- {rc}: {count}")
    lines += [
        "",
        "## Forward Return (T+5 outcomes)",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Dates observed | {fwd['n_observed']} / {memo['n_dates']} |",
        f"| Dates pending | {fwd['n_pending']} |",
    ]
    mo = fwd.get("mean_original_ret")
    lines.append(
        f"| Mean original top-30 ret | {mo:+.4f} |" if mo is not None else "| Mean original top-30 ret | N/A |"
    )
    ms = fwd.get("mean_shadow_ret")
    lines.append(f"| Mean shadow top-30 ret | {ms:+.4f} |" if ms is not None else "| Mean shadow top-30 ret | N/A |")
    md = fwd.get("mean_delta")
    lines.append(
        f"| **Mean delta (shadow − actual)** | **{md:+.4f}** |"
        if md is not None
        else "| Mean delta | N/A (no observed data yet) |"
    )
    lines += [
        "",
        f"## Gate Status: {memo['gate_status']}",
        "",
        "```",
        "PROMISING:            mean_delta > 0 with >= 3 observed outcomes",
        "NEUTRAL:              mean_delta near zero",
        "DEGRADED:             mean_delta < -0.001 with >= 3 outcomes",
        "INSUFFICIENT_DATA:    < 3 observed T+5 outcomes",
        "```",
        "",
        "**Note:** Do not tune rule parameters based on this memo. Parameters are locked.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_daily_cli(snap_date: str) -> None:
    print(f"Running stressed-optionality shadow monitor for {snap_date}...")
    model = load_ranker_v2_model()
    prices = load_price_history()
    trading_dates = get_trading_dates(prices)
    record = run_daily_shadow(snap_date, write_output=True, _model=model, _prices=prices, _trading_dates=trading_dates)
    if "error" in record:
        print(f"ERROR: {record['error']}")
        return
    ss = record["suppression_summary"]
    fr = record["forward_return"]
    print(f"  Suppressed: {ss['n_suppressed']} / {N_BASKET} ({ss['suppression_rate']:.0%})")
    print(f"  Guard: {ss['guard_status']}")
    for s in record["suppressed"]:
        repl = s["replacement_ticker"] or "—"
        print(f"    {s['ticker']:6} rank={s['original_rank']:2} [{s['reason_code']}] → {repl}")
    print(f"  Forward: {fr['status']} (T+5 due {fr['t5_due_date']})")
    print(f"  Output: {DAILY_DIR / (snap_date + '_stressed_optionality_shadow.json')}")


def _run_fill_forward_cli() -> None:
    print("Filling pending forward returns...")
    prices = load_price_history()
    trading_dates = get_trading_dates(prices)
    results = fill_all_pending(write_output=True, _prices=prices, _trading_dates=trading_dates)
    if not results:
        print("  No pending records found.")
        return
    for r in results:
        print(f"  {r['snap_date']}: {r['status']}", end="")
        if r["status"] == "FILLED" and r.get("delta") is not None:
            print(f" (delta={r['delta']:+.4f})", end="")
        print()


def _run_weekly_cli(end_date: Optional[str] = None) -> None:
    print(f"Generating weekly calibration memo{f' through {end_date}' if end_date else ''}...")
    memo = run_weekly_memo(end_date=end_date, write_output=True)
    if "error" in memo:
        print(f"ERROR: {memo['error']}")
        return
    print(f"  Window: {memo['window_start']} → {memo['window_end']} ({memo['n_dates']} dates)")
    print(f"  Gate status: {memo['gate_status']}")
    fwd = memo["forward_return_stats"]
    if fwd["mean_delta"] is not None:
        print(f"  Mean delta: {fwd['mean_delta']:+.4f}")
    else:
        print(f"  Mean delta: N/A ({fwd['n_observed']} observed, {fwd['n_pending']} pending)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stressed optionality forward shadow monitor")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="Run daily shadow for YYYY-MM-DD")
    group.add_argument("--fill-forward", action="store_true", help="Fill pending T+5 records")
    group.add_argument("--weekly", action="store_true", help="Generate weekly calibration memo")
    parser.add_argument("--end-date", help="End date for weekly memo (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.date:
        _run_daily_cli(args.date)
    elif args.fill_forward:
        _run_fill_forward_cli()
    elif args.weekly:
        _run_weekly_cli(args.end_date)
