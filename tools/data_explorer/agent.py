#!/usr/bin/env python3
"""Data Explorer Agent — CLI for analysis and reporting.

Usage:
    # Snapshot summary
    python -m tools.data_explorer.agent --summary data/snapshots/2026-04-13/rankings.csv

    # Compare two snapshots
    python -m tools.data_explorer.agent --compare data/snapshots/2026-04-12 data/snapshots/2026-04-13

    # QA check
    python -m tools.data_explorer.agent --qa data/snapshots/2026-04-13/rankings.csv

    # Catalog available artifacts
    python -m tools.data_explorer.agent --catalog data/snapshots/2026-04-13

    # Score distribution for a specific field
    python -m tools.data_explorer.agent --field selector_score data/snapshots/2026-04-13/rankings.csv

    # Top-N names
    python -m tools.data_explorer.agent --top-n 30 data/snapshots/2026-04-13/rankings.csv

    # Full daily report (summary + charts)
    python -m tools.data_explorer.agent --report daily data/snapshots/2026-04-13

Read-only. Does not modify production data.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from tools.data_explorer.catalog import catalog_summary
from tools.data_explorer.comparator import compare_snapshots
from tools.data_explorer.explorer import gate_counts, missingness, qa_checks, score_distributions, summarize, top_n
from tools.data_explorer.loader import load_file
from tools.data_explorer.reporter import comparison_report, qa_report, snapshot_report

logger = logging.getLogger("data_explorer")


def _output_dir(label: str = "") -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    name = f"{label}_{ts}" if label else ts
    out = Path("reports/data_explorer") / name
    out.mkdir(parents=True, exist_ok=True)
    return out


def _load_rankings(path_str: str) -> pd.DataFrame:
    """Load rankings.csv — accepts file path or snapshot directory."""
    path = Path(path_str)
    if path.is_dir():
        rankings_path = path / "rankings.csv"
        if rankings_path.exists():
            return load_file(rankings_path)
        raise FileNotFoundError(f"No rankings.csv in {path}")
    return load_file(path)


def cmd_summary(args: argparse.Namespace) -> None:
    """Print and save a snapshot summary."""
    df = _load_rankings(args.path)
    s = summarize(df)
    m = missingness(df)
    g = gate_counts(df)
    t = top_n(df, n=10)
    qa = qa_checks(df)

    # Print to stdout
    print(f"\n=== Snapshot Summary: {s.get('snapshot_date', 'unknown')} ===")
    print(f"Rows: {s['n_rows']}  Columns: {s['n_columns']}")
    print(f"Source: {s['source_path']}")
    print()

    stats = s.get("score_stats", {})
    if stats:
        print("Key Scores:")
        for col, st in stats.items():
            print(f"  {col:30s}  N={st['count']:4d}  mean={st['mean']:8.4f}  median={st['median']:8.4f}")
    print()

    if not t.empty:
        print("Top 10:")
        print(t.to_string(index=False))
    print()

    for gate, counts in g.items():
        parts = [f"{k}={v}" for k, v in counts.items()]
        print(f"  {gate}: {', '.join(parts)}")
    print()

    if qa["n_issues"] > 0:
        print(f"QA Issues: {qa['n_issues']}")
        for issue in qa["issues"][:10]:
            print(f"  [{issue['severity']}] {issue['check']}: {issue['detail']}")
    else:
        print("QA: all checks passed")

    # Generate charts and report
    out_dir = _output_dir("summary")
    chart_paths = []
    try:
        from tools.data_explorer.viz import plot_gate_bars, plot_score_distributions

        cp = plot_score_distributions(df, out_path=out_dir / "score_distributions.png")
        if cp:
            chart_paths.append(cp)
        gp = plot_gate_bars(g, out_path=out_dir / "gate_bars.png")
        if gp:
            chart_paths.append(gp)
    except ImportError:
        logger.debug("matplotlib not available, skipping charts")

    report_md = snapshot_report(s, m, g, t, qa, chart_paths)
    report_path = out_dir / "snapshot_summary.md"
    report_path.write_text(report_md)
    print(f"\nReport saved: {report_path}")
    if chart_paths:
        print(f"Charts: {', '.join(str(p) for p in chart_paths)}")


def cmd_compare(args: argparse.Namespace) -> None:
    """Compare two snapshots."""
    df_a = _load_rankings(args.path_a)
    df_b = _load_rankings(args.path_b)

    comp = compare_snapshots(df_a, df_b, n=args.n)
    overlap = comp["overlap"]

    print("\n=== Snapshot Comparison ===")
    print(f"A: {comp['date_a']} ({comp['n_rows_a']} rows)")
    print(f"B: {comp['date_b']} ({comp['n_rows_b']} rows)")
    print()
    print(f"Top-{args.n} overlap: {overlap['overlap_count']} ({overlap['overlap_pct']}%)")
    if overlap["added"]:
        print(f"  Added:   {', '.join(overlap['added'])}")
    if overlap["removed"]:
        print(f"  Removed: {', '.join(overlap['removed'])}")
    print()

    drift = comp.get("top_drift", [])
    if drift:
        print("Largest score drifts:")
        for d in drift[:10]:
            top_delta = max(d["deltas"].items(), key=lambda x: abs(x[1]["delta"]))
            col, vals = top_delta
            print(f"  {d['ticker']:8s}  {col}: {vals['before']:.4f} → {vals['after']:.4f} (Δ {vals['delta']:+.4f})")
    print()

    schema = comp.get("schema", {})
    if schema.get("only_in_a"):
        print(f"Columns only in A: {', '.join(schema['only_in_a'][:10])}")
    if schema.get("only_in_b"):
        print(f"Columns only in B: {', '.join(schema['only_in_b'][:10])}")

    # Save report
    out_dir = _output_dir("compare")
    report_md = comparison_report(comp)
    report_path = out_dir / "comparison_report.md"
    report_path.write_text(report_md)
    print(f"\nReport saved: {report_path}")

    try:
        from tools.data_explorer.viz import plot_overlap_chart, plot_rank_comparison

        plot_overlap_chart(overlap, out_path=out_dir / "overlap_chart.png")
        plot_rank_comparison(df_a, df_b, n=args.n, out_path=out_dir / "rank_comparison.png")
        print(f"Charts saved in: {out_dir}")
    except ImportError:
        pass


def cmd_qa(args: argparse.Namespace) -> None:
    """Run QA checks on a dataset."""
    df = _load_rankings(args.path)
    qa = qa_checks(df)

    print("\n=== QA Report ===")
    print(f"Rows: {qa['n_rows']}  Columns: {qa['n_columns']}")
    print(f"Issues: {qa['n_issues']}")
    print()

    for issue in qa["issues"]:
        print(f"  [{issue['severity'].upper():7s}] {issue['check']}: {issue['detail']}")

    if qa["n_issues"] == 0:
        print("  All checks passed.")

    out_dir = _output_dir("qa")
    report_md = qa_report(qa)
    report_path = out_dir / "qa_report.md"
    report_path.write_text(report_md)
    print(f"\nReport saved: {report_path}")


def cmd_catalog(args: argparse.Namespace) -> None:
    """List available artifacts in a snapshot directory."""
    cat = catalog_summary(args.path)

    print(f"\n=== Artifact Catalog: {cat['snapshot_date']} ===")
    print(f"Directory: {cat['snapshot_dir']}")
    print(f"Total artifacts: {cat['n_artifacts']}")
    print()

    for category, files in cat["by_category"].items():
        print(f"  {category.upper()}:")
        for f in files:
            info = cat["artifacts"][f]
            size_kb = info["size_bytes"] / 1024
            desc = info["description"]
            print(f"    {f:45s} {size_kb:8.1f} KB  {desc}")
    print()


def cmd_field(args: argparse.Namespace) -> None:
    """Show detailed stats for a specific field."""
    df = _load_rankings(args.path)
    field = args.field

    if field not in df.columns:
        print(f"Error: column '{field}' not found. Available: {', '.join(sorted(df.columns)[:20])}...")
        sys.exit(1)

    dist = score_distributions(df, columns=[field])
    if field in dist:
        print(f"\n=== {field} ===")
        for k, v in dist[field].items():
            print(f"  {k:12s}: {v}")
    else:
        print(f"\n{field}: no numeric data")

    # Value counts for non-numeric
    vals = df[field].value_counts().head(20)
    if len(vals) <= 20:
        print("\nValue counts (top 20):")
        for v, c in vals.items():
            print(f"  {str(v):40s}  {c}")


def cmd_top_n(args: argparse.Namespace) -> None:
    """Show top-N ranked names."""
    df = _load_rankings(args.path)
    t = top_n(df, n=args.n)
    if t.empty:
        print("No ranked data found.")
    else:
        print(f"\n=== Top {args.n} ===\n")
        print(t.to_string(index=False))


def cmd_report_daily(args: argparse.Namespace) -> None:
    """Generate a full daily report with charts."""
    snap_dir = Path(args.path)
    if not snap_dir.is_dir():
        print(f"Error: {snap_dir} is not a directory")
        sys.exit(1)

    # Load rankings
    df = _load_rankings(str(snap_dir))
    s = summarize(df)
    m = missingness(df)
    g = gate_counts(df)
    t = top_n(df, n=30)
    qa = qa_checks(df)

    # Generate everything
    out_dir = _output_dir("daily")
    chart_paths = []

    try:
        from tools.data_explorer.viz import plot_gate_bars, plot_score_distributions

        cp = plot_score_distributions(
            df,
            out_path=out_dir / "score_distributions.png",
            title_prefix=f"{s.get('snapshot_date', '')} ",
        )
        if cp:
            chart_paths.append(cp)
        gp = plot_gate_bars(g, out_path=out_dir / "gate_bars.png")
        if gp:
            chart_paths.append(gp)
    except ImportError:
        pass

    # Comparison with prior snapshot if available
    snapshots_dir = snap_dir.parent
    from tools.data_explorer.catalog import list_snapshot_dates

    dates = list_snapshot_dates(snapshots_dir)
    current_date = snap_dir.name[:10]
    prior_dates = [d for d in dates if d < current_date]

    comp_section = ""
    if prior_dates:
        prior_dir = snapshots_dir / prior_dates[0]
        prior_path = prior_dir / "rankings.csv"
        if prior_path.exists():
            df_prior = load_file(prior_path)
            comp = compare_snapshots(df, df_prior, n=30)
            comp_section = comparison_report(comp)

            try:
                from tools.data_explorer.viz import plot_overlap_chart, plot_rank_comparison

                op = plot_overlap_chart(comp["overlap"], out_path=out_dir / "overlap_chart.png")
                if op:
                    chart_paths.append(op)
                rp = plot_rank_comparison(df_prior, df, n=30, out_path=out_dir / "rank_comparison.png")
                if rp:
                    chart_paths.append(rp)
            except ImportError:
                pass

    # Write report
    report = snapshot_report(s, m, g, t, qa, chart_paths)
    if comp_section:
        report += "\n---\n\n" + comp_section

    # Catalog
    cat = catalog_summary(snap_dir)
    report += "\n---\n\n## Artifact Catalog\n\n"
    for category, files in cat["by_category"].items():
        report += f"### {category.upper()}\n"
        for f in files:
            info = cat["artifacts"][f]
            report += f"- `{f}` ({info['size_bytes'] / 1024:.1f} KB) — {info['description']}\n"
        report += "\n"

    report_path = out_dir / "daily_report.md"
    report_path.write_text(report)

    print(f"Daily report saved: {report_path}")
    print(f"Charts: {len(chart_paths)}")
    print(f"Output directory: {out_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Data Explorer Agent — analysis and reporting for biotech screener",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command")

    # Summary
    p_summary = sub.add_parser("summary", help="Snapshot summary")
    p_summary.add_argument("path", help="Path to rankings.csv or snapshot directory")

    # Compare
    p_compare = sub.add_parser("compare", help="Compare two snapshots")
    p_compare.add_argument("path_a", help="Path A (earlier)")
    p_compare.add_argument("path_b", help="Path B (later)")
    p_compare.add_argument("-n", type=int, default=30, help="Top-N for overlap (default: 30)")

    # QA
    p_qa = sub.add_parser("qa", help="Run QA checks")
    p_qa.add_argument("path", help="Path to rankings.csv or snapshot directory")

    # Catalog
    p_catalog = sub.add_parser("catalog", help="List available artifacts")
    p_catalog.add_argument("path", help="Path to snapshot directory")

    # Field
    p_field = sub.add_parser("field", help="Show stats for a specific field")
    p_field.add_argument("field", help="Column name")
    p_field.add_argument("path", help="Path to rankings.csv or snapshot directory")

    # Top-N
    p_topn = sub.add_parser("top-n", help="Show top-N ranked names")
    p_topn.add_argument("path", help="Path to rankings.csv or snapshot directory")
    p_topn.add_argument("-n", type=int, default=30, help="Number of names (default: 30)")

    # Daily report
    p_daily = sub.add_parser("daily", help="Generate full daily report")
    p_daily.add_argument("path", help="Path to snapshot directory")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    if args.command is None:
        parser.print_help()
        return 1

    commands = {
        "summary": cmd_summary,
        "compare": cmd_compare,
        "qa": cmd_qa,
        "catalog": cmd_catalog,
        "field": cmd_field,
        "top-n": cmd_top_n,
        "daily": cmd_report_daily,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
