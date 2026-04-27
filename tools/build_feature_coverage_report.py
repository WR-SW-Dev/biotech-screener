#!/usr/bin/env python3
"""build_feature_coverage_report.py — Read-only feature missingness audit.

Tracks how complete each input feature is across the universe — overall and
segmented by tier_any and stage_bucket. Catches silent data-source drift
where a field becomes broadly unpopulated without an obvious upstream error.

Diagnostic only. Does NOT modify scoring, selectors, ranking, eligibility,
or portfolio construction.

Outputs under data/snapshots/{date}/:
    feature_coverage_report.json
    feature_coverage_report.md

Usage:
    python tools/build_feature_coverage_report.py
    python tools/build_feature_coverage_report.py --as-of-date 2026-04-27
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
SCHEMA_VERSION = "feature_coverage_report.v1"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Features tracked. Order is canonical for the rendered table.
TRACKED_FEATURES = [
    "ranker_v2_score",
    "selector_score",
    "final_score",
    "composite_score",
    "tier_any",
    "stage_bucket",
    "catalyst_days",
    "clinical_score",
    "clinical_alpha_z",
    "short_interest_pct",
    "market_cap_mm",
    "close_price",
    "priced_move_pct",
    "insider_net_buy_value_90d",
    "pre_event_put_call_ratio",
    "opt_put_call_skew",
    "implied_event_move",
]

# Coverage thresholds (% populated). Below WARN_BELOW_PCT raises WARN; below
# FAIL_BELOW_PCT raises FAIL — but only for features the model expects to be
# broadly populated (i.e. universe-wide, not cohort-only fields).
UNIVERSE_WIDE_FEATURES = {
    "tier_any",
    "stage_bucket",
    "catalyst_days",
    "market_cap_mm",
    "close_price",
}
WARN_BELOW_PCT = 80.0
FAIL_BELOW_PCT = 50.0

SEVERITY_ORDER = ["PASS", "INFO", "WARN", "FAIL"]


def _max_severity(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.index(a) >= SEVERITY_ORDER.index(b) else b


def _is_present(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    return bool(s) and s.lower() not in ("nan", "none", "null")


def find_latest_date(snapshots_dir: Path) -> Optional[str]:
    if not snapshots_dir.exists():
        return None
    dates = [
        p.name
        for p in snapshots_dir.iterdir()
        if p.is_dir() and DATE_RE.match(p.name) and (p / "rankings.csv").exists()
    ]
    return max(dates) if dates else None


def load_rankings(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        rows = list(reader)
    return cols, rows


def coverage_for_feature(
    feature: str,
    rows: list[dict[str, str]],
    cols_present: bool,
) -> dict[str, Any]:
    if not cols_present:
        return {
            "feature": feature,
            "n_total": len(rows),
            "n_present": 0,
            "pct_present": 0.0,
            "column_present": False,
            "severity": "FAIL",
        }
    n_total = len(rows)
    n_present = sum(1 for r in rows if _is_present(r.get(feature)))
    pct = round(100.0 * n_present / max(n_total, 1), 2)

    if feature in UNIVERSE_WIDE_FEATURES:
        if pct < FAIL_BELOW_PCT:
            sev = "FAIL"
        elif pct < WARN_BELOW_PCT:
            sev = "WARN"
        else:
            sev = "PASS"
    else:
        sev = "INFO"  # cohort/optional fields — coverage is informational

    return {
        "feature": feature,
        "n_total": n_total,
        "n_present": n_present,
        "pct_present": pct,
        "column_present": True,
        "severity": sev,
    }


def segment_by(
    rows: list[dict[str, str]],
    feature: str,
    segment_field: str,
) -> dict[str, dict[str, Any]]:
    """Compute coverage of `feature` within each value of `segment_field`."""
    by_seg: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        seg = (r.get(segment_field) or "").strip() or "(blank)"
        by_seg[seg].append(r)

    out: dict[str, dict[str, Any]] = {}
    for seg, seg_rows in sorted(by_seg.items()):
        n = len(seg_rows)
        n_present = sum(1 for r in seg_rows if _is_present(r.get(feature)))
        out[seg] = {
            "n_total": n,
            "n_present": n_present,
            "pct_present": round(100.0 * n_present / max(n, 1), 2),
        }
    return out


def build_coverage_report(snapshot_dir: Path) -> dict[str, Any]:
    rankings_path = snapshot_dir / "rankings.csv"
    if not rankings_path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "as_of_date": snapshot_dir.name,
            "ok": False,
            "overall_severity": "FAIL",
            "features": [],
            "error": f"missing rankings.csv at {rankings_path}",
        }

    cols, rows = load_rankings(rankings_path)
    cols_set = set(cols)

    feature_rows: list[dict[str, Any]] = []
    overall = "PASS"
    for f in TRACKED_FEATURES:
        rec = coverage_for_feature(f, rows, f in cols_set)
        if rec["column_present"]:
            rec["by_tier"] = segment_by(rows, f, "tier_any")
            rec["by_stage"] = segment_by(rows, f, "stage_bucket")
        feature_rows.append(rec)
        overall = _max_severity(overall, rec["severity"])

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of_date": snapshot_dir.name,
        "rankings_csv": str(rankings_path),
        "n_rows": len(rows),
        "n_features_tracked": len(TRACKED_FEATURES),
        "ok": overall in ("PASS", "INFO"),
        "overall_severity": overall,
        "features": feature_rows,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        f"# Feature coverage report — {report.get('as_of_date')}",
        "",
        f"- **overall**: `{report.get('overall_severity')}`",
        f"- **rows**: {report.get('n_rows')}    " f"**features tracked**: {report.get('n_features_tracked')}",
        "",
    ]
    if "error" in report:
        lines.append(f"_Error: {report['error']}_")
        return "\n".join(lines)

    lines.append("## Feature presence")
    lines.append("")
    lines.append("| feature | severity | present | pct |")
    lines.append("|---|---|---|---|")
    for f in report["features"]:
        lines.append(
            f"| {f['feature']} | {f['severity']} | " f"{f['n_present']}/{f['n_total']} | {f['pct_present']:.1f}% |"
        )
    lines.append("")

    # Per-tier coverage table for universe-wide features only (compact)
    lines.append("## Coverage by tier (universe-wide features)")
    lines.append("")
    universe = [f for f in report["features"] if f["feature"] in UNIVERSE_WIDE_FEATURES]
    if universe:
        # Collect all tier values
        tiers = set()
        for f in universe:
            tiers.update((f.get("by_tier") or {}).keys())
        tiers = sorted(tiers)
        header = "| feature | " + " | ".join(tiers) + " |"
        sep = "|---|" + "---|" * len(tiers)
        lines.append(header)
        lines.append(sep)
        for f in universe:
            row = [f["feature"]]
            for t in tiers:
                seg = (f.get("by_tier") or {}).get(t)
                if seg:
                    row.append(f"{seg['pct_present']:.0f}% ({seg['n_present']}/{seg['n_total']})")
                else:
                    row.append("—")
            lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date")
    parser.add_argument("--snapshots-dir", default=str(SNAPSHOTS_DIR))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    snapshots_dir = Path(args.snapshots_dir)
    as_of = args.as_of_date or find_latest_date(snapshots_dir)
    if not as_of:
        print(f"ERROR: no snapshots found under {snapshots_dir}")
        return 2

    snapshot_dir = snapshots_dir / as_of
    report = build_coverage_report(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    json_path = snapshot_dir / "feature_coverage_report.json"
    md_path = snapshot_dir / "feature_coverage_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_md(report), encoding="utf-8")

    if not args.quiet:
        n_fail = sum(1 for f in report.get("features", []) if f["severity"] == "FAIL")
        n_warn = sum(1 for f in report.get("features", []) if f["severity"] == "WARN")
        print(f"feature_coverage {as_of}: overall={report['overall_severity']} " f"FAIL={n_fail} WARN={n_warn}")
        print(f"  json: {json_path}")
        print(f"  md:   {md_path}")
        if n_fail or n_warn:
            problem = [f for f in report["features"] if f["severity"] in ("FAIL", "WARN")]
            for f in problem:
                print(
                    f"  [{f['severity']}] {f['feature']}: " f"{f['n_present']}/{f['n_total']} ({f['pct_present']:.1f}%)"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
