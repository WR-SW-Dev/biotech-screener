"""
EES v3 Veto Autopsy Ledger

Analyzes the HL bucket (ranker-selected names that veto_core would have removed)
across all PIT snapshots to classify failure modes and validate the veto hypothesis.

For each historical HL name:
- Fetches forward returns at 21d/42d/63d
- Classifies the veto as TRUE_NEGATIVE (veto correct) or FALSE_NEGATIVE (veto wrong)
- Assigns a primary failure mode

GOVERNANCE: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON
LEAD_HYPOTHESIS: VETO_CORE | STATUS: DIAGNOSTIC_ONLY
"""

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

GOVERNANCE = "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON"
SNAP_DIR = "data/snapshots_pit_v2"
PRICE_HISTORY = "production_data/price_history.csv"
OUTPUT_JSON = "artifacts/research/ees_v3_veto_autopsy_2026_06_25.json"
OUTPUT_MD = "artifacts/readiness/EES_V3_VETO_AUTOPSY_2026_06_25.md"

HORIZONS = [21, 42, 63]
PRIMARY_HORIZON = 63
QUINTILE_PCT = 20
EARLY_END = "2024-08-31"
LATE_START = "2024-09-30"


# ─── helpers ─────────────────────────────────────────────────────────────────


def _safe_float(v, default=None):
    if v is None or v == "" or v in ("None", "nan", "NaN"):
        return default
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return default


def _has_priced_move(row):
    val = row.get("priced_move_pct", "")
    if not val or val in ("None", "nan", "NaN", "0", "0.0", ""):
        return False
    try:
        f = float(val)
        return not math.isnan(f) and f != 0.0
    except (ValueError, TypeError):
        return False


def _top_q_threshold(values, pct):
    vals = sorted([v for v in values if v is not None], reverse=True)
    n = max(1, int(len(vals) * pct / 100))
    return vals[n - 1] if vals else 0.0


def _bottom_q_threshold(values, pct):
    vals = sorted([v for v in values if v is not None])
    n = max(1, int(len(vals) * pct / 100))
    return vals[n - 1] if vals else 0.0


def _median(values):
    vals = sorted([v for v in values if v is not None])
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2 == 0:
        return (vals[mid - 1] + vals[mid]) / 2
    return vals[mid]


def _next_trading_date(base_date, n, sorted_dates):
    idx = None
    for i, d in enumerate(sorted_dates):
        if d >= base_date:
            idx = i
            break
    if idx is None:
        return None
    target = idx + n
    return sorted_dates[target] if target < len(sorted_dates) else None


# ─── price loading ────────────────────────────────────────────────────────────


def load_prices():
    prices = defaultdict(dict)
    with open(PRICE_HISTORY) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row["ticker"]
            date = row["date"]
            close = _safe_float(row.get("close"))
            if close is not None:
                prices[ticker][date] = close
    print(f"Loaded prices for {len(prices)} tickers", file=sys.stderr)
    return prices


def compute_forward_return(ticker, snap_date, horizon, prices, sorted_dates):
    tp = prices.get(ticker, {})
    anchor = tp.get(snap_date) or next(
        (tp[d] for d in reversed(sorted_dates) if d <= snap_date and d in tp),
        None,
    )
    if anchor is None or anchor == 0:
        return None
    fwd_date = _next_trading_date(snap_date, horizon, sorted_dates)
    if fwd_date is None:
        return None
    fwd = tp.get(fwd_date)
    if fwd is None:
        return None
    return (fwd - anchor) / anchor


def compute_excess_return(ticker, snap_date, horizon, prices, sorted_dates):
    ret = compute_forward_return(ticker, snap_date, horizon, prices, sorted_dates)
    if ret is None:
        return None
    xbi_ret = compute_forward_return("XBI", snap_date, horizon, prices, sorted_dates)
    if xbi_ret is None:
        return None
    return ret - xbi_ret


# ─── PIT snapshot loading ─────────────────────────────────────────────────────


