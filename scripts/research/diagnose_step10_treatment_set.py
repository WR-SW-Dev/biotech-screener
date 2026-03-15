#!/usr/bin/env python3
"""Step-10 treatment set diagnostic (pre-window-widening analysis).

Counts eligible names under current and proposed wider windows across
all dated snapshots to determine whether widening alone unblocks a
meaningful A/B harness.

Usage:
    python scripts/research/diagnose_step10_treatment_set.py
"""
from __future__ import annotations

import csv
import json
import logging
import re
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Set

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _sf(v: Any) -> float:
    if v is None or v == "":
        return float("nan")
    try:
        return float(v)
    except (ValueError, TypeError):
        return float("nan")


def _is_hard(row: dict) -> bool:
    v = str(row.get("is_hard_catalyst", "0")).strip().lower()
    return v in ("1", "1.0", "true")


def _has_oqc(row: dict) -> bool:
    v = str(row.get("options_quality_composite", "")).strip()
    return v not in ("", "0", "0.0")


def load_inferred_calendar(data_dir: Path) -> Dict[str, str]:
    """Load inferred_regulatory_dates.json → {ticker: inferred_pdufa_date}."""
    path = data_dir / "inferred_regulatory_dates.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        entries = data.get("entries", [])
        return {e["ticker"].upper(): e["pdufa_date"] for e in entries if e.get("pdufa_date")}
    except (json.JSONDecodeError, OSError):
        return {}


def analyze_snapshots(snapshots_dir: Path, inferred_calendar: Dict[str, str] = None) -> List[Dict[str, Any]]:
    if inferred_calendar is None:
        inferred_calendar = {}
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    results = []

    for d in sorted(snapshots_dir.iterdir()):
        if not d.is_dir() or not date_re.match(d.name):
            continue
        csv_path = d / "rankings.csv"
        if not csv_path.exists():
            continue

        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except (OSError, csv.Error):
            continue

        a_tickers: Set[str] = set()  # current_step10
        b_tickers: Set[str] = set()  # widened_regulatory
        c_tickers: Set[str] = set()  # broad_hard_window
        d_tickers: Set[str] = set()  # widened_regulatory_with_oqc
        e_tickers: Set[str] = set()  # current_step10_with_oqc
        f_tickers: Set[str] = set()  # broad_hard_window_with_oqc

        for row in rows:
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                continue

            has_reg = str(row.get("has_regulatory_upcoming_180d", "")).strip() == "1"
            reg_days = _sf(row.get("regulatory_days"))
            cat_days = _sf(row.get("catalyst_days"))
            hard = _is_hard(row)
            oqc = _has_oqc(row)

            # A: current Step-10
            if has_reg and reg_days > 90 and reg_days <= 180:
                a_tickers.add(ticker)
                if oqc:
                    e_tickers.add(ticker)

            # B: widened regulatory
            if has_reg and reg_days >= 61 and reg_days <= 210:
                b_tickers.add(ticker)
                if oqc:
                    d_tickers.add(ticker)

            # C: broad hard window
            if hard and cat_days >= 61 and cat_days <= 210:
                c_tickers.add(ticker)
                if oqc:
                    f_tickers.add(ticker)

        # G: Step-10-like with inferred entries admitted
        # Simulate: if inferred regulatory dates counted as has_regulatory_upcoming
        g_tickers: Set[str] = set(e_tickers)  # start with confirmed Step-10 + OQC
        snap_date_obj = None
        try:
            snap_date_obj = date.fromisoformat(d.name)
        except (ValueError, TypeError):
            pass

        if snap_date_obj:
            for inf_ticker, inf_date_str in inferred_calendar.items():
                if not inf_date_str:
                    continue
                try:
                    inf_date = date.fromisoformat(inf_date_str)
                    inf_days = (inf_date - snap_date_obj).days
                except (ValueError, TypeError):
                    continue
                # Would this name be Step-10 eligible if inferred date counted?
                if 91 <= inf_days <= 210:
                    # Check if it has OQC in this snapshot
                    for row in rows:
                        tk = (row.get("ticker") or "").strip().upper()
                        if tk == inf_ticker and _has_oqc(row):
                            g_tickers.add(tk)
                            break

        results.append(
            {
                "date": d.name,
                "n_total": len(rows),
                "A_current_step10": len(a_tickers),
                "B_widened_regulatory": len(b_tickers),
                "C_broad_hard_window": len(c_tickers),
                "D_widened_reg_oqc": len(d_tickers),
                "E_current_step10_oqc": len(e_tickers),
                "F_broad_hard_oqc": len(f_tickers),
                "G_step10_with_inferred_oqc": len(g_tickers),
                "G_delta_from_E": len(g_tickers) - len(e_tickers),
                "overlap_B_C": len(b_tickers & c_tickers),
                "overlap_D_F": len(d_tickers & f_tickers),
                "A_tickers": sorted(a_tickers),
                "B_tickers": sorted(b_tickers),
                "C_tickers": sorted(c_tickers),
            }
        )

    return results


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    conditions = [
        "A_current_step10",
        "B_widened_regulatory",
        "C_broad_hard_window",
        "D_widened_reg_oqc",
        "E_current_step10_oqc",
        "F_broad_hard_oqc",
        "G_step10_with_inferred_oqc",
    ]

    summary = {}
    for cond in conditions:
        vals = [r[cond] for r in results]
        summary[cond] = {
            "min": min(vals),
            "median": round(statistics.median(vals), 1),
            "max": max(vals),
            "dates_gte_5": sum(1 for v in vals if v >= 5),
            "dates_gte_10": sum(1 for v in vals if v >= 10),
            "dates_gte_15": sum(1 for v in vals if v >= 15),
            "dates_gte_20": sum(1 for v in vals if v >= 20),
            "n_dates": len(vals),
        }

    # Overlap stats
    overlap_bc = [r["overlap_B_C"] for r in results]
    overlap_df = [r["overlap_D_F"] for r in results]

    summary["overlap_B_C_median"] = round(statistics.median(overlap_bc), 1) if overlap_bc else 0
    summary["overlap_D_F_median"] = round(statistics.median(overlap_df), 1) if overlap_df else 0

    return summary


