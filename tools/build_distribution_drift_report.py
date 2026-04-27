#!/usr/bin/env python3
"""build_distribution_drift_report.py — Read-only distributional summary.

Reports per-snapshot distributions over key categorical fields plus
day-over-day turnover for top-30 and top-60 cohort. Catches silent shifts
in the universe composition before they become portfolio-construction
surprises.

Diagnostic only. Does NOT modify scoring, selectors, ranking, eligibility,
or portfolio construction.

Outputs under data/snapshots/{date}/:
    distribution_drift_report.json
    distribution_drift_report.md

Usage:
    python tools/build_distribution_drift_report.py
    python tools/build_distribution_drift_report.py --as-of-date 2026-04-27
    python tools/build_distribution_drift_report.py --as-of-date 2026-04-27 --prior-date 2026-04-24
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
SCHEMA_VERSION = "distribution_drift_report.v1"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TOP_N = 30
COHORT_N = 60

# Categorical fields to summarize
CATEGORICAL_FIELDS = [
    "tier_any",
    "stage_bucket",
    "archetype",
    "mom_state",
    "catalyst_bucket",
    "size_band",
    "catalyst_in_window",
]

# catalyst_days bucket boundaries (days)
CATALYST_BUCKETS = [
    ("≤7", lambda d: d <= 7),
    ("8-30", lambda d: 7 < d <= 30),
    ("31-90", lambda d: 30 < d <= 90),
    ("91-180", lambda d: 90 < d <= 180),
    ("181-365", lambda d: 180 < d <= 365),
    (">365", lambda d: d > 365),
]


def _si(val: Any) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def find_latest_date(snapshots_dir: Path) -> Optional[str]:
    if not snapshots_dir.exists():
        return None
    dates = [
        p.name
        for p in snapshots_dir.iterdir()
        if p.is_dir() and DATE_RE.match(p.name) and (p / "rankings.csv").exists()
    ]
    return max(dates) if dates else None


def find_prior_date(snapshots_dir: Path, current: str) -> Optional[str]:
    if not snapshots_dir.exists():
        return None
    candidates = [
        p.name
        for p in snapshots_dir.iterdir()
        if p.is_dir() and DATE_RE.match(p.name) and p.name < current and (p / "rankings.csv").exists()
    ]
    return max(candidates) if candidates else None


def load_rankings(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def distribution(values: list[str]) -> dict[str, dict[str, Any]]:
    """Return {value: {count, pct}} ordered by count desc."""
    cnt = Counter(v if v else "(blank)" for v in values)
    total = sum(cnt.values())
    return {
        k: {
            "count": v,
            "pct": round(100.0 * v / max(total, 1), 1),
        }
        for k, v in cnt.most_common()
    }


def categorical_distributions(rows: list[dict[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in CATEGORICAL_FIELDS:
        out[f] = distribution([(r.get(f) or "").strip() for r in rows])
    return out


def catalyst_days_buckets(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    counts: dict[str, int] = {label: 0 for label, _ in CATALYST_BUCKETS}
    n_blank = 0
    n_total = 0
    for r in rows:
        d = _si(r.get("catalyst_days"))
        if d is None:
            n_blank += 1
            continue
        n_total += 1
        for label, predicate in CATALYST_BUCKETS:
            if predicate(d):
                counts[label] += 1
                break
    out = {
        label: {"count": counts[label], "pct": round(100.0 * counts[label] / max(n_total, 1), 1)}
        for label, _ in CATALYST_BUCKETS
    }
    out["(blank)"] = {"count": n_blank, "pct": round(100.0 * n_blank / max(len(rows), 1), 1)}
    return out


def top_n_set(rows: list[dict[str, str]], n: int) -> set[str]:
    ranked = []
    for r in rows:
        rk = _si(r.get("actionable_rank"))
        if rk is not None:
            ranked.append((rk, r.get("ticker", "")))
    ranked.sort()
    return {t for _, t in ranked[:n]}


def cohort_set(rows: list[dict[str, str]]) -> set[str]:
    return {(r.get("ticker") or "").strip() for r in rows if str(r.get("ranker_v2_score") or "").strip()}


def turnover(prev: set[str], curr: set[str]) -> dict[str, Any]:
    entered = sorted(curr - prev)
    exited = sorted(prev - curr)
    union_size = max(len(prev | curr), 1)
    # Jaccard distance: |symmetric difference| / |union|. Identical sets → 0%,
    # disjoint sets → 100%.
    return {
        "n_prev": len(prev),
        "n_curr": len(curr),
        "n_entered": len(entered),
        "n_exited": len(exited),
        "entered": entered,
        "exited": exited,
        "turnover_pct": round(100.0 * (len(entered) + len(exited)) / union_size, 2),
    }


def filter_top(rows: list[dict[str, str]], n: int) -> list[dict[str, str]]:
    out = []
    for r in rows:
        rk = _si(r.get("actionable_rank"))
        if rk is not None and rk <= n:
            out.append(r)
    return out


def filter_eligible(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if str(r.get("eligible") or "").strip().lower() in ("1", "true", "yes")]


def build_drift_report(
    curr_rows: list[dict[str, str]],
    prev_rows: Optional[list[dict[str, str]]],
) -> dict[str, Any]:
    top30 = filter_top(curr_rows, TOP_N)
    top60 = filter_top(curr_rows, COHORT_N)
    eligible = filter_eligible(curr_rows)

    payload = {
        "n_universe": len(curr_rows),
        "n_eligible": len(eligible),
        "n_top30": len(top30),
        "n_top60": len(top60),
        "universe_distributions": categorical_distributions(curr_rows),
        "eligible_distributions": categorical_distributions(eligible),
        "top30_distributions": categorical_distributions(top30),
        "catalyst_buckets_universe": catalyst_days_buckets(curr_rows),
        "catalyst_buckets_top30": catalyst_days_buckets(top30),
    }

    if prev_rows is not None:
        prev_top30 = top_n_set(prev_rows, TOP_N)
        prev_top60 = top_n_set(prev_rows, COHORT_N)
        prev_cohort = cohort_set(prev_rows)
        curr_top30 = top_n_set(curr_rows, TOP_N)
        curr_top60 = top_n_set(curr_rows, COHORT_N)
        curr_cohort = cohort_set(curr_rows)
        payload["turnover"] = {
            "top30": turnover(prev_top30, curr_top30),
            "top60": turnover(prev_top60, curr_top60),
            "v2_cohort": turnover(prev_cohort, curr_cohort),
        }
    return payload


def render_md(report: dict[str, Any], as_of: str, prior: Optional[str]) -> str:
    lines = [
        f"# Distribution drift report — {as_of}",
        "",
        f"- **prior**: `{prior or '(none)'}`",
        f"- **universe**: {report['n_universe']}    "
        f"**eligible**: {report['n_eligible']}    "
        f"**top-30**: {report['n_top30']}    **top-60**: {report['n_top60']}",
        "",
    ]

    if "turnover" in report:
        lines.append("## Turnover (vs prior)")
        lines.append("")
        for tag, label in [("top30", "top-30"), ("top60", "top-60"), ("v2_cohort", "v2 cohort")]:
            t = report["turnover"][tag]
            lines.append(
                f"- **{label}**: {t['n_prev']}→{t['n_curr']}    "
                f"+{t['n_entered']} / −{t['n_exited']}    "
                f"turnover={t['turnover_pct']}%"
            )
            if t["entered"]:
                lines.append(f"  - entered: {', '.join(t['entered'][:15])}")
            if t["exited"]:
                lines.append(f"  - exited: {', '.join(t['exited'][:15])}")
        lines.append("")

    def _table(title: str, dist_block: dict[str, dict[str, Any]]) -> list[str]:
        out = [f"### {title}", "", "| value | count | pct |", "|---|---|---|"]
        for v, info in dist_block.items():
            out.append(f"| {v} | {info['count']} | {info['pct']:.1f}% |")
        out.append("")
        return out

    lines.append("## Categorical distributions — top-30")
    lines.append("")
    for f in CATEGORICAL_FIELDS:
        lines.extend(_table(f, report["top30_distributions"][f]))

    lines.append("## Categorical distributions — eligible universe")
    lines.append("")
    for f in CATEGORICAL_FIELDS:
        lines.extend(_table(f, report["eligible_distributions"][f]))

    lines.append("## Catalyst-day buckets")
    lines.append("")
    lines.extend(_table("universe", report["catalyst_buckets_universe"]))
    lines.extend(_table("top-30", report["catalyst_buckets_top30"]))

    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date")
    parser.add_argument("--prior-date")
    parser.add_argument("--snapshots-dir", default=str(SNAPSHOTS_DIR))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    snapshots_dir = Path(args.snapshots_dir)
    as_of = args.as_of_date or find_latest_date(snapshots_dir)
    if not as_of:
        print(f"ERROR: no snapshots found under {snapshots_dir}")
        return 2

    curr_path = snapshots_dir / as_of / "rankings.csv"
    if not curr_path.exists():
        print(f"ERROR: missing {curr_path}")
        return 2
    curr_rows = load_rankings(curr_path)

    prior = args.prior_date or find_prior_date(snapshots_dir, as_of)
    prev_rows = None
    if prior:
        prev_path = snapshots_dir / prior / "rankings.csv"
        if prev_path.exists():
            prev_rows = load_rankings(prev_path)

    report = build_drift_report(curr_rows, prev_rows)
    report.update(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "as_of_date": as_of,
            "prior_date": prior,
        }
    )

    snapshot_dir = snapshots_dir / as_of
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    json_path = snapshot_dir / "distribution_drift_report.json"
    md_path = snapshot_dir / "distribution_drift_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_md(report, as_of, prior), encoding="utf-8")

    if not args.quiet:
        msg = (
            f"distribution_drift {as_of} (vs {prior or '∅'}): "
            f"universe={report['n_universe']} eligible={report['n_eligible']}"
        )
        if "turnover" in report:
            t30 = report["turnover"]["top30"]
            tcoh = report["turnover"]["v2_cohort"]
            msg += f" top30_turnover={t30['turnover_pct']}% " f"cohort_turnover={tcoh['turnover_pct']}%"
        print(msg)
        print(f"  json: {json_path}")
        print(f"  md:   {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
