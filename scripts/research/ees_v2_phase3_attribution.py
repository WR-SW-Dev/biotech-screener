"""
EES v2 Phase 3 attribution analysis — 2026-06-23.
Diagnostic-only. Read-only. No production changes.

Question: WHY does EES v2 show diagnostic predictive signal for Phase 3 names
in the PIT panel? Which catalyst types, score ranges, and tickers drive it?

Input:
    artifacts/audit/ees_validation_panel_2026-06-23.csv  (PIT panel joined with EES)

Output:
    artifacts/audit/ees_v2_phase3_attribution_report_2026-06-23.md

Governance:
    DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE
"""

from __future__ import annotations

import csv
import logging
import math
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent.parent
PANEL = REPO / "artifacts" / "audit" / "ees_validation_panel_2026-06-23.csv"
OUT = REPO / "artifacts" / "audit" / "ees_v2_phase3_attribution_report_2026-06-23.md"
RUN_DATE = "2026-06-23"

MIN_PAIRS = 5


# ---------------------------------------------------------------------------
# Utilities (duplicated from ees_forward_validation.py — research script)
# ---------------------------------------------------------------------------


def _float(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _bool(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def _rank(xs):
    sorted_vals = sorted(enumerate(xs), key=lambda t: t[1])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(sorted_vals):
        j = i
        while j < len(sorted_vals) - 1 and sorted_vals[j + 1][1] == sorted_vals[i][1]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[sorted_vals[k][0]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    n = len(xs)
    if n < MIN_PAIRS:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((r - mx) ** 2 for r in rx)
    vy = sum((r - my) ** 2 for r in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def t_stat(ics):
    n = len(ics)
    if n < 3:
        return None
    mean = sum(ics) / n
    var = sum((x - mean) ** 2 for x in ics) / (n - 1)
    if var == 0:
        return None
    return mean / math.sqrt(var / n)


def per_date_ic(rows, score_col, ret_col, complete_col):
    by_date = defaultdict(list)
    for r in rows:
        if not r.get(complete_col):
            continue
        s = r.get(score_col)
        ret = r.get(ret_col)
        if s is None or ret is None:
            continue
        by_date[r["snap_date"]].append((s, ret))
    ics = []
    for pairs in by_date.values():
        if len(pairs) < MIN_PAIRS:
            continue
        xs, ys = zip(*pairs)
        ic = spearman(list(xs), list(ys))
        if ic is not None:
            ics.append(ic)
    if not ics:
        return {"mean": None, "median": None, "t": None, "hit": None, "n": 0}
    n = len(ics)
    ics_s = sorted(ics)
    mean = sum(ics) / n
    median = ics_s[n // 2] if n % 2 else (ics_s[n // 2 - 1] + ics_s[n // 2]) / 2
    ts = t_stat(ics)
    return {
        "mean": round(mean, 4),
        "median": round(median, 4),
        "t": round(ts, 2) if ts is not None else None,
        "hit": round(sum(1 for ic in ics if ic > 0) / n, 3),
        "n": n,
    }


def decile_returns(rows, score_col, ret_col, complete_col, n_buckets=5):
    pairs = [
        (r[score_col], r[ret_col])
        for r in rows
        if r.get(complete_col) and r.get(score_col) is not None and r.get(ret_col) is not None
    ]
    if len(pairs) < n_buckets * 2:
        return []
    pairs.sort(key=lambda p: p[0])
    total = len(pairs)
    bucket_size = total // n_buckets
    results = []
    for i in range(n_buckets):
        lo = i * bucket_size
        hi = lo + bucket_size if i < n_buckets - 1 else total
        bucket = pairs[lo:hi]
        rets = [p[1] for p in bucket]
        scores = [p[0] for p in bucket]
        results.append(
            {
                "bucket": i + 1,
                "score_lo": round(min(scores), 3),
                "score_hi": round(max(scores), 3),
                "score_mean": round(sum(scores) / len(scores), 3),
                "ret_mean": round(sum(rets) / len(rets), 4),
                "ret_pos_pct": round(sum(1 for r in rets if r > 0) / len(rets), 3),
                "n": len(bucket),
            }
        )
    return results


def ticker_contribution(rows, score_col, ret_col, complete_col):
    """Per-ticker: obs count, mean score, mean excess return, IC contribution proxy."""
    by_ticker = defaultdict(list)
    for r in rows:
        if not r.get(complete_col):
            continue
        s = r.get(score_col)
        ret = r.get(ret_col)
        if s is None or ret is None:
            continue
        by_ticker[r["ticker"]].append((s, ret))
    result = []
    for tkr, pairs in sorted(by_ticker.items()):
        scores = [p[0] for p in pairs]
        rets = [p[1] for p in pairs]
        ic = spearman(scores, rets) if len(pairs) >= MIN_PAIRS else None
        result.append(
            {
                "ticker": tkr,
                "n": len(pairs),
                "score_mean": round(sum(scores) / len(scores), 4),
                "ret_mean_5d": round(sum(rets) / len(rets), 4),
                "ic": round(ic, 4) if ic is not None else None,
            }
        )
    result.sort(key=lambda x: -(x["ic"] or -99))
    return result


# ---------------------------------------------------------------------------
# Load panel
# ---------------------------------------------------------------------------


def load_panel():
    rows = []
    with open(PANEL) as f:
        for r in csv.DictReader(f):
            r["ees_v2_score"] = _float(r.get("ees_v2_score"))
            r["base_rate_gap_score"] = _float(r.get("base_rate_gap_score"))
            r["priced_move_pct"] = _float(r.get("priced_move_pct"))
            r["excess_return_5d"] = _float(r.get("excess_return_5d"))
            r["excess_return_20d"] = _float(r.get("excess_return_20d"))
            r["actual_return_1d"] = _float(r.get("actual_return_1d"))
            r["lead_program_phase"] = _float(r.get("lead_program_phase"))
            r["forward_complete_5d"] = _bool(r.get("forward_complete_5d", ""))
            r["forward_complete_20d"] = _bool(r.get("forward_complete_20d", ""))
            r["atxs_excluded"] = _bool(r.get("atxs_excluded", ""))
            r["ees_eligible"] = _bool(r.get("ees_eligible", ""))
            r["is_hard_catalyst"] = _bool(r.get("is_hard_catalyst", ""))
            rows.append(r)
    log.info("Panel loaded: %d rows", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def main():
    log.info("=== EES v2 Phase 3 Attribution Analysis ===")
    log.info("DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE")

    rows = load_panel()

    # Exclude ATXS
    rows = [r for r in rows if not r["atxs_excluded"]]

    p3 = [r for r in rows if r["lead_program_phase"] is not None and r["lead_program_phase"] >= 3.0]
    p2 = [r for r in rows if r["lead_program_phase"] is not None and 2.0 <= r["lead_program_phase"] < 3.0]
    log.info("Phase 3: %d rows | Phase 2: %d rows", len(p3), len(p2))

    # -----------------------------------------------------------------------
    # A. Score distribution by phase
    # -----------------------------------------------------------------------
    def score_stats(rows_sub, col):
        vals = [r[col] for r in rows_sub if r.get(col) is not None]
        if not vals:
            return {}
        vals_s = sorted(vals)
        n = len(vals_s)
        mean = sum(vals_s) / n
        var = sum((x - mean) ** 2 for x in vals_s) / n
        q25 = vals_s[n // 4]
        q75 = vals_s[3 * n // 4]
        median = vals_s[n // 2] if n % 2 else (vals_s[n // 2 - 1] + vals_s[n // 2]) / 2
        return {
            "n": n,
            "mean": round(mean, 4),
            "median": round(median, 4),
            "std": round(math.sqrt(var), 4),
            "q25": round(q25, 4),
            "q75": round(q75, 4),
            "min": round(vals_s[0], 4),
            "max": round(vals_s[-1], 4),
            "pct_positive": round(sum(1 for v in vals_s if v > 0) / n, 3),
        }

    p3_score_dist = score_stats(p3, "ees_v2_score")
    p2_score_dist = score_stats(p2, "ees_v2_score")
    log.info(
        "Phase 3 score dist: mean=%.4f std=%.4f pct_pos=%.3f",
        p3_score_dist["mean"],
        p3_score_dist["std"],
        p3_score_dist["pct_positive"],
    )
    log.info(
        "Phase 2 score dist: mean=%.4f std=%.4f pct_pos=%.3f",
        p2_score_dist["mean"],
        p2_score_dist["std"],
        p2_score_dist["pct_positive"],
    )

    # -----------------------------------------------------------------------
    # B. Per-event-type IC within Phase 3
    # -----------------------------------------------------------------------
    evt_types = sorted({r.get("catalyst_event_type", "") for r in p3 if r.get("catalyst_event_type")})
    evt_ic = {}
    log.info("--- Phase 3 by catalyst_event_type ---")
    for evt in evt_types:
        sub = [r for r in p3 if r.get("catalyst_event_type") == evt]
        n_sub = len(sub)
        if n_sub < 10:
            continue
        ic5 = per_date_ic(sub, "ees_v2_score", "excess_return_5d", "forward_complete_5d")
        ic20 = per_date_ic(sub, "ees_v2_score", "excess_return_20d", "forward_complete_20d")
        evt_ic[evt] = {"n": n_sub, "ic5": ic5, "ic20": ic20}
        log.info(
            "  %s (n=%d): 5d mean=%.4f t=%s  20d mean=%.4f t=%s",
            evt,
            n_sub,
            ic5["mean"] or 0,
            ic5["t"],
            ic20["mean"] or 0,
            ic20["t"],
        )

    # -----------------------------------------------------------------------
    # C. Eligible vs non-eligible within Phase 3
    # -----------------------------------------------------------------------
    p3_elig = [r for r in p3 if r["ees_eligible"]]
    p3_nelig = [r for r in p3 if not r["ees_eligible"]]
    log.info("--- Phase 3: eligible=%d non-eligible=%d ---", len(p3_elig), len(p3_nelig))

    elig_ic5 = per_date_ic(p3_elig, "ees_v2_score", "excess_return_5d", "forward_complete_5d")
    elig_ic20 = per_date_ic(p3_elig, "ees_v2_score", "excess_return_20d", "forward_complete_20d")
    nelig_ic5 = per_date_ic(p3_nelig, "ees_v2_score", "excess_return_5d", "forward_complete_5d")
    nelig_ic20 = per_date_ic(p3_nelig, "ees_v2_score", "excess_return_20d", "forward_complete_20d")
    log.info("  Eligible  5d: mean=%.4f t=%s n=%d", elig_ic5["mean"] or 0, elig_ic5["t"], elig_ic5["n"])
    log.info("  Eligible 20d: mean=%.4f t=%s n=%d", elig_ic20["mean"] or 0, elig_ic20["t"], elig_ic20["n"])
    log.info("  Non-elig  5d: mean=%.4f t=%s n=%d", nelig_ic5["mean"] or 0, nelig_ic5["t"], nelig_ic5["n"])
    log.info("  Non-elig 20d: mean=%.4f t=%s n=%d", nelig_ic20["mean"] or 0, nelig_ic20["t"], nelig_ic20["n"])

    # -----------------------------------------------------------------------
    # D. Quintile / decile breakdown (score → return) for Phase 3
    # -----------------------------------------------------------------------
    log.info("--- Phase 3 score quintile → return ---")
    p3_quintiles_5d = decile_returns(p3, "ees_v2_score", "excess_return_5d", "forward_complete_5d", 5)
    p3_quintiles_20d = decile_returns(p3, "ees_v2_score", "excess_return_20d", "forward_complete_20d", 5)
    for q in p3_quintiles_5d:
        log.info(
            "  Q%d [%.3f,%.3f] ret=%.4f pos_pct=%.2f n=%d",
            q["bucket"],
            q["score_lo"],
            q["score_hi"],
            q["ret_mean"],
            q["ret_pos_pct"],
            q["n"],
        )

    # -----------------------------------------------------------------------
    # E. Ticker concentration — does signal come from a few names?
    # -----------------------------------------------------------------------
    log.info("--- Phase 3 ticker concentration (5d) ---")
    tckr_data = ticker_contribution(p3, "ees_v2_score", "excess_return_5d", "forward_complete_5d")
    for t in tckr_data[:10]:
        log.info(
            "  %s: n=%d score_mean=%.4f ret_mean=%.4f ic=%s",
            t["ticker"],
            t["n"],
            t["score_mean"],
            t["ret_mean_5d"],
            t["ic"],
        )

    # -----------------------------------------------------------------------
    # F. High vs low ees_v2 within Phase 3 (above/below median score)
    # -----------------------------------------------------------------------
    p3_with_score = [r for r in p3 if r["ees_v2_score"] is not None]
    median_score = sorted(r["ees_v2_score"] for r in p3_with_score)[len(p3_with_score) // 2]
    p3_high = [r for r in p3_with_score if r["ees_v2_score"] >= median_score]
    p3_low = [r for r in p3_with_score if r["ees_v2_score"] < median_score]
    log.info("--- Phase 3 high vs low score (median=%.4f) ---", median_score)

    def mean_ret(rows_sub, ret_col, complete_col):
        vals = [r[ret_col] for r in rows_sub if r.get(complete_col) and r.get(ret_col) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    hi5 = mean_ret(p3_high, "excess_return_5d", "forward_complete_5d")
    lo5 = mean_ret(p3_low, "excess_return_5d", "forward_complete_5d")
    hi20 = mean_ret(p3_high, "excess_return_20d", "forward_complete_20d")
    lo20 = mean_ret(p3_low, "excess_return_20d", "forward_complete_20d")
    log.info("  High score  5d mean=%.4f  20d mean=%.4f  n=%d", hi5 or 0, hi20 or 0, len(p3_high))
    log.info("  Low score   5d mean=%.4f  20d mean=%.4f  n=%d", lo5 or 0, lo20 or 0, len(p3_low))

    # -----------------------------------------------------------------------
    # G. Hard catalyst flag within Phase 3
    # -----------------------------------------------------------------------
    p3_hard = [r for r in p3 if r["is_hard_catalyst"]]
    p3_soft = [r for r in p3 if not r["is_hard_catalyst"]]
    hard_ic5 = per_date_ic(p3_hard, "ees_v2_score", "excess_return_5d", "forward_complete_5d")
    soft_ic5 = per_date_ic(p3_soft, "ees_v2_score", "excess_return_5d", "forward_complete_5d")
    log.info(
        "--- Phase 3: hard_catalyst=%d (IC 5d mean=%.4f t=%s) | soft=%d (IC=%.4f t=%s)",
        len(p3_hard),
        hard_ic5["mean"] or 0,
        hard_ic5["t"],
        len(p3_soft),
        soft_ic5["mean"] or 0,
        soft_ic5["t"],
    )

    # -----------------------------------------------------------------------
    # H. Per-date IC distribution for Phase 3 (where does it work?)
    # -----------------------------------------------------------------------
    by_date = defaultdict(list)
    for r in p3:
        if not r["forward_complete_5d"]:
            continue
        s = r.get("ees_v2_score")
        ret = r.get("excess_return_5d")
        if s is None or ret is None:
            continue
        by_date[r["snap_date"]].append((s, ret))

    date_ics = []
    for date, pairs in sorted(by_date.items()):
        if len(pairs) < MIN_PAIRS:
            continue
        xs, ys = zip(*pairs)
        ic = spearman(list(xs), list(ys))
        if ic is not None:
            date_ics.append((date, ic, len(pairs)))

    positive_dates = [(d, ic, n) for d, ic, n in date_ics if ic > 0]
    log.info("--- Per-date IC distribution (Phase 3, 5d) ---")
    log.info(
        "  Dates with IC > 0: %d / %d (%.0f%%)",
        len(positive_dates),
        len(date_ics),
        100 * len(positive_dates) / len(date_ics) if date_ics else 0,
    )

    top5 = sorted(date_ics, key=lambda x: -x[1])[:5]
    bot5 = sorted(date_ics, key=lambda x: x[1])[:5]
    log.info("  Best dates: %s", [(d, round(ic, 3)) for d, ic, _ in top5])
    log.info("  Worst dates: %s", [(d, round(ic, 3)) for d, ic, _ in bot5])

    # -----------------------------------------------------------------------
    # Write report
    # -----------------------------------------------------------------------
    _write_report(
        p3_score_dist,
        p2_score_dist,
        evt_ic,
        elig_ic5,
        elig_ic20,
        nelig_ic5,
        nelig_ic20,
        p3_quintiles_5d,
        p3_quintiles_20d,
        tckr_data,
        median_score,
        hi5,
        lo5,
        hi20,
        lo20,
        len(p3_high),
        len(p3_low),
        hard_ic5,
        soft_ic5,
        len(p3_hard),
        len(p3_soft),
        date_ics,
        positive_dates,
        len(p3),
        len(p2),
    )
    log.info("Report written: %s", OUT)
    log.info("=== Attribution complete === DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES ===")


def _write_report(
    p3_score_dist,
    p2_score_dist,
    evt_ic,
    elig_ic5,
    elig_ic20,
    nelig_ic5,
    nelig_ic20,
    p3_q5,
    p3_q20,
    tckr_data,
    median_score,
    hi5,
    lo5,
    hi20,
    lo20,
    n_high,
    n_low,
    hard_ic5,
    soft_ic5,
    n_hard,
    n_soft,
    date_ics,
    positive_dates,
    n_p3,
    n_p2,
):
    def _ic_row(label, n, ic5, ic20):
        return (
            f"| {label} | {n} | {ic5.get('mean', '—')} | {ic5.get('t', '—')} | "
            f"{ic5.get('n', 0)} | {ic20.get('mean', '—')} | {ic20.get('t', '—')} | {ic20.get('n', 0)} |"
        )

    lines = [
        "# EES v2 Phase 3 Attribution Report",
        "",
        f"**Date:** {RUN_DATE}  ",
        "**Governance:** DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE  ",
        "**Input:** ees_validation_panel_2026-06-23.csv (PIT Method A panel + EES scores)  ",
        "**Question:** Why does EES v2 show diagnostic predictive signal for Phase 3 names?",
        "",
        "---",
        "",
        "## A. EES v2 Score Distribution by Phase",
        "",
        "| Metric | Phase 3 | Phase 2 |",
        "|--------|---------|---------|",
        f"| N rows | {p3_score_dist['n']} | {p2_score_dist['n']} |",
        f"| Mean score | {p3_score_dist['mean']} | {p2_score_dist['mean']} |",
        f"| Median score | {p3_score_dist['median']} | {p2_score_dist['median']} |",
        f"| Std dev | {p3_score_dist['std']} | {p2_score_dist['std']} |",
        f"| Q25 / Q75 | {p3_score_dist['q25']} / {p3_score_dist['q75']} | {p2_score_dist['q25']} / {p2_score_dist['q75']} |",
        f"| Min / Max | {p3_score_dist['min']} / {p3_score_dist['max']} | {p2_score_dist['min']} / {p2_score_dist['max']} |",
        f"| % positive score | {p3_score_dist['pct_positive']:.1%} | {p2_score_dist['pct_positive']:.1%} |",
        "",
    ]

    lines += [
        "## B. Per-Event-Type IC Within Phase 3",
        "",
        "| Event type | N | 5d IC mean | 5d t | 5d dates | 20d IC mean | 20d t | 20d dates |",
        "|-----------|---|-----------|------|---------|------------|-------|----------|",
    ]
    for evt, data in sorted(evt_ic.items(), key=lambda x: -(x[1]["ic5"]["mean"] or -99)):
        lines.append(_ic_row(evt, data["n"], data["ic5"], data["ic20"]))

    lines += [
        "",
        "## C. EES-Eligible vs Non-Eligible Within Phase 3",
        "",
        "| Subset | N rows | 5d IC mean | 5d t | 5d dates | 20d IC mean | 20d t | 20d dates |",
        "|--------|--------|-----------|------|---------|------------|-------|----------|",
        (
            f"| Eligible (ees_eligible=True) | — "
            f"| {elig_ic5.get('mean', '—')} | {elig_ic5.get('t', '—')} | {elig_ic5.get('n', 0)}"
            f" | {elig_ic20.get('mean', '—')} | {elig_ic20.get('t', '—')} | {elig_ic20.get('n', 0)} |"
        ),
        (
            f"| Non-eligible (ees_eligible=False) | — "
            f"| {nelig_ic5.get('mean', '—')} | {nelig_ic5.get('t', '—')} | {nelig_ic5.get('n', 0)}"
            f" | {nelig_ic20.get('mean', '—')} | {nelig_ic20.get('t', '—')} | {nelig_ic20.get('n', 0)} |"
        ),
    ]

    lines += [
        "",
        "## D. Score Quintile → Return Relationship (Phase 3)",
        "",
        "### 5d XBI-excess return by ees_v2_score quintile",
        "",
        "| Quintile | Score range | Mean score | Mean 5d excess return | % positive |",
        "|---------|-------------|-----------|----------------------|------------|",
    ]
    for q in p3_q5:
        lines.append(
            f"| Q{q['bucket']} | [{q['score_lo']}, {q['score_hi']}] | {q['score_mean']} "
            f"| {q['ret_mean']:.4f} ({q['ret_mean']*100:.2f}%) | {q['ret_pos_pct']:.0%} |"
        )

    lines += [
        "",
        "### 20d XBI-excess return by ees_v2_score quintile",
        "",
        "| Quintile | Score range | Mean score | Mean 20d excess return | % positive |",
        "|---------|-------------|-----------|------------------------|------------|",
    ]
    for q in p3_q20:
        lines.append(
            f"| Q{q['bucket']} | [{q['score_lo']}, {q['score_hi']}] | {q['score_mean']} "
            f"| {q['ret_mean']:.4f} ({q['ret_mean']*100:.2f}%) | {q['ret_pos_pct']:.0%} |"
        )

    lines += [
        "",
        "## E. Ticker Concentration (Phase 3, 5d)",
        "",
        "Top 10 tickers by per-ticker IC (min 5 observations):",
        "",
        "| Ticker | N obs | Mean EES v2 | Mean 5d excess return | Per-ticker IC |",
        "|--------|-------|------------|----------------------|---------------|",
    ]
    shown = [t for t in tckr_data if t["ic"] is not None][:10]
    for t in shown:
        lines.append(f"| {t['ticker']} | {t['n']} | {t['score_mean']} | {t['ret_mean_5d']:.4f} | {t['ic']} |")

    lines += [
        "",
        "## F. Above vs Below Median Score (Phase 3)",
        "",
        f"Median ees_v2_score: {round(median_score, 4)}",
        "",
        "| Subset | N | Mean 5d excess return | Mean 20d excess return |",
        "|--------|---|----------------------|----------------------|",
        f"| High score (≥ median) | {n_high} | {hi5} | {hi20} |",
        f"| Low score (< median) | {n_low} | {lo5} | {lo20} |",
        f"| Spread | — | {round((hi5 or 0) - (lo5 or 0), 4)} | {round((hi20 or 0) - (lo20 or 0), 4)} |",
        "",
        "## G. Hard Catalyst Flag Within Phase 3",
        "",
        "| Subset | N rows | 5d IC mean | 5d t | 5d dates |",
        "|--------|--------|-----------|------|---------|",
        f"| Hard catalyst | {n_hard} | {hard_ic5.get('mean', '—')} | {hard_ic5.get('t', '—')} | {hard_ic5.get('n', 0)} |",
        f"| Non-hard catalyst | {n_soft} | {soft_ic5.get('mean', '—')} | {soft_ic5.get('t', '—')} | {soft_ic5.get('n', 0)} |",
        "",
        "## H. Per-Date IC Distribution (Phase 3, 5d)",
        "",
        f"- Dates with valid IC: {len(date_ics)}",
        (
            f"- Positive IC dates: {len(positive_dates)} ({len(positive_dates)/len(date_ics):.0%})"
            if date_ics
            else "- No valid IC dates"
        ),
        f"- Negative IC dates: {len(date_ics) - len(positive_dates)}",
    ]

    top5 = sorted(date_ics, key=lambda x: -x[1])[:5]
    bot5 = sorted(date_ics, key=lambda x: x[1])[:5]
    lines += [
        "",
        "Best 5 dates (highest IC):",
        "| Date | IC | N pairs |",
        "|------|----|---------|",
    ]
    for d, ic, n in top5:
        lines.append(f"| {d} | {round(ic, 4)} | {n} |")
    lines += [
        "",
        "Worst 5 dates (lowest IC):",
        "| Date | IC | N pairs |",
        "|------|----|---------|",
    ]
    for d, ic, n in bot5:
        lines.append(f"| {d} | {round(ic, 4)} | {n} |")

    lines += [
        "",
        "---",
        "",
        "*Generated by scripts/research/ees_v2_phase3_attribution.py — "
        "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE*",
    ]

    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
