#!/usr/bin/env python3
"""Weekly Go/No-Go Gate — deterministic safety latch before trading.

Runs hard and soft checks on snapshot integrity, price coverage,
gap-risk concentration, turnover sanity, and focus bucket health.
Produces GO_NOGO.md (human) + GO_NOGO.json (machine).

Usage:
    python3 tools/weekly_go_nogo.py --as-of-date 2026-03-08
    python3 tools/weekly_go_nogo.py --as-of-date 2026-03-08 --confirm
    python3 tools/weekly_go_nogo.py --as-of-date 2026-03-08 --relaxed
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import BUCKET_DISPLAY, BUCKET_NAMES, SHADOW_ROOT, SNAPSHOTS_ROOT, load_price_map

SCHEMA_VERSION = "weekly_go_nogo.v1"

# Required metadata provenance fields
REQUIRED_PROVENANCE = ["ruleset_id", "ruleset_hash", "engine_version"]

# Required rankings.csv columns
REQUIRED_RANKINGS_COLS = [
    "ticker",
    "actionable_rank",
    "catalyst_days",
    "catalyst_mode",
    "eligible",
]

# Default thresholds
DEFAULT_MAX_HIGH_GAP_NAMES = 5
DEFAULT_TURNOVER_WARN_MULT = 2.5
DEFAULT_TURNOVER_WARN_FLOOR = 0.05
DEFAULT_TURNOVER_FAIL_MULT = 4.0
DEFAULT_TURNOVER_FAIL_FLOOR = 0.10
DEFAULT_FOCUS_MIN_NAMES = 15
DEFAULT_FOCUS_WARN_STREAK = 3
DEFAULT_FOCUS_FAIL_STREAK = 6


# ---------------------------------------------------------------------------
# Check result helpers
# ---------------------------------------------------------------------------


def _check(
    name: str,
    status: str,
    detail: str,
    *,
    hard: bool = False,
) -> Dict[str, Any]:
    return {
        "check": name,
        "status": status,  # PASS, WARN, FAIL
        "hard": hard,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# A) Snapshot integrity (hard)
# ---------------------------------------------------------------------------


def check_snapshot_integrity(snap_dir: Path) -> List[Dict[str, Any]]:
    """Check metadata provenance, preflight status, rankings columns."""
    results = []

    # Metadata provenance
    meta_path = snap_dir / "metadata.json"
    if not meta_path.is_file():
        results.append(
            _check(
                "snapshot_metadata",
                "FAIL",
                f"metadata.json not found in {snap_dir}",
                hard=True,
            )
        )
        return results

    with open(meta_path) as f:
        meta = json.load(f)

    missing_fields = [k for k in REQUIRED_PROVENANCE if not meta.get(k)]
    if missing_fields:
        results.append(
            _check(
                "snapshot_provenance",
                "FAIL",
                f"Missing provenance fields: {', '.join(missing_fields)}",
                hard=True,
            )
        )
    else:
        results.append(
            _check(
                "snapshot_provenance",
                "PASS",
                f"ruleset={meta['ruleset_id']}, engine={meta['engine_version']}",
                hard=True,
            )
        )

    # Preflight / manifest status
    manifest_path = snap_dir / "run_manifest.json"
    if manifest_path.is_file():
        with open(manifest_path) as f:
            manifest = json.load(f)
        overall = manifest.get("overall_status", "").upper()
        if overall == "FAIL":
            results.append(
                _check(
                    "preflight_status",
                    "FAIL",
                    f"run_manifest overall_status={overall}",
                    hard=True,
                )
            )
        else:
            results.append(
                _check(
                    "preflight_status",
                    "PASS",
                    f"run_manifest overall_status={overall or 'n/a'}",
                    hard=True,
                )
            )
    else:
        results.append(
            _check(
                "preflight_status",
                "PASS",
                "No run_manifest.json (skipped check)",
                hard=True,
            )
        )

    # Rankings.csv columns
    rankings_path = snap_dir / "rankings.csv"
    if not rankings_path.is_file():
        results.append(
            _check(
                "rankings_columns",
                "FAIL",
                "rankings.csv not found",
                hard=True,
            )
        )
    else:
        with open(rankings_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            cols = reader.fieldnames or []
        missing_cols = [c for c in REQUIRED_RANKINGS_COLS if c not in cols]
        if missing_cols:
            results.append(
                _check(
                    "rankings_columns",
                    "FAIL",
                    f"Missing columns: {', '.join(missing_cols)}",
                    hard=True,
                )
            )
        else:
            results.append(
                _check(
                    "rankings_columns",
                    "PASS",
                    f"{len(cols)} columns present",
                    hard=True,
                )
            )

    return results


# ---------------------------------------------------------------------------
# B) Price coverage for tradable set (hard)
# ---------------------------------------------------------------------------


def check_price_coverage(
    traded_tickers: List[str],
    prices: Dict[str, float],
    positions: List[Dict[str, Any]],
    *,
    relaxed: bool = False,
) -> List[Dict[str, Any]]:
    """Check price exists for all traded tickers."""
    missing = []
    for t in traded_tickers:
        if t not in prices or prices[t] <= 0:
            missing.append(t)

    # Also check MISSING price_coverage flags on positions
    coverage_missing = [
        p["ticker"] for p in positions if p.get("price_coverage") == "MISSING" and p["ticker"] in traded_tickers
    ]
    all_missing = sorted(set(missing) | set(coverage_missing))

    if all_missing:
        status = "FAIL" if not relaxed else "WARN"
        return [
            _check(
                "price_coverage",
                status,
                f"{len(all_missing)} traded names missing price: {', '.join(all_missing[:10])}",
                hard=not relaxed,
            )
        ]
    return [
        _check(
            "price_coverage",
            "PASS",
            f"All {len(traded_tickers)} traded names have prices",
            hard=True,
        )
    ]


# ---------------------------------------------------------------------------
# C) Gap-risk concentration (soft → escalates)
# ---------------------------------------------------------------------------


def check_gap_risk(
    positions: List[Dict[str, Any]],
    buy_tickers: List[str],
    *,
    max_high_gap: int = DEFAULT_MAX_HIGH_GAP_NAMES,
) -> List[Dict[str, Any]]:
    """Check gap-risk HIGH count in portfolio + new buys."""
    high_names = [p["ticker"] for p in positions if p.get("gap_risk") == "HIGH"]
    n_high = len(high_names)

    if n_high > max_high_gap + 2:
        return [
            _check(
                "gap_risk_concentration",
                "FAIL",
                f"{n_high} HIGH gap-risk names (limit {max_high_gap}+2): {', '.join(high_names[:8])}",
            )
        ]
    if n_high > max_high_gap:
        return [
            _check(
                "gap_risk_concentration",
                "WARN",
                f"{n_high} HIGH gap-risk names (warn threshold {max_high_gap}): {', '.join(high_names[:8])}",
            )
        ]
    return [
        _check(
            "gap_risk_concentration",
            "PASS",
            f"{n_high} HIGH gap-risk names (limit {max_high_gap})",
        )
    ]


# ---------------------------------------------------------------------------
# D) Turnover sanity (soft)
# ---------------------------------------------------------------------------


def _load_trailing_turnover(
    perf_csv: Path,
    as_of_date: str,
    n_weeks: int = 4,
) -> List[float]:
    """Load last n_weeks turnover values from performance.csv."""
    if not perf_csv.is_file():
        return []
    rows = []
    with open(perf_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("date", "") < as_of_date:
                try:
                    rows.append(float(row.get("turnover", 0)))
                except (ValueError, TypeError):
                    pass
    return rows[-n_weeks:]


def check_turnover(
    projected_turnover: float,
    perf_csv: Path,
    as_of_date: str,
    *,
    warn_mult: float = DEFAULT_TURNOVER_WARN_MULT,
    warn_floor: float = DEFAULT_TURNOVER_WARN_FLOOR,
    fail_mult: float = DEFAULT_TURNOVER_FAIL_MULT,
    fail_floor: float = DEFAULT_TURNOVER_FAIL_FLOOR,
) -> List[Dict[str, Any]]:
    """Check projected turnover vs trailing average."""
    trailing = _load_trailing_turnover(perf_csv, as_of_date)
    avg = sum(trailing) / len(trailing) if trailing else 0.0

    detail = f"projected={projected_turnover:.1%}, trailing_4w_avg={avg:.1%}"

    if avg > 0 and projected_turnover > fail_mult * avg and projected_turnover > fail_floor:
        return [_check("turnover_sanity", "FAIL", f"Spike: {detail}")]
    if avg > 0 and projected_turnover > warn_mult * avg and projected_turnover > warn_floor:
        return [_check("turnover_sanity", "WARN", f"Elevated: {detail}")]
    if not trailing:
        return [
            _check(
                "turnover_sanity",
                "PASS",
                f"No trailing data; projected={projected_turnover:.1%}",
            )
        ]
    return [_check("turnover_sanity", "PASS", detail)]


# ---------------------------------------------------------------------------
# E) Focus bucket health (soft)
# ---------------------------------------------------------------------------


def _load_sleeve_excess_streak(
    perf_csv: Path,
    as_of_date: str,
    bucket: str = "binary_91_180",
) -> List[float]:
    """Load weekly excess vs XBI for the focus bucket.

    Returns list of excess_pct values (most recent last).
    """
    if not perf_csv.is_file():
        return []

    rows = []
    with open(perf_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("date", "") <= as_of_date:
                try:
                    sleeve_pnl = float(row.get(f"sleeve_{bucket}_pnl", 0))
                    xbi_ret = float(row.get("xbi_return_pct", 0))
                    # excess = sleeve return - xbi return (approximate)
                    rows.append(sleeve_pnl - xbi_ret)
                except (ValueError, TypeError):
                    pass
    return rows


def check_focus_bucket_health(
    positions: List[Dict[str, Any]],
    perf_csv: Path,
    as_of_date: str,
    *,
    min_names: int = DEFAULT_FOCUS_MIN_NAMES,
    warn_streak: int = DEFAULT_FOCUS_WARN_STREAK,
    fail_streak: int = DEFAULT_FOCUS_FAIL_STREAK,
) -> List[Dict[str, Any]]:
    """Check binary_91_180 min names + negative excess streak."""
    results = []
    focus_count = sum(1 for p in positions if p.get("bucket") == "binary_91_180")

    if focus_count < min_names:
        results.append(
            _check(
                "focus_bucket_names",
                "WARN",
                f"binary_91_180 has {focus_count} names (min {min_names})",
            )
        )
    else:
        results.append(
            _check(
                "focus_bucket_names",
                "PASS",
                f"binary_91_180 has {focus_count} names (min {min_names})",
            )
        )

    # Negative excess streak
    excess_vals = _load_sleeve_excess_streak(perf_csv, as_of_date)
    if not excess_vals:
        results.append(
            _check(
                "focus_bucket_streak",
                "PASS",
                "No trailing data for streak check",
            )
        )
        return results

    # Count consecutive negatives from end
    streak = 0
    for v in reversed(excess_vals):
        if v < 0:
            streak += 1
        else:
            break

    if streak >= fail_streak:
        results.append(
            _check(
                "focus_bucket_streak",
                "FAIL",
                f"{streak}-week negative excess streak (fail at {fail_streak})",
            )
        )
    elif streak >= warn_streak:
        results.append(
            _check(
                "focus_bucket_streak",
                "WARN",
                f"{streak}-week negative excess streak (warn at {warn_streak})",
            )
        )
    else:
        results.append(
            _check(
                "focus_bucket_streak",
                "PASS",
                f"Negative excess streak: {streak} weeks",
            )
        )

    return results


# ---------------------------------------------------------------------------
# IC memo (factual one-pager)
# ---------------------------------------------------------------------------


def _load_perf_rows(
    perf_csv: Path,
    as_of_date: str,
    n_weeks: int = 4,
) -> List[Dict[str, Any]]:
    """Load performance rows up to as_of_date."""
    if not perf_csv.is_file():
        return []
    rows = []
    with open(perf_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("date", "") <= as_of_date:
                parsed: Dict[str, Any] = {"date": row["date"]}
                for k in [
                    "total_pnl",
                    "pnl_pct",
                    "xbi_return_pct",
                    "excess_vs_xbi_pct",
                    "turnover",
                ]:
                    try:
                        parsed[k] = float(row.get(k, 0) or 0)
                    except (ValueError, TypeError):
                        parsed[k] = 0.0
                for b in BUCKET_NAMES:
                    key = f"sleeve_{b}_pnl"
                    try:
                        parsed[key] = float(row.get(key, 0) or 0)
                    except (ValueError, TypeError):
                        parsed[key] = 0.0
                rows.append(parsed)
    return rows[-n_weeks:]


def build_ic_memo(
    perf_csv: Path,
    as_of_date: str,
    contributors: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """Build IC memo lines for GO_NOGO.md."""
    lines = ["## IC Memo — Weekly Context", ""]
    rows = _load_perf_rows(perf_csv, as_of_date)

    if not rows:
        lines.append("_No performance data available._")
        lines.append("")
        return lines

    # Latest week
    latest = rows[-1]
    lines.append(f"**Latest period**: {latest['date']}")
    lines.append(f"**P&L**: ${latest['total_pnl']:,.0f} ({latest['pnl_pct']:+.2f}%)")
    xbi = latest.get("xbi_return_pct", 0)
    excess = latest.get("excess_vs_xbi_pct", 0)
    lines.append(f"**XBI**: {xbi:+.2f}% | **Excess**: {excess:+.2f}%")
    lines.append("")

    # Trailing bucket table
    lines.append("### Trailing Bucket P&L")
    lines.append("")
    hdr = "| Date |"
    sep = "|------|"
    for b in BUCKET_NAMES:
        hdr += f" {BUCKET_DISPLAY.get(b, b)} |"
        sep += "----------|"
    hdr += " Total |"
    sep += "-------|"
    lines.append(hdr)
    lines.append(sep)
    for r in rows:
        row_str = f"| {r['date']} |"
        for b in BUCKET_NAMES:
            v = r.get(f"sleeve_{b}_pnl", 0)
            row_str += f" ${v:,.0f} |"
        row_str += f" ${r['total_pnl']:,.0f} |"
        lines.append(row_str)
    lines.append("")

    # Top/bottom contributors (reuse from weekly summary if provided)
    if contributors:
        top5 = contributors[:5]
        bot5 = list(reversed(contributors[-5:])) if len(contributors) > 5 else []
        top_tickers = {c["ticker"] for c in top5}
        bot5 = [c for c in bot5 if c["ticker"] not in top_tickers]

        lines.append("### Top Contributors")
        lines.append("")
        lines.append("| Ticker | Bucket | P&L $ | Return % |")
        lines.append("|--------|--------|-------|----------|")
        for c in top5:
            lines.append(
                f"| {c['ticker']} "
                f"| {BUCKET_DISPLAY.get(c.get('bucket', ''), c.get('bucket', ''))} "
                f"| ${c['pnl']:,.2f} "
                f"| {c['return_pct']:+.2f}% |"
            )
        lines.append("")

        if bot5:
            lines.append("### Bottom Contributors")
            lines.append("")
            lines.append("| Ticker | Bucket | P&L $ | Return % |")
            lines.append("|--------|--------|-------|----------|")
            for c in bot5:
                lines.append(
                    f"| {c['ticker']} "
                    f"| {BUCKET_DISPLAY.get(c.get('bucket', ''), c.get('bucket', ''))} "
                    f"| ${c['pnl']:,.2f} "
                    f"| {c['return_pct']:+.2f}% |"
                )
            lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_go_nogo(
    as_of_date: str,
    *,
    snapshot_root: Path = SNAPSHOTS_ROOT,
    shadow_root: Path = SHADOW_ROOT,
    perf_csv: Optional[Path] = None,
    price_path: Optional[Path] = None,
    confirm: bool = False,
    relaxed: bool = False,
    max_high_gap: int = DEFAULT_MAX_HIGH_GAP_NAMES,
    focus_min_names: int = DEFAULT_FOCUS_MIN_NAMES,
    out_dir: Optional[Path] = None,
    contributors: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run all go/no-go checks.

    Returns dict with verdict, checks, paths.
    """
    snap_dir = snapshot_root / as_of_date
    if perf_csv is None:
        perf_csv = shadow_root / "performance.csv"
    if price_path is None:
        from tools.live_shadow_portfolio import PRICE_HISTORY_PATH

        price_path = PRICE_HISTORY_PATH

    positions_path = shadow_root / "positions" / f"{as_of_date}.json"

    # Load positions
    positions: List[Dict[str, Any]] = []
    if positions_path.is_file():
        with open(positions_path) as f:
            doc = json.load(f)
        positions = doc.get("positions", [])

    # Load prices
    prices = load_price_map(price_path, as_of_date) if price_path else {}

    # Derive traded tickers (all current position tickers as proxy)
    traded_tickers = sorted({p["ticker"] for p in positions})
    buy_tickers = traded_tickers  # conservative: treat all as potential buys

    # Compute projected turnover from positions vs prior
    from tools.live_shadow_portfolio import load_prior_positions

    prior = load_prior_positions(as_of_date, shadow_root / "positions")
    if prior:
        prior_date, prior_positions = prior
        prior_tickers = {p["ticker"] for p in prior_positions}
        current_tickers = {p["ticker"] for p in positions}
        overlap = prior_tickers & current_tickers
        projected_turnover = 1.0 - len(overlap) / len(prior_tickers) if prior_tickers else 0.0
    else:
        projected_turnover = 0.0

    # Run checks
    checks: List[Dict[str, Any]] = []
    checks.extend(check_snapshot_integrity(snap_dir))
    checks.extend(check_price_coverage(traded_tickers, prices, positions, relaxed=relaxed))
    checks.extend(check_gap_risk(positions, buy_tickers, max_high_gap=max_high_gap))
    checks.extend(check_turnover(projected_turnover, perf_csv, as_of_date))
    checks.extend(
        check_focus_bucket_health(
            positions,
            perf_csv,
            as_of_date,
            min_names=focus_min_names,
        )
    )

    # Determine verdict
    has_fail = any(c["status"] == "FAIL" for c in checks)

    if relaxed:
        verdict = "NOGO"
    elif has_fail:
        verdict = "NOGO"
    elif not confirm:
        verdict = "NOGO"
    else:
        verdict = "GO"

    # Reason for NOGO
    nogo_reason = None
    if relaxed:
        nogo_reason = "RELAXED mode — always NOGO"
    elif has_fail:
        fails = [c["check"] for c in checks if c["status"] == "FAIL"]
        nogo_reason = f"Failed checks: {', '.join(fails)}"
    elif not confirm:
        nogo_reason = "Missing --confirm flag (safety latch)"

    # Build IC memo
    memo_lines = build_ic_memo(perf_csv, as_of_date, contributors)

    # Write outputs
    if out_dir is None:
        out_dir = shadow_root / "go_nogo" / as_of_date
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "nogo_reason": nogo_reason,
        "relaxed": relaxed,
        "confirm": confirm,
        "n_checks": len(checks),
        "n_pass": sum(1 for c in checks if c["status"] == "PASS"),
        "n_warn": sum(1 for c in checks if c["status"] == "WARN"),
        "n_fail": sum(1 for c in checks if c["status"] == "FAIL"),
        "checks": checks,
    }

    # Write JSON
    json_path = out_dir / "GO_NOGO.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)

    # Write MD
    md_path = out_dir / "GO_NOGO.md"
    _write_go_nogo_md(result, memo_lines, md_path, relaxed=relaxed)

    result["json_path"] = str(json_path)
    result["md_path"] = str(md_path)
    return result


