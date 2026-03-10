#!/usr/bin/env python3
"""Pre-Trade Check — sanity gate before executing weekly trades.

FAILs (blocks trades) if:
  1. Snapshot missing provenance fields (ruleset_id, as_of_date)
  2. Bucket totals deviate from policy by > deviation_max_pct
  3. Too many missing prices in held/top-K
  4. Gap-risk HIGH positions exceed cap after execution
  5. Weekly turnover exceeds max_turnover_pct

Outputs:
    artifacts/live_shadow/pre_trade/YYYY-MM-DD.json
    artifacts/live_shadow/pre_trade/YYYY-MM-DD.md

Usage:
    python3 tools/pre_trade_check.py --as-of-date 2026-03-08
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_trade_deltas import POSITIONS_DIR, find_prior_positions, load_positions_json
from tools.live_shadow_portfolio import BUCKET_DISPLAY, BUCKET_NAMES, SHADOW_ROOT, load_metadata, load_policy

PRE_TRADE_ROOT = SHADOW_ROOT / "pre_trade"
SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "snapshots"
MANIFEST_PATH = PROJECT_ROOT / "production_data" / "decision_rulesets" / "manifest.json"

SCHEMA_VERSION = "pre_trade_check.v1"


def _in_pytest() -> bool:
    """True when running inside a pytest session."""
    return "PYTEST_CURRENT_TEST" in os.environ


def _assert_not_production_default(name: str, value: Path, production_default: Path) -> None:
    """Raise AssertionError if a test is using a production default path.

    Only active when PYTEST_CURRENT_TEST is set; no-op in production.
    """
    if _in_pytest() and value == production_default:
        raise AssertionError(f"Tests must pass `{name}` explicitly — got production default {production_default}")


@dataclass
class CheckResult:
    name: str
    status: str  # PASS, WARN, FAIL
    detail: str
    value: Any = None
    threshold: Any = None


@dataclass
class PreTradeResult:
    schema: str = SCHEMA_VERSION
    as_of_date: str = ""
    overall: str = "PASS"  # PASS, WARN, FAIL
    checks: List[Dict[str, Any]] = field(default_factory=list)
    can_trade: bool = True


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_provenance(
    snap_dir: Path,
) -> CheckResult:
    """FAIL if snapshot missing ruleset_id or as_of_date in metadata."""
    metadata = load_metadata(snap_dir)
    if not metadata:
        return CheckResult("provenance", "FAIL", f"metadata.json not found in {snap_dir}")

    missing = []
    if not metadata.get("ruleset_id"):
        missing.append("ruleset_id")
    if not metadata.get("as_of_date"):
        missing.append("as_of_date")

    if missing:
        return CheckResult("provenance", "FAIL", f"Missing provenance: {', '.join(missing)}")
    return CheckResult(
        "provenance",
        "PASS",
        f"ruleset={metadata['ruleset_id'][:8]}, date={metadata['as_of_date']}",
    )


def _get_manifest_active_id(manifest_path: Path = MANIFEST_PATH) -> Optional[str]:
    """Read the manifest and return the active ruleset ID, or None."""
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in data.get("rulesets", []):
            if entry.get("status") == "active":
                return entry["id"]
    except Exception:
        pass
    return None


def check_ruleset_active(
    snap_dir: Path,
    *,
    relaxed: bool = False,
    manifest_path: Path = MANIFEST_PATH,
) -> CheckResult:
    """FAIL if snapshot ruleset_id does not match manifest active ID.

    When relaxed=True, downgrades mismatch to WARN instead of FAIL.
    """
    _assert_not_production_default("manifest_path", manifest_path, MANIFEST_PATH)
    metadata = load_metadata(snap_dir)
    if not metadata:
        return CheckResult("ruleset_active", "FAIL", f"metadata.json not found in {snap_dir}")

    snap_ruleset_id = metadata.get("ruleset_id", "")
    if not snap_ruleset_id:
        return CheckResult("ruleset_active", "FAIL", "Snapshot has no ruleset_id in metadata")

    active_id = _get_manifest_active_id(manifest_path)
    if not active_id:
        return CheckResult(
            "ruleset_active",
            "WARN",
            "Cannot determine active ruleset from manifest — skipping check",
        )

    if snap_ruleset_id[:8] == active_id[:8]:
        return CheckResult(
            "ruleset_active",
            "PASS",
            f"Snapshot ruleset {snap_ruleset_id[:8]} matches active manifest ID",
        )

    # Mismatch
    status = "WARN" if relaxed else "FAIL"
    detail = f"Snapshot ruleset {snap_ruleset_id[:8]} != active {active_id}. " f"Snapshot path: {snap_dir}"
    if relaxed:
        detail = f"[RELAXED] {detail}"
    return CheckResult("ruleset_active", status, detail)


def check_bucket_deviation(
    positions: List[Dict[str, Any]],
    policy: Dict[str, Any],
    max_deviation_pct: float = 3.0,
) -> CheckResult:
    """FAIL if any bucket's actual allocation deviates from policy by > max_deviation_pct."""
    account_usd = policy.get("account_usd", 500_000)
    bucket_targets = policy.get("bucket_targets", {})

    worst_bucket = ""
    worst_dev = 0.0
    details = []

    for b in BUCKET_NAMES:
        target_pct = bucket_targets.get(b, 0.25) * 100
        actual_usd = sum(p["target_dollars"] for p in positions if p.get("bucket") == b)
        actual_pct = (actual_usd / account_usd * 100) if account_usd > 0 else 0
        dev = abs(actual_pct - target_pct)
        details.append(f"{BUCKET_DISPLAY.get(b, b)}: {actual_pct:.1f}% vs {target_pct:.0f}% (Δ{dev:.1f}pp)")
        if dev > worst_dev:
            worst_dev = dev
            worst_bucket = b

    if worst_dev > max_deviation_pct:
        return CheckResult(
            "bucket_deviation",
            "FAIL",
            f"{BUCKET_DISPLAY.get(worst_bucket, worst_bucket)} deviates {worst_dev:.1f}pp > {max_deviation_pct}pp. "
            + "; ".join(details),
            value=round(worst_dev, 2),
            threshold=max_deviation_pct,
        )
    return CheckResult(
        "bucket_deviation",
        "PASS",
        f"All within {max_deviation_pct}pp. " + "; ".join(details),
        value=round(worst_dev, 2),
        threshold=max_deviation_pct,
    )


