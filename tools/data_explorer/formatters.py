"""Output formatters — render response envelopes to text or JSON.

Every format_* function takes a response envelope dict and returns a string.
"""

from __future__ import annotations

import json
from typing import Any, Dict

# ---------------------------------------------------------------------------
# JSON formatter (universal)
# ---------------------------------------------------------------------------


def format_json(resp: Dict[str, Any], *, indent: int = 2) -> str:
    """Render any response envelope as pretty JSON."""
    return json.dumps(resp, indent=indent, default=str)


# ---------------------------------------------------------------------------
# Text formatters (per-command)
# ---------------------------------------------------------------------------


def format_summary_text(resp: Dict[str, Any]) -> str:
    """Human-readable summary output."""
    d = resp["data"]
    lines = [
        f"\n=== Snapshot Summary: {resp.get('snapshot_date', 'unknown')} ===",
        f"Rows: {d['rows']}  Columns: {d['columns']}",
        f"Source: {d['source']}",
        "",
    ]

    stats = d.get("score_stats", {})
    if stats:
        lines.append("Key Scores:")
        for col, st in stats.items():
            lines.append(f"  {col:30s}  N={st['count']:4d}  " f"mean={st['mean']:8.4f}  median={st['median']:8.4f}")
    lines.append("")

    top10 = d.get("top_10", [])
    if top10:
        lines.append("Top 10:")
        # Build aligned table
        cols = list(top10[0].keys()) if top10 else []
        if cols:
            header = "  ".join(f"{c:>14s}" for c in cols)
            lines.append(f"  {header}")
            for row in top10:
                vals = "  ".join(f"{str(row.get(c, '')):>14s}" for c in cols)
                lines.append(f"  {vals}")
    lines.append("")

    gates = d.get("gates", {})
    for gate, counts in gates.items():
        parts = [f"{k}={v}" for k, v in counts.items()]
        lines.append(f"  {gate}: {', '.join(parts)}")
    lines.append("")

    qa = d.get("qa", {})
    n_issues = qa.get("n_issues", 0)
    if n_issues > 0:
        lines.append(f"QA Issues: {n_issues}")
        for issue in qa.get("issues", [])[:10]:
            lines.append(f"  [{issue['severity']}] {issue['check']}: {issue['detail']}")
    else:
        lines.append("QA: all checks passed")

    return "\n".join(lines)


def format_compare_text(resp: Dict[str, Any]) -> str:
    """Human-readable comparison output."""
    d = resp["data"]
    lines = [
        "\n=== Snapshot Comparison ===",
        f"A: {d['snapshot_a']} ({d['n_rows_a']} rows)",
        f"B: {d['snapshot_b']} ({d['n_rows_b']} rows)",
        "",
        f"Top-{d['top_n']} overlap: {d['overlap_count']} ({d['overlap_pct']}%)",
    ]
    if d.get("added"):
        lines.append(f"  Added:   {', '.join(d['added'])}")
    if d.get("removed"):
        lines.append(f"  Removed: {', '.join(d['removed'])}")
    lines.append("")

    drifts = d.get("largest_rank_changes", [])
    if drifts:
        lines.append("Largest score drifts:")
        for item in drifts[:10]:
            deltas = item.get("deltas", {})
            if deltas:
                top_col = max(deltas.items(), key=lambda x: abs(x[1]["delta"]))
                col, vals = top_col
                lines.append(
                    f"  {item['ticker']:8s}  {col}: "
                    f"{vals['before']:.4f} -> {vals['after']:.4f} "
                    f"(d {vals['delta']:+.4f})"
                )
    lines.append("")

    schema = d.get("schema", {})
    if schema.get("only_in_a"):
        lines.append(f"Columns only in A: {', '.join(schema['only_in_a'][:10])}")
    if schema.get("only_in_b"):
        lines.append(f"Columns only in B: {', '.join(schema['only_in_b'][:10])}")

    return "\n".join(lines)


def format_qa_text(resp: Dict[str, Any]) -> str:
    """Human-readable QA report."""
    d = resp["data"]
    lines = [
        "\n=== QA Report ===",
        f"Rows: {d['rows']}  Columns: {d['columns']}",
        f"Issues: {d['n_issues']}",
        "",
    ]

    sev = d.get("severity_summary", {})
    if any(sev.values()):
        parts = [f"{k}={v}" for k, v in sev.items() if v > 0]
        lines.append(f"  Severity: {', '.join(parts)}")
        lines.append("")

    for issue in d.get("issues", []):
        lines.append(f"  [{issue['severity'].upper():7s}] {issue['check']}: {issue['detail']}")

    if d["n_issues"] == 0:
        lines.append("  All checks passed.")

    return "\n".join(lines)


