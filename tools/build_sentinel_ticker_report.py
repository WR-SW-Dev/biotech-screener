#!/usr/bin/env python3
"""build_sentinel_ticker_report.py — Read-only per-ticker dashboard.

Tracks a fixed set of sentinel tickers chosen for their distinct properties:
ERAS for cohort-boundary noise, ARVN for PDUFA-date validation, AXSM for
commercial/tier precedence, ARGX for multi-regulatory-event ambiguity, etc.
Reports current rank/tier/catalyst state plus rank delta vs prior snapshot.
Useful for catching silent shifts in canonical reference cases without
asserting exact rank.

Diagnostic only. Does NOT modify scoring, selectors, ranking, eligibility,
or portfolio construction.

Outputs under data/snapshots/{date}/:
    sentinel_ticker_report.json
    sentinel_ticker_report.md

Usage:
    python tools/build_sentinel_ticker_report.py
    python tools/build_sentinel_ticker_report.py --as-of-date 2026-04-27
    python tools/build_sentinel_ticker_report.py --tickers ERAS,ARVN,AXSM
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
SCHEMA_VERSION = "sentinel_ticker_report.v1"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_SENTINELS: list[tuple[str, str]] = [
    ("ERAS", "cohort-boundary noise; phase 3; A-tier; watch v2 dropout"),
    ("ARVN", "PDUFA-date validation; canonical near-term catalyst"),
    ("AXSM", "commercial/tier precedence; tier_commercial path"),
    ("ARGX", "multi-regulatory-event ambiguity"),
    ("NBIX", "commercial bucket sanity"),
    ("ALKS", "commercial bucket sanity"),
    ("BCRX", "commercial bucket sanity"),
    ("ORIC", "phase-1 top-30 exposure sanity"),
    ("TNGX", "phase-1 top-30 exposure sanity"),
]

REPORTED_FIELDS = [
    "ticker",
    "company_name",
    "actionable_rank",
    "tier_any",
    "tier_dev",
    "tier_commercial",
    "stage_bucket",
    "catalyst_days",
    "catalyst_in_window",
    "ranker_v2_score",
    "ranker_v2_rank",
    "selector_score",
    "final_score",
    "composite_score",
    "eligible",
    "ineligible_reasons",
    "fundamental_red_flag",
    "top_3_drivers",
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


def load_rankings(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = (r.get("ticker") or "").strip()
            if t:
                out[t] = r
    return out


def get_cohort_membership(row: Optional[dict[str, str]]) -> str:
    if row is None:
        return "absent"
    return "in_cohort" if str(row.get("ranker_v2_score") or "").strip() else "out_of_cohort"


def extract_for_sentinel(
    ticker: str,
    note: str,
    curr_row: Optional[dict[str, str]],
    prev_row: Optional[dict[str, str]],
) -> dict[str, Any]:
    record: dict[str, Any] = {"ticker": ticker, "note": note}

    if curr_row is None:
        record["status"] = "missing_from_universe"
        record["cohort_membership"] = "absent"
        return record

    record["status"] = "present"
    record["cohort_membership"] = get_cohort_membership(curr_row)
    record["prev_cohort_membership"] = get_cohort_membership(prev_row)

    fields: dict[str, Any] = {}
    for f in REPORTED_FIELDS:
        v = (curr_row.get(f) or "").strip()
        fields[f] = v
    record["fields"] = fields

    curr_rk = _si(curr_row.get("actionable_rank"))
    prev_rk = _si((prev_row or {}).get("actionable_rank"))
    record["prev_actionable_rank"] = prev_rk
    record["curr_actionable_rank"] = curr_rk
    if prev_rk is not None and curr_rk is not None:
        record["rank_delta"] = curr_rk - prev_rk
    else:
        record["rank_delta"] = None

    cm_curr = record["cohort_membership"]
    cm_prev = record.get("prev_cohort_membership")
    if cm_prev and cm_prev != cm_curr:
        record["cohort_transition"] = f"{cm_prev}→{cm_curr}"
    else:
        record["cohort_transition"] = None

    return record


def build_sentinel_report(
    curr_rows: dict[str, dict[str, str]],
    prev_rows: dict[str, dict[str, str]],
    sentinels: list[tuple[str, str]],
) -> dict[str, Any]:
    records = [extract_for_sentinel(t, note, curr_rows.get(t), prev_rows.get(t)) for t, note in sentinels]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_sentinels": len(sentinels),
        "n_present": sum(1 for r in records if r.get("status") == "present"),
        "n_absent": sum(1 for r in records if r.get("status") == "missing_from_universe"),
        "n_cohort_transitions": sum(1 for r in records if r.get("cohort_transition")),
        "records": records,
    }


def render_md(report: dict[str, Any], as_of: str, prior: Optional[str]) -> str:
    lines = [
        f"# Sentinel ticker report — {as_of}",
        "",
        f"- **prior snapshot**: `{prior or '(none)'}`",
        f"- **sentinels tracked**: {report['n_sentinels']}    "
        f"**present**: {report['n_present']}    "
        f"**absent from universe**: {report['n_absent']}    "
        f"**cohort transitions**: {report['n_cohort_transitions']}",
        "",
    ]
    lines.append("## Summary")
    lines.append("")
    lines.append("| ticker | status | rank | rankΔ | tier | stage | catΔ days | v2 | cohort transition |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in report["records"]:
        if r.get("status") != "present":
            lines.append(f"| {r['ticker']} | {r.get('status')} | — | — | — | — | — | — | — |")
            continue
        f = r["fields"]
        rd = r.get("rank_delta")
        rd_str = f"{rd:+d}" if isinstance(rd, int) else "—"
        v2_present = "✓" if r["cohort_membership"] == "in_cohort" else "—"
        ct = r.get("cohort_transition") or "—"
        lines.append(
            f"| {r['ticker']} | OK | {f.get('actionable_rank') or '—'} | {rd_str} | "
            f"{f.get('tier_any') or '—'} | {f.get('stage_bucket') or '—'} | "
            f"{f.get('catalyst_days') or '—'} | {v2_present} | {ct} |"
        )
    lines.append("")

    lines.append("## Per-ticker detail")
    lines.append("")
    for r in report["records"]:
        lines.append(f"### {r['ticker']} — {r.get('note', '')}")
        lines.append("")
        if r.get("status") != "present":
            lines.append(f"_status: {r.get('status')}_")
            lines.append("")
            continue
        f = r["fields"]
        rd = r.get("rank_delta")
        lines.append(
            f"- **rank**: {f.get('actionable_rank') or '—'}    "
            f"(prev {r.get('prev_actionable_rank') or '—'}, "
            f"Δ {rd if isinstance(rd, int) else '—'})"
        )
        lines.append(
            f"- **cohort**: {r['cohort_membership']}    " f"(transition: {r.get('cohort_transition') or 'none'})"
        )
        lines.append(
            f"- **tier_any / dev / commercial**: "
            f"{f.get('tier_any') or '—'} / "
            f"{f.get('tier_dev') or '—'} / "
            f"{f.get('tier_commercial') or '—'}"
        )
        lines.append(
            f"- **stage_bucket**: {f.get('stage_bucket') or '—'}    "
            f"**catalyst_days**: {f.get('catalyst_days') or '—'}    "
            f"**in_window**: {f.get('catalyst_in_window') or '—'}"
        )
        lines.append(
            f"- **v2 score / rank**: " f"{f.get('ranker_v2_score') or '—'} / " f"{f.get('ranker_v2_rank') or '—'}"
        )
        lines.append(
            f"- **selector / final / composite**: "
            f"{f.get('selector_score') or '—'} / "
            f"{f.get('final_score') or '—'} / "
            f"{f.get('composite_score') or '—'}"
        )
        lines.append(
            f"- **eligible**: {f.get('eligible') or '—'}    "
            f"**ineligible_reasons**: {f.get('ineligible_reasons') or '—'}"
        )
        lines.append(f"- **top_3_drivers**: `{f.get('top_3_drivers') or '—'}`")
        lines.append("")
    return "\n".join(lines)


def parse_sentinel_arg(arg: Optional[str]) -> Optional[list[tuple[str, str]]]:
    if not arg:
        return None
    return [(t.strip().upper(), "") for t in arg.split(",") if t.strip()]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date")
    parser.add_argument("--prior-date")
    parser.add_argument("--snapshots-dir", default=str(SNAPSHOTS_DIR))
    parser.add_argument("--tickers", help="comma-separated override (e.g. ERAS,ARVN,AXSM)")
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
    prev_rows: dict[str, dict[str, str]] = {}
    if prior:
        prev_path = snapshots_dir / prior / "rankings.csv"
        if prev_path.exists():
            prev_rows = load_rankings(prev_path)

    sentinels = parse_sentinel_arg(args.tickers) or DEFAULT_SENTINELS
    report = build_sentinel_report(curr_rows, prev_rows, sentinels)
    report["as_of_date"] = as_of
    report["prior_date"] = prior

    snapshot_dir = snapshots_dir / as_of
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    json_path = snapshot_dir / "sentinel_ticker_report.json"
    md_path = snapshot_dir / "sentinel_ticker_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_md(report, as_of, prior), encoding="utf-8")

    if not args.quiet:
        print(
            f"sentinel_report {as_of} (vs {prior or '∅'}): "
            f"{report['n_present']}/{report['n_sentinels']} present, "
            f"{report['n_cohort_transitions']} cohort transition(s)"
        )
        print(f"  json: {json_path}")
        print(f"  md:   {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