def check_missing_prices(
    positions: List[Dict[str, Any]],
    max_missing: int = 2,
) -> CheckResult:
    """FAIL if too many held positions have missing price coverage."""
    missing = [p["ticker"] for p in positions if p.get("price_coverage") == "MISSING"]
    if len(missing) > max_missing:
        return CheckResult(
            "missing_prices",
            "FAIL",
            f"{len(missing)} missing prices > {max_missing}: {', '.join(missing[:10])}",
            value=len(missing),
            threshold=max_missing,
        )
    if missing:
        return CheckResult(
            "missing_prices",
            "WARN",
            f"{len(missing)} missing price(s): {', '.join(missing)}",
            value=len(missing),
            threshold=max_missing,
        )
    return CheckResult("missing_prices", "PASS", "All positions have price coverage")


def check_gap_risk_concentration(
    positions: List[Dict[str, Any]],
    policy: Dict[str, Any],
    max_gap_high_pct: float = 10.0,
) -> CheckResult:
    """FAIL if gap-risk HIGH positions exceed max % of account after execution."""
    account_usd = policy.get("account_usd", 500_000)
    gap_high = [p for p in positions if p.get("gap_risk") == "HIGH"]
    gap_usd = sum(p["target_dollars"] for p in gap_high)
    gap_pct = (gap_usd / account_usd * 100) if account_usd > 0 else 0

    if gap_pct > max_gap_high_pct:
        tickers = ", ".join(p["ticker"] for p in gap_high[:10])
        return CheckResult(
            "gap_risk_concentration",
            "FAIL",
            f"Gap-risk HIGH = {gap_pct:.1f}% > {max_gap_high_pct}% "
            f"(${gap_usd:,.0f}, {len(gap_high)} names: {tickers})",
            value=round(gap_pct, 2),
            threshold=max_gap_high_pct,
        )
    return CheckResult(
        "gap_risk_concentration",
        "PASS",
        f"Gap-risk HIGH = {gap_pct:.1f}% (${gap_usd:,.0f}, {len(gap_high)} names)",
        value=round(gap_pct, 2),
        threshold=max_gap_high_pct,
    )