def load_pit_snapshots():
    snapshots = []
    dates = sorted(os.listdir(SNAP_DIR))
    for d in dates:
        path = os.path.join(SNAP_DIR, d, "rankings.csv")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            rows = list(csv.DictReader(f))
        snapshots.append((d, rows))
    print(f"Loaded {len(snapshots)} PIT snapshots", file=sys.stderr)
    return snapshots


# ─── failure mode classification ─────────────────────────────────────────────


def classify_failure_mode(row, forward_ret_63):
    """
    Classify why EES v3 was skeptical of this name.
    Returns (primary_mode, secondary_modes).
    """
    misprice = _safe_float(row.get("conditional_misprice_score"))
    expected_move = _safe_float(row.get("conditional_expected_move"))
    priced = _has_priced_move(row)
    financing = _safe_float(row.get("financing_truth_gate"), default=1.0)
    dilution = _safe_float(row.get("dilution_haircut"), default=0.0)
    catalyst_days = _safe_float(row.get("catalyst_days"))
    crowding = row.get("crowding_level", "")
    adv = _safe_float(row.get("adv_20d")) or _safe_float(row.get("median_dollar_volume_20d"))

    modes = []

    # Market already priced: priced_move available AND misprice score is negative
    # (market paid MORE than the event is worth, so EES v3 sees it as a bad trade)
    if priced and misprice is not None and misprice < -0.1:
        modes.append("market_already_priced")

    # Weak expected move: the options market has low IV premium
    if expected_move is not None and expected_move < 8.0:
        modes.append("weak_expected_move")

    # No coverage: no priced move data to compute misprice
    if not priced and misprice is not None and abs(misprice) < 0.05:
        modes.append("no_options_coverage")

    # Financing / dilution overhang
    if financing is not None and financing < 0.5:
        modes.append("financing_overhang")
    elif dilution is not None and dilution > 0.25:
        modes.append("dilution_overhang")

    # Catalyst timing issues: very far out (> 180d) or too close (< 5d)
    if catalyst_days is not None:
        if catalyst_days > 180:
            modes.append("catalyst_too_far")
        elif catalyst_days < 5 and catalyst_days >= 0:
            modes.append("catalyst_too_close")

    # Crowded mechanism
    if crowding and crowding.lower() in ("high", "very_high"):
        modes.append("crowded_mechanism")

    # Liquidity trap: tiny ADV
    if adv is not None and adv < 1.0:
        modes.append("liquidity_trap")

    # Stale/delisted: forward return unavailable
    if forward_ret_63 is None:
        modes.append("stale_or_delisted")

    # Assign primary
    priority = [
        "stale_or_delisted",
        "financing_overhang",
        "dilution_overhang",
        "market_already_priced",
        "weak_expected_move",
        "no_options_coverage",
        "catalyst_too_far",
        "catalyst_too_close",
        "liquidity_trap",
        "crowded_mechanism",
    ]
    primary = next((m for m in priority if m in modes), "other_unknown")
    secondary = [m for m in modes if m != primary]

    return primary, secondary


def classify_veto_verdict(excess_63):
    """
    TRUE_NEGATIVE: veto was correct (name underperformed XBI)
    FALSE_NEGATIVE: veto was wrong (name outperformed XBI)
    INCONCLUSIVE: no data
    """
    if excess_63 is None:
        return "INCONCLUSIVE"
    return "TRUE_NEGATIVE" if excess_63 < 0 else "FALSE_NEGATIVE"


# ─── main analysis ────────────────────────────────────────────────────────────


