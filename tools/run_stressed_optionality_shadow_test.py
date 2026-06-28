"""
STRESSED_OPTIONALITY_CONFIRMATION_SHADOW_TEST_NO_MODEL_CHANGE

Test a shadow guardrail rule that requires recoverability confirmation before
promoting financially-stressed names. Distinguishes recoverable stress (SYRE) from
unconfirmed stress (DRUG, CELC, ABVX).

Two suppression paths — parameters are explicit constants, not tuned post-hoc:

  Path 1 (EES-flagged):
    If financial_stress is primary rank driver AND ees_v3_score <= EES_SUPPRESS_THRESHOLD
    → SUPPRESSED_EES_FLAGGED

  Path 2 (extreme stress unconfirmed):
    If financial_stress is primary rank driver AND fi_z <= EXTREME_STRESS_FI_Z_THRESHOLD
    AND NOT (ees_v3 > 0 AND momentum >= MOMENTUM_CONFIRM_THRESHOLD)
    → SUPPRESSED_EXTREME_STRESS_UNCONFIRMED

Governance (HARD — do not remove):
  NO_MODEL_CHANGE  NO_RANKER_CHANGE  NO_SELECTOR_CHANGE  NO_SIZING_CHANGE
  NO_REGIME_CHANGE  NO_PRODUCTION_WIRING  NO_CRON

Output: artifacts/autopsy/stressed_optionality_shadow_test/
"""

from __future__ import annotations

import copy
import csv
import json
import math
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_v2_pairwise import RankerV2Config, filter_cohort, model_from_dict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLASSIFICATION = "STRESSED_OPTIONALITY_CONFIRMATION_SHADOW_TEST_NO_MODEL_CHANGE"

# Rule parameters — explicit, not tuned
EES_SUPPRESS_THRESHOLD: float = -0.75
EXTREME_STRESS_FI_Z_THRESHOLD: float = -1.0
MOMENTUM_CONFIRM_THRESHOLD: float = 60.0

PHASE3_DATES = {
    "2026-05-18",
    "2026-05-19",
    "2026-05-20",
    "2026-05-21",
    "2026-05-22",
    "2026-05-26",
    "2026-05-27",
    "2026-05-28",
    "2026-05-29",
    "2026-06-01",
    "2026-06-02",
    "2026-06-03",
    "2026-06-04",
    "2026-06-05",
    "2026-06-08",
    "2026-06-09",
}

# Names that should NOT be suppressed (winners from component attribution)
EXPECTED_PASS_THROUGH = {"TNGX", "ALKS", "SYRE"}
# Names that should be suppressed (losers with clear failure modes)
EXPECTED_SUPPRESSED = {"CELC", "DRUG", "ABVX"}

PRODUCTION_RANKER_V2_CONFIG = RankerV2Config(feature_set="minimal_v2")

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
BACKTEST_CSV = PROJECT_ROOT / "artifacts" / "surveillance" / "pit_backtest_5d_ytd_2026.csv"
PRICE_HISTORY_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
RANKER_V2_MODEL_JSON = PROJECT_ROOT / "production_data" / "ranker_v2_model.json"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "autopsy" / "stressed_optionality_shadow_test"
OUTPUT_JSON = OUTPUT_DIR / "stressed_optionality_shadow_test.json"
OUTPUT_MD = OUTPUT_DIR / "STRESSED_OPTIONALITY_SHADOW_TEST.md"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_ranker_v2_model():
    with open(RANKER_V2_MODEL_JSON) as f:
        artifact = json.load(f)
    return model_from_dict(artifact["model"])


def load_ytd_dates() -> list[str]:
    """Load YTD snapshot dates from backtest CSV (authoritative non-v1.3 list)."""
    dates = []
    with open(BACKTEST_CSV) as f:
        for row in csv.DictReader(f):
            snap = row.get("snap_date", "").strip()
            if snap and snap not in dates:
                dates.append(snap)
    return sorted(dates)


