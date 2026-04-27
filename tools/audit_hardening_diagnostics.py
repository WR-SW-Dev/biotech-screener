#!/usr/bin/env python3
"""audit_hardening_diagnostics.py — Soak-window audit of the diagnostic suite.

Reads the four diagnostic artifacts produced by the hardening pass
across a date range and reports calibration evidence: integrity pass rate,
feature-coverage drift, distribution turnover percentiles, sentinel
transition counts. Surfaces missing days explicitly (per the
observation-bias guidance).

Read-only. Does NOT modify any state.

Usage:
    python tools/audit_hardening_diagnostics.py
    python tools/audit_hardening_diagnostics.py --start-date 2026-04-28 --end-date 2026-05-04
    python tools/audit_hardening_diagnostics.py --json-out artifacts/audit/2026-05-04.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"

ARTIFACT_NAMES = [
    "snapshot_integrity_report.json",
    "feature_coverage_report.json",
    "distribution_drift_report.json",
    "sentinel_ticker_report.json",
]


def _weekdays_between(start: date, end: date) -> list[str]:
    out: list[str] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def collect(snapshots_dir: Path, start: str, end: str) -> dict[str, Any]:
    expected = _weekdays_between(date.fromisoformat(start), date.fromisoformat(end))
    days: list[dict[str, Any]] = []
    missing_artifacts: defaultdict[str, list[str]] = defaultdict(list)
    fully_missing: list[str] = []

    for d in expected:
        snap = snapshots_dir / d
        if not snap.exists():
            fully_missing.append(d)
            continue
        record: dict[str, Any] = {"date": d}
        any_artifact = False
        for name in ARTIFACT_NAMES:
            path = snap / name
            if not path.exists():
                missing_artifacts[d].append(name)
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    record[name] = json.load(f)
                any_artifact = True
            except (OSError, json.JSONDecodeError) as e:
                missing_artifacts[d].append(f"{name}({type(e).__name__})")
        if any_artifact:
            days.append(record)
        else:
            fully_missing.append(d)

    return {
        "expected": expected,
        "present_dates": [d["date"] for d in days],
        "fully_missing": fully_missing,
        "partial_missing": dict(missing_artifacts),
        "days": days,
    }


def aggregate_integrity(days: list[dict[str, Any]]) -> dict[str, Any]:
    sev_counts: Counter = Counter()
    fail_days: list[dict[str, Any]] = []
    check_fail_counts: Counter = Counter()
    for d in days:
        rep = d.get("snapshot_integrity_report.json")
        if not rep:
            continue
        sev = rep.get("overall_severity", "?")
        sev_counts[sev] += 1
        if sev == "FAIL":
            failed = [c["name"] for c in rep.get("checks", []) if c["severity"] == "FAIL"]
            fail_days.append({"date": d["date"], "failed_checks": failed})
            for n in failed:
                check_fail_counts[n] += 1
    return {
        "n_days": sum(sev_counts.values()),
        "severity_counts": dict(sev_counts),
        "fail_days": fail_days,
        "top_failing_checks": check_fail_counts.most_common(),
    }


def aggregate_feature_coverage(days: list[dict[str, Any]]) -> dict[str, Any]:
    feature_pcts: defaultdict[str, list[float]] = defaultdict(list)
    feature_severities: defaultdict[str, Counter] = defaultdict(Counter)
    for d in days:
        rep = d.get("feature_coverage_report.json")
        if not rep:
            continue
        for f in rep.get("features", []):
            name = f["feature"]
            feature_pcts[name].append(float(f.get("pct_present", 0.0)))
            feature_severities[name][f.get("severity", "?")] += 1

    summary = []
    for name, vals in sorted(feature_pcts.items()):
        if not vals:
            continue
        vals_sorted = sorted(vals)
        median = vals_sorted[len(vals_sorted) // 2]
        summary.append(
            {
                "feature": name,
                "n_days": len(vals),
                "min_pct": round(min(vals), 1),
                "median_pct": round(median, 1),
                "max_pct": round(max(vals), 1),
                "severity_mix": dict(feature_severities[name]),
            }
        )
    # Sort: most-degraded first (lowest min_pct)
    summary.sort(key=lambda r: r["min_pct"])
    return {
        "n_features": len(summary),
        "features": summary,
    }


def aggregate_drift(days: list[dict[str, Any]]) -> dict[str, Any]:
    top30_turnover: list[float] = []
    top60_turnover: list[float] = []
    cohort_turnover: list[float] = []
    high_churn_days: list[dict[str, Any]] = []
    for d in days:
        rep = d.get("distribution_drift_report.json")
        if not rep:
            continue
        t = rep.get("turnover", {})
        if not t:
            continue
        v_top30 = float((t.get("top30") or {}).get("turnover_pct", 0.0))
        v_top60 = float((t.get("top60") or {}).get("turnover_pct", 0.0))
        v_coh = float((t.get("v2_cohort") or {}).get("turnover_pct", 0.0))
        top30_turnover.append(v_top30)
        top60_turnover.append(v_top60)
        cohort_turnover.append(v_coh)
        if v_top30 >= 25.0 or v_coh >= 20.0:
            high_churn_days.append(
                {
                    "date": d["date"],
                    "top30_pct": v_top30,
                    "top60_pct": v_top60,
                    "cohort_pct": v_coh,
                }
            )

    def _stats(vals: list[float]) -> dict[str, Any]:
        if not vals:
            return {"n": 0}
        s = sorted(vals)
        return {
            "n": len(s),
            "median": round(s[len(s) // 2], 2),
            "p90": round(s[max(0, int(0.9 * (len(s) - 1)))], 2),
            "max": round(s[-1], 2),
        }

    return {
        "top30": _stats(top30_turnover),
        "top60": _stats(top60_turnover),
        "v2_cohort": _stats(cohort_turnover),
        "high_churn_days": high_churn_days,
    }


def aggregate_sentinel(days: list[dict[str, Any]]) -> dict[str, Any]:
    per_ticker_transitions: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    per_ticker_rank_deltas: defaultdict[str, list[int]] = defaultdict(list)
    n_days_with_report = 0
    for d in days:
        rep = d.get("sentinel_ticker_report.json")
        if not rep:
            continue
        n_days_with_report += 1
        for r in rep.get("records", []):
            tk = r.get("ticker", "?")
            rd = r.get("rank_delta")
            if isinstance(rd, int):
                per_ticker_rank_deltas[tk].append(rd)
            ct = r.get("cohort_transition")
            if ct:
                per_ticker_transitions[tk].append({"date": d["date"], "transition": ct})

    summary = []
    tickers = sorted(set(per_ticker_rank_deltas) | set(per_ticker_transitions))
    for tk in tickers:
        deltas = per_ticker_rank_deltas.get(tk, [])
        ts = per_ticker_transitions.get(tk, [])
        summary.append(
            {
                "ticker": tk,
                "n_days_observed": len(deltas),
                "n_cohort_transitions": len(ts),
                "abs_max_rank_delta": max((abs(d) for d in deltas), default=0),
                "transitions": ts,
            }
        )
    summary.sort(key=lambda r: -r["n_cohort_transitions"])
    return {
        "n_days_with_report": n_days_with_report,
        "per_ticker": summary,
    }


def derive_observations(coverage: dict[str, Any], aggs: dict[str, Any]) -> list[str]:
    obs: list[str] = []
    n_expected = len(coverage["expected"])
    n_present = len(coverage["present_dates"])

    if coverage["fully_missing"] or coverage["partial_missing"]:
        obs.append(
            f"COVERAGE: {n_present}/{n_expected} weekday snapshots have at least one "
            f"diagnostic artifact; {len(coverage['fully_missing'])} fully missing, "
            f"{len(coverage['partial_missing'])} partial — missing days bias structural "
            f"conclusions; treat with caution"
        )
    else:
        obs.append(f"COVERAGE: {n_present}/{n_expected} weekday snapshots clean")

    integ = aggs["integrity"]
    if integ["n_days"]:
        sev = integ["severity_counts"]
        obs.append(
            "INTEGRITY: " + ", ".join(f"{k}={v}" for k, v in sorted(sev.items())) + f" across {integ['n_days']} day(s)"
        )
        if integ["fail_days"]:
            obs.append(
                f"INTEGRITY-FAIL: {len(integ['fail_days'])} day(s) — "
                f"top-failing checks: {dict(integ['top_failing_checks'][:3])}"
            )

    fc = aggs["feature_coverage"]
    if fc["features"]:
        worst = fc["features"][:3]  # already sorted by min_pct ascending
        obs.append(
            "FEATURE-COVERAGE: most-degraded features (min over window): "
            + ", ".join(f"{w['feature']}={w['min_pct']}%" for w in worst)
        )

    dr = aggs["drift"]
    if dr["top30"].get("n", 0):
        obs.append(
            f"TURNOVER: top-30 median={dr['top30']['median']}% "
            f"p90={dr['top30']['p90']}% max={dr['top30']['max']}%; "
            f"v2 cohort median={dr['v2_cohort']['median']}% max={dr['v2_cohort']['max']}%"
        )
    if dr["high_churn_days"]:
        obs.append(
            f"HIGH-CHURN: {len(dr['high_churn_days'])} day(s) above review threshold "
            f"(top30 ≥25% or cohort ≥20%) — investigate before tuning"
        )

    sent = aggs["sentinel"]
    if sent["per_ticker"]:
        active = [r for r in sent["per_ticker"] if r["n_cohort_transitions"] > 0]
        if active:
            obs.append(
                f"SENTINELS: {len(active)} ticker(s) saw cohort transitions over window — "
                + ", ".join(f"{r['ticker']}={r['n_cohort_transitions']}" for r in active[:5])
            )
        else:
            obs.append("SENTINELS: zero cohort transitions over window (stable)")

    return obs


def render_text(coverage: dict[str, Any], aggs: dict[str, Any], window: tuple[str, str]) -> str:
    start, end = window
    lines: list[str] = []
    lines.append(f"Hardening diagnostics audit — window {start} → {end}")
    lines.append("")
    lines.append(
        f"Days expected (weekdays): {len(coverage['expected'])}    "
        f"present: {len(coverage['present_dates'])}    "
        f"fully missing: {len(coverage['fully_missing'])}    "
        f"partial: {len(coverage['partial_missing'])}"
    )
    if coverage["fully_missing"]:
        lines.append(f"  fully missing: {', '.join(coverage['fully_missing'])}")
    if coverage["partial_missing"]:
        lines.append("  partial missing per-day:")
        for d, names in sorted(coverage["partial_missing"].items()):
            lines.append(f"    {d}: {', '.join(names)}")
    lines.append("")

    # Integrity
    lines.append("## Integrity")
    integ = aggs["integrity"]
    sev_str = ", ".join(f"{k}={v}" for k, v in sorted(integ["severity_counts"].items()))
    lines.append(f"  severity counts: {sev_str or '(none)'}")
    if integ["fail_days"]:
        lines.append("  FAIL days:")
        for fd in integ["fail_days"]:
            lines.append(f"    {fd['date']}: {', '.join(fd['failed_checks'])}")
    if integ["top_failing_checks"]:
        lines.append(f"  top-failing checks: {dict(integ['top_failing_checks'])}")
    lines.append("")

    # Feature coverage
    lines.append("## Feature coverage (sorted by min_pct over window)")
    fc = aggs["feature_coverage"]
    if fc["features"]:
        lines.append("  feature                               n   min%   med%   max%   severity_mix")
        for f in fc["features"]:
            sev_mix = ", ".join(f"{k}={v}" for k, v in sorted(f["severity_mix"].items()))
            lines.append(
                f"  {f['feature']:<36}  {f['n_days']:>2}   "
                f"{f['min_pct']:>4.0f}   {f['median_pct']:>4.0f}   "
                f"{f['max_pct']:>4.0f}   {sev_mix}"
            )
    lines.append("")

    # Distribution drift
    lines.append("## Distribution drift / turnover")
    dr = aggs["drift"]
    for tag in ("top30", "top60", "v2_cohort"):
        s = dr[tag]
        if s.get("n"):
            lines.append(f"  {tag:10s}  n={s['n']}  median={s['median']}%  " f"p90={s['p90']}%  max={s['max']}%")
    if dr["high_churn_days"]:
        lines.append("  HIGH-CHURN days (top30 ≥25% or cohort ≥20%):")
        for h in dr["high_churn_days"]:
            lines.append(f"    {h['date']}: top30={h['top30_pct']}%  cohort={h['cohort_pct']}%")
    lines.append("")

    # Sentinel
    lines.append("## Sentinel ticker activity")
    sent = aggs["sentinel"]
    if sent["per_ticker"]:
        lines.append("  ticker  n_days  abs_max_Δ  transitions")
        for r in sent["per_ticker"]:
            t_str = ", ".join(f"{x['date']}({x['transition']})" for x in r["transitions"])
            lines.append(
                f"  {r['ticker']:<6}  {r['n_days_observed']:>5}   "
                f"{r['abs_max_rank_delta']:>6}     {t_str or '(stable)'}"
            )
    lines.append("")

    lines.append("## Observations")
    for o in derive_observations(coverage, aggs):
        lines.append(f"  - {o}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-dir", default=str(SNAPSHOTS_DIR))
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    end_date = args.end_date or date.today().isoformat()
    if args.start_date:
        start_date = args.start_date
    else:
        end_d = date.fromisoformat(end_date)
        start_date = (end_d - timedelta(days=args.days * 2)).isoformat()

    snapshots_dir = Path(args.snapshots_dir)
    coverage = collect(snapshots_dir, start_date, end_date)
    aggs = {
        "integrity": aggregate_integrity(coverage["days"]),
        "feature_coverage": aggregate_feature_coverage(coverage["days"]),
        "drift": aggregate_drift(coverage["days"]),
        "sentinel": aggregate_sentinel(coverage["days"]),
    }

    print(render_text(coverage, aggs, (start_date, end_date)))

    if args.json_out:
        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "window": {"start": start_date, "end": end_date},
            "coverage": {
                "expected": coverage["expected"],
                "present_dates": coverage["present_dates"],
                "fully_missing": coverage["fully_missing"],
                "partial_missing": coverage["partial_missing"],
            },
            "aggregate": aggs,
            "observations": derive_observations(coverage, aggs),
        }
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
