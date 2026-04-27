#!/usr/bin/env python3
"""build_rank_change_monitor.py — Read-only deterministic rank-change monitor.

Compares the latest rankings.csv against the most recent prior snapshot and
flags meaningful day-over-day rank movement. Does NOT change scoring,
selectors, ranking, eligibility, or portfolio construction.

Outputs three artifacts under data/snapshots/{date}/:
    rank_change_alerts.csv
    rank_change_alerts.md
    rank_change_alerts.json

Flag rules:
    1. top-30 entry/exit
    2. actionable_rank delta >= 10
    3. top-60 ranker_v2 cohort entry/exit
    4. ranker_v2_score appears/disappears
    5. final_score drops > 50% while composite_score changes < 10%
    6. A-tier name exits top 60
    7. cohort churn >= 10%
    8. duplicate / missing / non-sequential actionable_rank values

Usage:
    python tools/build_rank_change_monitor.py
    python tools/build_rank_change_monitor.py --as-of-date 2026-04-25
    python tools/build_rank_change_monitor.py --as-of-date 2026-04-25 --prior-date 2026-04-24
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
SCHEMA_VERSION = "rank_change_monitor.v1"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TOP_N = 30
COHORT_N = 60
EXPECTED_V2_COHORT_SIZE = 60

RANK_DELTA_FLAG = 10
COHORT_CHURN_PCT_FLAG = 10.0
FINAL_DROP_PCT = 50.0
COMPOSITE_STABLE_PCT = 10.0
SELECTOR_MOVE_ABS = 0.05
CATALYST_DAYS_DELTA = 7
# Only flag final-score collapse when the prior value was meaningful — guards
# against tiny-baseline noise (rank-220 names whose final_score floats near
# 1e-4 and where 2x swings are routine).
FINAL_COLLAPSE_PREV_MIN = 0.10

REASON_PRIORITY = [
    "ranker_v2_cohort_dropout",
    "ranker_v2_cohort_entry",
    "eligibility_change",
    "source_data_change",
    "selector_score_move",
    "tier_change",
    "catalyst_timing_change",
    "score_model_change",
    "unknown",
]

SEVERITY_ORDER = ["INFO", "WATCH", "WARN", "CRITICAL"]


def _sf(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _si(val: Any) -> Optional[int]:
    f = _sf(val)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


def _present(val: Any) -> bool:
    return _sf(val) is not None


def _max_severity(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.index(a) >= SEVERITY_ORDER.index(b) else b


def load_rankings(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tkr = (row.get("ticker") or "").strip()
            if tkr:
                rows[tkr] = row
    return rows


def find_prior_date(snapshots_dir: Path, current_date: str) -> Optional[str]:
    if not snapshots_dir.exists():
        return None
    candidates = []
    for p in snapshots_dir.iterdir():
        if not p.is_dir() or not DATE_RE.match(p.name):
            continue
        if p.name >= current_date:
            continue
        if not (p / "rankings.csv").exists():
            continue
        candidates.append(p.name)
    return max(candidates) if candidates else None


def find_latest_date(snapshots_dir: Path) -> Optional[str]:
    if not snapshots_dir.exists():
        return None
    dates = [
        p.name
        for p in snapshots_dir.iterdir()
        if p.is_dir() and DATE_RE.match(p.name) and (p / "rankings.csv").exists()
    ]
    return max(dates) if dates else None


def check_integrity(rows: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Validate actionable_rank space: dense [1..N], no dups."""
    rank_to_tickers: dict[int, list[str]] = {}
    for tkr, row in rows.items():
        rk = _si(row.get("actionable_rank"))
        if rk is None:
            continue
        rank_to_tickers.setdefault(rk, []).append(tkr)

    duplicates = {rk: tks for rk, tks in rank_to_tickers.items() if len(tks) > 1}
    ranks = sorted(rank_to_tickers.keys())
    gaps: list[int] = []
    if ranks:
        expected = set(range(min(ranks), max(ranks) + 1))
        gaps = sorted(expected - set(ranks))

    starts_at_one = bool(ranks) and ranks[0] == 1
    return {
        "n_ranked": len(ranks),
        "min_rank": ranks[0] if ranks else None,
        "max_rank": ranks[-1] if ranks else None,
        "duplicate_ranks": duplicates,
        "missing_ranks": gaps,
        "starts_at_one": starts_at_one,
        "ok": (not duplicates) and (not gaps) and starts_at_one,
    }


