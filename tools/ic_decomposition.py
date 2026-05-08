#!/usr/bin/env python3
"""IC Decomposition — coinvest_score_z attribution by cohort.

Read-only diagnostic. Joins the forward-returns panel with per-snapshot
rankings to compute:

  1. Overall Spearman IC of coinvest_score_z vs excess_return_5d
  2. IC decomposed by segment (stage_bucket, catalyst_quality)
  3. Top-30 walk-forward performance: mean/median excess return per snap date,
     cumulative EW return vs XBI

Architecture policy: ATTRIBUTION ONLY — does not modify rankings, scoring,
model weights, or any production artifact. Output is read-only diagnostic
for frozen-model behaviour study (policy: freeze architecture, study live).

PIT note: forward returns are genuinely out-of-sample (collected after each
snap date). This is the only valid evidence base (historical backtest is
invalidated per 2026-04-17 audit).

Statistical note: 14 snap dates yields ~37 effective observations (multi-day
overlap in 5d windows creates serial correlation). IC t-stats are indicative
only; treat as early signal not promotion-grade evidence. Promotion requires
Checklist v2 (FM + bootstrap + FDR + LOSO + year stab).

Usage:
    python3 tools/ic_decomposition.py
    python3 tools/ic_decomposition.py --as-of-date 2026-05-08
    python3 tools/ic_decomposition.py --dry-run          # print only, no artifact

Output:
    artifacts/ic_decomposition/YYYY-MM-DD_ic_decomp.json
    artifacts/ic_decomposition/YYYY-MM-DD_ic_decomp.md
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

SNAP_ROOT = PROJECT_ROOT / "data" / "snapshots"
PANEL_PATH = SNAP_ROOT / "_forward_returns_panel.csv"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "ic_decomposition"

FORWARD_COL = "excess_return_5d"
SIGNAL_COL = "coinvest_score_z"
RANK_COL = "actionable_rank"
TOP_N = 30

SEGMENT_COLS = ["stage_bucket", "catalyst_quality"]

# 2026-04-25: 4 new managers added to elite_core registry → inst_delta_z and
# coinvest rankings contaminated through ~2026-05-15 (per cohort-quarantine policy).
# Dates in [COHORT_CHANGE_DATE, COHORT_CLEAR_DATE) are flagged as contaminated.
COHORT_CHANGE_DATE = "2026-04-25"
COHORT_CLEAR_DATE = "2026-05-15"  # expected Q1 13F refresh landing


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _sf(v: Any) -> Optional[float]:
    if v in (None, "", "nan", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def spearman_ic(xs: List[float], ys: List[float]) -> Optional[float]:
    """Spearman rank correlation. Returns None if n < 5."""
    n = len(xs)
    if n < 5:
        return None
    rank_x = _rank_vector(xs)
    rank_y = _rank_vector(ys)
    mean_rx = sum(rank_x) / n
    mean_ry = sum(rank_y) / n
    num = sum((rank_x[i] - mean_rx) * (rank_y[i] - mean_ry) for i in range(n))
    den_x = math.sqrt(sum((r - mean_rx) ** 2 for r in rank_x))
    den_y = math.sqrt(sum((r - mean_ry) ** 2 for r in rank_y))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _rank_vector(vals: List[float]) -> List[float]:
    indexed = sorted(enumerate(vals), key=lambda x: x[1])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def ic_t_stat(ic: float, n: int) -> Optional[float]:
    """t-statistic for IC under H0: IC=0. Approx valid for n≥10."""
    if n < 5 or ic is None:
        return None
    denom = math.sqrt((1 - ic**2) / max(n - 2, 1))
    if denom == 0:
        return None
    return ic / denom


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_panel() -> Dict[str, Dict[str, Dict[str, float]]]:
    """Returns {snap_date: {ticker: {col: val}}}."""
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"Forward returns panel not found: {PANEL_PATH}")
    panel: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(dict)
    with PANEL_PATH.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("forward_complete", "").lower() != "true":
                continue
            snap = row["snap_date"]
            ticker = row["ticker"]
            fwd = _sf(row.get(FORWARD_COL))
            if fwd is not None:
                panel[snap][ticker] = {FORWARD_COL: fwd}
    return panel


def load_rankings(snap_date: str) -> List[Dict[str, str]]:
    p = SNAP_ROOT / snap_date / "rankings.csv"
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# IC computation
# ---------------------------------------------------------------------------


def compute_ic_for_date(
    snap_date: str,
    rows: List[Dict[str, str]],
    fwd_map: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    """Compute overall + segmented IC for one snap date."""
    pairs: List[Tuple[float, float, Dict[str, str]]] = []
    for r in rows:
        ticker = r.get("ticker", "")
        sig = _sf(r.get(SIGNAL_COL))
        fwd_entry = fwd_map.get(ticker)
        if sig is None or fwd_entry is None:
            continue
        fwd = fwd_entry.get(FORWARD_COL)
        if fwd is None:
            continue
        pairs.append((sig, fwd, r))

    n = len(pairs)
    overall_ic = spearman_ic([p[0] for p in pairs], [p[1] for p in pairs])

    # Segment breakdown
    segments: Dict[str, Dict[str, Any]] = {}
    for seg_col in SEGMENT_COLS:
        by_bucket: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        for sig, fwd, r in pairs:
            bucket = r.get(seg_col, "") or "unknown"
            by_bucket[bucket].append((sig, fwd))
        seg_result: Dict[str, Any] = {}
        for bucket, bucket_pairs in sorted(by_bucket.items()):
            sigs = [x[0] for x in bucket_pairs]
            fwds = [x[1] for x in bucket_pairs]
            ic = spearman_ic(sigs, fwds)
            seg_result[bucket] = {
                "n": len(bucket_pairs),
                "ic": round(ic, 4) if ic is not None else None,
                "mean_fwd": round(statistics.mean(fwds), 5) if fwds else None,
            }
        segments[seg_col] = seg_result

    # Top-30 excess return
    ranked = []
    for r in rows:
        ar = _sf(r.get(RANK_COL))
        ticker = r.get("ticker", "")
        if ar is not None and ar <= TOP_N and ticker in fwd_map:
            fwd_entry = fwd_map[ticker]
            fwd = fwd_entry.get(FORWARD_COL)
            if fwd is not None:
                ranked.append((ticker, ar, fwd))

    top30_mean = statistics.mean(x[2] for x in ranked) if ranked else None
    top30_median = statistics.median(x[2] for x in ranked) if ranked else None

    cohort_contaminated = COHORT_CHANGE_DATE <= snap_date < COHORT_CLEAR_DATE
    _t = ic_t_stat(overall_ic, n) if overall_ic is not None else None

    return {
        "snap_date": snap_date,
        "cohort_contaminated": cohort_contaminated,
        "n_obs": n,
        "ic": round(overall_ic, 4) if overall_ic is not None else None,
        "t_stat": round(_t, 2) if _t is not None else None,
        "segments": segments,
        "top30": {
            "n": len(ranked),
            "mean_excess_5d": round(top30_mean, 5) if top30_mean is not None else None,
            "median_excess_5d": round(top30_median, 5) if top30_median is not None else None,
            "tickers": [x[0] for x in sorted(ranked, key=lambda x: x[1])],
        },
    }


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------


def run(as_of_date: str, dry_run: bool) -> int:
    log.info("IC decomposition as of %s", as_of_date)

    panel = load_panel()
    snap_dates = sorted(panel.keys())
    if not snap_dates:
        log.error("No forward-complete entries in panel")
        return 2

    log.info("Panel covers %d snap dates: %s → %s", len(snap_dates), snap_dates[0], snap_dates[-1])

    date_results: List[Dict[str, Any]] = []
    for snap_date in snap_dates:
        rows = load_rankings(snap_date)
        if not rows:
            log.warning("No rankings.csv for %s — skipping", snap_date)
            continue
        result = compute_ic_for_date(snap_date, rows, panel[snap_date])
        date_results.append(result)
        ic_str = f"{result['ic']:+.4f}" if result["ic"] is not None else "n/a"
        t_str = f"t={result['t_stat']:+.2f}" if result["t_stat"] is not None else ""
        log.info(
            "  %s  n=%d  IC=%s %s  top30_mean=%s",
            snap_date,
            result["n_obs"],
            ic_str,
            t_str,
            f"{result['top30']['mean_excess_5d']:+.4f}" if result["top30"]["mean_excess_5d"] is not None else "n/a",
        )

    if not date_results:
        log.error("No results computed")
        return 2

    # Aggregate — split by cohort-contamination status
    clean_results = [r for r in date_results if not r["cohort_contaminated"]]
    dirty_results = [r for r in date_results if r["cohort_contaminated"]]

    all_ics = [r["ic"] for r in date_results if r["ic"] is not None]
    clean_ics = [r["ic"] for r in clean_results if r["ic"] is not None]
    dirty_ics = [r["ic"] for r in dirty_results if r["ic"] is not None]
    all_top30_mean = [r["top30"]["mean_excess_5d"] for r in date_results if r["top30"]["mean_excess_5d"] is not None]

    # Pool all (signal, fwd) pairs for a single aggregate IC
    pool_sig, pool_fwd = [], []
    for snap_date in snap_dates:
        rows = load_rankings(snap_date)
        fwd_map = panel.get(snap_date, {})
        for r in rows:
            sig = _sf(r.get(SIGNAL_COL))
            ticker = r.get("ticker", "")
            fwd_entry = fwd_map.get(ticker)
            if sig is None or fwd_entry is None:
                continue
            fwd = fwd_entry.get(FORWARD_COL)
            if fwd is not None:
                pool_sig.append(sig)
                pool_fwd.append(fwd)
    pooled_ic = spearman_ic(pool_sig, pool_fwd)
    pooled_t = ic_t_stat(pooled_ic, len(pool_sig)) if pooled_ic is not None else None

    # Segment aggregate (pool across all dates)
    # catalyst_quality only exists on snapshots from ~2026-05-08 onward
    seg_pool: Dict[str, Dict[str, Tuple[List[float], List[float]]]] = {
        c: defaultdict(lambda: ([], [])) for c in SEGMENT_COLS
    }
    seg_available_dates: Dict[str, int] = {c: 0 for c in SEGMENT_COLS}
    for snap_date in snap_dates:
        rows = load_rankings(snap_date)
        if not rows:
            continue
        fwd_map = panel.get(snap_date, {})
        # Detect which segments are actually populated for this snapshot
        sample = rows[0] if rows else {}
        seg_present = {c: c in sample and any(r.get(c, "") not in ("", None) for r in rows[:10]) for c in SEGMENT_COLS}
        for r in rows:
            sig = _sf(r.get(SIGNAL_COL))
            ticker = r.get("ticker", "")
            fwd_entry = fwd_map.get(ticker)
            if sig is None or fwd_entry is None:
                continue
            fwd = fwd_entry.get(FORWARD_COL)
            if fwd is None:
                continue
            for seg_col in SEGMENT_COLS:
                if not seg_present.get(seg_col):
                    continue
                bucket = r.get(seg_col, "") or "no_signal"
                seg_pool[seg_col][bucket][0].append(sig)
                seg_pool[seg_col][bucket][1].append(fwd)
        for seg_col in SEGMENT_COLS:
            if seg_present.get(seg_col):
                seg_available_dates[seg_col] += 1

    pooled_segments: Dict[str, Dict[str, Any]] = {}
    for seg_col, buckets in seg_pool.items():
        n_dates_with_data = seg_available_dates[seg_col]
        if not buckets:
            pooled_segments[seg_col] = {
                "_note": f"No data — column missing from all {len(snap_dates)} snapshots (added after this window)"
            }
            continue
        pooled_segments[seg_col] = {"_n_dates_with_data": n_dates_with_data}
        for bucket, (sigs, fwds) in sorted(buckets.items()):
            ic = spearman_ic(sigs, fwds)
            t = ic_t_stat(ic, len(sigs)) if ic is not None else None
            pooled_segments[seg_col][bucket] = {
                "n": len(sigs),
                "ic": round(ic, 4) if ic is not None else None,
                "t_stat": round(t, 2) if t is not None else None,
                "mean_fwd": round(statistics.mean(fwds), 5) if fwds else None,
            }

    # Cumulative top-30 EW return
    cum_top30 = 1.0
    cum_top30_series = []
    for r in date_results:
        m = r["top30"].get("mean_excess_5d")
        if m is not None:
            cum_top30 *= 1 + m
            cum_top30_series.append(round(cum_top30 - 1, 5))

    def _ic_summary(ics: List[float]) -> Dict[str, Any]:
        if not ics:
            return {"n_dates": 0}
        return {
            "n_dates": len(ics),
            "mean_ic": round(statistics.mean(ics), 4),
            "hit_rate": round(sum(1 for ic in ics if ic > 0) / len(ics), 3),
        }

    summary = {
        "schema": "ic_decomposition.v1",
        "as_of_date": as_of_date,
        "signal": SIGNAL_COL,
        "forward_col": FORWARD_COL,
        "n_snap_dates": len(date_results),
        "date_range": [snap_dates[0], snap_dates[-1]],
        "cohort_change_date": COHORT_CHANGE_DATE,
        "cohort_clear_date": COHORT_CLEAR_DATE,
        "pooled": {
            "n_obs": len(pool_sig),
            "ic": round(pooled_ic, 4) if pooled_ic is not None else None,
            "t_stat": round(pooled_t, 2) if pooled_t is not None else None,
        },
        "mean_rolling_ic": round(statistics.mean(all_ics), 4) if all_ics else None,
        "ic_hit_rate": round(sum(1 for ic in all_ics if ic > 0) / len(all_ics), 3) if all_ics else None,
        "pre_cohort_change": _ic_summary(clean_ics),
        "post_cohort_change_contaminated": _ic_summary(dirty_ics),
        "top30_mean_excess_5d_avg": round(statistics.mean(all_top30_mean), 5) if all_top30_mean else None,
        "top30_cumulative_excess": round(cum_top30 - 1, 5),
        "pooled_segments": pooled_segments,
        "per_date": date_results,
    }

    # Markdown report
    md = _render_md(summary)

    print(md)

    if not dry_run:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        json_path = ARTIFACTS_DIR / f"{as_of_date}_ic_decomp.json"
        md_path = ARTIFACTS_DIR / f"{as_of_date}_ic_decomp.md"
        json_path.write_text(json.dumps(summary, indent=2) + "\n")
        md_path.write_text(md)
        log.info("Artifacts written: %s", ARTIFACTS_DIR)

    return 0


def _render_md(s: Dict[str, Any]) -> str:
    pre = s.get("pre_cohort_change", {})
    dirty = s.get("post_cohort_change_contaminated", {})

    lines = [
        f"# IC Decomposition — {s['as_of_date']}",
        "",
        f"Signal: `{s['signal']}` vs `{s['forward_col']}`  |  "
        f"Dates: {s['date_range'][0]} → {s['date_range'][1]} ({s['n_snap_dates']} snapshots)",
        "",
        "## Overall (pooled across all dates)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Pooled IC (n={s['pooled']['n_obs']}) | {s['pooled']['ic']:+.4f} |",
        f"| Pooled t-stat | {s['pooled']['t_stat']:+.2f} |",
        f"| Mean rolling IC | {s['mean_rolling_ic']:+.4f} |",
        f"| IC hit rate (>0) | {s['ic_hit_rate']:.1%} |",
        f"| Top-30 avg excess 5d | {s['top30_mean_excess_5d_avg']:+.4f} |",
        f"| Top-30 cumulative excess | {s['top30_cumulative_excess']:+.4f} |",
        "",
        "## Cohort-change split",
        "",
        f"> Cohort change: {s['cohort_change_date']} (4 new managers added)."
        f" Contamination window: {s['cohort_change_date']} → {s['cohort_clear_date']} (expected 13F refresh).",
        "> Dates in contamination window are excluded from clean IC. Do NOT interpret dirty-window IC as signal evidence.",
        "",
        "| Window | n_dates | mean_IC | hit_rate |",
        "|---|---|---|---|",
        (
            f"| Pre-cohort-change (clean) | {pre.get('n_dates', 0)} | "
            f"{pre['mean_ic']:+.4f} | {pre['hit_rate']:.1%} |"
            if pre.get("n_dates")
            else "| Pre-cohort-change (clean) | 0 | — | — |"
        ),
        (
            f"| Post-cohort-change (contaminated) | {dirty.get('n_dates', 0)} | "
            f"{dirty['mean_ic']:+.4f} | {dirty['hit_rate']:.1%} |"
            if dirty.get("n_dates")
            else "| Post-cohort-change (contaminated) | 0 | — | — |"
        ),
        "",
        "## Segment decomposition",
        "",
    ]

    for seg_col, buckets in s["pooled_segments"].items():
        lines.append(f"### {seg_col}")
        lines.append("")
        note = buckets.get("_note") if isinstance(buckets, dict) else None
        n_dates = buckets.get("_n_dates_with_data") if isinstance(buckets, dict) else None
        if note:
            lines.append(f"_{note}_")
            lines.append("")
            continue
        if n_dates is not None:
            lines.append(f"_(data from {n_dates} snapshot(s))_")
            lines.append("")
        lines.append("| Bucket | n | IC | t-stat | mean_fwd |")
        lines.append("|---|---|---|---|---|")
        for bucket, stats in buckets.items():
            if bucket.startswith("_"):
                continue
            if not isinstance(stats, dict):
                continue
            ic_str = f"{stats['ic']:+.4f}" if stats.get("ic") is not None else "—"
            t_str = f"{stats['t_stat']:+.2f}" if stats.get("t_stat") is not None else "—"
            fwd_str = f"{stats['mean_fwd']:+.5f}" if stats.get("mean_fwd") is not None else "—"
            lines.append(f"| {bucket} | {stats['n']} | {ic_str} | {t_str} | {fwd_str} |")
        lines.append("")

    lines += [
        "## Per-date IC and Top-30 performance",
        "",
        "| Date | cohort | n | IC | t | top30_n | top30_mean_excess |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in s["per_date"]:
        ic_str = f"{r['ic']:+.4f}" if r["ic"] is not None else "—"
        t_str = f"{r['t_stat']:+.2f}" if r["t_stat"] is not None else "—"
        m = r["top30"].get("mean_excess_5d")
        m_str = f"{m:+.4f}" if m is not None else "—"
        cohort_tag = "⚠ contaminated" if r.get("cohort_contaminated") else "clean"
        lines.append(
            f"| {r['snap_date']} | {cohort_tag} | {r['n_obs']} | {ic_str} | {t_str} | {r['top30']['n']} | {m_str} |"
        )

    lines += [
        "",
        "---",
        "_Attribution only — architecture frozen. t-stats indicative at n≈14 snap dates (serial correlation from overlapping 5d windows)._",
        "_Note: snap dates 04-20 to 04-24 have 5d forward windows that extend into or past the 04-25 cohort change, yet are labeled_",
        '_"clean" by snap date. If pre-cohort IC < contaminated-window IC, the driver is more likely market regime (April selloff) than signal._',
        "_Promotion requires Checklist v2 (FM + bootstrap + FDR + LOSO + year stab). Verdict checkpoint: h20d=2026-05-26._",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--as-of-date", default=date.today().isoformat(), help="Artifact date (default: today)")
    p.add_argument("--dry-run", action="store_true", help="Print only; do not write artifact")
    args = p.parse_args(argv)
    return run(args.as_of_date, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