def load_canonical_rankings(snap_date: str) -> list[dict]:
    path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    with open(path) as f:
        return list(csv.DictReader(f))


def load_price_history() -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = {}
    with open(PRICE_HISTORY_CSV) as f:
        for row in csv.DictReader(f):
            try:
                prices.setdefault(row["ticker"], {})[row["date"]] = float(row["close"])
            except (ValueError, KeyError):
                pass
    return prices


def get_trading_dates(prices: dict) -> list[str]:
    dates: set[str] = set()
    for td in prices.values():
        dates.update(td.keys())
    return sorted(dates)


def get_fwd_date(snap_date: str, trading_dates: list[str], n: int = 5) -> Optional[str]:
    try:
        idx = trading_dates.index(snap_date)
        return trading_dates[idx + n] if idx + n < len(trading_dates) else None
    except ValueError:
        return None


def compute_basket_return(tickers: list[str], snap_date: str, fwd_date: Optional[str], prices: dict) -> Optional[float]:
    if fwd_date is None or not tickers:
        return None
    returns = []
    for ticker in tickers:
        p0 = prices.get(ticker, {}).get(snap_date)
        p1 = prices.get(ticker, {}).get(fwd_date)
        if p0 and p1:
            returns.append((p1 - p0) / p0)
    return sum(returns) / len(returns) if returns else None


# ---------------------------------------------------------------------------
# Cohort statistics
# ---------------------------------------------------------------------------


def _cohort_stats(cohort: list[dict]) -> dict:
    def _stats(vals):
        n = len(vals)
        if n == 0:
            return 0.0, 1.0
        mu = sum(vals) / n
        std = math.sqrt(sum((x - mu) ** 2 for x in vals) / n) or 1.0
        return mu, std

    ci_vals = [float(r.get("coinvest_score_z") or 0) for r in cohort]
    fi_vals = [float(r.get("financial_score") or 0) for r in cohort]
    ci_mean, ci_std = _stats(ci_vals)
    fi_mean, fi_std = _stats(fi_vals)
    return {"ci_mean": ci_mean, "ci_std": ci_std, "fi_mean": fi_mean, "fi_std": fi_std, "n": len(cohort)}


def _float_or_none(row: dict, key: str) -> Optional[float]:
    val = row.get(key, "")
    if val in ("", "None", "nan", None):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Shadow rule
# ---------------------------------------------------------------------------