def check_turnover(
    current_positions: List[Dict[str, Any]],
    prior_positions: List[Dict[str, Any]],
    max_turnover_pct: float = 40.0,
) -> CheckResult:
    """FAIL if name-level turnover exceeds weekly threshold."""
    if not prior_positions:
        return CheckResult("turnover", "PASS", "First snapshot — no turnover to check")

    prior_tickers = {p["ticker"] for p in prior_positions}
    current_tickers = {p["ticker"] for p in current_positions}
    overlap = prior_tickers & current_tickers
    turnover_pct = (1.0 - len(overlap) / len(prior_tickers)) * 100 if prior_tickers else 0

    if turnover_pct > max_turnover_pct:
        dropped = sorted(prior_tickers - current_tickers)[:10]
        return CheckResult(
            "turnover",
            "FAIL",
            f"Turnover {turnover_pct:.0f}% > {max_turnover_pct}% "
            f"({len(prior_tickers - current_tickers)} dropped: {', '.join(dropped)})",
            value=round(turnover_pct, 1),
            threshold=max_turnover_pct,
        )
    return CheckResult(
        "turnover",
        "PASS",
        f"Turnover {turnover_pct:.0f}% (overlap {len(overlap)}/{len(prior_tickers)})",
        value=round(turnover_pct, 1),
        threshold=max_turnover_pct,
    )


# ---------------------------------------------------------------------------
# Alpha health gate
# ---------------------------------------------------------------------------


def check_alpha_health(
    perf_rows: List[Dict[str, str]],
    policy: Dict[str, Any],
) -> CheckResult:
    """WARN (NO_ADD_RISK) if trailing hedged excess is negative at both
    portfolio and binary_91_180 level.

    Returns PASS (ADD_OK) on cold start, insufficient history, or when
    at least one of the two metrics is non-negative.
    """
    ah = policy.get("alpha_health", {})
    if not ah.get("enabled", True):
        return CheckResult("alpha_health", "PASS", "alpha_health disabled in policy")

    lookback = ah.get("lookback_weeks", 4)
    min_weeks = ah.get("min_weeks", 3)
    portfolio_thresh = ah.get("no_add_if_portfolio_hedged_excess_lt", 0.0)
    b91_thresh = ah.get("no_add_if_b91_hedged_excess_lt", 0.0)

    if len(perf_rows) < min_weeks:
        return CheckResult(
            "alpha_health",
            "PASS",
            f"insufficient history (cold start): {len(perf_rows)} weeks < min_weeks={min_weeks}",
            value={"weeks_available": len(perf_rows), "decision": "ADD_OK"},
        )

    tail = perf_rows[-lookback:]
    weeks_used = len(tail)

    # Portfolio hedged excess (sum over trailing window)
    portfolio_excess = _sum_column(tail, "excess_vs_xbi_pct")

    # Per-bucket hedged excess (sum of $ P&L as proxy)
    bucket_excess = {}
    for b in ["binary_0_30", "binary_31_90", "binary_91_180", "less_binary"]:
        bucket_excess[b] = _sum_column(tail, f"sleeve_{b}_pnl")

    b91_excess = bucket_excess.get("binary_91_180", 0.0)

    # Gate logic: NO_ADD_RISK if BOTH portfolio AND b91 are below threshold
    no_add = portfolio_excess < portfolio_thresh and b91_excess < b91_thresh
    decision = "NO_ADD_RISK" if no_add else "ADD_OK"

    detail_parts = [
        f"portfolio_hedged_excess_4w={portfolio_excess:+.4f}%",
        f"b91_hedged_excess_4w=${b91_excess:+,.2f}",
        f"weeks={weeks_used}",
        f"decision={decision}",
    ]
    detail = "; ".join(detail_parts)

    value = {
        "portfolio_hedged_excess_4w": round(portfolio_excess, 4),
        "bucket_hedged_excess_4w": {b: round(v, 2) for b, v in bucket_excess.items()},
        "weeks_used": weeks_used,
        "decision": decision,
    }

    status = "WARN" if no_add else "PASS"
    return CheckResult("alpha_health", status, detail, value=value)


