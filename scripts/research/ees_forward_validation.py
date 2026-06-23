"""
EES Forward Validation — 2026-06-23
Diagnostic-only. Read-only. No production changes.

Answers: Do EES scores have forward-return information after using the
accepted PIT diagnostic panel?

Inputs:
  - artifacts/audit/gap_panel_method_a_2026-06-23.csv   (Method A, primary)
  - artifacts/audit/gap_panel_method_b_sensitivity_2026-06-23.csv (Method B, 60d sensitivity)
  - data/snapshots/{date}/rankings.csv  (EES scores, PIT-safe lookup)

Outputs:
  - artifacts/audit/ees_validation_panel_2026-06-23.csv  (joined panel, gitignored)
  - artifacts/audit/ees_validation_report_2026-06-23.md  (machine-readable stats)

Governance:
  DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE
"""

import csv
import logging
import math
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SNAP_ROOT = REPO_ROOT / "data" / "snapshots"
AUDIT_DIR = REPO_ROOT / "artifacts" / "audit"
RUN_DATE = "2026-06-23"

PANEL_A = AUDIT_DIR / f"gap_panel_method_a_{RUN_DATE}.csv"
PANEL_B = AUDIT_DIR / f"gap_panel_method_b_sensitivity_{RUN_DATE}.csv"
OUT_PANEL = AUDIT_DIR / f"ees_validation_panel_{RUN_DATE}.csv"
OUT_REPORT = AUDIT_DIR / f"ees_validation_report_{RUN_DATE}.md"

# Binary-event filter: exclude rows where |1d return| exceeds this threshold
BINARY_EVENT_THRESHOLD = 0.30  # 30% single-day move