def apply_shadow_rule(row: dict, stats: dict, model) -> dict:
    """
    Apply the two-path suppression rule to a single top-30 row.

    Returns dict with keys:
      shadow_status: ELIGIBLE | SUPPRESSED
      suppression_type: EES_FLAGGED | EXTREME_STRESS_UNCONFIRMED | None
      rule_path: path1_ees | path2_extreme_stress | none
      ci_z, fi_z, fi_contrib, ci_contrib
      is_financial_primary
      reason: explanation string
    """
    ticker = row.get("ticker", "?")

    ci_raw = float(row.get("coinvest_score_z") or 0)
    fi_raw = float(row.get("financial_score") or 0)
    ees = _float_or_none(row, "ees_v3_score")
    momentum = _float_or_none(row, "momentum_score")

    ci_z = (ci_raw - stats["ci_mean"]) / stats["ci_std"]
    fi_z = (fi_raw - stats["fi_mean"]) / stats["fi_std"]
    ci_contrib = model.weights[0] * ci_z
    fi_contrib = model.weights[1] * fi_z
    is_financial_primary = abs(fi_contrib) >= abs(ci_contrib)

    base = {
        "ticker": ticker,
        "ci_z": ci_z,
        "fi_z": fi_z,
        "ci_contrib": ci_contrib,
        "fi_contrib": fi_contrib,
        "is_financial_primary": is_financial_primary,
        "ees_v3_score": ees,
        "momentum_score": momentum,
    }

    # Only apply rules to financially-primary names
    if not is_financial_primary:
        return {
            **base,
            "shadow_status": "ELIGIBLE",
            "suppression_type": None,
            "rule_path": "none",
            "reason": "coinvest_signal is primary driver — no suppression",
        }

    # Path 1: EES-flagged (requires ees_v3 data)
    if ees is not None and ees <= EES_SUPPRESS_THRESHOLD:
        return {
            **base,
            "shadow_status": "SUPPRESSED",
            "suppression_type": "EES_FLAGGED",
            "rule_path": "path1_ees",
            "reason": (f"ees_v3={ees:.3f} <= {EES_SUPPRESS_THRESHOLD}; " f"financial_stress primary (fi_z={fi_z:.3f})"),
        }

    # Path 2: Extreme stress — require EES > 0 AND momentum >= threshold
    if fi_z <= EXTREME_STRESS_FI_Z_THRESHOLD:
        # ees_ok: benefit of doubt for missing data; only fail if present and <= 0
        ees_ok = (ees is None) or (ees > 0)
        momentum_ok = (momentum is not None) and (momentum >= MOMENTUM_CONFIRM_THRESHOLD)
        if not (ees_ok and momentum_ok):
            missing = []
            if not ees_ok:
                missing.append(f"ees_v3={ees:.3f} (need >0)")
            if not momentum_ok:
                m_str = f"{momentum:.1f}" if momentum is not None else "N/A"
                missing.append(f"momentum={m_str} (need >={MOMENTUM_CONFIRM_THRESHOLD})")
            return {
                **base,
                "shadow_status": "SUPPRESSED",
                "suppression_type": "EXTREME_STRESS_UNCONFIRMED",
                "rule_path": "path2_extreme_stress",
                "reason": f"fi_z={fi_z:.3f} <= {EXTREME_STRESS_FI_Z_THRESHOLD}; "
                f"missing confirmation: {', '.join(missing)}",
            }

    return {
        **base,
        "shadow_status": "ELIGIBLE",
        "suppression_type": None,
        "rule_path": "none",
        "reason": f"financial_primary but passes all gates (fi_z={fi_z:.3f})",
    }


# ---------------------------------------------------------------------------
# Shadow basket construction
# ---------------------------------------------------------------------------


def build_shadow_basket(rows: list[dict], shadow_by_ticker: dict, n: int = 30) -> list[str]:
    """
    Build shadow-eligible top-N basket.
    Replace suppressed names with next-ranked eligible names.
    Rows sorted by actionable_rank ascending.
    """

    def _rank(r):
        try:
            return int(r.get("actionable_rank") or 9999)
        except ValueError:
            return 9999

    sorted_rows = sorted(rows, key=_rank)
    basket = []
    for r in sorted_rows:
        ticker = r["ticker"]
        sr = shadow_by_ticker.get(ticker, {})
        status = sr.get("shadow_status", "ELIGIBLE")
        if status == "ELIGIBLE":
            basket.append(ticker)
        if len(basket) == n:
            break
    return basket


# ---------------------------------------------------------------------------
# Per-date analysis
# ---------------------------------------------------------------------------