def _sum_column(rows: List[Dict[str, str]], col: str) -> float:
    """Sum a numeric column from perf rows, skipping blanks/NaN."""
    total = 0.0
    for r in rows:
        v = r.get(col, "")
        if not v or str(v).strip().lower() in ("nan", "none", ""):
            continue
        try:
            total += float(v)
        except (ValueError, TypeError):
            continue
    return total


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_pre_trade_check(
    as_of_date: str,
    *,
    positions_dir: Path = POSITIONS_DIR,
    policy_path: Optional[Path] = None,
    snap_dir: Optional[Path] = None,
    deviation_max_pct: float = 3.0,
    max_missing_prices: int = 2,
    max_gap_high_pct: float = 10.0,
    max_turnover_pct: float = 40.0,
    relaxed: bool = False,
    manifest_path: Path = MANIFEST_PATH,
    perf_csv: Optional[Path] = None,
) -> PreTradeResult:
    """Run all pre-trade checks. Returns PreTradeResult."""
    _assert_not_production_default("positions_dir", positions_dir, POSITIONS_DIR)
    _assert_not_production_default("manifest_path", manifest_path, MANIFEST_PATH)
    result = PreTradeResult(as_of_date=as_of_date)

    current_path = positions_dir / f"{as_of_date}.json"
    if not current_path.is_file():
        result.overall = "FAIL"
        result.can_trade = False
        result.checks.append({"name": "positions", "status": "FAIL", "detail": f"No positions for {as_of_date}"})
        return result

    _, current_positions = load_positions_json(current_path)
    policy = load_policy(policy_path)

    # Prior positions for turnover check
    prior_path = find_prior_positions(as_of_date, positions_dir)
    prior_positions = load_positions_json(prior_path)[1] if prior_path else []

    # Snapshot dir for provenance
    if snap_dir is None:
        if _in_pytest():
            raise AssertionError(
                "Tests must pass `snap_dir` explicitly — would fall through to " f"production default {SNAPSHOTS_ROOT}"
            )
        snap_dir = SNAPSHOTS_ROOT / as_of_date

    # Alpha health gate (uses performance.csv)
    alpha_health_check = None
    if policy.get("alpha_health", {}).get("enabled", True):
        try:
            from tools.build_trade_plan import load_performance_rows

            _perf_csv = perf_csv if perf_csv is not None else SHADOW_ROOT / "performance.csv"
            perf_rows = load_performance_rows(_perf_csv)
            alpha_health_check = check_alpha_health(perf_rows, policy)
        except Exception:
            alpha_health_check = None

    checks = [
        check_provenance(snap_dir),
        check_ruleset_active(snap_dir, relaxed=relaxed, manifest_path=manifest_path),
        check_bucket_deviation(current_positions, policy, deviation_max_pct),
        check_missing_prices(current_positions, max_missing_prices),
        check_gap_risk_concentration(current_positions, policy, max_gap_high_pct),
        check_turnover(current_positions, prior_positions, max_turnover_pct),
    ]
    if alpha_health_check is not None:
        checks.append(alpha_health_check)

    has_fail = False
    has_warn = False
    for c in checks:
        result.checks.append(
            {
                "name": c.name,
                "status": c.status,
                "detail": c.detail,
                "value": c.value,
                "threshold": c.threshold,
            }
        )
        if c.status == "FAIL":
            has_fail = True
        elif c.status == "WARN":
            has_warn = True

    if has_fail:
        result.overall = "FAIL"
        result.can_trade = False
    elif has_warn:
        result.overall = "WARN"
        result.can_trade = True
    else:
        result.overall = "PASS"
        result.can_trade = True

    return result


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_pre_trade_json(result: PreTradeResult, out_path: Path) -> Path:
    """Write pre_trade check result as JSON."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": result.schema,
        "as_of_date": result.as_of_date,
        "overall": result.overall,
        "can_trade": result.can_trade,
        "checks": result.checks,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return out_path


def write_pre_trade_md(result: PreTradeResult, out_path: Path) -> Path:
    """Write pre-trade checklist markdown."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    status_icon = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
    lines = []
    lines.append("# Pre-Trade Checklist")
    lines.append("")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"**Date**: {result.as_of_date}")
    lines.append(f"**Generated**: {ts}")

    if result.overall == "FAIL":
        lines.append("")
        lines.append("**BLOCKED — DO NOT TRADE**")
    elif result.overall == "WARN":
        lines.append("")
        lines.append("**CAUTION — review warnings before trading**")
    else:
        lines.append("")
        lines.append("**CLEAR TO TRADE**")
    lines.append("")

    lines.append("## Checks")
    lines.append("")
    for c in result.checks:
        icon = status_icon.get(c["status"], "[???]")
        lines.append(f"- {icon} **{c['name']}**: {c['detail']}")
    lines.append("")

    # Alpha Health detail section (if present)
    ah_check = next((c for c in result.checks if c["name"] == "alpha_health"), None)
    if ah_check and isinstance(ah_check.get("value"), dict):
        v = ah_check["value"]
        lines.append("## Alpha Health (Trailing 4w)")
        lines.append("")
        lines.append(f"**Decision**: {v.get('decision', '?')}")
        lines.append(f"**Weeks used**: {v.get('weeks_used', '?')}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        phe = v.get("portfolio_hedged_excess_4w")
        if phe is not None:
            lines.append(f"| Portfolio hedged excess | {phe:+.4f}% |")
        bucket_exc = v.get("bucket_hedged_excess_4w", {})
        for b in ["binary_91_180", "binary_31_90", "binary_0_30", "less_binary"]:
            bv = bucket_exc.get(b)
            if bv is not None:
                lines.append(f"| {b} hedged excess | ${bv:+,.2f} |")
        lines.append("")

    text = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-trade sanity check")
    parser.add_argument("--as-of-date", type=str, required=True)
    parser.add_argument("--policy", type=str, help="Portfolio policy JSON path")
    parser.add_argument("--deviation-max-pct", type=float, default=3.0)
    parser.add_argument("--max-missing-prices", type=int, default=2)
    parser.add_argument("--max-gap-high-pct", type=float, default=10.0)
    parser.add_argument("--max-turnover-pct", type=float, default=40.0)
    parser.add_argument("--relaxed", action="store_true", help="Downgrade ruleset mismatch from FAIL to WARN")
    args = parser.parse_args()

    policy_path = Path(args.policy) if args.policy else None
    result = run_pre_trade_check(
        args.as_of_date,
        policy_path=policy_path,
        deviation_max_pct=args.deviation_max_pct,
        max_missing_prices=args.max_missing_prices,
        max_gap_high_pct=args.max_gap_high_pct,
        max_turnover_pct=args.max_turnover_pct,
        relaxed=args.relaxed,
    )

    out_dir = PRE_TRADE_ROOT / args.as_of_date
    write_pre_trade_json(result, out_dir / "pre_trade.json")
    md_path = write_pre_trade_md(result, out_dir / "pre_trade.md")

    print(f"Pre-trade check: {result.overall}")
    for c in result.checks:
        print(f"  [{c['status']}] {c['name']}: {c['detail']}")
    print(f"\nCan trade: {result.can_trade}")
    print(f"Report: {md_path}")

    sys.exit(0 if result.can_trade else 1)


if __name__ == "__main__":
    main()