def cohort_set(rows: dict[str, dict[str, str]]) -> set[str]:
    return {t for t, r in rows.items() if _present(r.get("ranker_v2_score"))}


def top_set(rows: dict[str, dict[str, str]], n: int) -> set[str]:
    ranked = []
    for tkr, row in rows.items():
        rk = _si(row.get("actionable_rank"))
        if rk is not None:
            ranked.append((rk, tkr))
    ranked.sort()
    return {t for _, t in ranked[:n]}


def pick_primary_reason(reasons: list[str]) -> str:
    if not reasons:
        return "unknown"
    for r in REASON_PRIORITY:
        if r in reasons:
            return r
    return reasons[0]


def evaluate_ticker(
    tkr: str,
    prev: Optional[dict[str, str]],
    curr: Optional[dict[str, str]],
    *,
    prev_top30: set[str],
    curr_top30: set[str],
    prev_cohort: set[str],
    curr_cohort: set[str],
) -> Optional[dict[str, Any]]:
    """Return an alert dict if this ticker meets any flag rule, else None."""
    prev_rk = _si((prev or {}).get("actionable_rank"))
    curr_rk = _si((curr or {}).get("actionable_rank"))
    rank_delta: Optional[int] = None
    if prev_rk is not None and curr_rk is not None:
        rank_delta = curr_rk - prev_rk

    prev_v2 = _sf((prev or {}).get("ranker_v2_score"))
    curr_v2 = _sf((curr or {}).get("ranker_v2_score"))
    prev_sel = _sf((prev or {}).get("selector_score"))
    curr_sel = _sf((curr or {}).get("selector_score"))
    prev_fin = _sf((prev or {}).get("final_score"))
    curr_fin = _sf((curr or {}).get("final_score"))
    prev_comp = _sf((prev or {}).get("composite_score"))
    curr_comp = _sf((curr or {}).get("composite_score"))

    prev_tier = (prev or {}).get("tier_any", "") or ""
    curr_tier = (curr or {}).get("tier_any", "") or ""
    prev_stage = (prev or {}).get("stage_bucket", "") or ""
    curr_stage = (curr or {}).get("stage_bucket", "") or ""
    prev_cat = _sf((prev or {}).get("catalyst_days"))
    curr_cat = _sf((curr or {}).get("catalyst_days"))
    prev_elig = (prev or {}).get("eligible", "") or ""
    curr_elig = (curr or {}).get("eligible", "") or ""

    company = (curr or prev or {}).get("company_name", "") or ""

    flags: list[str] = []
    reasons: list[str] = []
    severity = "INFO"

    in_prev_top30 = tkr in prev_top30
    in_curr_top30 = tkr in curr_top30
    in_prev_cohort = tkr in prev_cohort
    in_curr_cohort = tkr in curr_cohort

    if in_prev_top30 and not in_curr_top30:
        flags.append("top30_exit")
        severity = _max_severity(severity, "WARN")
    if in_curr_top30 and not in_prev_top30:
        flags.append("top30_entry")
        severity = _max_severity(severity, "WARN")

    if in_prev_cohort and not in_curr_cohort:
        flags.append("cohort_exit")
        reasons.append("ranker_v2_cohort_dropout")
        severity = _max_severity(severity, "WATCH")
    if in_curr_cohort and not in_prev_cohort:
        flags.append("cohort_entry")
        reasons.append("ranker_v2_cohort_entry")
        severity = _max_severity(severity, "WATCH")

    v2_was_present = prev_v2 is not None
    v2_now_present = curr_v2 is not None
    if v2_was_present and not v2_now_present and "cohort_exit" not in flags:
        flags.append("v2_score_disappeared")
        reasons.append("ranker_v2_cohort_dropout")
        severity = _max_severity(severity, "WATCH")
    if v2_now_present and not v2_was_present and "cohort_entry" not in flags:
        flags.append("v2_score_appeared")
        reasons.append("ranker_v2_cohort_entry")
        severity = _max_severity(severity, "WATCH")

    if rank_delta is not None and abs(rank_delta) >= RANK_DELTA_FLAG:
        flags.append(f"rank_delta_{rank_delta:+d}")
        severity = _max_severity(severity, "WATCH")

    # Final-score collapse with stable composite (the ERAS pattern). Only
    # meaningful when the prior final_score was not floor-noise.
    if prev_fin is not None and curr_fin is not None and prev_fin >= FINAL_COLLAPSE_PREV_MIN:
        final_drop_pct = 100.0 * (prev_fin - curr_fin) / prev_fin
        comp_change_pct = None
        if prev_comp is not None and curr_comp is not None and abs(prev_comp) > 1e-9:
            comp_change_pct = 100.0 * abs(curr_comp - prev_comp) / abs(prev_comp)
        if final_drop_pct > FINAL_DROP_PCT and (comp_change_pct is None or comp_change_pct < COMPOSITE_STABLE_PCT):
            flags.append("final_collapse_composite_stable")
            severity = _max_severity(severity, "WARN")

    # A-tier name exits top 30 / top 60 (must have been inside, now outside)
    if (prev_tier or "").upper().startswith("A"):
        prev_in_top30 = prev_rk is not None and prev_rk <= TOP_N
        curr_in_top30 = curr_rk is not None and curr_rk <= TOP_N
        prev_in_top60 = prev_rk is not None and prev_rk <= COHORT_N
        curr_in_top60 = curr_rk is not None and curr_rk <= COHORT_N
        if prev_in_top30 and not curr_in_top30:
            flags.append("a_tier_exit_top30")
            severity = _max_severity(severity, "WARN")
        if prev_in_top60 and not curr_in_top60:
            flags.append("a_tier_exit_top60")
            severity = _max_severity(severity, "WARN")

    # Eligibility change
    if prev_elig != curr_elig and (prev_elig != "" or curr_elig != ""):
        flags.append(f"eligible:{prev_elig or '∅'}→{curr_elig or '∅'}")
        reasons.append("eligibility_change")
        if in_prev_top30 or in_curr_top30:
            severity = _max_severity(severity, "CRITICAL")
        else:
            severity = _max_severity(severity, "WATCH")

    # Tier change
    if prev_tier != curr_tier and (prev_tier != "" or curr_tier != ""):
        flags.append(f"tier:{prev_tier or '∅'}→{curr_tier or '∅'}")
        reasons.append("tier_change")
        severity = _max_severity(severity, "WATCH")

    # Catalyst timing change
    if prev_cat is not None and curr_cat is not None:
        if abs(curr_cat - prev_cat) >= CATALYST_DAYS_DELTA:
            flags.append(f"catalyst_days:{prev_cat:g}→{curr_cat:g}")
            reasons.append("catalyst_timing_change")

    # Selector-score move (informational reason)
    if prev_sel is not None and curr_sel is not None:
        if abs(curr_sel - prev_sel) >= SELECTOR_MOVE_ABS:
            reasons.append("selector_score_move")

    # Composite-score model change (informational reason)
    if prev_comp is not None and curr_comp is not None and abs(prev_comp) > 1e-9:
        if 100.0 * abs(curr_comp - prev_comp) / abs(prev_comp) > 25.0:
            reasons.append("score_model_change")

    if not flags:
        return None

    cohort_change = ""
    if "cohort_entry" in flags:
        cohort_change = "entered"
    elif "cohort_exit" in flags:
        cohort_change = "exited"

    likely_reason = pick_primary_reason(reasons)

    return {
        "ticker": tkr,
        "company_name": company,
        "prev_actionable_rank": prev_rk,
        "curr_actionable_rank": curr_rk,
        "rank_delta": rank_delta,
        "prev_ranker_v2_score": prev_v2,
        "curr_ranker_v2_score": curr_v2,
        "prev_selector_score": prev_sel,
        "curr_selector_score": curr_sel,
        "prev_final_score": prev_fin,
        "curr_final_score": curr_fin,
        "prev_composite_score": prev_comp,
        "curr_composite_score": curr_comp,
        "prev_tier_any": prev_tier,
        "curr_tier_any": curr_tier,
        "prev_development_stage": prev_stage,
        "curr_development_stage": curr_stage,
        "prev_catalyst_days": prev_cat,
        "curr_catalyst_days": curr_cat,
        "cohort_membership_change": cohort_change,
        "flags": flags,
        "reasons": sorted(set(reasons)),
        "likely_reason": likely_reason,
        "severity": severity,
    }