EES_SCORE_COLS = ["ees_v2_score", "ees_v3_score", "base_rate_gap_score"]
RETURN_COLS_5D = "excess_return_5d"
RETURN_COLS_20D = "excess_return_20d"
RETURN_COLS_60D = "excess_return_60d"  # Method B only


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _float(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def spearman_ic(xs, ys):
    """Spearman rank correlation between paired lists (no NaN)."""
    n = len(xs)
    if n < 5:
        return None
    rx = _rank(xs)
    ry = _rank(ys)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    cov = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    var_x = sum((r - mean_rx) ** 2 for r in rx)
    var_y = sum((r - mean_ry) ** 2 for r in ry)
    if var_x == 0 or var_y == 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _rank(xs):
    """Return rank list (1-based, average ties)."""
    sorted_vals = sorted(enumerate(xs), key=lambda t: t[1])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(sorted_vals):
        j = i
        while j < len(sorted_vals) - 1 and sorted_vals[j + 1][1] == sorted_vals[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[sorted_vals[k][0]] = avg_rank
        i = j + 1
    return ranks


def t_stat(ic_vals):
    n = len(ic_vals)
    if n < 3:
        return None
    mean = sum(ic_vals) / n
    var = sum((x - mean) ** 2 for x in ic_vals) / (n - 1)
    if var == 0:
        return None
    return mean / (math.sqrt(var / n))


def quintile_spread(rows, score_col, return_col):
    """Return top-quintile mean return minus bottom-quintile mean return."""
    pairs = [
        (r[score_col], r[return_col]) for r in rows if r.get(score_col) is not None and r.get(return_col) is not None
    ]
    if len(pairs) < 10:
        return None, None, len(pairs)
    pairs.sort(key=lambda p: p[0])
    n = len(pairs)
    q = max(1, n // 5)
    bottom = [p[1] for p in pairs[:q]]
    top = [p[1] for p in pairs[-q:]]
    spread = sum(top) / len(top) - sum(bottom) / len(bottom)
    return sum(top) / len(top), sum(bottom) / len(bottom), spread


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_panel(path):
    rows = []
    with open(path) as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    reader = csv.DictReader(lines)
    for row in reader:
        rows.append(row)
    logger.info(f"Loaded panel: {path.name} — {len(rows)} rows")
    return rows


def load_ees_scores(snap_date):
    """Load EES and catalyst columns from rankings.csv for a given date."""
    rcsv = SNAP_ROOT / snap_date / "rankings.csv"
    if not rcsv.exists():
        return {}
    scores = {}
    with open(rcsv) as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "")
            if not ticker:
                continue
            scores[ticker] = {
                "ees_v2_score": _float(row.get("ees_v2_score")),
                "ees_v3_score": _float(row.get("ees_v3_score")),
                "base_rate_gap_score": _float(row.get("base_rate_gap_score")),
                "priced_move_pct": _float(row.get("priced_move_pct")),
                "ees_eligible": _bool(row.get("ees_eligible", False)),
                "ees_v3_gate": row.get("ees_v3_gate", ""),
                "ees_v3_pctile": _float(row.get("ees_v3_pctile")),
                "catalyst_family": row.get("catalyst_family", ""),
                "lead_program_phase": row.get("lead_program_phase", ""),
                "is_hard_catalyst": _bool(row.get("is_hard_catalyst", False)),
                "catalyst_event_type": row.get("catalyst_event_type", ""),
            }
    return scores


def build_joined_panel(panel_rows, method_b=False):
    """Join PIT panel with EES scores from each snapshot."""
    # Cache by snap_date
    ees_cache = {}
    joined = []
    skipped_no_scores = 0
    for row in panel_rows:
        snap_date = row["snap_date"]
        ticker = row["ticker"]
        if snap_date not in ees_cache:
            ees_cache[snap_date] = load_ees_scores(snap_date)
        ees = ees_cache[snap_date].get(ticker)
        if ees is None:
            skipped_no_scores += 1
            continue
        merged = dict(row)
        merged.update(ees)
        # Parse return fields
        for col in [
            "actual_return_1d",
            "actual_return_3d",
            "actual_return_5d",
            "actual_return_20d",
            "excess_return_1d",
            "excess_return_3d",
            "excess_return_5d",
            "excess_return_20d",
            "xbi_return_5d",
            "xbi_return_20d",
        ]:
            merged[col] = _float(row.get(col))
        if method_b:
            merged["excess_return_60d"] = _float(row.get("excess_return_60d"))
            merged["forward_complete_60d"] = _bool(row.get("forward_complete_60d", False))
        merged["forward_complete_5d"] = _bool(row.get("forward_complete_5d", False))
        merged["forward_complete_20d"] = _bool(row.get("forward_complete_20d", False))
        merged["atxs_excluded"] = _bool(row.get("atxs_excluded", False))
        merged["is_binary_event"] = (
            merged.get("actual_return_1d") is not None and abs(merged["actual_return_1d"]) >= BINARY_EVENT_THRESHOLD
        )
        joined.append(merged)
    logger.info(f"Joined panel: {len(joined)} rows | skipped_no_scores={skipped_no_scores}")
    return joined


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def coverage_stats(joined):
    total = len(joined)
    stats = {
        "total_rows": total,
        "total_tickers": len({r["ticker"] for r in joined}),
        "total_dates": len({r["snap_date"] for r in joined}),
    }
    for col in EES_SCORE_COLS + ["priced_move_pct", "catalyst_family", "lead_program_phase"]:
        n = sum(1 for r in joined if r.get(col) not in (None, "", "nan"))
        stats[f"has_{col}"] = n
        stats[f"pct_{col}"] = round(100 * n / total, 1) if total else 0
    stats["ees_eligible_count"] = sum(1 for r in joined if r.get("ees_eligible"))
    stats["binary_event_count"] = sum(1 for r in joined if r.get("is_binary_event"))
    stats["atxs_excluded_count"] = sum(1 for r in joined if r.get("atxs_excluded"))
    return stats


def per_date_ic(joined, score_col, return_col, complete_col, exclude_binary=False):
    """Compute per-date Spearman IC for score vs return."""
    by_date = defaultdict(list)
    for r in joined:
        if not r.get(complete_col):
            continue
        if r.get("atxs_excluded"):
            continue
        if exclude_binary and r.get("is_binary_event"):
            continue
        s = r.get(score_col)
        ret = r.get(return_col)
        if s is None or ret is None:
            continue
        by_date[r["snap_date"]].append((s, ret))

    ics = []
    for date in sorted(by_date):
        pairs = by_date[date]
        if len(pairs) < 5:
            continue
        xs, ys = zip(*pairs)
        ic = spearman_ic(list(xs), list(ys))
        if ic is not None:
            ics.append(ic)

    if not ics:
        return {"n_dates": 0, "mean_ic": None, "median_ic": None, "hit_rate": None, "t_stat": None, "ic_values": []}
    n = len(ics)
    mean = sum(ics) / n
    sorted_ics = sorted(ics)
    median = sorted_ics[n // 2] if n % 2 else (sorted_ics[n // 2 - 1] + sorted_ics[n // 2]) / 2
    hit_rate = sum(1 for ic in ics if ic > 0) / n
    ts = t_stat(ics)
    return {
        "n_dates": n,
        "mean_ic": round(mean, 4),
        "median_ic": round(median, 4),
        "hit_rate": round(hit_rate, 3),
        "t_stat": round(ts, 2) if ts is not None else None,
        "ic_values": [round(ic, 4) for ic in ics],
    }


def cohort_ic(joined, score_col, return_col, complete_col, cohort_col, cohort_val):
    """IC restricted to a specific cohort value."""
    subset = [r for r in joined if str(r.get(cohort_col, "")).strip() == cohort_val]
    return per_date_ic(subset, score_col, return_col, complete_col)


def quintile_analysis(joined, score_col, return_col, complete_col, exclude_binary=False):
    rows = [
        r
        for r in joined
        if r.get(complete_col)
        and not r.get("atxs_excluded")
        and (not exclude_binary or not r.get("is_binary_event"))
        and r.get(score_col) is not None
        and r.get(return_col) is not None
    ]
    top_ret, bot_ret, spread = quintile_spread(rows, score_col, return_col)
    return {
        "n": len(rows),
        "top_q_mean": round(top_ret, 4) if top_ret is not None else None,
        "bottom_q_mean": round(bot_ret, 4) if bot_ret is not None else None,
        "spread": round(spread, 4) if spread is not None else None,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    logger.info("=== EES Forward Validation ===")
    logger.info(f"Run date: {RUN_DATE} | DIAGNOSTIC_ONLY | FREEZE_ACTIVE")

    if not PANEL_A.exists():
        logger.error(f"PIT panel not found: {PANEL_A}")
        sys.exit(1)

    # --- Load and join ---
    panel_a_rows = load_panel(PANEL_A)
    joined = build_joined_panel(panel_a_rows)

    # Method B
    panel_b_rows = load_panel(PANEL_B) if PANEL_B.exists() else []
    joined_b = build_joined_panel(panel_b_rows, method_b=True) if panel_b_rows else []

    # --- Coverage ---
    logger.info("--- Coverage ---")
    cov = coverage_stats(joined)
    logger.info(f"Total rows: {cov['total_rows']} | dates: {cov['total_dates']} | tickers: {cov['total_tickers']}")
    for col in EES_SCORE_COLS:
        logger.info(f"  {col}: {cov[f'has_{col}']} rows ({cov[f'pct_{col}']}%)")
    logger.info(f"  ees_eligible: {cov['ees_eligible_count']}")
    logger.info(f"  binary_events (|1d|>30%): {cov['binary_event_count']}")

    # --- IC analysis ---
    results = {}
    logger.info("--- Cross-sectional IC ---")
    for score in EES_SCORE_COLS:
        for hz, rcol, ccol in [
            ("5d", "excess_return_5d", "forward_complete_5d"),
            ("20d", "excess_return_20d", "forward_complete_20d"),
        ]:
            key = f"{score}_{hz}"
            ic = per_date_ic(joined, score, rcol, ccol)
            results[key] = ic
            logger.info(
                f"  {score} vs {hz}: mean_ic={ic['mean_ic']} median={ic['median_ic']} "
                f"hit_rate={ic['hit_rate']} t={ic['t_stat']} n_dates={ic['n_dates']}"
            )

    # Robustness: exclude binary events
    logger.info("--- IC excluding binary events (|1d|>30%) ---")
    results_no_binary = {}
    for score in EES_SCORE_COLS:
        for hz, rcol, ccol in [
            ("5d", "excess_return_5d", "forward_complete_5d"),
            ("20d", "excess_return_20d", "forward_complete_20d"),
        ]:
            key = f"{score}_{hz}_no_binary"
            ic = per_date_ic(joined, score, rcol, ccol, exclude_binary=True)
            results_no_binary[key] = ic
            logger.info(f"  {score} vs {hz} (no binary): mean_ic={ic['mean_ic']} t={ic['t_stat']}")

    # --- Quintile spreads ---
    logger.info("--- Quintile spreads ---")
    quintiles = {}
    for score in EES_SCORE_COLS:
        for hz, rcol, ccol in [
            ("5d", "excess_return_5d", "forward_complete_5d"),
            ("20d", "excess_return_20d", "forward_complete_20d"),
        ]:
            key = f"{score}_{hz}"
            q = quintile_analysis(joined, score, rcol, ccol)
            quintiles[key] = q
            logger.info(
                f"  {score} {hz}: top={q['top_q_mean']} bot={q['bottom_q_mean']} spread={q['spread']} n={q['n']}"
            )

    # --- Cohort breakdown ---
    logger.info("--- Cohort breakdown ---")
    cohort_results = {}

    # Catalyst family
    families = sorted({str(r.get("catalyst_family", "")).strip() for r in joined if r.get("catalyst_family")})
    for fam in families:
        n = sum(1 for r in joined if str(r.get("catalyst_family", "")).strip() == fam)
        if n < 20:
            continue
        logger.info(f"  Family={fam} (n={n})")
        for score in ["ees_v2_score", "ees_v3_score"]:
            for hz, rcol, ccol in [
                ("5d", "excess_return_5d", "forward_complete_5d"),
                ("20d", "excess_return_20d", "forward_complete_20d"),
            ]:
                ic = cohort_ic(joined, score, rcol, ccol, "catalyst_family", fam)
                key = f"family_{fam}_{score}_{hz}"
                cohort_results[key] = ic
                if ic["n_dates"] >= 3:
                    logger.info(f"    {score} {hz}: mean_ic={ic['mean_ic']} t={ic['t_stat']} n={ic['n_dates']}")

    # Phase breakdown
    phases = sorted({str(r.get("lead_program_phase", "")).strip() for r in joined if r.get("lead_program_phase")})
    for phase in phases:
        n = sum(1 for r in joined if str(r.get("lead_program_phase", "")).strip() == phase)
        if n < 15:
            continue
        logger.info(f"  Phase={phase} (n={n})")
        for score in ["ees_v2_score", "ees_v3_score"]:
            for hz, rcol, ccol in [
                ("5d", "excess_return_5d", "forward_complete_5d"),
                ("20d", "excess_return_20d", "forward_complete_20d"),
            ]:
                ic = cohort_ic(joined, score, rcol, ccol, "lead_program_phase", phase)
                key = f"phase_{phase}_{score}_{hz}"
                cohort_results[key] = ic
                if ic["n_dates"] >= 3:
                    logger.info(f"    {score} {hz}: mean_ic={ic['mean_ic']} t={ic['t_stat']} n={ic['n_dates']}")

    # EES-eligible only
    eligible_subset = [r for r in joined if r.get("ees_eligible")]
    logger.info(f"  EES-eligible subset: {len(eligible_subset)} rows")
    results_eligible = {}
    for score in ["ees_v2_score", "ees_v3_score"]:
        for hz, rcol, ccol in [
            ("5d", "excess_return_5d", "forward_complete_5d"),
            ("20d", "excess_return_20d", "forward_complete_20d"),
        ]:
            ic = per_date_ic(eligible_subset, score, rcol, ccol)
            key = f"eligible_{score}_{hz}"
            results_eligible[key] = ic
            logger.info(f"    eligible {score} {hz}: mean_ic={ic['mean_ic']} t={ic['t_stat']} n={ic['n_dates']}")

    # --- Method B 60d sensitivity ---
    logger.info("--- Method B 60d sensitivity (SENSITIVITY_ONLY) ---")
    results_60d = {}
    if joined_b:
        for score in EES_SCORE_COLS:
            ic = per_date_ic(joined_b, score, "excess_return_60d", "forward_complete_60d")
            key = f"{score}_60d_sensitivity"
            results_60d[key] = ic
            logger.info(f"  [SENSITIVITY] {score} vs 60d: mean_ic={ic['mean_ic']} t={ic['t_stat']} n={ic['n_dates']}")
    else:
        logger.info("  Method B panel not available")

    # --- Write joined panel CSV ---
    all_cols = list(joined[0].keys()) if joined else []
    with open(OUT_PANEL, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(joined)
    logger.info(f"Joined panel written: {OUT_PANEL} ({len(joined)} rows)")

    # --- Write validation report ---
    _write_report(cov, results, results_no_binary, quintiles, cohort_results, results_eligible, results_60d, joined)
    logger.info(f"Validation report written: {OUT_REPORT}")
    logger.info("=== EES validation complete ===")
    logger.info("DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE")


def _write_report(cov, results, results_no_binary, quintiles, cohort_results, results_eligible, results_60d, joined):
    lines = [
        "# EES Forward Validation — Machine-Readable Report",
        "",
        f"**Run date:** {RUN_DATE}  ",
        "**Governance:** DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE  ",
        f"**PIT panel:** gap_panel_method_a_{RUN_DATE}.csv (Method A, 5d/20d primary)  ",
        "",
        "## Coverage",
        "",
        f"- Total rows: {cov['total_rows']}",
        f"- Unique dates: {cov['total_dates']}",
        f"- Unique tickers: {cov['total_tickers']}",
        f"- ees_v2_score: {cov['has_ees_v2_score']} rows ({cov['pct_ees_v2_score']}%)",
        f"- ees_v3_score: {cov['has_ees_v3_score']} rows ({cov['pct_ees_v3_score']}%)",
        f"- base_rate_gap_score: {cov['has_base_rate_gap_score']} rows ({cov['pct_base_rate_gap_score']}%)",
        f"- catalyst_family: {cov['has_catalyst_family']} rows ({cov['pct_catalyst_family']}%)",
        f"- lead_program_phase: {cov['has_lead_program_phase']} rows ({cov['pct_lead_program_phase']}%)",
        f"- ees_eligible: {cov['ees_eligible_count']}",
        f"- binary_event_flags (|1d|>30%): {cov['binary_event_count']}",
        f"- atxs_excluded: {cov['atxs_excluded_count']}",
        "",
        "## Cross-sectional IC (full sample)",
        "",
        "| Score | Horizon | Mean IC | Median IC | Hit Rate | t-stat | N dates |",
        "|-------|---------|---------|-----------|----------|--------|---------|",
    ]
    for score in EES_SCORE_COLS:
        for hz in ["5d", "20d"]:
            ic = results.get(f"{score}_{hz}", {})
            lines.append(
                f"| {score} | {hz} | {ic.get('mean_ic', '—')} | {ic.get('median_ic', '—')} | "
                f"{ic.get('hit_rate', '—')} | {ic.get('t_stat', '—')} | {ic.get('n_dates', 0)} |"
            )

    lines += [
        "",
        "## IC excluding binary events (|1d return| > 30%)",
        "",
        "| Score | Horizon | Mean IC | t-stat | N dates |",
        "|-------|---------|---------|--------|---------|",
    ]
    for score in EES_SCORE_COLS:
        for hz in ["5d", "20d"]:
            ic = results_no_binary.get(f"{score}_{hz}_no_binary", {})
            lines.append(
                f"| {score} | {hz} | {ic.get('mean_ic', '—')} | {ic.get('t_stat', '—')} | {ic.get('n_dates', 0)} |"
            )

    lines += [
        "",
        "## Quintile spreads (top vs bottom quintile XBI-excess return)",
        "",
        "| Score | Horizon | Top Q | Bottom Q | Spread | N |",
        "|-------|---------|-------|----------|--------|---|",
    ]
    for score in EES_SCORE_COLS:
        for hz in ["5d", "20d"]:
            q = quintiles.get(f"{score}_{hz}", {})
            lines.append(
                f"| {score} | {hz} | {q.get('top_q_mean', '—')} | {q.get('bottom_q_mean', '—')} | "
                f"{q.get('spread', '—')} | {q.get('n', 0)} |"
            )

    lines += ["", "## EES-eligible subset IC", ""]
    for score in ["ees_v2_score", "ees_v3_score"]:
        for hz in ["5d", "20d"]:
            ic = results_eligible.get(f"eligible_{score}_{hz}", {})
            lines.append(
                f"- eligible {score} {hz}: mean_ic={ic.get('mean_ic', '—')} "
                f"t={ic.get('t_stat', '—')} n_dates={ic.get('n_dates', 0)}"
            )

    lines += ["", "## Cohort breakdown", ""]
    for key, ic in sorted(cohort_results.items()):
        if ic.get("n_dates", 0) >= 3:
            lines.append(
                f"- {key}: mean_ic={ic.get('mean_ic', '—')} t={ic.get('t_stat', '—')} n={ic.get('n_dates', 0)}"
            )

    lines += ["", "## Method B 60d sensitivity (SENSITIVITY_ONLY_NOT_PRIMARY_EVIDENCE)", ""]
    if results_60d:
        for key, ic in results_60d.items():
            lines.append(
                f"- [SENSITIVITY] {key}: mean_ic={ic.get('mean_ic', '—')} "
                f"t={ic.get('t_stat', '—')} n_dates={ic.get('n_dates', 0)}"
            )
    else:
        lines.append("- Method B panel not available")

    lines += ["", "---", "", "*Generated by scripts/research/ees_forward_validation.py*"]

    with open(OUT_REPORT, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