def main() -> int:
    snapshots_dir = PROJECT_ROOT / "data" / "snapshots"
    output_dir = PROJECT_ROOT / "output" / "step10_treatment_diagnostic"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Analyzing snapshots from %s ...", snapshots_dir)
    inferred_cal = load_inferred_calendar(PROJECT_ROOT / "production_data")
    logger.info("Loaded %d inferred regulatory entries", len(inferred_cal))
    results = analyze_snapshots(snapshots_dir, inferred_cal)
    logger.info("Analyzed %d snapshots", len(results))

    if not results:
        logger.warning("No snapshots found")
        return 1

    # CSV
    csv_path = output_dir / "step10_treatment_by_date.csv"
    fields = [
        "date",
        "n_total",
        "A_current_step10",
        "B_widened_regulatory",
        "C_broad_hard_window",
        "D_widened_reg_oqc",
        "E_current_step10_oqc",
        "F_broad_hard_oqc",
        "G_step10_with_inferred_oqc",
        "G_delta_from_E",
        "overlap_B_C",
        "overlap_D_F",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    # Summary JSON
    summary = summarize(results)
    summary["n_snapshots"] = len(results)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    # Markdown
    md = [
        "# Step-10 Treatment Set Diagnostic",
        "",
        f"**Snapshots analyzed**: {len(results)}",
        "",
        "## Condition Definitions",
        "",
        "| Code | Definition |",
        "|------|-----------|",
        "| A | has_regulatory_upcoming_180d=1, 90 < reg_days <= 180 (current Step-10) |",
        "| B | has_regulatory_upcoming_180d=1, 61 <= reg_days <= 210 (widened window) |",
        "| C | is_hard_catalyst=1, 61 <= catalyst_days <= 210 (broad hard) |",
        "| D | B + options_quality_composite > 0 |",
        "| E | A + options_quality_composite > 0 |",
        "| F | C + options_quality_composite > 0 |",
        "",
        "## Summary Statistics",
        "",
        "| Condition | Min | Median | Max | Dates >= 5 | Dates >= 10 | Dates >= 15 | Dates >= 20 |",
        "|-----------|-----|--------|-----|-----------|------------|------------|------------|",
    ]
    for cond in [
        "A_current_step10",
        "B_widened_regulatory",
        "C_broad_hard_window",
        "D_widened_reg_oqc",
        "E_current_step10_oqc",
        "F_broad_hard_oqc",
        "G_step10_with_inferred_oqc",
    ]:
        s = summary[cond]
        md.append(
            f"| {cond} | {s['min']} | {s['median']} | {s['max']} | {s['dates_gte_5']} | {s['dates_gte_10']} | {s['dates_gte_15']} | {s['dates_gte_20']} |"
        )

    md += [
        "",
        f"**Overlap B∩C median**: {summary['overlap_B_C_median']}",
        f"**Overlap D∩F median**: {summary['overlap_D_F_median']}",
    ]

    # Top 20 dates by widened regulatory
    top_b = sorted(results, key=lambda r: r["B_widened_regulatory"], reverse=True)[:20]
    md += [
        "",
        "## Top 20 Dates by Widened Regulatory (B)",
        "",
        "| Date | A | B | C | D | E | F |",
        "|------|---|---|---|---|---|---|",
    ]
    for r in top_b:
        md.append(
            f"| {r['date']} | {r['A_current_step10']} | {r['B_widened_regulatory']} | {r['C_broad_hard_window']} | {r['D_widened_reg_oqc']} | {r['E_current_step10_oqc']} | {r['F_broad_hard_oqc']} |"
        )

    # Verdict
    med_d = summary["D_widened_reg_oqc"]["median"]
    md += ["", "## Verdict", ""]
    if med_d >= 15:
        verdict = "WINDOW_WIDENING_LIKELY_SUFFICIENT"
    elif med_d >= 10:
        verdict = "WINDOW_WIDENING_POSSIBLY_SUFFICIENT_NEEDS_AB"
    else:
        verdict = "WINDOW_WIDENING_NOT_SUFFICIENT_CONSIDER_EXPANDING_TO_LATE_STAGE_CLINICAL"
        med_c = summary["C_broad_hard_window"]["median"]
        md.append(f"Widened regulatory with OQC median = {med_d} (below 10).")
        md.append(f"Broad hard-catalyst window median = {med_c}.")
        if med_c >= 15:
            md.append("Expanding to late-stage clinical hard catalysts would likely provide sufficient treatment set.")
        md.append("")
        md.append("Recommendation: create a NEW candidate for broad hard-catalyst [61,210]d window,")
        md.append("rather than mutating existing regulatory candidate 73113d54.")

    md.append(f"**Verdict**: `{verdict}`")
    md.append("")

    (output_dir / "summary.md").write_text("\n".join(md))
    logger.info("Output → %s", output_dir)

    # Print key stats
    for cond in ["A_current_step10", "B_widened_regulatory", "C_broad_hard_window", "D_widened_reg_oqc"]:
        s = summary[cond]
        logger.info(
            "  %s: median=%s, max=%s, dates>=10: %d/%d", cond, s["median"], s["max"], s["dates_gte_10"], s["n_dates"]
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
