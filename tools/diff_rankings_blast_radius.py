#!/usr/bin/env python3
"""diff_rankings_blast_radius.py — Quantify downstream impact of a data refresh.

Compares two rankings.csv files (before/after a data-quality change) and reports:
  - Top-N membership churn (who entered/left actionable_rank ≤ N)
  - Per-ticker rows affected (any column changed)
  - Per-column blast radius (count of tickers changed, mean abs delta for numeric)
  - Rank movement summary (max rank shift, mean rank shift)

Designed to satisfy the "blast-radius diff" requirement before shipping a
data-quality patch (per feedback_quarantine_blast_radius_diff.md).

Usage:
    python tools/diff_rankings_blast_radius.py \\
        --before data/snapshots/2026-04-24/rankings.csv \\
        --after  data/snapshots/2026-04-28/rankings.csv

    # Optional: write a markdown report
    python tools/diff_rankings_blast_radius.py \\
        --before <path> --after <path> \\
        --report artifacts/blast_radius/2026-04-28.md

    # Restrict to fields likely affected by a specific fetcher
    python tools/diff_rankings_blast_radius.py \\
        --before <path> --after <path> \\
        --field-prefix insider_,short_,days_to_cover,runway_,financial_score
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

TOP_N_DEFAULT = 30
NUMERIC_TOL = 1e-9


def load_rankings(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        rows = {}
        for row in reader:
            tkr = row.get("ticker") or row.get("Ticker")
            if not tkr:
                continue
            rows[tkr] = row
    if "ticker" not in cols and "Ticker" not in cols:
        sys.exit(f"ERROR: {path} has no 'ticker' column")
    return cols, rows


def safe_float(x: Optional[str]) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def values_equal(before: str, after: str) -> bool:
    if before == after:
        return True
    fb, fa = safe_float(before), safe_float(after)
    if fb is not None and fa is not None:
        return abs(fb - fa) < NUMERIC_TOL
    return False


def field_matches_prefix(field: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return True
    return any(field.startswith(p) for p in prefixes)


def diff(before_path: Path, after_path: Path, top_n: int, prefixes: list[str]) -> dict:
    before_cols, before_rows = load_rankings(before_path)
    after_cols, after_rows = load_rankings(after_path)

    before_tkrs = set(before_rows)
    after_tkrs = set(after_rows)
    shared = before_tkrs & after_tkrs

    schema_added = [c for c in after_cols if c not in before_cols]
    schema_removed = [c for c in before_cols if c not in after_cols]
    shared_cols = [c for c in after_cols if c in before_cols and c != "ticker"]

    # Top-N churn
    def top_set(rows: dict, n: int) -> set[str]:
        with_rank = []
        for tkr, row in rows.items():
            r = safe_float(row.get("actionable_rank"))
            if r is not None:
                with_rank.append((r, tkr))
        with_rank.sort()
        return {t for _, t in with_rank[:n]}

    top_before = top_set(before_rows, top_n)
    top_after = top_set(after_rows, top_n)

    entered = sorted(top_after - top_before)
    left = sorted(top_before - top_after)

    # Per-column blast radius
    col_changes: dict[str, int] = defaultdict(int)
    col_abs_delta: dict[str, list[float]] = defaultdict(list)
    tickers_changed: set[str] = set()
    rank_shifts: list[tuple[str, float]] = []

    for tkr in sorted(shared):
        b, a = before_rows[tkr], after_rows[tkr]
        ticker_dirty = False
        for col in shared_cols:
            if not field_matches_prefix(col, prefixes):
                continue
            bv, av = b.get(col, ""), a.get(col, "")
            if not values_equal(bv, av):
                col_changes[col] += 1
                ticker_dirty = True
                fb, fa = safe_float(bv), safe_float(av)
                if fb is not None and fa is not None:
                    col_abs_delta[col].append(abs(fa - fb))
        if ticker_dirty:
            tickers_changed.add(tkr)
        rb = safe_float(b.get("actionable_rank"))
        ra = safe_float(a.get("actionable_rank"))
        if rb is not None and ra is not None and rb != ra:
            rank_shifts.append((tkr, ra - rb))

    return {
        "before_path": str(before_path),
        "after_path": str(after_path),
        "before_count": len(before_tkrs),
        "after_count": len(after_tkrs),
        "shared_count": len(shared),
        "added_tickers": sorted(after_tkrs - before_tkrs),
        "removed_tickers": sorted(before_tkrs - after_tkrs),
        "schema_added": schema_added,
        "schema_removed": schema_removed,
        "top_n": top_n,
        "top_entered": entered,
        "top_left": left,
        "tickers_changed": sorted(tickers_changed),
        "col_changes": dict(col_changes),
        "col_mean_abs_delta": {c: (sum(v) / len(v)) for c, v in col_abs_delta.items() if v},
        "rank_shifts": rank_shifts,
        "field_prefix_filter": prefixes or None,
    }


def render_text(d: dict) -> str:
    lines = []
    lines.append("Blast-radius diff")
    lines.append(f"  before: {d['before_path']} ({d['before_count']} tickers)")
    lines.append(f"  after:  {d['after_path']} ({d['after_count']} tickers)")
    lines.append(f"  shared: {d['shared_count']} tickers")
    if d["field_prefix_filter"]:
        lines.append(f"  field filter: {','.join(d['field_prefix_filter'])}")
    lines.append("")

    if d["added_tickers"]:
        lines.append(f"Universe added (+{len(d['added_tickers'])}): {', '.join(d['added_tickers'][:20])}")
    if d["removed_tickers"]:
        lines.append(f"Universe removed (-{len(d['removed_tickers'])}): {', '.join(d['removed_tickers'][:20])}")
    if d["schema_added"]:
        lines.append(f"Schema added: {', '.join(d['schema_added'])}")
    if d["schema_removed"]:
        lines.append(f"Schema removed: {', '.join(d['schema_removed'])}")
    lines.append("")

    lines.append(f"Top-{d['top_n']} churn:")
    lines.append(f"  entered ({len(d['top_entered'])}): {', '.join(d['top_entered']) or '—'}")
    lines.append(f"  left    ({len(d['top_left'])}): {', '.join(d['top_left']) or '—'}")
    lines.append("")

    n_dirty = len(d["tickers_changed"])
    pct_dirty = (100.0 * n_dirty / d["shared_count"]) if d["shared_count"] else 0.0
    lines.append(f"Tickers with any field change: {n_dirty}/{d['shared_count']} ({pct_dirty:.1f}%)")

    shifts = d["rank_shifts"]
    if shifts:
        max_shift = max(shifts, key=lambda x: abs(x[1]))
        mean_shift = sum(abs(s) for _, s in shifts) / len(shifts)
        lines.append(
            f"Rank movement: {len(shifts)} tickers shifted, mean |Δrank|={mean_shift:.2f}, max |Δrank|={abs(max_shift[1]):.0f} ({max_shift[0]})"
        )
    lines.append("")

    if d["col_changes"]:
        lines.append("Top columns by tickers-changed:")
        ranked = sorted(d["col_changes"].items(), key=lambda x: -x[1])[:25]
        for col, n in ranked:
            mad = d["col_mean_abs_delta"].get(col)
            mad_str = f"  mean|Δ|={mad:.4g}" if mad is not None else "  (non-numeric)"
            lines.append(f"  {n:5d}  {col}{mad_str}")
    else:
        lines.append("No column changes detected (within numeric tolerance).")

    return "\n".join(lines)


def render_markdown(d: dict) -> str:
    lines = []
    lines.append("# Blast-radius diff\n")
    lines.append(f"- **before**: `{d['before_path']}` ({d['before_count']} tickers)")
    lines.append(f"- **after**: `{d['after_path']}` ({d['after_count']} tickers)")
    lines.append(f"- **shared**: {d['shared_count']} tickers")
    if d["field_prefix_filter"]:
        lines.append(f"- **field filter**: `{','.join(d['field_prefix_filter'])}`")
    lines.append("")

    lines.append(f"## Top-{d['top_n']} churn")
    lines.append(f"- entered ({len(d['top_entered'])}): {', '.join(d['top_entered']) or '—'}")
    lines.append(f"- left ({len(d['top_left'])}): {', '.join(d['top_left']) or '—'}")
    lines.append("")

    if d["added_tickers"] or d["removed_tickers"]:
        lines.append("## Universe changes")
        if d["added_tickers"]:
            lines.append(f"- added ({len(d['added_tickers'])}): {', '.join(d['added_tickers'])}")
        if d["removed_tickers"]:
            lines.append(f"- removed ({len(d['removed_tickers'])}): {', '.join(d['removed_tickers'])}")
        lines.append("")

    if d["schema_added"] or d["schema_removed"]:
        lines.append("## Schema changes")
        if d["schema_added"]:
            lines.append(f"- added: `{', '.join(d['schema_added'])}`")
        if d["schema_removed"]:
            lines.append(f"- removed: `{', '.join(d['schema_removed'])}`")
        lines.append("")

    n_dirty = len(d["tickers_changed"])
    pct_dirty = (100.0 * n_dirty / d["shared_count"]) if d["shared_count"] else 0.0
    lines.append("## Magnitude")
    lines.append(f"- tickers with any change: **{n_dirty}/{d['shared_count']} ({pct_dirty:.1f}%)**")

    shifts = d["rank_shifts"]
    if shifts:
        max_shift = max(shifts, key=lambda x: abs(x[1]))
        mean_shift = sum(abs(s) for _, s in shifts) / len(shifts)
        lines.append(
            f"- rank movement: {len(shifts)} shifted, mean |Δrank|={mean_shift:.2f}, max |Δrank|={abs(max_shift[1]):.0f} ({max_shift[0]})"
        )
    lines.append("")

    if d["col_changes"]:
        lines.append("## Columns by blast radius")
        lines.append("")
        lines.append("| tickers changed | column | mean \\|Δ\\| |")
        lines.append("|---:|---|---:|")
        ranked = sorted(d["col_changes"].items(), key=lambda x: -x[1])[:50]
        for col, n in ranked:
            mad = d["col_mean_abs_delta"].get(col)
            mad_str = f"{mad:.4g}" if mad is not None else "—"
            lines.append(f"| {n} | `{col}` | {mad_str} |")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", required=True, type=Path, help="Pre-change rankings.csv")
    parser.add_argument("--after", required=True, type=Path, help="Post-change rankings.csv")
    parser.add_argument(
        "--top-n", type=int, default=TOP_N_DEFAULT, help=f"Top-N for membership churn (default {TOP_N_DEFAULT})"
    )
    parser.add_argument(
        "--field-prefix", default="", help="Comma-separated column prefixes to filter (e.g. insider_,short_)"
    )
    parser.add_argument("--report", type=Path, help="Optional markdown report path")
    args = parser.parse_args()

    if not args.before.exists():
        sys.exit(f"ERROR: --before path does not exist: {args.before}")
    if not args.after.exists():
        sys.exit(f"ERROR: --after path does not exist: {args.after}")

    prefixes = [p.strip() for p in args.field_prefix.split(",") if p.strip()]
    result = diff(args.before, args.after, args.top_n, prefixes)

    print(render_text(result))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_markdown(result), encoding="utf-8")
        print(f"\nMarkdown report written: {args.report}")


if __name__ == "__main__":
    main()