def build_hl_ledger(snapshots, prices, sorted_dates):
    ledger = []
    for snap_date, rows in snapshots:
        # Compute quintile thresholds
        fs_vals = [_safe_float(r.get("final_score")) for r in rows]
        v3_vals = [_safe_float(r.get("ees_v3_score")) for r in rows]

        fs_top_q = _top_q_threshold(fs_vals, QUINTILE_PCT)
        v3_bottom_q = _bottom_q_threshold(v3_vals, QUINTILE_PCT)

        for row in rows:
            ticker = row.get("ticker", "")
            fs = _safe_float(row.get("final_score"))
            v3 = _safe_float(row.get("ees_v3_score"))

            if fs is None or v3 is None:
                continue

            # HL: ranker top-Q AND ees_v3 bottom-Q
            if not (fs >= fs_top_q and v3 <= v3_bottom_q):
                continue

            # Forward returns
            fwd = {}
            exc = {}
            for h in HORIZONS:
                fwd[h] = compute_forward_return(ticker, snap_date, h, prices, sorted_dates)
                exc[h] = compute_excess_return(ticker, snap_date, h, prices, sorted_dates)

            primary_mode, secondary_modes = classify_failure_mode(row, fwd.get(PRIMARY_HORIZON))
            verdict = classify_veto_verdict(exc.get(PRIMARY_HORIZON))
            era = "EARLY" if snap_date <= EARLY_END else "LATE"

            entry = {
                "snap_date": snap_date,
                "ticker": ticker,
                "era": era,
                # Core signals
                "final_score": fs,
                "ees_v3_score": v3,
                "conditional_misprice_score": _safe_float(row.get("conditional_misprice_score")),
                "conditional_expected_move": _safe_float(row.get("conditional_expected_move")),
                "priced_move_pct": _safe_float(row.get("priced_move_pct")),
                "has_priced_move": _has_priced_move(row),
                # Snapshot context
                "fs_top_q_threshold": fs_top_q,
                "v3_bottom_q_threshold": v3_bottom_q,
                "v3_percentile_in_snap": (
                    round(
                        sum(1 for v in v3_vals if v is not None and v <= v3)
                        / max(1, sum(1 for v in v3_vals if v is not None)),
                        3,
                    )
                    if v3 is not None
                    else None
                ),
                # Catalyst
                "catalyst_days": _safe_float(row.get("catalyst_days")),
                "catalyst_family": row.get("catalyst_family", ""),
                "catalyst_event_type": row.get("catalyst_event_type", ""),
                "is_hard_catalyst": row.get("is_hard_catalyst", ""),
                "catalyst_bucket": row.get("catalyst_bucket", ""),
                # Fundamentals
                "market_cap_mm": _safe_float(row.get("market_cap_mm")),
                "adv_20d": _safe_float(row.get("adv_20d")),
                "median_dollar_volume_20d": _safe_float(row.get("median_dollar_volume_20d")),
                "short_interest_pct": _safe_float(row.get("short_interest_pct")),
                # Structure
                "financing_truth_gate": _safe_float(row.get("financing_truth_gate"), default=1.0),
                "dilution_haircut": _safe_float(row.get("dilution_haircut"), default=0.0),
                "ranker_active": row.get("ranker_active", ""),
                # Biotech program
                "therapeutic_area": row.get("therapeutic_area", ""),
                "stage_bucket": row.get("stage_bucket", ""),
                "crowding_level": row.get("crowding_level", ""),
                "lead_program_phase": row.get("lead_program_phase", ""),
                "program_count": _safe_float(row.get("program_count")),
                # OVF
                "ovf_near_catalyst": row.get("ovf_near_catalyst", ""),
                "ovf11_catalyst_class": row.get("ovf11_catalyst_class", ""),
                # Forward returns
                "fwd_ret_21d": fwd.get(21),
                "fwd_ret_42d": fwd.get(42),
                "fwd_ret_63d": fwd.get(63),
                "excess_ret_21d": exc.get(21),
                "excess_ret_42d": exc.get(42),
                "excess_ret_63d": exc.get(63),
                # Verdict
                "veto_verdict": verdict,
                "primary_failure_mode": primary_mode,
                "secondary_failure_modes": secondary_modes,
            }
            ledger.append(entry)

    return ledger