def run_shadow_test_date(
    snap_date: str,
    rows: list[dict],
    model,
    prices: dict,
    trading_dates: list[str],
    brow: Optional[dict],
) -> dict:
    """Full shadow test for one snapshot date."""
    cohort = filter_cohort(copy.deepcopy(rows), PRODUCTION_RANKER_V2_CONFIG)
    stats = _cohort_stats(cohort)
    fwd_date = get_fwd_date(snap_date, trading_dates)

    # Get top-30 by actionable_rank
    def _rank(r):
        try:
            return int(r.get("actionable_rank") or 9999)
        except ValueError:
            return 9999

    top30_rows = [r for r in sorted(rows, key=_rank) if _rank(r) <= 30]
    top30_tickers = [r["ticker"] for r in top30_rows]

    # Apply shadow rule to each top-30 name
    shadow_results = {}
    for r in top30_rows:
        sr = apply_shadow_rule(r, stats, model)
        shadow_results[r["ticker"]] = sr

    # Also apply to ranks 31–60 (needed for replacement basket)
    extension_rows = [r for r in sorted(rows, key=_rank) if 30 < _rank(r) <= 60]
    for r in extension_rows:
        sr = apply_shadow_rule(r, stats, model)
        shadow_results[r["ticker"]] = sr

    # Count suppressions in top-30
    n_suppressed = sum(1 for t in top30_tickers if shadow_results.get(t, {}).get("shadow_status") == "SUPPRESSED")

    # Check expected pass-throughs
    pass_through_violations = [
        t
        for t in EXPECTED_PASS_THROUGH
        if t in shadow_results and shadow_results[t].get("shadow_status") == "SUPPRESSED"
    ]

    # Build shadow basket
    shadow_basket = build_shadow_basket(rows, shadow_results, n=30)

    # Returns
    actual_ret = compute_basket_return(top30_tickers, snap_date, fwd_date, prices)
    shadow_ret = compute_basket_return(shadow_basket, snap_date, fwd_date, prices)

    # Backtest IC (from CSV if available)
    bt_ic = float(brow["ic_5d"]) if brow and brow.get("ic_5d") not in ("", None) else None

    # Target name shadow statuses
    target_statuses = {
        t: shadow_results[t].get("shadow_status", "NOT_IN_TOP30")
        for t in EXPECTED_PASS_THROUGH | EXPECTED_SUPPRESSED
        if t in shadow_results
    }

    return {
        "snap_date": snap_date,
        "is_phase3": snap_date in PHASE3_DATES,
        "fwd_date": fwd_date,
        "n_suppressed_in_top30": n_suppressed,
        "suppressed_tickers": [
            t for t in top30_tickers if shadow_results.get(t, {}).get("shadow_status") == "SUPPRESSED"
        ],
        "pass_through_violations": pass_through_violations,
        "actual_top30": top30_tickers,
        "shadow_top30": shadow_basket,
        "actual_basket_ret": actual_ret,
        "shadow_basket_ret": shadow_ret,
        "backtest_ic_5d": bt_ic,
        "target_statuses": target_statuses,
        "shadow_detail": {
            t: {
                "shadow_status": shadow_results[t].get("shadow_status"),
                "suppression_type": shadow_results[t].get("suppression_type"),
                "fi_z": shadow_results[t].get("fi_z"),
                "ees_v3_score": shadow_results[t].get("ees_v3_score"),
                "reason": shadow_results[t].get("reason"),
            }
            for t in top30_tickers
        },
    }


# ---------------------------------------------------------------------------
# Aggregate helpers
# ---------------------------------------------------------------------------


def _mean(vals: list) -> Optional[float]:
    valid = [v for v in vals if v is not None]
    return sum(valid) / len(valid) if valid else None


