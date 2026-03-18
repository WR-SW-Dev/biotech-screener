#!/usr/bin/env python3
"""Weekly readiness scorecard — HOLD / REVIEW / READY verdict.

Consumes existing pipeline artifacts (performance.csv, pre_trade.json,
phase2_health.json, ruleset_health.json, portfolio_alerts.json, positions)
and produces a single go/no-go verdict with explicit thresholds.

The scorecard tracks six dimensions:
    1. Shadow excess vs XBI  (trailing performance)
    2. Turnover stability    (not churning)
    3. Bucket drift vs policy (allocation discipline)
    4. Repeated WARNs         (health gate stability)
    5. Gap-risk concentration (no blow-up exposure)
    6. Trade packet reasonableness (pre-trade gate clean)

Verdicts:
    READY  — all checks PASS; model behaves calmly
    REVIEW — one or more WARN checks; needs operator attention
    HOLD   — any FAIL check; do not trade until resolved

Exit codes:
    0 = READY   (safe to proceed)
    1 = HOLD    (expected during cold-start — not a crash)
    2 = REVIEW  (operator attention needed)

Usage:
    python tools/weekly_readiness_scorecard.py \\
        --as-of-date 2026-03-10 \\
        [--snapshots-dir data/snapshots] \\
        [--artifacts-dir artifacts/live_shadow] \\
        [--output-dir artifacts/readiness] \\
        [--history-file artifacts/readiness/history.jsonl]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema & thresholds
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "weekly_readiness_scorecard.v1"

DEFAULT_READINESS_POLICY = Path(__file__).resolve().parent.parent / "production_data" / "readiness_policy.json"

# Minimum weeks of performance data to evaluate (cold-start → HOLD)
MIN_PERF_WEEKS = 2

# Check thresholds
THRESHOLDS = {
    # 1. Shadow excess vs XBI (trailing N-week average)
    "excess_lookback_weeks": 4,
    "excess_fail_pct": -2.0,  # avg weekly excess < -2pp → FAIL
    "excess_warn_pct": -0.5,  # avg weekly excess < -0.5pp → WARN
    # 2. Turnover (trailing average)
    "turnover_fail_pct": 35.0,  # avg turnover > 35% → FAIL
    "turnover_warn_pct": 25.0,  # avg turnover > 25% → WARN
    # 3. Bucket drift (max deviation from policy target)
    "bucket_drift_fail_pp": 25.0,  # any bucket > 25pp off target → FAIL
    "bucket_drift_warn_pp": 15.0,  # any bucket > 15pp off target → WARN
    # 4. Repeated WARNs (consecutive health gate WARNs)
    "warn_streak_fail": 3,  # ≥3 consecutive WARN snapshots → FAIL
    "warn_streak_warn": 2,  # ≥2 consecutive WARN snapshots → WARN
    # 5. Gap-risk concentration
    "gap_risk_fail_pct": 10.0,  # gap-risk HIGH weight > 10% → FAIL
    "gap_risk_warn_pct": 5.0,  # gap-risk HIGH weight > 5% → WARN
    # 6. Pre-trade gate
    # Any FAIL check in pre_trade.json → scorecard FAIL
    # Any WARN check (excluding missing_prices ≤ 2) → scorecard WARN
}

# Bucket allocation targets from portfolio_policy.json (defaults if file missing)
DEFAULT_BUCKET_TARGETS = {
    "binary_0_30": 10.0,
    "binary_31_90": 25.0,
    "binary_91_180": 55.0,
    "less_binary": 10.0,
}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_performance_rows(
    perf_csv: Path,
    ruleset_id: str = "",
) -> List[Dict[str, Any]]:
    """Load performance.csv, optionally filtered to a specific ruleset."""
    rows: List[Dict[str, Any]] = []
    if not perf_csv.exists():
        return rows
    with open(perf_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if ruleset_id and row.get("ruleset_id", "") != ruleset_id:
                continue
            rows.append(row)
    return rows


def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON file, return None on any error."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_bucket_targets(policy_path: Path) -> Dict[str, float]:
    """Load bucket targets from portfolio_policy.json."""
    data = load_json_safe(policy_path)
    if not data:
        return dict(DEFAULT_BUCKET_TARGETS)
    raw = data.get("bucket_targets", {})
    return {k: float(v) * 100 for k, v in raw.items()} if raw else dict(DEFAULT_BUCKET_TARGETS)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_shadow_excess(
    perf_rows: List[Dict[str, Any]],
    lookback: int,
) -> Dict[str, Any]:
    """Check 1: trailing average weekly excess vs XBI."""
    check = {
        "name": "shadow_excess_vs_xbi",
        "status": "PASS",
        "detail": "",
        "value": None,
        "threshold_warn": THRESHOLDS["excess_warn_pct"],
        "threshold_fail": THRESHOLDS["excess_fail_pct"],
    }

    # Filter to rows with real excess data (not blank)
    valid = [r for r in perf_rows if r.get("excess_vs_xbi_pct", "") not in ("", None)]

    if len(valid) < MIN_PERF_WEEKS:
        check["status"] = "HOLD"
        check["detail"] = f"Insufficient data: {len(valid)} periods (need {MIN_PERF_WEEKS})"
        return check

    # Take last N rows
    recent = valid[-lookback:]
    excess_vals = []
    for r in recent:
        try:
            excess_vals.append(float(r["excess_vs_xbi_pct"]))
        except (ValueError, TypeError):
            continue

    if not excess_vals:
        check["status"] = "HOLD"
        check["detail"] = "No valid excess values"
        return check

    avg_excess = sum(excess_vals) / len(excess_vals)
    check["value"] = round(avg_excess, 4)
    check["detail"] = f"Trailing {len(excess_vals)}-period avg excess: {avg_excess:+.4f}pp"

    if avg_excess < THRESHOLDS["excess_fail_pct"]:
        check["status"] = "FAIL"
    elif avg_excess < THRESHOLDS["excess_warn_pct"]:
        check["status"] = "WARN"
    return check


def check_turnover(perf_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Check 2: trailing average turnover."""
    check = {
        "name": "turnover_stability",
        "status": "PASS",
        "detail": "",
        "value": None,
        "threshold_warn": THRESHOLDS["turnover_warn_pct"],
        "threshold_fail": THRESHOLDS["turnover_fail_pct"],
    }

    valid = [r for r in perf_rows if r.get("turnover", "") not in ("", None)]
    if len(valid) < MIN_PERF_WEEKS:
        check["status"] = "HOLD"
        check["detail"] = f"Insufficient data: {len(valid)} periods"
        return check

    recent = valid[-4:]
    turnover_vals = []
    for r in recent:
        try:
            turnover_vals.append(float(r["turnover"]) * 100)  # fraction → pct
        except (ValueError, TypeError):
            continue

    if not turnover_vals:
        check["status"] = "HOLD"
        check["detail"] = "No valid turnover values"
        return check

    avg = sum(turnover_vals) / len(turnover_vals)
    check["value"] = round(avg, 2)
    check["detail"] = f"Trailing {len(turnover_vals)}-period avg turnover: {avg:.1f}%"

    if avg > THRESHOLDS["turnover_fail_pct"]:
        check["status"] = "FAIL"
    elif avg > THRESHOLDS["turnover_warn_pct"]:
        check["status"] = "WARN"
    return check