def aggregate_stats(ledger):
    total = len(ledger)
    if total == 0:
        return {}

    # Overall veto accuracy
    with_data = [e for e in ledger if e["veto_verdict"] != "INCONCLUSIVE"]
    true_neg = sum(1 for e in with_data if e["veto_verdict"] == "TRUE_NEGATIVE")

    def _mean(vals):
        v = [x for x in vals if x is not None]
        return sum(v) / len(v) if v else None

    def _pct(n, d):
        return round(n / d, 3) if d > 0 else None

    # By failure mode
    mode_stats = defaultdict(lambda: {"n": 0, "true_neg": 0, "false_neg": 0, "exc_63d": []})
    for e in ledger:
        m = e["primary_failure_mode"]
        mode_stats[m]["n"] += 1
        if e["veto_verdict"] == "TRUE_NEGATIVE":
            mode_stats[m]["true_neg"] += 1
            mode_stats[m]["exc_63d"].append(e["excess_ret_63d"])
        elif e["veto_verdict"] == "FALSE_NEGATIVE":
            mode_stats[m]["false_neg"] += 1
            mode_stats[m]["exc_63d"].append(e["excess_ret_63d"])

    mode_summary = {}
    for m, s in sorted(mode_stats.items(), key=lambda x: -x[1]["n"]):
        n = s["n"]
        tn = s["true_neg"]
        fn = s["false_neg"]
        denom = tn + fn
        mode_summary[m] = {
            "n": n,
            "pct_of_hl": _pct(n, total),
            "true_neg_rate": _pct(tn, denom) if denom > 0 else None,
            "false_neg_rate": _pct(fn, denom) if denom > 0 else None,
            "mean_excess_63d": round(_mean(s["exc_63d"]) * 100, 2) if _mean(s["exc_63d"]) is not None else None,
        }

    # By era
    def era_summary(era_label):
        era_rows = [e for e in ledger if e["era"] == era_label]
        era_data = [e for e in era_rows if e["veto_verdict"] != "INCONCLUSIVE"]
        tn_era = sum(1 for e in era_data if e["veto_verdict"] == "TRUE_NEGATIVE")
        exc_vals = [e["excess_ret_63d"] for e in era_data if e["excess_ret_63d"] is not None]
        return {
            "n": len(era_rows),
            "n_with_data": len(era_data),
            "true_neg_rate": _pct(tn_era, len(era_data)) if era_data else None,
            "mean_excess_63d": round(_mean(exc_vals) * 100, 2) if exc_vals else None,
        }

    # Most frequent tickers in HL bucket
    ticker_counts = defaultdict(lambda: {"n": 0, "true_neg": 0, "exc_63d": []})
    for e in ledger:
        t = e["ticker"]
        ticker_counts[t]["n"] += 1
        if e["veto_verdict"] == "TRUE_NEGATIVE":
            ticker_counts[t]["true_neg"] += 1
        if e["excess_ret_63d"] is not None:
            ticker_counts[t]["exc_63d"].append(e["excess_ret_63d"])

    top_tickers = []
    for t, s in sorted(ticker_counts.items(), key=lambda x: -x[1]["n"])[:20]:
        denom_t = s["n"]
        top_tickers.append(
            {
                "ticker": t,
                "n_appearances": s["n"],
                "true_neg_rate": _pct(s["true_neg"], denom_t),
                "mean_excess_63d": round(_mean(s["exc_63d"]) * 100, 2) if s["exc_63d"] else None,
            }
        )

    # Therapeutic area breakdown
    ta_stats = defaultdict(lambda: {"n": 0, "true_neg": 0, "exc_63d": []})
    for e in ledger:
        ta = e.get("therapeutic_area") or "unknown"
        ta_stats[ta]["n"] += 1
        if e["veto_verdict"] == "TRUE_NEGATIVE":
            ta_stats[ta]["true_neg"] += 1
        if e["excess_ret_63d"] is not None:
            ta_stats[ta]["exc_63d"].append(e["excess_ret_63d"])

    ta_summary = {}
    for ta, s in sorted(ta_stats.items(), key=lambda x: -x[1]["n"])[:10]:
        denom_ta = s["n"]
        ta_summary[ta] = {
            "n": s["n"],
            "true_neg_rate": _pct(s["true_neg"], denom_ta),
            "mean_excess_63d": round(_mean(s["exc_63d"]) * 100, 2) if s["exc_63d"] else None,
        }

    # Coverage breakdown: names with vs without priced_move
    covered = [e for e in ledger if e["has_priced_move"]]
    uncovered = [e for e in ledger if not e["has_priced_move"]]

    def _mini_summary(rows):
        d = [e for e in rows if e["veto_verdict"] != "INCONCLUSIVE"]
        tn = sum(1 for e in d if e["veto_verdict"] == "TRUE_NEGATIVE")
        exc = [e["excess_ret_63d"] for e in d if e["excess_ret_63d"] is not None]
        return {
            "n": len(rows),
            "true_neg_rate": _pct(tn, len(d)) if d else None,
            "mean_excess_63d": round(_mean(exc) * 100, 2) if exc else None,
        }

    return {
        "total_hl_observations": total,
        "observations_with_data": len(with_data),
        "overall_true_neg_rate": _pct(true_neg, len(with_data)) if with_data else None,
        "overall_mean_excess_63d": (
            round(_mean([e["excess_ret_63d"] for e in with_data if e["excess_ret_63d"] is not None]) * 100, 2)
            if with_data
            else None
        ),
        "by_era": {
            "EARLY": era_summary("EARLY"),
            "LATE": era_summary("LATE"),
        },
        "by_failure_mode": mode_summary,
        "by_therapeutic_area": ta_summary,
        "by_coverage": {
            "has_priced_move": _mini_summary(covered),
            "no_priced_move": _mini_summary(uncovered),
        },
        "top_repeating_tickers": top_tickers,
    }