def _aggregate_window(date_results: list[dict]) -> dict:
    n = len(date_results)
    suppressed_counts = [d["n_suppressed_in_top30"] for d in date_results]
    actual_rets = [d["actual_basket_ret"] for d in date_results]
    shadow_rets = [d["shadow_basket_ret"] for d in date_results]
    violations = [v for d in date_results for v in d["pass_through_violations"]]

    mean_actual = _mean(actual_rets)
    mean_shadow = _mean(shadow_rets)
    improvement = (mean_shadow - mean_actual) if (mean_shadow is not None and mean_actual is not None) else None

    return {
        "n_dates": n,
        "n_dates_with_suppression": sum(1 for c in suppressed_counts if c > 0),
        "mean_suppressed_per_date": _mean(suppressed_counts),
        "mean_actual_basket_ret": mean_actual,
        "mean_shadow_basket_ret": mean_shadow,
        "mean_basket_improvement": improvement,
        "pass_through_violations": violations,
        "n_pass_through_violations": len(violations),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_shadow_test(write_output: bool = True) -> dict:
    model = load_ranker_v2_model()
    prices = load_price_history()
    trading_dates = get_trading_dates(prices)
    ytd_dates = load_ytd_dates()

    # Load backtest CSV for IC reference
    backtest_by_date: dict[str, dict] = {}
    with open(BACKTEST_CSV) as f:
        for row in csv.DictReader(f):
            backtest_by_date[row["snap_date"]] = row

    date_results: list[dict] = []
    for snap_date in ytd_dates:
        path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
        if not path.exists():
            continue
        rows = load_canonical_rankings(snap_date)
        brow = backtest_by_date.get(snap_date)
        result = run_shadow_test_date(snap_date, rows, model, prices, trading_dates, brow)
        date_results.append(result)

    phase3_results = [d for d in date_results if d["is_phase3"]]
    non_phase3_results = [d for d in date_results if not d["is_phase3"]]

    phase3_agg = _aggregate_window(phase3_results)
    non_phase3_agg = _aggregate_window(non_phase3_results)
    ytd_agg = _aggregate_window(date_results)

    # Per-target summary across Phase 3
    target_phase3_summary: dict[str, dict] = {}
    for ticker in EXPECTED_PASS_THROUGH | EXPECTED_SUPPRESSED:
        appearances = sum(1 for d in phase3_results if ticker in d["target_statuses"])
        suppressions = sum(1 for d in phase3_results if d["target_statuses"].get(ticker) == "SUPPRESSED")
        target_phase3_summary[ticker] = {
            "n_appearances": appearances,
            "n_suppressed": suppressions,
            "suppression_rate": suppressions / appearances if appearances else 0.0,
            "expected": "SUPPRESSED" if ticker in EXPECTED_SUPPRESSED else "ELIGIBLE",
        }

    # Verdict
    p3_improved = phase3_agg["mean_basket_improvement"] is not None and phase3_agg["mean_basket_improvement"] > 0
    no_winner_violations = (
        non_phase3_agg["n_pass_through_violations"] == 0 and phase3_agg["n_pass_through_violations"] == 0
    )
    expected_suppressions_correct = all(
        target_phase3_summary.get(t, {}).get("n_suppressed", 0) > 0 for t in EXPECTED_SUPPRESSED
    )

    if p3_improved and no_winner_violations and expected_suppressions_correct:
        verdict = "SHADOW_GUARDRAIL_IMPROVES_PHASE3_WITHOUT_WINNER_DEGRADATION"
    elif not expected_suppressions_correct:
        verdict = "SHADOW_RULE_MISSED_TARGET_LOSERS"
    elif not p3_improved:
        verdict = "SHADOW_RULE_DID_NOT_IMPROVE_PHASE3_BASKET"
    elif not no_winner_violations:
        verdict = "SHADOW_RULE_SUPPRESSED_EXPECTED_WINNERS"
    else:
        verdict = "PARTIAL"

    result = {
        "classification": CLASSIFICATION,
        "schema": "stressed_optionality_shadow_test_v1",
        "governance": {
            "model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "regime_change": False,
            "production_wiring": False,
            "canonical_snapshots_modified": False,
            "cron": False,
        },
        "rule_parameters": {
            "ees_suppress_threshold": EES_SUPPRESS_THRESHOLD,
            "extreme_stress_fi_z_threshold": EXTREME_STRESS_FI_Z_THRESHOLD,
            "momentum_confirm_threshold": MOMENTUM_CONFIRM_THRESHOLD,
        },
        "window": {
            "n_ytd_dates": len(date_results),
            "n_phase3_dates": len(phase3_results),
            "n_non_phase3_dates": len(non_phase3_results),
        },
        "verdict": verdict,
        "phase3": phase3_agg,
        "non_phase3": non_phase3_agg,
        "ytd": ytd_agg,
        "target_phase3_summary": target_phase3_summary,
        "detail": date_results,
    }

    if write_output:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        # Write detail-free summary JSON (detail is large)
        summary = {k: v for k, v in result.items() if k != "detail"}
        with open(OUTPUT_JSON, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        # Write per-date detail
        detail_json = OUTPUT_DIR / "shadow_test_detail.json"
        with open(detail_json, "w") as f:
            json.dump(result["detail"], f, indent=2, default=str)
        _write_memo(result)

    return result


def _write_memo(results: dict) -> None:
    p3 = results["phase3"]
    np3 = results["non_phase3"]
    ytd = results["ytd"]
    ts = results["target_phase3_summary"]
    rp = results["rule_parameters"]

    lines = [
        "# Stressed Optionality Confirmation Shadow Test",
        "",
        f"> Classification: `{CLASSIFICATION}`",
        "> Date: 2026-06-26",
        "> Scope: Shadow guardrail only. No model, ranker, selector, or production change.",
        "",
        "---",
        "",
        "## Rule Definition",
        "",
        "```",
        "If financial_stress is primary rank driver (|fi_contrib| >= |ci_contrib|):",
        "",
        "  Path 1 — EES-flagged suppression:",
        f"    if ees_v3_score <= {rp['ees_suppress_threshold']}",
        "    → SUPPRESSED_EES_FLAGGED",
        "",
        "  Path 2 — Extreme stress unconfirmed:",
        f"    if fi_z <= {rp['extreme_stress_fi_z_threshold']}",
        f"    AND NOT (ees_v3 > 0 AND momentum >= {rp['momentum_confirm_threshold']})",
        "    → SUPPRESSED_EXTREME_STRESS_UNCONFIRMED",
        "",
        "Otherwise: ELIGIBLE",
        "```",
        "",
        "---",
        "",
        "## Phase 3 Results",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Dates tested | {p3['n_dates']} |",
        f"| Dates with ≥1 suppression | {p3['n_dates_with_suppression']} |",
    ]

    mean_s = p3.get("mean_suppressed_per_date")
    lines.append(f"| Mean suppressions per date | {mean_s:.2f} |" if mean_s else "| Mean suppressions per date | N/A |")

    act = p3.get("mean_actual_basket_ret")
    lines.append(f"| Actual mean basket ret | {act:+.4f} |" if act is not None else "| Actual mean basket ret | N/A |")

    shd = p3.get("mean_shadow_basket_ret")
    lines.append(f"| Shadow mean basket ret | {shd:+.4f} |" if shd is not None else "| Shadow mean basket ret | N/A |")

    imp = p3.get("mean_basket_improvement")
    lines.append(f"| **Improvement** | **{imp:+.4f}** |" if imp is not None else "| **Improvement** | N/A |")

    lines += [
        f"| Pass-through violations | {p3['n_pass_through_violations']} |",
        "",
        "### Phase 3 Target Suppression",
        "",
        "| Ticker | Role | Appearances | Suppressed | Rate | Expected |",
        "|--------|------|------------:|-----------:|-----:|---------|",
    ]

    for ticker in sorted(ts.keys()):
        t = ts[ticker]
        role = "loser" if ticker in EXPECTED_SUPPRESSED else "winner"
        rate = f"{t['suppression_rate']:.0%}"
        lines.append(f"| {ticker} | {role} | {t['n_appearances']} | {t['n_suppressed']} | {rate} | {t['expected']} |")

    lines += [
        "",
        "---",
        "",
        "## Non-Phase-3 (YTD Clean) Results",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Dates tested | {np3['n_dates']} |",
        f"| Dates with ≥1 suppression | {np3['n_dates_with_suppression']} |",
    ]

    mean_s2 = np3.get("mean_suppressed_per_date")
    lines.append(
        f"| Mean suppressions per date | {mean_s2:.2f} |" if mean_s2 else "| Mean suppressions per date | N/A |"
    )

    act2 = np3.get("mean_actual_basket_ret")
    lines.append(
        f"| Actual mean basket ret | {act2:+.4f} |" if act2 is not None else "| Actual mean basket ret | N/A |"
    )

    shd2 = np3.get("mean_shadow_basket_ret")
    lines.append(
        f"| Shadow mean basket ret | {shd2:+.4f} |" if shd2 is not None else "| Shadow mean basket ret | N/A |"
    )

    imp2 = np3.get("mean_basket_improvement")
    lines.append(f"| Basket improvement | {imp2:+.4f} |" if imp2 is not None else "| Basket improvement | N/A |")

    lines += [
        f"| Pass-through violations (TNGX/ALKS/SYRE) | **{np3['n_pass_through_violations']}** |",
        "",
        "---",
        "",
        "## YTD Summary",
        "",
        "| Window | Mean actual ret | Mean shadow ret | Improvement |",
        "|--------|----------------:|----------------:|------------:|",
    ]

    def _fmt(v):
        return f"{v:+.4f}" if v is not None else "N/A"

    lines.append(
        f"| Phase 3 | {_fmt(p3.get('mean_actual_basket_ret'))} | {_fmt(p3.get('mean_shadow_basket_ret'))} | {_fmt(p3.get('mean_basket_improvement'))} |"
    )
    lines.append(
        f"| Non-Phase-3 | {_fmt(np3.get('mean_actual_basket_ret'))} | {_fmt(np3.get('mean_shadow_basket_ret'))} | {_fmt(np3.get('mean_basket_improvement'))} |"
    )
    lines.append(
        f"| YTD | {_fmt(ytd.get('mean_actual_basket_ret'))} | {_fmt(ytd.get('mean_shadow_basket_ret'))} | {_fmt(ytd.get('mean_basket_improvement'))} |"
    )

    lines += [
        "",
        "---",
        "",
        "## Verdict",
        "",
        f"**`{results['verdict']}`**",
        "",
        "---",
        "",
        "## Governance Verdict",
        "",
        "```",
        f"Classification:     {CLASSIFICATION}",
        "Model change:       NO",
        "Ranker change:      NO",
        "Production wiring:  NO (shadow-only output)",
        "",
        f"Rule parameters:    EES_SUPPRESS={rp['ees_suppress_threshold']}",
        f"                    EXTREME_STRESS_FI_Z={rp['extreme_stress_fi_z_threshold']}",
        f"                    MOMENTUM_CONFIRM={rp['momentum_confirm_threshold']}",
        "```",
        "",
    ]

    with open(OUTPUT_MD, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = run_shadow_test(write_output=True)
    print(f"Classification: {results['classification']}")
    print(f"Verdict: {results['verdict']}")
    print()
    print(f"Phase 3 ({results['phase3']['n_dates']} dates):")
    print(f"  Actual mean ret:   {results['phase3'].get('mean_actual_basket_ret'):+.4f}")
    print(f"  Shadow mean ret:   {results['phase3'].get('mean_shadow_basket_ret'):+.4f}")
    imp = results["phase3"].get("mean_basket_improvement")
    print(f"  Improvement:       {imp:+.4f}" if imp is not None else "  Improvement: N/A")
    print(f"  Pass-thru violations: {results['phase3']['n_pass_through_violations']}")
    print()
    print(f"Non-Phase-3 ({results['non_phase3']['n_dates']} dates):")
    print(f"  Actual mean ret:   {results['non_phase3'].get('mean_actual_basket_ret'):+.4f}")
    print(f"  Shadow mean ret:   {results['non_phase3'].get('mean_shadow_basket_ret'):+.4f}")
    imp2 = results["non_phase3"].get("mean_basket_improvement")
    print(f"  Improvement:       {imp2:+.4f}" if imp2 is not None else "  Improvement: N/A")
    print(f"  Pass-thru violations: {results['non_phase3']['n_pass_through_violations']}")
    print()
    print("Target Phase 3 suppression:")
    for ticker, t in sorted(results["target_phase3_summary"].items()):
        role = "loser" if ticker in EXPECTED_SUPPRESSED else "winner"
        print(
            f"  {ticker:6} ({role:6}) {t['n_suppressed']:2}/{t['n_appearances']:2} suppressed  expected={t['expected']}"
        )