def check_bucket_drift(
    pre_trade: Optional[Dict[str, Any]],
    policy_targets: Dict[str, float],
) -> Dict[str, Any]:
    """Check 3: max bucket deviation from policy."""
    check = {
        "name": "bucket_drift_vs_policy",
        "status": "PASS",
        "detail": "",
        "value": None,
        "threshold_warn": THRESHOLDS["bucket_drift_warn_pp"],
        "threshold_fail": THRESHOLDS["bucket_drift_fail_pp"],
    }

    if not pre_trade:
        check["status"] = "PASS"
        check["detail"] = "No pre_trade.json (snapshot-only run; skipped)"
        return check

    # Extract bucket deviation from pre_trade checks
    for c in pre_trade.get("checks", []):
        if c.get("name") == "bucket_deviation":
            max_dev = c.get("value")
            if max_dev is not None:
                check["value"] = float(max_dev)
                check["detail"] = c.get("detail", f"Max deviation: {max_dev}pp")
                if float(max_dev) > THRESHOLDS["bucket_drift_fail_pp"]:
                    check["status"] = "FAIL"
                elif float(max_dev) > THRESHOLDS["bucket_drift_warn_pp"]:
                    check["status"] = "WARN"
                return check

    check["detail"] = "bucket_deviation check not found in pre_trade.json"
    return check


