"""Report generator — compact markdown reports from explorer outputs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

ANALYSIS_BANNER = (
    "> **ANALYSIS ONLY** — This report is generated from production data "
    "for operator review. It does not represent trading recommendations "
    "or model changes."
)


def _md_table(rows: List[Dict[str, Any]], columns: List[str]) -> str:
    """Render a simple markdown table."""
    if not rows:
        return "(no data)\n"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, sep]
    for row in rows:
        vals = [str(row.get(c, "")) for c in columns]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def snapshot_report(
    summary: Dict[str, Any],
    missingness_data: Dict[str, Any],
    gate_data: Dict[str, Dict[str, int]],
    top_n_df: pd.DataFrame,
    qa_data: Dict[str, Any],
    chart_paths: Optional[List[Path]] = None,
) -> str:
    """Generate a snapshot summary report in markdown."""
    lines = [
        f"# Snapshot Summary — {summary.get('snapshot_date', 'unknown')}",
        "",
        ANALYSIS_BANNER,
        "",
        f"**Source:** `{summary.get('source_path', 'N/A')}`",
        f"**Rows:** {summary.get('n_rows', 0)} | **Columns:** {summary.get('n_columns', 0)}",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Key Score Distributions",
        "",
    ]

    stats = summary.get("score_stats", {})
    if stats:
        stat_rows = []
        for col, s in stats.items():
            stat_rows.append(
                {
                    "Column": col,
                    "N": s.get("count", 0),
                    "Mean": s.get("mean", ""),
                    "Std": s.get("std", ""),
                    "Min": s.get("min", ""),
                    "Median": s.get("median", ""),
                    "Max": s.get("max", ""),
                }
            )
        lines.append(_md_table(stat_rows, ["Column", "N", "Mean", "Std", "Min", "Median", "Max"]))
    else:
        lines.append("(no score columns found)\n")

    # Top-N
    lines.extend(["", "## Top 10 by Rank", ""])
    if not top_n_df.empty:
        rows = top_n_df.head(10).to_dict("records")
        cols = list(top_n_df.columns)
        lines.append(_md_table(rows, cols))
    else:
        lines.append("(no ranked data)\n")

    # Gates
    lines.extend(["", "## Gate Pass/Fail", ""])
    if gate_data:
        for gate, counts in gate_data.items():
            parts = [f"{k}={v}" for k, v in counts.items()]
            lines.append(f"- **{gate}:** {', '.join(parts)}")
        lines.append("")
    else:
        lines.append("(no gate data)\n")

    # Missingness (top 10)
    lines.extend(["", "## Top Missingness", ""])
    top_missing = missingness_data.get("top_10_missing", [])
    if top_missing:
        miss_rows = [
            {
                "Column": m["column"],
                "N Missing": m["n_missing"],
                "% Missing": f"{m['pct_missing']}%",
            }
            for m in top_missing
            if m["pct_missing"] > 0
        ]
        if miss_rows:
            lines.append(_md_table(miss_rows, ["Column", "N Missing", "% Missing"]))
        else:
            lines.append("No missing values detected.\n")
    else:
        lines.append("(no missingness data)\n")

    # QA
    lines.extend(["", "## QA Checks", ""])
    issues = qa_data.get("issues", [])
    if issues:
        for issue in issues[:15]:
            sev = issue.get("severity", "info").upper()
            lines.append(f"- [{sev}] {issue.get('check', '')}: {issue.get('detail', '')}")
        lines.append("")
    else:
        lines.append("All checks passed.\n")

    # Charts
    if chart_paths:
        lines.extend(["", "## Charts", ""])
        for cp in chart_paths:
            if cp:
                lines.append(f"![{cp.stem}]({cp.name})")
        lines.append("")

    return "\n".join(lines) + "\n"


def comparison_report(comparison: Dict[str, Any]) -> str:
    """Generate a snapshot comparison report in markdown."""
    overlap = comparison.get("overlap", {})
    schema = comparison.get("schema", {})
    drift = comparison.get("top_drift", [])

    lines = [
        "# Snapshot Comparison",
        "",
        ANALYSIS_BANNER,
        "",
        f"**A:** `{comparison.get('path_a', '?')}` ({comparison.get('date_a', '?')}, {comparison.get('n_rows_a', '?')} rows)",
        f"**B:** `{comparison.get('path_b', '?')}` ({comparison.get('date_b', '?')}, {comparison.get('n_rows_b', '?')} rows)",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Top-N Overlap",
        "",
        f"- **N:** {overlap.get('n', 30)}",
        f"- **Overlap:** {overlap.get('overlap_count', 0)} ({overlap.get('overlap_pct', 0)}%)",
        f"- **Added:** {overlap.get('n_added', 0)} — {', '.join(overlap.get('added', [])[:10]) or '(none)'}",
        f"- **Removed:** {overlap.get('n_removed', 0)} — {', '.join(overlap.get('removed', [])[:10]) or '(none)'}",
        "",
        "## Schema Changes",
        "",
        f"- Common columns: {schema.get('n_common', 0)}",
    ]

    only_a = schema.get("only_in_a", [])
    only_b = schema.get("only_in_b", [])
    if only_a:
        lines.append(f"- Only in A: {', '.join(only_a[:10])}")
    if only_b:
        lines.append(f"- Only in B: {', '.join(only_b[:10])}")
    if not only_a and not only_b:
        lines.append("- Schemas are identical.")

    lines.extend(["", "## Largest Score Drifts (top 15)", ""])
    if drift:
        drift_rows = []
        for d in drift[:15]:
            tk = d["ticker"]
            for col, vals in d["deltas"].items():
                drift_rows.append(
                    {
                        "Ticker": tk,
                        "Score": col,
                        "Before": vals["before"],
                        "After": vals["after"],
                        "Delta": vals["delta"],
                    }
                )
        # Take top 20 individual field changes by abs delta
        drift_rows.sort(key=lambda x: -abs(x["Delta"]))
        lines.append(_md_table(drift_rows[:20], ["Ticker", "Score", "Before", "After", "Delta"]))
    else:
        lines.append("(no common tickers or score columns)\n")

    return "\n".join(lines) + "\n"


def qa_report(qa_data: Dict[str, Any]) -> str:
    """Generate a QA report in markdown."""
    lines = [
        "# Dataset QA Report",
        "",
        ANALYSIS_BANNER,
        "",
        f"**Rows:** {qa_data.get('n_rows', 0)} | **Columns:** {qa_data.get('n_columns', 0)}",
        f"**Issues found:** {qa_data.get('n_issues', 0)}",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    issues = qa_data.get("issues", [])
    if not issues:
        lines.append("All checks passed. No issues detected.")
        return "\n".join(lines) + "\n"

    by_severity = {"error": [], "warning": [], "info": []}
    for issue in issues:
        sev = issue.get("severity", "info")
        by_severity.setdefault(sev, []).append(issue)

    for sev in ("error", "warning", "info"):
        items = by_severity.get(sev, [])
        if items:
            lines.extend([f"## {sev.upper()} ({len(items)})", ""])
            for item in items:
                lines.append(f"- **{item['check']}**: {item['detail']}")
            lines.append("")

    return "\n".join(lines) + "\n"
