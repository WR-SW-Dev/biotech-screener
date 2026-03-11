#!/usr/bin/env python3
"""Weekly catalyst/regulatory date slip tracker.

Compares consecutive weekly snapshots to detect catalyst_days changes per ticker.
Emits:
  artifacts/calendar_slips/<as_of_date>/slips.csv
  artifacts/calendar_slips/<as_of_date>/slip_summary.md

Usage:
    python3 tools/track_calendar_slips.py --as-of-date 2026-03-10
    python3 tools/track_calendar_slips.py --as-of-date 2026-03-10 --snap-root data/snapshots
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import SNAPSHOTS_ROOT

ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts" / "calendar_slips"

SCHEMA_VERSION = "calendar_slips.v1"
DEFAULT_LOOKBACK_DAYS = 7
LARGE_SLIP_THRESHOLD = 14  # days

# Columns extracted from rankings.csv for slip tracking
_TRACKING_COLS = [
    "catalyst_days",
    "catalyst_mode",
    "catalyst_source",
    "catalyst_event_type",
    "catalyst_reason_detail",
    "de_catalyst_days",
    "de_catalyst_mode",
    "confidence_overall",
]

SLIPS_COLUMNS = [
    "ticker",
    "family",
    "prior_days",
    "current_days",
    "delta_days",
    "expected_days",
    "slip_days",
    "prior_event_type",
    "current_event_type",
    "prior_source",
    "current_source",
    "prior_confidence",
    "current_confidence",
    "prior_mode",
    "current_mode",
    "prior_snapshot_date",
    "current_snapshot_date",
    "new_flag",
    "dropped_flag",
    "large_slip",
    "imminent",
]


# ---------------------------------------------------------------------------
# Production-path guards
# ---------------------------------------------------------------------------


def _in_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _assert_not_production_default(name: str, value: Path, production_default: Path) -> None:
    if _in_pytest() and value == production_default:
        raise AssertionError(f"Tests must pass `{name}` explicitly — got production default {production_default}")


# ---------------------------------------------------------------------------
# Snapshot loading
# ---------------------------------------------------------------------------


def load_snapshot_calendar(snap_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load rankings.csv and extract calendar-relevant fields per ticker.

    Returns {ticker: {field: value, ...}}.
    """
    rankings_path = snap_dir / "rankings.csv"
    if not rankings_path.is_file():
        return {}

    result = {}
    with open(rankings_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip()
            if not ticker:
                continue
            eligible = row.get("eligible", "1")
            if eligible == "0":
                continue

            entry: Dict[str, Any] = {}
            for col in _TRACKING_COLS:
                entry[col] = row.get(col, "")

            # Parse catalyst_days as int (or None)
            raw_days = entry.get("catalyst_days", "")
            try:
                entry["_days_int"] = int(float(raw_days)) if raw_days.strip() else None
            except (ValueError, TypeError):
                entry["_days_int"] = None

            # Infer family from event_type or mode
            entry["_family"] = _infer_family(entry)

            result[ticker] = entry

    return result


def _infer_family(entry: Dict[str, Any]) -> str:
    """Infer REGULATORY / CLINICAL / OTHER from available fields."""
    evt = entry.get("catalyst_event_type", "").upper()
    if evt:
        if any(k in evt for k in ("PDUFA", "ADCOM", "NDA", "BLA", "FDA", "EMA", "REGULATORY")):
            return "REGULATORY"
        if any(k in evt for k in ("CT_", "CLINICAL", "READOUT", "STUDY", "PRIMARY")):
            return "CLINICAL"

    # Fallback: check catalyst_reason_detail
    detail = entry.get("catalyst_reason_detail", "").lower()
    if "pdufa" in detail or "regulatory" in detail or "nda" in detail:
        return "REGULATORY"

    mode = entry.get("catalyst_mode", "")
    if mode and mode != "no_upcoming":
        return "CLINICAL"

    return "OTHER"


def find_prior_snapshot(
    as_of_date: str,
    snap_root: Path,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> Optional[Tuple[str, Path]]:
    """Find the nearest snapshot date strictly before as_of_date within lookback window.

    Returns (prior_date_str, prior_snap_dir) or None.
    """
    target = datetime.strptime(as_of_date, "%Y-%m-%d")
    # Scan backwards from (target - 1 day) up to lookback_days
    for offset in range(1, lookback_days + 7):  # extra margin for weekends
        candidate = (target - timedelta(days=offset)).strftime("%Y-%m-%d")
        candidate_dir = snap_root / candidate
        if candidate_dir.is_dir() and (candidate_dir / "rankings.csv").is_file():
            return candidate, candidate_dir
    return None


# ---------------------------------------------------------------------------
# Slip computation
# ---------------------------------------------------------------------------


def compute_slips(
    prior_cal: Dict[str, Dict[str, Any]],
    current_cal: Dict[str, Dict[str, Any]],
    prior_date: str,
    current_date: str,
    elapsed_days: int,
) -> List[Dict[str, Any]]:
    """Compare two snapshots and compute per-ticker slips.

    For a ticker present in both snapshots:
      expected_days = max(prior_days - elapsed_days, 0)
      slip_days = current_days - expected_days  (positive = pushed out, negative = pulled in)

    elapsed_days = calendar days between prior and current snapshot dates.
    """
    all_tickers = sorted(set(prior_cal) | set(current_cal))
    slips = []

    for ticker in all_tickers:
        prior = prior_cal.get(ticker)
        current = current_cal.get(ticker)

        prior_days = prior["_days_int"] if prior else None
        current_days = current["_days_int"] if current else None

        # Flags
        new_flag = prior is None and current is not None
        dropped_flag = prior is not None and current is None

        # Skip if ticker has no catalyst data in either snapshot
        if prior_days is None and current_days is None:
            continue

        # Compute expected days and slip
        if prior_days is not None and current_days is not None:
            expected_days = max(prior_days - elapsed_days, 0)
            slip_days = current_days - expected_days
            delta_days = current_days - prior_days
        elif new_flag and current_days is not None:
            expected_days = None
            slip_days = None
            delta_days = None
        elif dropped_flag and prior_days is not None:
            expected_days = max(prior_days - elapsed_days, 0)
            slip_days = None
            delta_days = None
        else:
            expected_days = None
            slip_days = None
            delta_days = None

        # Imminent: current days <= 14
        imminent = current_days is not None and current_days <= 14

        # Large slip
        large_slip = slip_days is not None and abs(slip_days) >= LARGE_SLIP_THRESHOLD

        # Family from whichever snapshot has data
        family = (current or prior or {}).get("_family", "OTHER")

        slips.append(
            {
                "ticker": ticker,
                "family": family,
                "prior_days": prior_days if prior_days is not None else "",
                "current_days": current_days if current_days is not None else "",
                "delta_days": delta_days if delta_days is not None else "",
                "expected_days": expected_days if expected_days is not None else "",
                "slip_days": slip_days if slip_days is not None else "",
                "prior_event_type": (prior or {}).get("catalyst_event_type", ""),
                "current_event_type": (current or {}).get("catalyst_event_type", ""),
                "prior_source": (prior or {}).get("catalyst_source", ""),
                "current_source": (current or {}).get("catalyst_source", ""),
                "prior_confidence": (prior or {}).get("confidence_overall", ""),
                "current_confidence": (current or {}).get("confidence_overall", ""),
                "prior_mode": (prior or {}).get("catalyst_mode", ""),
                "current_mode": (current or {}).get("catalyst_mode", ""),
                "prior_snapshot_date": prior_date if prior is not None else "",
                "current_snapshot_date": current_date if current is not None else "",
                "new_flag": "1" if new_flag else "0",
                "dropped_flag": "1" if dropped_flag else "0",
                "large_slip": "1" if large_slip else "0",
                "imminent": "1" if imminent else "0",
            }
        )

    return slips


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------


def compute_slip_summary(slips: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregate slip statistics."""
    total = len(slips)
    new_count = sum(1 for s in slips if s["new_flag"] == "1")
    dropped_count = sum(1 for s in slips if s["dropped_flag"] == "1")
    large_slip_count = sum(1 for s in slips if s["large_slip"] == "1")
    imminent_count = sum(1 for s in slips if s["imminent"] == "1")
    imminent_large_slip = sum(1 for s in slips if s["large_slip"] == "1" and s["imminent"] == "1")

    # Tickers with actual slip_days
    with_slip = [s for s in slips if s["slip_days"] != "" and s["slip_days"] != 0]
    slip_values = []
    for s in with_slip:
        try:
            slip_values.append(int(float(s["slip_days"])))
        except (ValueError, TypeError):
            pass

    abs_slip_values = [abs(v) for v in slip_values]
    mean_abs_slip = sum(abs_slip_values) / len(abs_slip_values) if abs_slip_values else 0
    median_abs_slip = sorted(abs_slip_values)[len(abs_slip_values) // 2] if abs_slip_values else 0

    # Flagged regulatory names = those with family=REGULATORY and current_days present
    flagged_reg = [s for s in slips if s["family"] == "REGULATORY" and s["current_days"] != ""]
    flagged_reg_large_slip = [s for s in flagged_reg if s["large_slip"] == "1"]
    large_slip_rate_reg = len(flagged_reg_large_slip) / len(flagged_reg) if flagged_reg else 0

    # Breakdown by source × confidence
    breakdown: Dict[str, Dict[str, Any]] = {}
    for s in slips:
        if s["slip_days"] == "":
            continue
        try:
            sv = int(float(s["slip_days"]))
        except (ValueError, TypeError):
            continue
        source = s.get("current_source", "") or s.get("prior_source", "") or "UNKNOWN"
        conf = s.get("current_confidence", "") or s.get("prior_confidence", "") or "UNKNOWN"
        key = f"{source}|{conf}"
        if key not in breakdown:
            breakdown[key] = {"source": source, "confidence": conf, "count": 0, "abs_slips": []}
        breakdown[key]["count"] += 1
        breakdown[key]["abs_slips"].append(abs(sv))

    for v in breakdown.values():
        slips_list = v.pop("abs_slips")
        v["mean_abs_slip"] = round(sum(slips_list) / len(slips_list), 1) if slips_list else 0

    # Top 10 largest slips by abs value
    ranked = sorted(
        [s for s in slips if s["slip_days"] != ""],
        key=lambda s: abs(int(float(s["slip_days"]))),
        reverse=True,
    )[:10]
    top_slips = [
        {
            "ticker": s["ticker"],
            "family": s["family"],
            "slip_days": s["slip_days"],
            "prior_days": s["prior_days"],
            "current_days": s["current_days"],
            "source": s.get("current_source", "") or s.get("prior_source", ""),
        }
        for s in ranked
    ]

    return {
        "schema": SCHEMA_VERSION,
        "total_tracked": total,
        "new_count": new_count,
        "dropped_count": dropped_count,
        "large_slip_count": large_slip_count,
        "imminent_count": imminent_count,
        "imminent_large_slip_count": imminent_large_slip,
        "mean_abs_slip_days": round(mean_abs_slip, 1),
        "median_abs_slip_days": median_abs_slip,
        "flagged_regulatory_count": len(flagged_reg),
        "flagged_regulatory_large_slip_count": len(flagged_reg_large_slip),
        "large_slip_rate_regulatory": round(large_slip_rate_reg, 4),
        "top_slips": top_slips,
        "breakdown_by_source_confidence": sorted(breakdown.values(), key=lambda x: (-x["count"], x["source"])),
    }


# ---------------------------------------------------------------------------
# WARN gate
# ---------------------------------------------------------------------------


def check_calendar_slips(
    summary: Dict[str, Any],
    *,
    max_imminent_large_slip: int = 3,
    max_large_slip_rate_reg: float = 0.20,
) -> Dict[str, Any]:
    """WARN-only gate: flags if slip rate is alarming.

    Returns {"status": "PASS"|"WARN", "detail": str, ...}.
    """
    issues = []

    imminent_ls = summary.get("imminent_large_slip_count", 0)
    if imminent_ls >= max_imminent_large_slip:
        issues.append(f"imminent_large_slip_count={imminent_ls} >= {max_imminent_large_slip}")

    ls_rate = summary.get("large_slip_rate_regulatory", 0)
    if ls_rate >= max_large_slip_rate_reg:
        issues.append(f"large_slip_rate_regulatory={ls_rate:.2%} >= {max_large_slip_rate_reg:.0%}")

    if issues:
        return {
            "name": "calendar_slips",
            "status": "WARN",
            "detail": "; ".join(issues),
            "imminent_large_slip_count": imminent_ls,
            "large_slip_rate_regulatory": round(ls_rate, 4),
        }

    return {
        "name": "calendar_slips",
        "status": "PASS",
        "detail": (f"imminent_large_slip={imminent_ls}, " f"reg_large_slip_rate={ls_rate:.2%}"),
        "imminent_large_slip_count": imminent_ls,
        "large_slip_rate_regulatory": round(ls_rate, 4),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_slip_summary_md(
    summary: Dict[str, Any],
    prior_date: str,
    current_date: str,
    gate_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Render slip_summary.md from summary dict."""
    lines: List[str] = []
    lines.append(f"# Calendar Slip Summary — {current_date}")
    lines.append("")
    lines.append(f"**Prior snapshot**: {prior_date}")
    lines.append(f"**Current snapshot**: {current_date}")
    lines.append("")

    if gate_result:
        status = gate_result.get("status", "?")
        lines.append(f"**Slip gate**: {status}")
        if status == "WARN":
            lines.append(f"> WARN: {gate_result.get('detail', '')}")
        lines.append("")

    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Total tracked: {summary.get('total_tracked', 0)}")
    lines.append(f"- New entries: {summary.get('new_count', 0)}")
    lines.append(f"- Dropped entries: {summary.get('dropped_count', 0)}")
    lines.append(f"- Large slips (|slip| >= {LARGE_SLIP_THRESHOLD}d): {summary.get('large_slip_count', 0)}")
    lines.append(f"- Imminent (days <= 14): {summary.get('imminent_count', 0)}")
    lines.append(f"- Imminent + large slip: {summary.get('imminent_large_slip_count', 0)}")
    lines.append(f"- Mean |slip|: {summary.get('mean_abs_slip_days', 0):.1f}d")
    lines.append(f"- Median |slip|: {summary.get('median_abs_slip_days', 0)}d")
    lines.append("")

    # Regulatory breakdown
    lines.append("## Regulatory Slip Rate")
    lines.append("")
    reg_count = summary.get("flagged_regulatory_count", 0)
    reg_ls = summary.get("flagged_regulatory_large_slip_count", 0)
    rate = summary.get("large_slip_rate_regulatory", 0)
    lines.append(f"- Flagged regulatory names: {reg_count}")
    lines.append(f"- Large slip: {reg_ls} ({rate:.1%})")
    lines.append("")

    # Top 10 slips
    top = summary.get("top_slips", [])
    if top:
        lines.append("## Top 10 Largest Slips")
        lines.append("")
        lines.append("| Ticker | Family | Slip (d) | Prior Days | Current Days | Source |")
        lines.append("|--------|--------|----------|------------|-------------|--------|")
        for s in top:
            lines.append(
                f"| {s['ticker']} | {s['family']} | {s['slip_days']} "
                f"| {s['prior_days']} | {s['current_days']} | {s.get('source', '')} |"
            )
        lines.append("")

    # Breakdown table
    bd = summary.get("breakdown_by_source_confidence", [])
    if bd:
        lines.append("## Breakdown by Source × Confidence")
        lines.append("")
        lines.append("| Source | Confidence | Count | Mean |Slip| (d) |")
        lines.append("|--------|-----------|-------|----------------|")
        for row in bd:
            lines.append(f"| {row['source']} | {row['confidence']} " f"| {row['count']} | {row['mean_abs_slip']:.1f} |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_slip_artifacts(
    slips: List[Dict[str, Any]],
    summary: Dict[str, Any],
    prior_date: str,
    current_date: str,
    *,
    out_root: Path = ARTIFACTS_ROOT,
    gate_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Write slips.csv, slip_summary.json, and slip_summary.md.

    Returns dict of written paths.
    """
    out_dir = out_root / current_date
    out_dir.mkdir(parents=True, exist_ok=True)

    # slips.csv
    csv_path = out_dir / "slips.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SLIPS_COLUMNS)
        w.writeheader()
        for s in slips:
            w.writerow({k: s.get(k, "") for k in SLIPS_COLUMNS})

    # slip_summary.json
    json_path = out_dir / "slip_summary.json"
    out_data = dict(summary)
    out_data["prior_snapshot_date"] = prior_date
    out_data["current_snapshot_date"] = current_date
    if gate_result:
        out_data["gate"] = gate_result
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, default=str)

    # slip_summary.md
    md_path = out_dir / "slip_summary.md"
    md_content = render_slip_summary_md(summary, prior_date, current_date, gate_result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return {
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "md_path": str(md_path),
    }


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def run_slip_tracker(
    as_of_date: str,
    *,
    snap_root: Path = SNAPSHOTS_ROOT,
    out_root: Path = ARTIFACTS_ROOT,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> Dict[str, Any]:
    """Run slip tracker for a given date.

    Returns result dict with summary, gate, and artifact paths.
    """
    _assert_not_production_default("snap_root", snap_root, SNAPSHOTS_ROOT)
    _assert_not_production_default("out_root", out_root, ARTIFACTS_ROOT)

    current_dir = snap_root / as_of_date
    if not (current_dir / "rankings.csv").is_file():
        return {"error": f"No snapshot for {as_of_date}", "status": "SKIP"}

    prior_result = find_prior_snapshot(as_of_date, snap_root, lookback_days)
    if prior_result is None:
        return {"error": "No prior snapshot found", "status": "SKIP"}

    prior_date, prior_dir = prior_result

    # Elapsed calendar days
    d_current = datetime.strptime(as_of_date, "%Y-%m-%d")
    d_prior = datetime.strptime(prior_date, "%Y-%m-%d")
    elapsed_days = (d_current - d_prior).days

    # Load calendar data
    prior_cal = load_snapshot_calendar(prior_dir)
    current_cal = load_snapshot_calendar(current_dir)

    # Compute slips
    slips = compute_slips(prior_cal, current_cal, prior_date, as_of_date, elapsed_days)
    summary = compute_slip_summary(slips)
    gate = check_calendar_slips(summary)

    # Write artifacts
    paths = write_slip_artifacts(
        slips,
        summary,
        prior_date,
        as_of_date,
        out_root=out_root,
        gate_result=gate,
    )

    return {
        "status": "OK",
        "prior_date": prior_date,
        "current_date": as_of_date,
        "elapsed_days": elapsed_days,
        "summary": summary,
        "gate": gate,
        "paths": paths,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly catalyst/regulatory date slip tracker")
    parser.add_argument("--as-of-date", type=str, required=True, help="Current snapshot date (YYYY-MM-DD)")
    parser.add_argument("--snap-root", type=str, help="Snapshot directory root")
    parser.add_argument(
        "--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS, help="Max lookback for prior snapshot"
    )
    args = parser.parse_args()

    snap_root = Path(args.snap_root) if args.snap_root else SNAPSHOTS_ROOT
    result = run_slip_tracker(
        args.as_of_date,
        snap_root=snap_root,
        lookback_days=args.lookback_days,
    )

    if result.get("error"):
        print(f"SKIP: {result['error']}")
        sys.exit(0)

    summary = result["summary"]
    gate = result["gate"]
    print(f"Slip tracker: {result['prior_date']} → {result['current_date']} ({result['elapsed_days']}d)")
    print(
        f"  Tracked: {summary['total_tracked']}, Large slips: {summary['large_slip_count']}, "
        f"Imminent+large: {summary['imminent_large_slip_count']}"
    )
    print(f"  Gate: {gate['status']} — {gate['detail']}")
    print(f"  Artifacts: {result['paths']['csv_path']}")


if __name__ == "__main__":
    main()