def _write_go_nogo_md(
    result: Dict[str, Any],
    memo_lines: List[str],
    path: Path,
    *,
    relaxed: bool = False,
) -> None:
    verdict = result["verdict"]
    lines = []

    if relaxed:
        lines.append("# !!!! RELAXED MODE — DO NOT TRADE !!!!")
        lines.append("")

    emoji = "GO" if verdict == "GO" else "NO-GO"
    lines.append(f"# Weekly Go/No-Go: **{emoji}**")
    lines.append("")
    lines.append(f"**Date**: {result['as_of_date']}")
    ts = result.get("generated_at", "")
    lines.append(f"**Generated**: {ts}")
    if result.get("nogo_reason"):
        lines.append(f"**Reason**: {result['nogo_reason']}")
    lines.append("")

    # Check summary
    lines.append("## Checks")
    lines.append("")
    lines.append("| Check | Status | Hard | Detail |")
    lines.append("|-------|--------|------|--------|")
    for c in result["checks"]:
        hard_str = "Y" if c.get("hard") else ""
        lines.append(f"| {c['check']} | {c['status']} | {hard_str} | {c['detail']} |")
    lines.append("")

    lines.append(f"**Summary**: {result['n_pass']} PASS, " f"{result['n_warn']} WARN, {result['n_fail']} FAIL")
    lines.append("")

    # IC memo
    lines.extend(memo_lines)

    with open(path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly Go/No-Go gate for trading")
    parser.add_argument("--as-of-date", type=str, help="Date (YYYY-MM-DD), default latest")
    parser.add_argument("--snapshot-root", type=str)
    parser.add_argument("--shadow-root", type=str)
    parser.add_argument("--perf-csv", type=str)
    parser.add_argument("--price-history", type=str)
    parser.add_argument("--out-dir", type=str)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to emit GO verdict",
    )
    parser.add_argument(
        "--relaxed",
        action="store_true",
        help="Always NOGO with scarlet banner",
    )
    parser.add_argument("--max-high-gap", type=int, default=DEFAULT_MAX_HIGH_GAP_NAMES)
    parser.add_argument("--focus-min-names", type=int, default=DEFAULT_FOCUS_MIN_NAMES)
    args = parser.parse_args()

    # Resolve as-of-date
    if args.as_of_date:
        as_of_date = args.as_of_date
    else:
        snap_root = Path(args.snapshot_root) if args.snapshot_root else SNAPSHOTS_ROOT
        candidates = sorted(
            (d.name for d in snap_root.iterdir() if d.is_dir() and len(d.name) == 10),
        )
        if not candidates:
            print("ERROR: No snapshots found", file=sys.stderr)
            sys.exit(1)
        as_of_date = candidates[-1]

    result = run_go_nogo(
        as_of_date,
        snapshot_root=Path(args.snapshot_root) if args.snapshot_root else SNAPSHOTS_ROOT,
        shadow_root=Path(args.shadow_root) if args.shadow_root else SHADOW_ROOT,
        perf_csv=Path(args.perf_csv) if args.perf_csv else None,
        price_path=Path(args.price_history) if args.price_history else None,
        confirm=args.confirm,
        relaxed=args.relaxed,
        max_high_gap=args.max_high_gap,
        focus_min_names=args.focus_min_names,
        out_dir=Path(args.out_dir) if args.out_dir else None,
    )

    verdict = result["verdict"]
    print(f"Verdict: {verdict}")
    print(f"Checks: {result['n_pass']} PASS, " f"{result['n_warn']} WARN, {result['n_fail']} FAIL")
    if result.get("nogo_reason"):
        print(f"Reason: {result['nogo_reason']}")
    print(f"Report: {result.get('md_path', '')}")

    sys.exit(0 if verdict == "GO" else 1)


if __name__ == "__main__":
    main()