def check_warn_streak(
    phase2_health: Optional[Dict[str, Any]],
    ruleset_health: Optional[Dict[str, Any]],
    alerts: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check 4: repeated WARNs across health gates."""
    check = {
        "name": "health_gate_stability",
        "status": "PASS",
        "detail": "",
        "value": 0,
        "threshold_warn": THRESHOLDS["warn_streak_warn"],
        "threshold_fail": THRESHOLDS["warn_streak_fail"],
    }

    warn_reasons: List[str] = []

    # Phase2 health status
    p2_status = (phase2_health or {}).get("status", "")
    if p2_status == "WARN":
        p2_reasons = (phase2_health or {}).get("reasons", [])
        warn_reasons.append(f"phase2_health=WARN ({', '.join(p2_reasons)})")
    elif p2_status == "FAIL":
        check["status"] = "FAIL"
        check["detail"] = "phase2_health=FAIL"
        check["value"] = 99
        return check

    # Ruleset health
    rs_status = (ruleset_health or {}).get("status", "")
    consec = (ruleset_health or {}).get("consecutive_warn_days", 0)
    if (ruleset_health or {}).get("recommend_rollback"):
        check["status"] = "FAIL"
        check["detail"] = "ruleset_health recommends rollback"
        check["value"] = consec
        return check
    if rs_status == "WARN":
        warn_reasons.append(f"ruleset_health=WARN (consec={consec})")

    # Portfolio alerts
    alert_count = (alerts or {}).get("alert_count", 0)
    if alert_count > 0:
        alert_types = [a.get("type", "") for a in (alerts or {}).get("alerts", [])]
        fail_alerts = [a for a in (alerts or {}).get("alerts", []) if a.get("severity") == "FAIL"]
        if fail_alerts:
            check["status"] = "FAIL"
            check["detail"] = f"{len(fail_alerts)} FAIL alert(s): {', '.join(a.get('type', '') for a in fail_alerts)}"
            check["value"] = len(fail_alerts)
            return check
        warn_reasons.append(f"portfolio_alerts={alert_count} ({', '.join(alert_types)})")

    n_warns = len(warn_reasons)
    check["value"] = n_warns

    if n_warns >= THRESHOLDS["warn_streak_fail"]:
        check["status"] = "FAIL"
    elif n_warns >= THRESHOLDS["warn_streak_warn"]:
        check["status"] = "WARN"

    check["detail"] = "; ".join(warn_reasons) if warn_reasons else "All health gates clean"
    return check


def check_gap_risk(
    phase2_health: Optional[Dict[str, Any]],
    pre_trade: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check 5: gap-risk HIGH concentration."""
    check = {
        "name": "gap_risk_concentration",
        "status": "PASS",
        "detail": "",
        "value": None,
        "threshold_warn": THRESHOLDS["gap_risk_warn_pct"],
        "threshold_fail": THRESHOLDS["gap_risk_fail_pct"],
    }

    # Try pre_trade first (has gap_risk_concentration check)
    if pre_trade:
        for c in pre_trade.get("checks", []):
            if c.get("name") == "gap_risk_concentration":
                val = c.get("value")
                if val is not None:
                    check["value"] = float(val)
                    check["detail"] = c.get("detail", f"Gap-risk HIGH weight: {val}%")
                    if float(val) > THRESHOLDS["gap_risk_fail_pct"]:
                        check["status"] = "FAIL"
                    elif float(val) > THRESHOLDS["gap_risk_warn_pct"]:
                        check["status"] = "WARN"
                    return check

    # Fallback to phase2_health exposure
    exposure = (phase2_health or {}).get("metrics", {}).get("exposure", {})
    cat_7d_wt = exposure.get("catalyst_le_7d_weight_pct")
    if cat_7d_wt is not None:
        check["value"] = float(cat_7d_wt)
        check["detail"] = f"catalyst_le_7d_weight_pct: {cat_7d_wt}%"
        if float(cat_7d_wt) > THRESHOLDS["gap_risk_fail_pct"]:
            check["status"] = "FAIL"
        elif float(cat_7d_wt) > THRESHOLDS["gap_risk_warn_pct"]:
            check["status"] = "WARN"
        return check

    check["detail"] = "No gap-risk data available"
    return check


def check_pre_trade_gate(
    pre_trade: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check 6: pre-trade gate cleanliness."""
    check = {
        "name": "pre_trade_gate",
        "status": "PASS",
        "detail": "",
        "value": None,
        "threshold_warn": "any WARN",
        "threshold_fail": "any FAIL or can_trade=false",
    }

    if not pre_trade:
        check["status"] = "PASS"
        check["detail"] = "No pre_trade.json (snapshot-only run; skipped)"
        return check

    overall = pre_trade.get("overall", "")
    can_trade = pre_trade.get("can_trade", True)

    if not can_trade or overall == "FAIL":
        check["status"] = "FAIL"
        fails = [c for c in pre_trade.get("checks", []) if c.get("status") == "FAIL"]
        check["detail"] = f"Pre-trade FAIL: {', '.join(c.get('name', '') for c in fails)}"
        check["value"] = len(fails)
        return check

    if overall == "WARN":
        warns = [c for c in pre_trade.get("checks", []) if c.get("status") == "WARN"]
        check["status"] = "WARN"
        check["detail"] = f"Pre-trade WARN: {', '.join(c.get('name', '') for c in warns)}"
        check["value"] = len(warns)
        return check

    check["detail"] = f"Pre-trade {overall}"
    check["value"] = 0
    return check


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------


def compute_verdict(checks: List[Dict[str, Any]]) -> str:
    """Derive overall READY / REVIEW / HOLD from individual checks."""
    statuses = [c["status"] for c in checks]
    if "FAIL" in statuses or "HOLD" in statuses:
        return "HOLD"
    if "WARN" in statuses:
        return "REVIEW"
    return "READY"


# ---------------------------------------------------------------------------
# Main scorecard builder
# ---------------------------------------------------------------------------


def build_scorecard(
    as_of_date: str,
    snapshots_dir: Path,
    artifacts_dir: Path,
    policy_path: Path,
    ruleset_id: str = "",
) -> Dict[str, Any]:
    """Build the weekly readiness scorecard.

    Parameters
    ----------
    as_of_date : screen date (YYYY-MM-DD)
    snapshots_dir : base snapshot directory (data/snapshots)
    artifacts_dir : live shadow artifacts (artifacts/live_shadow)
    policy_path : portfolio policy JSON
    ruleset_id : active ruleset ID (filters performance rows)
    """
    # Load artifacts
    perf_csv = artifacts_dir / "performance.csv"
    perf_rows = load_performance_rows(perf_csv, ruleset_id)

    snap_path = snapshots_dir / as_of_date

    # Find latest trade plan directory
    trade_plan_dir = artifacts_dir / "trade_plan" / as_of_date
    pre_trade = load_json_safe(trade_plan_dir / "pre_trade.json")

    phase2_health = load_json_safe(snap_path / "phase2_health.json")
    ruleset_health = load_json_safe(snap_path / "ruleset_health.json")
    alerts = load_json_safe(artifacts_dir / "alerts" / f"{as_of_date}.json")

    policy_targets = load_bucket_targets(policy_path)

    # Run checks
    checks = [
        check_shadow_excess(perf_rows, THRESHOLDS["excess_lookback_weeks"]),
        check_turnover(perf_rows),
        check_bucket_drift(pre_trade, policy_targets),
        check_warn_streak(phase2_health, ruleset_health, alerts),
        check_gap_risk(phase2_health, pre_trade),
        check_pre_trade_gate(pre_trade),
    ]

    verdict = compute_verdict(checks)

    # Build context summary
    n_perf_rows = len(perf_rows)
    latest_perf = perf_rows[-1] if perf_rows else {}

    scorecard = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ruleset_id": ruleset_id or latest_perf.get("ruleset_id", ""),
        "verdict": verdict,
        "checks": checks,
        "context": {
            "n_performance_rows": n_perf_rows,
            "n_performance_rows_for_ruleset": len(perf_rows),
            "latest_perf_date": latest_perf.get("date", ""),
            "phase2_health_status": (phase2_health or {}).get("status", "N/A"),
            "ruleset_health_status": (ruleset_health or {}).get("status", "N/A"),
            "alert_count": (alerts or {}).get("alert_count", "N/A"),
            "pre_trade_overall": (pre_trade or {}).get("overall", "N/A"),
        },
    }

    return scorecard


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def format_scorecard_md(sc: Dict[str, Any]) -> str:
    """Render scorecard as markdown."""
    verdict = sc["verdict"]
    icon = {"READY": "**READY**", "REVIEW": "**REVIEW**", "HOLD": "**HOLD**"}
    lines = [
        f"# Weekly Readiness Scorecard — {sc['as_of_date']}",
        "",
        f"**Verdict: {icon.get(verdict, verdict)}**  ",
        f"Ruleset: `{sc.get('ruleset_id', '?')}`  ",
        f"Generated: {sc.get('generated_at', '')}",
        "",
        "## Checks",
        "",
        "| # | Check | Status | Value | Detail |",
        "|---|-------|--------|-------|--------|",
    ]

    for i, c in enumerate(sc.get("checks", []), 1):
        status = c["status"]
        val = c.get("value", "")
        if val is None:
            val = ""
        elif isinstance(val, float):
            val = f"{val:.2f}"
        lines.append(f"| {i} | {c['name']} | {status} | {val} | {c.get('detail', '')} |")

    lines.append("")

    # Context
    ctx = sc.get("context", {})
    lines.extend(
        [
            "## Context",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Performance rows (ruleset) | {ctx.get('n_performance_rows_for_ruleset', '?')} |",
            f"| Latest perf date | {ctx.get('latest_perf_date', '?')} |",
            f"| Phase2 health | {ctx.get('phase2_health_status', '?')} |",
            f"| Ruleset health | {ctx.get('ruleset_health_status', '?')} |",
            f"| Alert count | {ctx.get('alert_count', '?')} |",
            f"| Pre-trade overall | {ctx.get('pre_trade_overall', '?')} |",
            "",
        ]
    )

    # Guidance
    lines.extend(
        [
            "## Guidance",
            "",
        ]
    )
    if verdict == "READY":
        lines.append("All checks pass. Model is behaving calmly across repeated cycles.")
        lines.append("Proceed with normal weekly rebalance execution.")
    elif verdict == "REVIEW":
        warn_names = [c["name"] for c in sc.get("checks", []) if c["status"] == "WARN"]
        lines.append(f"WARN checks: {', '.join(warn_names)}")
        lines.append("")
        lines.append("Review the flagged dimensions before trading. If WARNs are")
        lines.append("expected (e.g., missing price for a recent IPO), proceed with caution.")
    else:
        fail_names = [c["name"] for c in sc.get("checks", []) if c["status"] in ("FAIL", "HOLD")]
        lines.append(f"Blocking checks: {', '.join(fail_names)}")
        lines.append("")
        lines.append("Do not trade until blocking issues are resolved.")
        lines.append("If HOLD due to insufficient data, continue accumulating weekly cycles.")
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# History management
# ---------------------------------------------------------------------------


def append_history(history_path: Path, scorecard: Dict[str, Any]) -> None:
    """Append a one-line JSON entry to the running history JSONL."""
    entry = {
        "date": scorecard["as_of_date"],
        "generated_at": scorecard["generated_at"],
        "ruleset_id": scorecard.get("ruleset_id", ""),
        "verdict": scorecard["verdict"],
        "checks_summary": {c["name"]: c["status"] for c in scorecard.get("checks", [])},
    }
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=False) + "\n")


def load_history(history_path: Path) -> List[Dict[str, Any]]:
    """Load history JSONL, return list of entries."""
    if not history_path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    with open(history_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


# ---------------------------------------------------------------------------
# Readiness policy & gate evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadinessPolicy:
    """Controls how the readiness verdict maps to execution boundaries."""

    schema: str = "readiness_policy.v1"
    hold_blocks_trades: bool = True
    review_blocks_trades: bool = False
    consecutive_review_to_hold: int = 0  # 0 = disabled
    ratchet_after_n_runs: int = 0  # 0 = disabled

    @classmethod
    def from_json(cls, path: Path) -> ReadinessPolicy:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        known = {fld for fld in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def default(cls) -> ReadinessPolicy:
        return cls()


def count_consecutive_verdict(
    history: List[Dict[str, Any]],
    verdict: str,
) -> int:
    """Count consecutive entries with the given verdict at the tail of history."""
    count = 0
    for entry in reversed(history):
        if entry.get("verdict") == verdict:
            count += 1
        else:
            break
    return count


def evaluate_readiness_gate(
    scorecard: Dict[str, Any],
    policy: ReadinessPolicy,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Evaluate whether the readiness verdict allows trading.

    Returns a dict with:
        can_trade: bool
        gate_status: "PASS" | "WARN" | "FAIL"
        verdict: str (original scorecard verdict)
        detail: str
        consecutive_review_runs: int
    """
    verdict = scorecard.get("verdict", "HOLD")
    consecutive_review = 0

    if history is not None:
        consecutive_review = count_consecutive_verdict(history, "REVIEW")
        # Count current run if it's REVIEW
        if verdict == "REVIEW":
            consecutive_review += 1

    # Ratchet escalation: consecutive REVIEW → HOLD
    ratchet_applied = False
    if (
        verdict == "REVIEW"
        and policy.consecutive_review_to_hold > 0
        and policy.ratchet_after_n_runs > 0
        and history is not None
        and len(history) >= policy.ratchet_after_n_runs
        and consecutive_review >= policy.consecutive_review_to_hold
    ):
        verdict = "HOLD"
        ratchet_applied = True

    # Map verdict to gate result
    if verdict == "HOLD":
        if policy.hold_blocks_trades:
            gate_status = "FAIL"
            can_trade = False
            detail = "HOLD — trades blocked by readiness policy"
            if ratchet_applied:
                detail = f"HOLD (ratchet: {consecutive_review} consecutive REVIEW) — trades blocked"
        else:
            gate_status = "WARN"
            can_trade = True
            detail = "HOLD — readiness policy set to advisory mode"
    elif verdict == "REVIEW":
        if policy.review_blocks_trades:
            gate_status = "FAIL"
            can_trade = False
            detail = "REVIEW — trades blocked by readiness policy"
        else:
            gate_status = "WARN"
            can_trade = True
            detail = f"REVIEW — advisory (consecutive={consecutive_review})"
    else:
        gate_status = "PASS"
        can_trade = True
        detail = "READY — all checks pass"

    return {
        "can_trade": can_trade,
        "gate_status": gate_status,
        "verdict": verdict,
        "original_verdict": scorecard.get("verdict", "HOLD"),
        "detail": detail,
        "consecutive_review_runs": consecutive_review,
        "ratchet_applied": ratchet_applied,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly readiness scorecard")
    parser.add_argument("--as-of-date", required=True, help="Screen date (YYYY-MM-DD)")
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=Path("data/snapshots"),
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("artifacts/live_shadow"),
    )
    parser.add_argument(
        "--policy-path",
        type=Path,
        default=Path("production_data/portfolio_policy.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/readiness"),
    )
    parser.add_argument(
        "--history-file",
        type=Path,
        default=Path("artifacts/readiness/history.jsonl"),
    )
    parser.add_argument("--ruleset-id", type=str, default="")
    parser.add_argument("--quiet", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    sc = build_scorecard(
        as_of_date=args.as_of_date,
        snapshots_dir=args.snapshots_dir,
        artifacts_dir=args.artifacts_dir,
        policy_path=args.policy_path,
        ruleset_id=args.ruleset_id,
    )

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_json = args.output_dir / f"scorecard_{args.as_of_date}.json"
    out_md = args.output_dir / f"scorecard_{args.as_of_date}.md"

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(sc, f, indent=2, default=str)
        f.write("\n")

    md = format_scorecard_md(sc)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)

    # Append history
    append_history(args.history_file, sc)

    # Print verdict
    if not args.quiet:
        print(md)
        logger.info("Scorecard written: %s", out_json)
        logger.info("History appended: %s", args.history_file)

    # Exit code: 0=READY, 1=HOLD, 2=REVIEW
    code = {"READY": 0, "REVIEW": 2, "HOLD": 1}.get(sc["verdict"], 1)
    sys.exit(code)


if __name__ == "__main__":
    main()
