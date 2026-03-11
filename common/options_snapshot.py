"""Options diagnostics snapshot writer and per-run summary.

Writes a dedicated sidecar CSV + summary JSON/MD into the dated snapshot
directory, alongside rankings.csv.  This captures the full options
diagnostics state for prospective analysis without coupling to the
rankings schema.

Snapshot artefacts:
    options_diagnostics.csv          — one row per ticker with all 15 columns
    options_diagnostics_summary.json — coverage, flag distributions, top names
    options_diagnostics_summary.md   — human-readable summary
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from common.options_diagnostics import OPTIONS_DIAGNOSTIC_COLUMNS

logger = logging.getLogger(__name__)

# Columns written to the sidecar CSV (ticker + catalyst context + diagnostics)
SNAPSHOT_SIDECAR_COLUMNS = [
    "ticker",
    "catalyst_days",
    "catalyst_bucket",
    *OPTIONS_DIAGNOSTIC_COLUMNS,
]


def write_options_snapshot(
    snap_path: Path,
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
) -> Optional[Path]:
    """Write options diagnostics sidecar files into the snapshot directory.

    Parameters
    ----------
    snap_path : dated snapshot directory (e.g. data/snapshots/2026-03-11)
    csv_rows  : ranked rows (same list used for rankings.csv), already
                enriched with OPTIONS_DIAGNOSTIC_COLUMNS
    as_of_date : screen date (YYYY-MM-DD)

    Returns
    -------
    Path to options_diagnostics.csv, or None on failure.
    """
    if not csv_rows:
        return None

    # Filter to rows that have options data
    opt_rows = [r for r in csv_rows if str(r.get("opt_has_data", "0")) == "1"]

    # Always write the CSV (even if empty — signals "ran but no data")
    csv_path = snap_path / "options_diagnostics.csv"
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SNAPSHOT_SIDECAR_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in opt_rows:
                writer.writerow(row)
    except OSError as exc:
        logger.warning("Could not write options_diagnostics.csv: %s", exc)
        return None

    # Build summary
    summary = _build_summary(csv_rows, opt_rows, as_of_date)

    # Write JSON summary
    try:
        with open(snap_path / "options_diagnostics_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, sort_keys=False)
            f.write("\n")
    except OSError as exc:
        logger.warning("Could not write options_diagnostics_summary.json: %s", exc)

    # Write MD summary
    try:
        md = _format_summary_md(summary)
        with open(snap_path / "options_diagnostics_summary.md", "w", encoding="utf-8") as f:
            f.write(md)
    except OSError as exc:
        logger.warning("Could not write options_diagnostics_summary.md: %s", exc)

    logger.info(
        "[OPTIONS SNAPSHOT] %d/%d tickers with data → %s",
        len(opt_rows),
        len(csv_rows),
        csv_path,
    )
    return csv_path


def _build_summary(
    all_rows: List[Dict[str, Any]],
    opt_rows: List[Dict[str, Any]],
    as_of_date: str,
) -> Dict[str, Any]:
    """Build summary dict for the options diagnostics snapshot."""
    n_total = len(all_rows)
    n_with_data = len(opt_rows)

    # Flag distributions (only for rows with data)
    iv_regime_counts = Counter(r.get("opt_iv_regime", "") for r in opt_rows)
    event_premium_counts = Counter(r.get("opt_event_premium", "") for r in opt_rows)
    liquidity_ok_counts = Counter(str(r.get("opt_liquidity_ok", "")) for r in opt_rows)
    judgment_counts = Counter(r.get("opt_use_for_judgment", "") for r in opt_rows)

    # Top backwardation names (event_premium == YES, sorted by term_slope ascending)
    backwardation = []
    for r in opt_rows:
        if r.get("opt_event_premium") == "YES":
            slope = r.get("opt_term_slope", "")
            try:
                float(slope)
            except (ValueError, TypeError):
                pass
            backwardation.append(
                {
                    "ticker": r.get("ticker", ""),
                    "opt_term_slope": slope,
                    "opt_atm_iv": r.get("opt_atm_iv", ""),
                    "catalyst_days": r.get("catalyst_days", ""),
                }
            )
    backwardation.sort(key=lambda x: float(x.get("opt_term_slope") or 0))
    top_backwardation = backwardation[:10]

    # Top IV names
    iv_ranked = []
    for r in opt_rows:
        iv = r.get("opt_atm_iv", "")
        try:
            float(iv)
        except (ValueError, TypeError):
            continue
        iv_ranked.append({"ticker": r.get("ticker", ""), "opt_atm_iv": iv})
    iv_ranked.sort(key=lambda x: float(x["opt_atm_iv"]), reverse=True)
    top_iv = iv_ranked[:10]

    return {
        "schema": "options_diagnostics_summary.v1",
        "as_of_date": as_of_date,
        "coverage": {
            "n_universe": n_total,
            "n_with_options_data": n_with_data,
            "coverage_pct": round(n_with_data / max(n_total, 1) * 100, 1),
        },
        "flag_distributions": {
            "iv_regime": dict(sorted(iv_regime_counts.items())),
            "event_premium": dict(sorted(event_premium_counts.items())),
            "liquidity_ok": dict(sorted(liquidity_ok_counts.items())),
            "use_for_judgment": dict(sorted(judgment_counts.items())),
        },
        "top_backwardation": top_backwardation,
        "top_iv": top_iv,
    }


def _format_summary_md(summary: Dict[str, Any]) -> str:
    """Format summary as markdown."""
    cov = summary.get("coverage", {})
    flags = summary.get("flag_distributions", {})
    lines = [
        f"# Options Diagnostics Summary — {summary.get('as_of_date', '?')}",
        "",
        "## Coverage",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Universe | {cov.get('n_universe', 0)} |",
        f"| With options data | {cov.get('n_with_options_data', 0)} |",
        f"| Coverage % | {cov.get('coverage_pct', 0)}% |",
        "",
        "## Flag Distributions",
        "",
    ]

    for flag_name, counts in flags.items():
        lines.append(f"### {flag_name}")
        lines.append("")
        lines.append("| Value | Count |")
        lines.append("|-------|-------|")
        for val, cnt in counts.items():
            lines.append(f"| {val} | {cnt} |")
        lines.append("")

    # Top backwardation
    top_back = summary.get("top_backwardation", [])
    if top_back:
        lines.append("## Top Backwardation Names")
        lines.append("")
        lines.append("| Ticker | Term Slope | ATM IV | Catalyst Days |")
        lines.append("|--------|-----------|--------|--------------|")
        for row in top_back:
            lines.append(
                f"| {row.get('ticker', '')} "
                f"| {row.get('opt_term_slope', '')} "
                f"| {row.get('opt_atm_iv', '')} "
                f"| {row.get('catalyst_days', '')} |"
            )
        lines.append("")

    # Top IV
    top_iv = summary.get("top_iv", [])
    if top_iv:
        lines.append("## Top IV Names")
        lines.append("")
        lines.append("| Ticker | ATM IV |")
        lines.append("|--------|--------|")
        for row in top_iv:
            lines.append(f"| {row.get('ticker', '')} | {row.get('opt_atm_iv', '')} |")
        lines.append("")

    return "\n".join(lines) + "\n"