def format_catalog_text(resp: Dict[str, Any]) -> str:
    """Human-readable artifact catalog."""
    d = resp["data"]
    lines = [
        f"\n=== Artifact Catalog: {resp.get('snapshot_date', '')} ===",
        f"Directory: {d['snapshot_dir']}",
        f"Total artifacts: {d['artifact_count']}",
        "",
    ]

    for category, files in d.get("by_category", {}).items():
        lines.append(f"  {category.upper()}:")
        for art in d.get("artifacts", []):
            if art["name"] in files:
                size_kb = art["size_bytes"] / 1024
                lines.append(f"    {art['name']:45s} {size_kb:8.1f} KB  {art['description']}")
    lines.append("")

    return "\n".join(lines)


def format_field_text(resp: Dict[str, Any]) -> str:
    """Human-readable field stats."""
    if not resp.get("ok"):
        return "\n".join(resp.get("errors", ["Unknown error"]))

    d = resp["data"]
    field = d["field"]
    lines = [f"\n=== {field} ==="]

    for key in (
        "count",
        "missing_count",
        "missing_pct",
        "zero_count",
        "zero_pct",
        "unique_count",
        "mean",
        "std",
        "min",
        "p5",
        "p25",
        "median",
        "p75",
        "p95",
        "max",
        "n_zero",
        "n_negative",
    ):
        if key in d and d[key] is not None:
            lines.append(f"  {key:12s}: {d[key]}")

    top = d.get("top_values", [])
    if top:
        lines.append("\n  Top values:")
        for v in top:
            lines.append(f"    {v['ticker']:10s}  {v['value']}")

    bottom = d.get("bottom_values", [])
    if bottom:
        lines.append("\n  Bottom values:")
        for v in bottom:
            lines.append(f"    {v['ticker']:10s}  {v['value']}")

    vc = d.get("value_counts", [])
    if vc and len(vc) <= 20:
        lines.append("\n  Value counts (top 20):")
        for v in vc:
            lines.append(f"    {v['value']:40s}  {v['count']}")

    return "\n".join(lines)


def format_top_n_text(resp: Dict[str, Any]) -> str:
    """Human-readable top-N."""
    d = resp["data"]
    rows = d.get("rows", [])
    n = d.get("n", 30)

    if not rows:
        return "No ranked data found."

    lines = [f"\n=== Top {n} ===\n"]
    cols = list(rows[0].keys())
    header = "  ".join(f"{c:>14s}" for c in cols)
    lines.append(header)
    for row in rows:
        vals = "  ".join(f"{str(row.get(c, '')):>14s}" for c in cols)
        lines.append(vals)

    return "\n".join(lines)


def format_daily_text(resp: Dict[str, Any]) -> str:
    """Human-readable daily summary (compact stdout version)."""
    d = resp["data"]
    lines = [
        f"\n=== Daily Report: {d.get('snapshot_date', '?')} ===",
    ]

    prior = d.get("prior_snapshot_date")
    if prior:
        lines.append(f"Prior: {prior}")

    # Summary headline
    summary = d.get("summary", {})
    lines.append(f"Rows: {summary.get('rows', '?')}  Columns: {summary.get('columns', '?')}")

    # QA headline
    qa = d.get("qa", {})
    sev = qa.get("severity_summary", {})
    exit_code = qa.get("exit_code", 0)
    status = {0: "CLEAN", 1: "WARNINGS", 2: "ERROR"}.get(exit_code, "?")
    lines.append(f"QA: {status} ({qa.get('n_issues', 0)} issues)")
    if sev:
        parts = [f"{k}={v}" for k, v in sev.items() if v > 0]
        if parts:
            lines.append(f"  {', '.join(parts)}")

    # Compare headline
    compare = d.get("compare")
    if compare:
        lines.append(f"Top-30 overlap: {compare.get('overlap_count', '?')} " f"({compare.get('overlap_pct', '?')}%)")
        added = compare.get("added", [])
        removed = compare.get("removed", [])
        if added:
            lines.append(f"  Added:   {', '.join(added)}")
        if removed:
            lines.append(f"  Removed: {', '.join(removed)}")

    # Catalog headline
    catalog = d.get("catalog", {})
    lines.append(f"Artifacts: {catalog.get('artifact_count', '?')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_TEXT_FORMATTERS = {
    "summary": format_summary_text,
    "compare": format_compare_text,
    "qa": format_qa_text,
    "catalog": format_catalog_text,
    "field": format_field_text,
    "top-n": format_top_n_text,
    "daily": format_daily_text,
}


def format_response(resp: Dict[str, Any], fmt: str = "text") -> str:
    """Format a response envelope as text or JSON."""
    if fmt == "json":
        return format_json(resp)

    command = resp.get("command", "")
    formatter = _TEXT_FORMATTERS.get(command)
    if formatter:
        return formatter(resp)

    # Fallback: pretty-print the data
    return format_json(resp)