def build_alerts(
    prev_rows: dict[str, dict[str, str]],
    curr_rows: dict[str, dict[str, str]],
) -> dict[str, Any]:
    prev_top30 = top_set(prev_rows, TOP_N)
    curr_top30 = top_set(curr_rows, TOP_N)
    prev_cohort = cohort_set(prev_rows)
    curr_cohort = cohort_set(curr_rows)

    alerts: list[dict[str, Any]] = []
    universe = sorted(set(prev_rows) | set(curr_rows))
    for tkr in universe:
        a = evaluate_ticker(
            tkr,
            prev_rows.get(tkr),
            curr_rows.get(tkr),
            prev_top30=prev_top30,
            curr_top30=curr_top30,
            prev_cohort=prev_cohort,
            curr_cohort=curr_cohort,
        )
        if a:
            alerts.append(a)

    cohort_entered = sorted(curr_cohort - prev_cohort)
    cohort_exited = sorted(prev_cohort - curr_cohort)
    cohort_total = max(len(prev_cohort | curr_cohort), 1)
    cohort_churn_pct = 100.0 * (len(cohort_entered) + len(cohort_exited)) / (2 * cohort_total)

    integrity_curr = check_integrity(curr_rows)
    integrity_prev = check_integrity(prev_rows)

    system_alerts: list[dict[str, Any]] = []
    if cohort_churn_pct >= COHORT_CHURN_PCT_FLAG:
        system_alerts.append(
            {
                "kind": "cohort_churn",
                "severity": "WARN",
                "value_pct": round(cohort_churn_pct, 2),
                "entered": cohort_entered,
                "exited": cohort_exited,
            }
        )
    if len(curr_cohort) != EXPECTED_V2_COHORT_SIZE:
        system_alerts.append(
            {
                "kind": "v2_cohort_size",
                "severity": "CRITICAL",
                "expected": EXPECTED_V2_COHORT_SIZE,
                "actual": len(curr_cohort),
            }
        )
    if integrity_curr["duplicate_ranks"]:
        system_alerts.append(
            {
                "kind": "duplicate_actionable_rank",
                "severity": "CRITICAL",
                "duplicates": integrity_curr["duplicate_ranks"],
            }
        )
    if integrity_curr["missing_ranks"]:
        system_alerts.append(
            {
                "kind": "rank_space_gaps",
                "severity": "CRITICAL",
                "gaps": integrity_curr["missing_ranks"],
            }
        )
    if integrity_curr["n_ranked"] and not integrity_curr["starts_at_one"]:
        system_alerts.append(
            {
                "kind": "rank_space_offset",
                "severity": "CRITICAL",
                "min_rank": integrity_curr["min_rank"],
            }
        )

    summary = {
        "n_ticker_alerts": len(alerts),
        "n_top30_entries": sum(1 for a in alerts if "top30_entry" in a["flags"]),
        "n_top30_exits": sum(1 for a in alerts if "top30_exit" in a["flags"]),
        "n_cohort_entries": len(cohort_entered),
        "n_cohort_exits": len(cohort_exited),
        "cohort_churn_pct": round(cohort_churn_pct, 2),
        "prev_cohort_size": len(prev_cohort),
        "curr_cohort_size": len(curr_cohort),
        "expected_cohort_size": EXPECTED_V2_COHORT_SIZE,
        "n_critical": sum(1 for a in alerts if a["severity"] == "CRITICAL")
        + sum(1 for s in system_alerts if s["severity"] == "CRITICAL"),
        "n_warn": sum(1 for a in alerts if a["severity"] == "WARN")
        + sum(1 for s in system_alerts if s["severity"] == "WARN"),
        "n_watch": sum(1 for a in alerts if a["severity"] == "WATCH"),
    }

    return {
        "alerts": alerts,
        "system_alerts": system_alerts,
        "summary": summary,
        "integrity": {"current": integrity_curr, "prior": integrity_prev},
        "cohort_entered": cohort_entered,
        "cohort_exited": cohort_exited,
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "ticker",
    "company_name",
    "severity",
    "likely_reason",
    "prev_actionable_rank",
    "curr_actionable_rank",
    "rank_delta",
    "prev_ranker_v2_score",
    "curr_ranker_v2_score",
    "prev_selector_score",
    "curr_selector_score",
    "prev_final_score",
    "curr_final_score",
    "prev_composite_score",
    "curr_composite_score",
    "prev_tier_any",
    "curr_tier_any",
    "prev_development_stage",
    "curr_development_stage",
    "prev_catalyst_days",
    "curr_catalyst_days",
    "cohort_membership_change",
    "flags",
    "reasons",
]


