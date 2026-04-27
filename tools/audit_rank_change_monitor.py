#!/usr/bin/env python3
"""audit_rank_change_monitor.py — Soak-window audit of the rank-change monitor.

Reads rank_change_alerts.json artifacts produced by build_rank_change_monitor.py
across a date range and reports calibration evidence: severity rates, top
firing reasons, integrity pass-rate, cohort-churn distribution, repeat
offenders, and explicit coverage (missing days are NOT silently ignored,
per the observation-bias guidance).

Read-only diagnostic. Does not modify any state.

Usage:
    python tools/audit_rank_change_monitor.py
    python tools/audit_rank_change_monitor.py --start-date 2026-04-28 --end-date 2026-05-11
    python tools/audit_rank_change_monitor.py --days 10
    python tools/audit_rank_change_monitor.py --json-out artifacts/audit/2026-05-11.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

COHORT_CHURN_REVIEW_PCT = 10.0
EXPECTED_V2_COHORT_SIZE = 60
REPEAT_OFFENDER_THRESHOLD = 3


def _weekdays_between(start: date, end: date) -> list[str]:
    out: list[str] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def collect(
    snapshots_dir: Path,
    start: str,
    end: str,
) -> dict[str, Any]:
    expected_dates = _weekdays_between(date.fromisoformat(start), date.fromisoformat(end))
    days: list[dict[str, Any]] = []
    missing: list[str] = []
    for d in expected_dates:
        path = snapshots_dir / d / "rank_change_alerts.json"
        if not path.exists():
            missing.append(d)
            continue
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            missing.append(f"{d}({type(e).__name__})")
            continue
        days.append(payload)
    return {
        "expected": expected_dates,
        "present": [d.get("as_of_date") for d in days],
        "missing": missing,
        "days": days,
    }


def aggregate(days: list[dict[str, Any]]) -> dict[str, Any]:
    total_critical = 0
    total_warn = 0
    total_watch = 0
    integrity_ok = 0
    integrity_fail: list[str] = []
    cohort_size_off: list[tuple[str, int]] = []
    churns: list[float] = []
    churn_above: list[tuple[str, float]] = []
    reason_counts: Counter = Counter()
    flag_counts: Counter = Counter()
    system_kind_counts: Counter = Counter()
    ticker_warn_days: defaultdict[str, list[tuple[str, str, list[str]]]] = defaultdict(list)
    per_day: list[dict[str, Any]] = []

    for d in days:
        s = d.get("summary", {})
        total_critical += s.get("n_critical", 0)
        total_warn += s.get("n_warn", 0)
        total_watch += s.get("n_watch", 0)
        churn = float(s.get("cohort_churn_pct", 0.0) or 0.0)
        churns.append(churn)
        if churn >= COHORT_CHURN_REVIEW_PCT:
            churn_above.append((d.get("as_of_date", "?"), churn))

        integ = (d.get("integrity") or {}).get("current") or {}
        if integ.get("ok"):
            integrity_ok += 1
        else:
            integrity_fail.append(d.get("as_of_date", "?"))
        cohort_actual = s.get("curr_cohort_size", EXPECTED_V2_COHORT_SIZE)
        if cohort_actual != EXPECTED_V2_COHORT_SIZE:
            cohort_size_off.append((d.get("as_of_date", "?"), int(cohort_actual)))

        for sa in d.get("system_alerts") or []:
            system_kind_counts[(sa.get("severity", "?"), sa.get("kind", "?"))] += 1

        for a in d.get("alerts") or []:
            sev = a.get("severity")
            if sev in ("CRITICAL", "WARN"):
                reason_counts[(sev, a.get("likely_reason", "unknown"))] += 1
                for f in a.get("flags") or []:
                    base = f.split(":")[0]
                    if base.startswith("rank_delta_"):
                        base = "rank_delta"
                    flag_counts[(sev, base)] += 1
                ticker_warn_days[a.get("ticker", "?")].append(
                    (
                        d.get("as_of_date", "?"),
                        sev,
                        a.get("flags") or [],
                    )
                )

        per_day.append(
            {
                "date": d.get("as_of_date"),
                "prior": d.get("prior_date"),
                "alerts": s.get("n_ticker_alerts", 0),
                "critical": s.get("n_critical", 0),
                "warn": s.get("n_warn", 0),
                "watch": s.get("n_watch", 0),
                "cohort_churn_pct": round(churn, 2),
                "cohort_size": s.get("curr_cohort_size"),
                "integrity_ok": bool(integ.get("ok")),
                "system_alerts": [f"{sa.get('severity')}:{sa.get('kind')}" for sa in d.get("system_alerts") or []],
            }
        )

    repeat_offenders = sorted(
        (
            {
                "ticker": t,
                "warn_days": len(rows),
                "dates": [r[0] for r in rows],
                "severities": Counter(r[1] for r in rows),
            }
            for t, rows in ticker_warn_days.items()
            if len(rows) >= REPEAT_OFFENDER_THRESHOLD
        ),
        key=lambda x: -x["warn_days"],
    )

    if churns:
        churns_sorted = sorted(churns)
        median_churn = churns_sorted[len(churns_sorted) // 2]
        p90_idx = max(0, int(0.9 * (len(churns_sorted) - 1)))
        p90_churn = churns_sorted[p90_idx]
        max_churn = churns_sorted[-1]
    else:
        median_churn = p90_churn = max_churn = 0.0

    total_alerts = total_critical + total_warn + total_watch
    return {
        "n_days": len(days),
        "total_critical": total_critical,
        "total_warn": total_warn,
        "total_watch": total_watch,
        "total_alerts": total_alerts,
        "integrity_ok_days": integrity_ok,
        "integrity_fail_days": integrity_fail,
        "cohort_size_off": cohort_size_off,
        "cohort_churn": {
            "median_pct": round(median_churn, 2),
            "p90_pct": round(p90_churn, 2),
            "max_pct": round(max_churn, 2),
            "days_above_threshold": len(churn_above),
            "above_threshold_days": churn_above,
        },
        "top_warn_reasons": reason_counts.most_common(20),
        "top_warn_flags": flag_counts.most_common(20),
        "system_kind_counts": [
            {"severity": sev, "kind": k, "count": n} for (sev, k), n in system_kind_counts.most_common()
        ],
        "repeat_offenders": repeat_offenders,
        "per_day": per_day,
    }


def derive_observations(agg: dict[str, Any], coverage: dict[str, Any]) -> list[str]:
    """Surface data-driven observations. Does NOT prescribe action."""
    obs: list[str] = []
    n_expected = len(coverage["expected"])
    n_present = len(coverage["present"])
    n_days = agg["n_days"]

    if coverage["missing"]:
        obs.append(
            f"COVERAGE: {n_present}/{n_expected} weekday alert files present — "
            f"missing days bias any structural conclusion; treat with caution"
        )
    else:
        obs.append(f"COVERAGE: {n_present}/{n_expected} weekday alert files present (clean)")

    if agg["integrity_fail_days"]:
        obs.append(
            f"INTEGRITY: rank-space failed on {len(agg['integrity_fail_days'])} day(s) "
            f"({', '.join(agg['integrity_fail_days'])}) — investigate before tuning"
        )
    elif n_days:
        obs.append(f"INTEGRITY: {agg['integrity_ok_days']}/{n_days} days clean")

    if n_days:
        if agg["total_critical"] == 0:
            obs.append(
                "CRITICAL rate = 0 — either rules are well-calibrated or thresholds "
                "are too lax; cross-check against any manual incident memory before "
                "concluding"
            )
        else:
            obs.append(
                f"CRITICAL: {agg['total_critical']} alert(s) fired across "
                f"{n_days} day(s) — review whether each was a real incident"
            )

    churn = agg["cohort_churn"]
    if churn["days_above_threshold"] >= max(1, n_days // 2):
        obs.append(
            f"COHORT-CHURN: ≥{COHORT_CHURN_REVIEW_PCT}% on "
            f"{churn['days_above_threshold']}/{n_days} day(s); "
            f"median={churn['median_pct']}%, p90={churn['p90_pct']}%, "
            f"max={churn['max_pct']}% — threshold may be too tight or "
            f"the cohort boundary is genuinely jittery"
        )
    elif n_days:
        obs.append(f"COHORT-CHURN: median={churn['median_pct']}%, " f"max={churn['max_pct']}% over {n_days} day(s)")

    if agg["top_warn_reasons"]:
        primary, primary_n = agg["top_warn_reasons"][0]
        total_warn_critical = agg["total_critical"] + agg["total_warn"]
        if total_warn_critical:
            primary_pct = 100.0 * primary_n / total_warn_critical
            sev, reason = primary
            if primary_pct >= 60.0 and "cohort" in reason:
                obs.append(
                    f"REASON-MIX: {sev}/{reason} accounts for {primary_pct:.0f}% of "
                    f"WARN+CRITICAL alerts — boundary churn dominates the signal; "
                    f"consider whether hysteresis would suppress real noise vs. mute "
                    f"real model regressions"
                )
            else:
                obs.append(f"REASON-MIX: top reason is {sev}/{reason} " f"({primary_pct:.0f}% of WARN+CRITICAL)")

    if agg["repeat_offenders"]:
        names = ", ".join(f"{r['ticker']}({r['warn_days']})" for r in agg["repeat_offenders"][:5])
        obs.append(
            f"REPEAT-OFFENDERS: {len(agg['repeat_offenders'])} ticker(s) flagged "
            f"WARN+ on ≥{REPEAT_OFFENDER_THRESHOLD} days — top: {names}"
        )

    return obs


def render_text(agg: dict[str, Any], coverage: dict[str, Any], window: tuple[str, str]) -> str:
    start, end = window
    lines: list[str] = []
    lines.append(f"Rank-change monitor audit — window {start} → {end}")
    lines.append("")
    lines.append(
        f"Days expected (weekdays): {len(coverage['expected'])}    "
        f"present: {len(coverage['present'])}    "
        f"missing: {len(coverage['missing'])}"
    )
    if coverage["missing"]:
        lines.append(f"  missing: {', '.join(coverage['missing'])}")
    lines.append("")

    n_days = agg["n_days"]
    lines.append("Per-day:")
    lines.append("  date         alerts  CRIT  WARN  WATCH  cohort%  v2_size  integ")
    for r in agg["per_day"]:
        lines.append(
            f"  {r['date']}    {r['alerts']:>5}    "
            f"{r['critical']:>2}    {r['warn']:>3}    {r['watch']:>4}   "
            f"{r['cohort_churn_pct']:>5}%   {r['cohort_size'] or '-':>5}    "
            f"{'OK' if r['integrity_ok'] else 'FAIL'}"
        )
    lines.append("")

    lines.append(f"Severity totals over {n_days} day(s):")
    lines.append(
        f"  CRITICAL: {agg['total_critical']:>4}    "
        f"WARN: {agg['total_warn']:>4}    "
        f"WATCH: {agg['total_watch']:>4}    "
        f"all: {agg['total_alerts']:>4}"
    )
    lines.append("")

    churn = agg["cohort_churn"]
    lines.append(
        f"Cohort churn: median={churn['median_pct']}%  "
        f"p90={churn['p90_pct']}%  max={churn['max_pct']}%  "
        f"days≥{COHORT_CHURN_REVIEW_PCT}%={churn['days_above_threshold']}"
    )
    lines.append("")

    if agg["system_kind_counts"]:
        lines.append("System alerts (kind × severity):")
        for s in agg["system_kind_counts"]:
            lines.append(f"  [{s['severity']}] {s['kind']}: {s['count']}")
        lines.append("")

    if agg["top_warn_reasons"]:
        lines.append("Top WARN/CRITICAL reasons:")
        for (sev, reason), n in agg["top_warn_reasons"][:10]:
            lines.append(f"  [{sev}] {reason:36s} {n}")
        lines.append("")

    if agg["top_warn_flags"]:
        lines.append("Top WARN/CRITICAL flags:")
        for (sev, flag), n in agg["top_warn_flags"][:10]:
            lines.append(f"  [{sev}] {flag:36s} {n}")
        lines.append("")

    if agg["repeat_offenders"]:
        lines.append(f"Repeat offenders (≥{REPEAT_OFFENDER_THRESHOLD} WARN+ days):")
        for r in agg["repeat_offenders"][:15]:
            sev = ", ".join(f"{k}={v}" for k, v in r["severities"].items())
            lines.append(f"  {r['ticker']:6s} days={r['warn_days']}  " f"({sev})  dates={', '.join(r['dates'])}")
        lines.append("")

    lines.append("Observations:")
    for o in derive_observations(agg, coverage):
        lines.append(f"  - {o}")

    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-dir", default=str(SNAPSHOTS_DIR))
    parser.add_argument("--start-date", help="YYYY-MM-DD; default: end-date minus N days")
    parser.add_argument("--end-date", help="YYYY-MM-DD; default: today")
    parser.add_argument("--days", type=int, default=10, help="window size when start-date omitted")
    parser.add_argument("--json-out", help="optional path to write the aggregated JSON")
    args = parser.parse_args(argv)

    end_date = args.end_date or date.today().isoformat()
    if args.start_date:
        start_date = args.start_date
    else:
        end_d = date.fromisoformat(end_date)
        start_date = (end_d - timedelta(days=args.days * 2)).isoformat()
        # widen to ensure we capture --days weekdays even with weekends in the window

    snapshots_dir = Path(args.snapshots_dir)
    coverage = collect(snapshots_dir, start_date, end_date)
    agg = aggregate(coverage["days"])

    print(render_text(agg, coverage, (start_date, end_date)))

    if args.json_out:
        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "window": {"start": start_date, "end": end_date},
            "coverage": {
                "expected": coverage["expected"],
                "present": coverage["present"],
                "missing": coverage["missing"],
            },
            "aggregate": agg,
            "observations": derive_observations(agg, coverage),
        }
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