def write_markdown(stats, ledger, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    total = stats.get("total_hl_observations", 0)
    tn_rate = stats.get("overall_true_neg_rate")
    mean_exc = stats.get("overall_mean_excess_63d")
    era = stats.get("by_era", {})
    mode = stats.get("by_failure_mode", {})

    lines = [
        "# EES v3 Veto Autopsy — HL Bucket Analysis",
        "",
        "**Date:** 2026-06-25",
        "**Status:** DIAGNOSTIC_ONLY",
        "**Governance:** FREEZE_ACTIVE | NO_PRODUCTION_WIRING | NO_PROMOTION_AUTHORIZED",
        "**Hypothesis tested:** veto_core removes ranker-selected names with low EES v3 score — are those removals correct?",
        "**Data:** 76 PIT monthly snapshots, 2020-01-31 -> 2026-04-16",
        "**Script:** `scripts/research/ees_v3_veto_autopsy.py`",
        "**Raw output:** `artifacts/research/ees_v3_veto_autopsy_2026_06_25.json` (gitignored)",
        "",
        "---",
        "",
        "## Definition",
        "",
        "**HL bucket**: ranker top-quintile (final_score) AND ees_v3 bottom-quintile.",
        "These are names `veto_core` would have removed from the selection universe.",
        "",
        "**TRUE_NEGATIVE**: veto was correct — name underperformed XBI at 63d.",
        "**FALSE_NEGATIVE**: veto was wrong — name outperformed XBI at 63d.",
        "",
        "---",
        "",
        "## Overall Results",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total HL observations | {total:,} |",
        f"| Observations with forward data | {stats.get('observations_with_data', 0):,} |",
        (
            f"| **True negative rate (veto correct)** | **{tn_rate:.1%}** |"
            if tn_rate is not None
            else "| True negative rate | n/a |"
        ),
        (
            f"| Mean excess return 63d (HL names) | {mean_exc:+.1f}% |"
            if mean_exc is not None
            else "| Mean excess 63d | n/a |"
        ),
        "",
    ]

    # Era breakdown
    lines += [
        "## Era Breakdown",
        "",
        "| Era | N | True Neg Rate | Mean Excess 63d |",
        "|-----|---|---------------|-----------------|",
    ]
    for e_label in ["EARLY", "LATE"]:
        e = era.get(e_label, {})
        tn_r = e.get("true_neg_rate")
        exc = e.get("mean_excess_63d")
        lines.append(
            f"| {e_label} (n={e.get('n', 0)}) | {e.get('n_with_data', 0)} | " f"{tn_r:.1%} |"
            if tn_r is not None
            else f"| {e_label} | — | — |" f" {exc:+.1f}% |" if exc is not None else " — |"
        )
    lines.append("")

    # Failure mode table
    lines += [
        "## Failure Mode Breakdown",
        "",
        "Primary reason EES v3 scored the name in its bottom quintile.",
        "",
        "| Failure Mode | N | % of HL | True Neg Rate | Mean Excess 63d |",
        "|--------------|---|---------|---------------|-----------------|",
    ]
    for m, s in sorted(mode.items(), key=lambda x: -x[1]["n"]):
        tn_r = s.get("true_neg_rate")
        exc = s.get("mean_excess_63d")
        pct = s.get("pct_of_hl")
        lines.append(
            f"| {m} | {s['n']} | {pct:.1%} | " f"{tn_r:.1%} | " + (f"{exc:+.1f}% |" if exc is not None else "n/a |")
            if tn_r is not None
            else f"| {m} | {s['n']} | {pct:.1%} | n/a | n/a |"
        )
    lines.append("")

    # Coverage split
    cov = stats.get("by_coverage", {})
    hpm = cov.get("has_priced_move", {})
    npm = cov.get("no_priced_move", {})
    lines += [
        "## Options Coverage Split",
        "",
        "| Coverage | N | True Neg Rate | Mean Excess 63d |",
        "|----------|---|---------------|-----------------|",
        f"| Has priced_move | {hpm.get('n', 0)} | "
        + (f"{hpm['true_neg_rate']:.1%}" if hpm.get("true_neg_rate") is not None else "n/a")
        + " | "
        + (f"{hpm['mean_excess_63d']:+.1f}%" if hpm.get("mean_excess_63d") is not None else "n/a")
        + " |",
        f"| No priced_move | {npm.get('n', 0)} | "
        + (f"{npm['true_neg_rate']:.1%}" if npm.get("true_neg_rate") is not None else "n/a")
        + " | "
        + (f"{npm['mean_excess_63d']:+.1f}%" if npm.get("mean_excess_63d") is not None else "n/a")
        + " |",
        "",
    ]

    # Top repeating tickers
    top_tickers = stats.get("top_repeating_tickers", [])[:15]
    lines += [
        "## Top Repeating HL Tickers",
        "",
        "Names that appear most frequently in the HL bucket across snapshots.",
        "",
        "| Ticker | Appearances | True Neg Rate | Mean Excess 63d |",
        "|--------|-------------|---------------|-----------------|",
    ]
    for t in top_tickers:
        tn_r = t.get("true_neg_rate")
        exc = t.get("mean_excess_63d")
        lines.append(
            f"| {t['ticker']} | {t['n_appearances']} | "
            + (f"{tn_r:.1%}" if tn_r is not None else "n/a")
            + " | "
            + (f"{exc:+.1f}%" if exc is not None else "n/a")
            + " |"
        )
    lines.append("")

    # Interpretation
    tn_r_val = tn_rate or 0.0
    veto_verdict = (
        "VETO_CREDIBLE — majority of removed names underperformed XBI"
        if tn_r_val > 0.55
        else (
            "VETO_MARGINAL — slight edge but not strongly predictive"
            if tn_r_val > 0.45
            else "VETO_QUESTIONABLE — removed names may have been valid selections"
        )
    )

    lines += [
        "## Interpretation",
        "",
        f"**Veto autopsy verdict:** `{veto_verdict}`",
        "",
        "Key questions this autopsy answers:",
        "",
        "1. **Is the veto correct more often than not?**",
        (
            f"   Overall true negative rate = {tn_rate:.1%} across {total:,} HL observations."
            if tn_rate is not None
            else "   No data."
        ),
        "",
        "2. **Which failure modes dominate?**",
        "   See failure mode table above. Market-already-priced and weak-expected-move",
        "   are the theoretically grounded failure modes for EES v3 veto.",
        "",
        "3. **Is the veto improving in the late regime?**",
        "   Compare EARLY vs LATE true-neg-rate. If late-regime rate is higher,",
        "   veto credibility is increasing with coverage expansion.",
        "",
        "---",
        "",
        "## Operator Decision",
        "",
        "```",
        "LEAD_EES_V3_INTEGRATION_HYPOTHESIS = VETO_CORE",
        "STATUS = DIAGNOSTIC_ONLY",
        "FREEZE = ACTIVE",
        "PRODUCTION_PROMOTION = NOT_AUTHORIZED",
        "VETO_AUTOPSY = COMPLETE (2026-06-25)",
        "```",
        "",
        "This autopsy is evidence for or against promoting veto_core.",
        "Do not promote until 20d shadow gate is met and operator approval received.",
        "",
    ]

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote markdown to {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="EES v3 veto autopsy ledger")
    parser.add_argument("--as-of-date", default=None, help="Run as of date (YYYY-MM-DD); filters snapshots")
    parser.add_argument("--output-json", default=OUTPUT_JSON)
    parser.add_argument("--output-md", default=OUTPUT_MD)
    parser.add_argument("--limit-snaps", type=int, default=None, help="Limit to N most recent snapshots (debug)")
    args = parser.parse_args()

    print(f"GOVERNANCE: {GOVERNANCE}", file=sys.stderr)
    print("Loading price history...", file=sys.stderr)
    prices = load_prices()

    all_dates = sorted(prices.get("XBI", {}).keys())
    price_dates = all_dates

    print("Loading PIT snapshots...", file=sys.stderr)
    snapshots = load_pit_snapshots()

    if args.as_of_date:
        snapshots = [(d, r) for d, r in snapshots if d <= args.as_of_date]
    if args.limit_snaps:
        snapshots = snapshots[-args.limit_snaps :]

    print(f"Building HL ledger from {len(snapshots)} snapshots...", file=sys.stderr)
    ledger = build_hl_ledger(snapshots, prices, price_dates)
    print(f"HL ledger: {len(ledger)} observations", file=sys.stderr)

    stats = aggregate_stats(ledger)

    # Write JSON
    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)
    output = {
        "governance": GOVERNANCE,
        "generated_at": datetime.now().isoformat(),
        "as_of_date": args.as_of_date or "all",
        "n_snapshots": len(snapshots),
        "methodology": {
            "hl_definition": "final_score >= top-{pct}th-pct AND ees_v3_score <= bottom-{pct}th-pct".format(
                pct=QUINTILE_PCT
            ),
            "primary_horizon_days": PRIMARY_HORIZON,
            "excess_vs": "XBI",
            "true_negative": "excess_ret_63d < 0 (veto correct)",
            "false_negative": "excess_ret_63d >= 0 (veto wrong)",
        },
        "aggregate_stats": stats,
        "ledger": ledger,
    }
    with open(args.output_json, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote JSON to {args.output_json}", file=sys.stderr)

    # Write markdown
    write_markdown(stats, ledger, args.output_md)

    # Print summary
    total = stats.get("total_hl_observations", 0)
    tn_rate = stats.get("overall_true_neg_rate")
    mean_exc = stats.get("overall_mean_excess_63d")
    print("\n=== EES v3 Veto Autopsy Summary ===")
    print(f"Total HL observations: {total:,}")
    print(f"Overall true-negative rate (veto correct): {tn_rate:.1%}" if tn_rate else "No data")
    print(f"Mean excess return 63d for HL names: {mean_exc:+.1f}%" if mean_exc else "No data")
    print()
    print("By era:")
    for era_label in ["EARLY", "LATE"]:
        e = stats.get("by_era", {}).get(era_label, {})
        tn_r = e.get("true_neg_rate")
        exc = e.get("mean_excess_63d")
        print(
            f"  {era_label}: n={e.get('n', 0)}, true_neg={tn_r:.1%}, mean_exc={exc:+.1f}%"
            if tn_r and exc
            else f"  {era_label}: n={e.get('n', 0)}, no data"
        )
    print()
    print("Top failure modes:")
    for m, s in sorted(stats.get("by_failure_mode", {}).items(), key=lambda x: -x[1]["n"])[:5]:
        tn_r = s.get("true_neg_rate")
        exc = s.get("mean_excess_63d")
        print(
            f"  {m}: n={s['n']} ({s['pct_of_hl']:.1%}), tn={tn_r:.1%}, exc={exc:+.1f}%"
            if tn_r and exc
            else f"  {m}: n={s['n']} ({s['pct_of_hl']:.1%})"
        )


if __name__ == "__main__":
    main()