def _sort_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(a: dict[str, Any]) -> tuple:
        sev_idx = -SEVERITY_ORDER.index(a["severity"])
        rd = a.get("rank_delta")
        rank_key = -abs(rd) if isinstance(rd, int) else 0
        return (sev_idx, rank_key, a["ticker"])

    return sorted(alerts, key=key)


def render_csv(alerts: list[dict[str, Any]]) -> str:
    import io

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for a in _sort_alerts(alerts):
        row = dict(a)
        row["flags"] = "|".join(a["flags"])
        row["reasons"] = "|".join(a["reasons"])
        w.writerow(row)
    return buf.getvalue()


def render_md(
    payload: dict[str, Any],
    as_of_date: str,
    prior_date: Optional[str],
) -> str:
    s = payload["summary"]
    sys_alerts = payload["system_alerts"]
    alerts = _sort_alerts(payload["alerts"])

    lines: list[str] = []
    lines.append(f"# Rank-change alerts — {as_of_date}")
    lines.append("")
    lines.append(f"- **prior snapshot**: `{prior_date or '(none)'}`")
    lines.append(f"- **ticker alerts**: {s['n_ticker_alerts']}")
    lines.append(f"- **severity counts**: CRITICAL={s['n_critical']}, " f"WARN={s['n_warn']}, WATCH={s['n_watch']}")
    lines.append(f"- **top-30**: +{s['n_top30_entries']} / −{s['n_top30_exits']}")
    lines.append(
        f"- **v2 cohort**: prev={s['prev_cohort_size']}, curr={s['curr_cohort_size']} "
        f"(expected {s['expected_cohort_size']}); churn={s['cohort_churn_pct']:.1f}%"
    )
    lines.append(f"- **cohort delta**: +{s['n_cohort_entries']} / −{s['n_cohort_exits']}")
    lines.append("")

    if sys_alerts:
        lines.append("## System alerts")
        for sa in sys_alerts:
            extras = {k: v for k, v in sa.items() if k not in ("kind", "severity")}
            lines.append(f"- **{sa['severity']}** `{sa['kind']}` — {extras}")
        lines.append("")

    if not alerts:
        lines.append("_No ticker alerts._")
        return "\n".join(lines)

    lines.append("## Ticker alerts")
    lines.append("")
    lines.append("| ticker | sev | rank Δ | likely reason | prev→curr | tier | flags |")
    lines.append("|---|---|---|---|---|---|---|")
    for a in alerts:
        rd = a.get("rank_delta")
        rd_str = f"{rd:+d}" if isinstance(rd, int) else "—"
        prev_rk = a.get("prev_actionable_rank")
        curr_rk = a.get("curr_actionable_rank")
        rk_pair = f"{prev_rk if prev_rk is not None else '∅'}→{curr_rk if curr_rk is not None else '∅'}"
        tier_pair = f"{a.get('prev_tier_any') or '∅'}→{a.get('curr_tier_any') or '∅'}"
        flags_str = ", ".join(a["flags"][:4]) + ("…" if len(a["flags"]) > 4 else "")
        lines.append(
            f"| {a['ticker']} | {a['severity']} | {rd_str} | "
            f"{a['likely_reason']} | {rk_pair} | {tier_pair} | {flags_str} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_rank_change_monitor(
    as_of_date: str,
    prior_date: Optional[str],
    snapshots_dir: Path,
) -> dict[str, Any]:
    curr_path = snapshots_dir / as_of_date / "rankings.csv"
    if not curr_path.exists():
        sys.exit(f"ERROR: missing current rankings: {curr_path}")
    curr_rows = load_rankings(curr_path)

    if prior_date is None:
        prior_date = find_prior_date(snapshots_dir, as_of_date)

    if prior_date is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "as_of_date": as_of_date,
            "prior_date": None,
            "alerts": [],
            "system_alerts": [],
            "summary": {
                "n_ticker_alerts": 0,
                "n_top30_entries": 0,
                "n_top30_exits": 0,
                "n_cohort_entries": 0,
                "n_cohort_exits": 0,
                "cohort_churn_pct": 0.0,
                "prev_cohort_size": 0,
                "curr_cohort_size": len(cohort_set(curr_rows)),
                "expected_cohort_size": EXPECTED_V2_COHORT_SIZE,
                "n_critical": 0,
                "n_warn": 0,
                "n_watch": 0,
            },
            "integrity": {"current": check_integrity(curr_rows), "prior": None},
            "cohort_entered": [],
            "cohort_exited": [],
            "note": "no prior snapshot available — cannot diff",
        }

    prev_path = snapshots_dir / prior_date / "rankings.csv"
    if not prev_path.exists():
        sys.exit(f"ERROR: missing prior rankings: {prev_path}")
    prev_rows = load_rankings(prev_path)

    payload = build_alerts(prev_rows, curr_rows)
    payload["schema_version"] = SCHEMA_VERSION
    payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["as_of_date"] = as_of_date
    payload["prior_date"] = prior_date
    return payload


def write_outputs(payload: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "rank_change_alerts.csv"
    md_path = out_dir / "rank_change_alerts.md"
    json_path = out_dir / "rank_change_alerts.json"

    csv_path.write_text(render_csv(payload["alerts"]), encoding="utf-8")
    md_path.write_text(
        render_md(payload, payload["as_of_date"], payload["prior_date"]),
        encoding="utf-8",
    )
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return {"csv": csv_path, "md": md_path, "json": json_path}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", help="snapshot date YYYY-MM-DD (default: latest)")
    parser.add_argument("--prior-date", help="prior date to diff against (default: most recent before as-of)")
    parser.add_argument(
        "--snapshots-dir",
        default=str(SNAPSHOTS_DIR),
        help="snapshots root (default: data/snapshots)",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress stdout summary")
    parser.add_argument(
        "--print-alerts",
        action="store_true",
        help="after summary, print one line per CRITICAL/WARN alert and system alerts",
    )
    args = parser.parse_args(argv)

    snapshots_dir = Path(args.snapshots_dir)
    as_of = args.as_of_date or find_latest_date(snapshots_dir)
    if not as_of:
        sys.exit(f"ERROR: no snapshots found under {snapshots_dir}")

    payload = build_rank_change_monitor(as_of, args.prior_date, snapshots_dir)
    paths = write_outputs(payload, snapshots_dir / as_of)

    if not args.quiet:
        s = payload["summary"]
        print(
            f"rank_change_monitor {as_of} (vs {payload.get('prior_date') or '∅'}): "
            f"alerts={s['n_ticker_alerts']} "
            f"CRITICAL={s['n_critical']} WARN={s['n_warn']} WATCH={s['n_watch']} "
            f"cohort_churn={s['cohort_churn_pct']:.1f}%"
        )
        print(f"  csv:  {paths['csv']}")
        print(f"  md:   {paths['md']}")
        print(f"  json: {paths['json']}")

    if args.print_alerts:
        for sa in payload.get("system_alerts", []):
            extras = {k: v for k, v in sa.items() if k not in ("kind", "severity")}
            print(f"  [SYSTEM-{sa['severity']}] {sa['kind']}: {extras}")
        hi = [a for a in payload.get("alerts", []) if a["severity"] in ("CRITICAL", "WARN")]
        for a in hi:
            rd = a.get("rank_delta")
            rd_str = f"{rd:+d}" if isinstance(rd, int) else "∅"
            flags = ",".join(a["flags"][:3])
            print(f"  [{a['severity']}] {a['ticker']:6s} rankΔ={rd_str:>4} " f"{a['likely_reason']:32s} {flags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
