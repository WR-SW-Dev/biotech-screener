#!/usr/bin/env python3
"""Trade Decision Engine — deterministic GO/NO-GO from IC packet + policy.

Consumes:
  - IC_PACKET.json  (risk flags, gates, performance, execution quality)
  - trade_decision_policy.json  (hard thresholds)

Emits:
  - TRADE_DECISION.json  (verdict + per-check detail + caps if applicable)
  - TRADE_DECISION.md

Verdicts:
  TRADE           — all checks pass, execute trade plan as-is
  TRADE_WITH_CAPS — some checks triggered caps, execute with adjustments
  NO_TRADE        — hard fail, do not trade

Usage:
    python3 tools/trade_decision.py --as-of-date 2026-03-10
    python3 tools/trade_decision.py --as-of-date 2026-03-10 --execution-dir path/to/dir
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import SHADOW_ROOT

EXECUTION_ROOT = SHADOW_ROOT / "execution"
POLICY_PATH = PROJECT_ROOT / "production_data" / "trade_decision_policy.json"

SCHEMA_VERSION = "trade_decision.v1"

VERDICT_TRADE = "TRADE"
VERDICT_TRADE_WITH_CAPS = "TRADE_WITH_CAPS"
VERDICT_NO_TRADE = "NO_TRADE"


# ---------------------------------------------------------------------------
# Production-path guards
# ---------------------------------------------------------------------------


def _in_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _assert_not_production_default(name: str, value: Path, production_default: Path) -> None:
    if _in_pytest() and value == production_default:
        raise AssertionError(f"Tests must pass `{name}` explicitly — got production default {production_default}")


# ---------------------------------------------------------------------------
# Policy loader
# ---------------------------------------------------------------------------


def load_trade_decision_policy(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load trade_decision_policy.json."""
    p = path or POLICY_PATH
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_ic_packet(execution_dir: Path) -> Dict[str, Any]:
    """Load IC_PACKET.json from execution dir."""
    ic_path = execution_dir / "IC_PACKET.json"
    with open(ic_path, encoding="utf-8") as f:
        return json.load(f)


def load_execution_packet(execution_dir: Path) -> Dict[str, Any]:
    """Load EXECUTION_PACKET.json from execution dir."""
    ep_path = execution_dir / "EXECUTION_PACKET.json"
    with open(ep_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Check result
# ---------------------------------------------------------------------------


@dataclass
class DecisionCheck:
    name: str
    status: str  # PASS, WARN, FAIL
    detail: str
    value: Any = None
    threshold: Any = None
    cap: Optional[Dict[str, Any]] = None  # Non-None if this triggers a cap

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "value": self.value,
            "threshold": self.threshold,
        }
        if self.cap is not None:
            d["cap"] = self.cap
        return d


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_pre_trade_gate(ic_packet: Dict[str, Any], policy: Dict[str, Any]) -> DecisionCheck:
    """FAIL if pre-trade gate overall is FAIL and policy requires it."""
    must_pass = policy.get("gates", {}).get("pre_trade_must_pass", True)
    gates = ic_packet.get("gates", {})
    overall = gates.get("overall", "N/A")
    can_trade = gates.get("can_trade", False)

    if must_pass and not can_trade:
        blocking = gates.get("blocking_reasons", [])
        detail = f"Pre-trade gate {overall}"
        if blocking:
            detail += f": {'; '.join(blocking[:3])}"
        return DecisionCheck(
            name="pre_trade_gate",
            status="FAIL",
            detail=detail,
            value=overall,
            threshold="must_pass",
        )

    return DecisionCheck(
        name="pre_trade_gate",
        status="PASS",
        detail=f"Pre-trade gate {overall}, can_trade={can_trade}",
        value=overall,
        threshold="must_pass" if must_pass else "advisory",
    )


def check_gap_risk_count(ic_packet: Dict[str, Any], policy: Dict[str, Any]) -> DecisionCheck:
    """FAIL if gap-risk HIGH count exceeds hard limit; WARN+cap if above trigger."""
    risk_limits = policy.get("risk_limits", {})
    max_count = risk_limits.get("max_gap_risk_high_count", 4)
    cap_trigger = policy.get("caps", {}).get("gap_risk_high_count_trigger", 3)

    gap_high = ic_packet.get("risk_flags", {}).get("gap_risk_high", [])
    count = len(gap_high)
    names = [g.get("ticker", "?") for g in gap_high]

    if count > max_count:
        return DecisionCheck(
            name="gap_risk_high_count",
            status="FAIL",
            detail=f"{count} gap-risk HIGH names ({', '.join(names)}) > max {max_count}",
            value=count,
            threshold=max_count,
        )

    if count >= cap_trigger:
        cap_pct = policy.get("caps", {}).get("gap_risk_high_name_cap_pct", 0.25)
        budget_reduction = policy.get("caps", {}).get("gap_risk_high_budget_reduction_pct", 15.0)
        return DecisionCheck(
            name="gap_risk_high_count",
            status="WARN",
            detail=f"{count} gap-risk HIGH names ({', '.join(names)}) >= trigger {cap_trigger}",
            value=count,
            threshold=cap_trigger,
            cap={
                "type": "gap_risk_cap",
                "name_cap_pct": cap_pct,
                "budget_reduction_pct": budget_reduction,
                "affected_tickers": names,
            },
        )

    return DecisionCheck(
        name="gap_risk_high_count",
        status="PASS",
        detail=f"{count} gap-risk HIGH names" + (f" ({', '.join(names)})" if names else ""),
        value=count,
        threshold=max_count,
    )


def check_gap_risk_weight(ic_packet: Dict[str, Any], policy: Dict[str, Any]) -> DecisionCheck:
    """FAIL if gap-risk HIGH aggregate weight exceeds limit."""
    max_weight = policy.get("risk_limits", {}).get("max_gap_risk_high_weight_pct", 8.0)
    gap_high = ic_packet.get("risk_flags", {}).get("gap_risk_high", [])
    total_weight = sum(g.get("weight_pct", 0) for g in gap_high)

    if total_weight > max_weight:
        return DecisionCheck(
            name="gap_risk_high_weight",
            status="FAIL",
            detail=f"Gap-risk HIGH weight {total_weight:.2f}% > max {max_weight}%",
            value=round(total_weight, 2),
            threshold=max_weight,
        )

    return DecisionCheck(
        name="gap_risk_high_weight",
        status="PASS",
        detail=f"Gap-risk HIGH weight {total_weight:.2f}%",
        value=round(total_weight, 2),
        threshold=max_weight,
    )


def check_missing_price_coverage(ic_packet: Dict[str, Any], policy: Dict[str, Any]) -> DecisionCheck:
    """FAIL if missing price coverage exceeds limit."""
    max_missing = policy.get("risk_limits", {}).get("max_missing_price_coverage", 2)
    missing = ic_packet.get("risk_flags", {}).get("missing_price_coverage", [])
    count = len(missing)

    if count > max_missing:
        return DecisionCheck(
            name="missing_price_coverage",
            status="FAIL",
            detail=f"{count} missing prices ({', '.join(missing)}) > max {max_missing}",
            value=count,
            threshold=max_missing,
        )

    status = "WARN" if count > 0 else "PASS"
    return DecisionCheck(
        name="missing_price_coverage",
        status=status,
        detail=f"{count} missing prices" + (f" ({', '.join(missing)})" if missing else ""),
        value=count,
        threshold=max_missing,
    )


def check_resolved_regulatory(ic_packet: Dict[str, Any], policy: Dict[str, Any]) -> DecisionCheck:
    """WARN if resolved regulatory names exceed limit (advisory, not blocking)."""
    max_resolved = policy.get("risk_limits", {}).get("max_resolved_regulatory", 3)
    resolved = ic_packet.get("risk_flags", {}).get("resolved_regulatory", [])
    count = len(resolved)

    if count > max_resolved:
        return DecisionCheck(
            name="resolved_regulatory",
            status="WARN",
            detail=f"{count} resolved regulatory ({', '.join(resolved)}) > advisory max {max_resolved}",
            value=count,
            threshold=max_resolved,
        )

    return DecisionCheck(
        name="resolved_regulatory",
        status="PASS",
        detail=f"{count} resolved regulatory" + (f" ({', '.join(resolved)})" if resolved else ""),
        value=count,
        threshold=max_resolved,
    )


def check_execution_quality(ic_packet: Dict[str, Any], policy: Dict[str, Any]) -> DecisionCheck:
    """WARN+cap if execution quality is poor (only when fill data available)."""
    eq = ic_packet.get("execution_quality", {})
    if not eq.get("available"):
        return DecisionCheck(
            name="execution_quality",
            status="PASS",
            detail="No fill data available — check skipped",
            value=None,
            threshold=None,
        )

    eq_policy = policy.get("execution_quality", {})
    min_coverage = eq_policy.get("min_fill_coverage_pct", 50.0)
    max_slippage = eq_policy.get("max_avg_slippage_bps", 50.0)

    fill_coverage = eq.get("fill_coverage_pct", 100.0)
    avg_slippage = eq.get("avg_slippage_bps")

    issues = []
    if fill_coverage is not None and fill_coverage < min_coverage:
        issues.append(f"fill coverage {fill_coverage:.0f}% < {min_coverage:.0f}%")
    if avg_slippage is not None and avg_slippage > max_slippage:
        issues.append(f"avg slippage {avg_slippage:.1f}bps > {max_slippage:.0f}bps")

    if issues:
        caps_policy = policy.get("caps", {})
        slippage_trigger = caps_policy.get("realized_worse_slippage_trigger_bps", 30.0)
        min_bump = caps_policy.get("realized_worse_min_trade_usd_bump", 500)
        cap = None
        if avg_slippage is not None and avg_slippage > slippage_trigger:
            cap = {
                "type": "min_trade_bump",
                "min_trade_usd_bump": min_bump,
                "reason": f"avg slippage {avg_slippage:.1f}bps > trigger {slippage_trigger:.0f}bps",
            }
        return DecisionCheck(
            name="execution_quality",
            status="WARN",
            detail="; ".join(issues),
            value={"fill_coverage_pct": fill_coverage, "avg_slippage_bps": avg_slippage},
            threshold={"min_fill_coverage_pct": min_coverage, "max_avg_slippage_bps": max_slippage},
            cap=cap,
        )

    return DecisionCheck(
        name="execution_quality",
        status="PASS",
        detail=(
            f"Fill coverage {fill_coverage:.0f}%, avg slippage {avg_slippage:.1f}bps"
            if avg_slippage is not None
            else f"Fill coverage {fill_coverage:.0f}%"
        ),
        value={"fill_coverage_pct": fill_coverage, "avg_slippage_bps": avg_slippage},
        threshold={"min_fill_coverage_pct": min_coverage, "max_avg_slippage_bps": max_slippage},
    )


def check_model_vs_realized(ic_packet: Dict[str, Any], policy: Dict[str, Any]) -> DecisionCheck:
    """WARN if realized P&L is significantly worse than model."""
    mvr = ic_packet.get("model_vs_realized")
    if not mvr:
        return DecisionCheck(
            name="model_vs_realized",
            status="PASS",
            detail="No model vs realized data — check skipped",
            value=None,
            threshold=None,
        )

    max_neg_gap = policy.get("model_vs_realized", {}).get("max_negative_gap_pct", -0.50)
    gap_pct = mvr.get("gap_pct")

    if gap_pct is None:
        return DecisionCheck(
            name="model_vs_realized",
            status="PASS",
            detail="Gap not computed",
            value=None,
            threshold=max_neg_gap,
        )

    if gap_pct < max_neg_gap:
        return DecisionCheck(
            name="model_vs_realized",
            status="WARN",
            detail=f"Realized gap {gap_pct:+.2f}% worse than threshold {max_neg_gap:+.2f}%",
            value=round(gap_pct, 4),
            threshold=max_neg_gap,
        )

    return DecisionCheck(
        name="model_vs_realized",
        status="PASS",
        detail=f"Realized gap {gap_pct:+.2f}%",
        value=round(gap_pct, 4),
        threshold=max_neg_gap,
    )


def check_alpha_health(ic_packet: Dict[str, Any], policy: Dict[str, Any]) -> DecisionCheck:
    """FAIL if trailing hedged excess is below floor."""
    aa = ic_packet.get("alpha_attribution", {})
    if not aa.get("available"):
        return DecisionCheck(
            name="alpha_health",
            status="PASS",
            detail="No alpha attribution data — check skipped",
            value=None,
            threshold=None,
        )

    min_excess = policy.get("alpha_health", {}).get("min_trailing_excess_pct", -1.0)
    excess = aa.get("excess_vs_xbi_pct")

    if excess is None:
        return DecisionCheck(
            name="alpha_health",
            status="PASS",
            detail="XBI excess not available",
            value=None,
            threshold=min_excess,
        )

    if excess < min_excess:
        return DecisionCheck(
            name="alpha_health",
            status="FAIL",
            detail=f"Trailing excess {excess:+.4f}% < floor {min_excess:+.1f}%",
            value=round(excess, 4),
            threshold=min_excess,
        )

    return DecisionCheck(
        name="alpha_health",
        status="PASS",
        detail=f"Trailing excess {excess:+.4f}%",
        value=round(excess, 4),
        threshold=min_excess,
    )


def check_turnover(ic_packet: Dict[str, Any], policy: Dict[str, Any]) -> DecisionCheck:
    """FAIL if turnover exceeds limit."""
    max_turnover = policy.get("turnover", {}).get("max_turnover_pct", 40.0)
    ps = ic_packet.get("positions_summary", {})
    turnover = ps.get("turnover_estimate_pct")

    if turnover is None:
        return DecisionCheck(
            name="turnover",
            status="PASS",
            detail="No turnover estimate — check skipped",
            value=None,
            threshold=max_turnover,
        )

    if turnover > max_turnover:
        return DecisionCheck(
            name="turnover",
            status="FAIL",
            detail=f"Turnover {turnover:.1f}% > max {max_turnover:.0f}%",
            value=round(turnover, 2),
            threshold=max_turnover,
        )

    return DecisionCheck(
        name="turnover",
        status="PASS",
        detail=f"Turnover {turnover:.1f}%",
        value=round(turnover, 2),
        threshold=max_turnover,
    )


# ---------------------------------------------------------------------------
# Decision builder
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_pre_trade_gate,
    check_gap_risk_count,
    check_gap_risk_weight,
    check_missing_price_coverage,
    check_resolved_regulatory,
    check_execution_quality,
    check_model_vs_realized,
    check_alpha_health,
    check_turnover,
]


def build_trade_decision(
    ic_packet: Dict[str, Any],
    policy: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate all policy checks against IC packet and return trade decision.

    Returns dict with schema, verdict, checks, caps, and provenance.
    """
    checks: List[DecisionCheck] = []
    for check_fn in ALL_CHECKS:
        checks.append(check_fn(ic_packet, policy))

    # Determine verdict
    fails = [c for c in checks if c.status == "FAIL"]
    caps = [c for c in checks if c.cap is not None]

    if fails:
        verdict = VERDICT_NO_TRADE
    elif caps:
        verdict = VERDICT_TRADE_WITH_CAPS
    else:
        verdict = VERDICT_TRADE

    # Build caps list
    active_caps = []
    for c in caps:
        cap = dict(c.cap)  # type: ignore[arg-type]
        cap["triggered_by"] = c.name
        active_caps.append(cap)

    prov = ic_packet.get("provenance", {})
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    decision = {
        "schema": SCHEMA_VERSION,
        "as_of_date": prov.get("as_of_date", ic_packet.get("provenance", {}).get("as_of_date", "")),
        "generated_at": ts,
        "verdict": verdict,
        "checks": [c.to_dict() for c in checks],
        "n_pass": sum(1 for c in checks if c.status == "PASS"),
        "n_warn": sum(1 for c in checks if c.status == "WARN"),
        "n_fail": sum(1 for c in checks if c.status == "FAIL"),
        "blocking_reasons": [c.detail for c in fails],
        "caps": active_caps,
        "provenance": {
            "ruleset_id": prov.get("ruleset_id", "N/A"),
            "policy_schema": policy.get("schema", "N/A"),
            "ic_packet_schema": ic_packet.get("schema", "N/A"),
        },
    }

    return decision


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def render_trade_decision_md(decision: Dict[str, Any]) -> str:
    """Render TRADE_DECISION.md from decision dict."""
    lines: List[str] = []
    verdict = decision.get("verdict", "UNKNOWN")
    as_of = decision.get("as_of_date", "?")

    verdict_icon = {
        VERDICT_TRADE: "TRADE",
        VERDICT_TRADE_WITH_CAPS: "TRADE WITH CAPS",
        VERDICT_NO_TRADE: "NO TRADE",
    }.get(verdict, verdict)

    lines.append(f"# Trade Decision — {as_of}")
    lines.append("")
    lines.append(f"**Verdict: {verdict_icon}**")
    lines.append("")
    lines.append(
        f"Checks: {decision.get('n_pass', 0)} PASS, "
        f"{decision.get('n_warn', 0)} WARN, "
        f"{decision.get('n_fail', 0)} FAIL"
    )
    lines.append("")

    # Blocking reasons
    blocking = decision.get("blocking_reasons", [])
    if blocking:
        lines.append("## Blocking Reasons")
        lines.append("")
        for r in blocking:
            lines.append(f"- {r}")
        lines.append("")

    # Checks table
    lines.append("## Checks")
    lines.append("")
    lines.append("| Check | Status | Detail |")
    lines.append("|-------|--------|--------|")
    for c in decision.get("checks", []):
        status = c.get("status", "?")
        lines.append(f"| {c.get('name', '?')} | **{status}** | {c.get('detail', '')} |")
    lines.append("")

    # Caps
    caps = decision.get("caps", [])
    if caps:
        lines.append("## Active Caps")
        lines.append("")
        for cap in caps:
            cap_type = cap.get("type", "?")
            triggered = cap.get("triggered_by", "?")
            lines.append(f"### {cap_type} (triggered by {triggered})")
            lines.append("")
            for k, v in cap.items():
                if k in ("type", "triggered_by"):
                    continue
                if isinstance(v, list):
                    lines.append(f"- **{k}**: {', '.join(str(x) for x in v)}")
                else:
                    lines.append(f"- **{k}**: {v}")
            lines.append("")

    # Provenance
    prov = decision.get("provenance", {})
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- ruleset_id: `{prov.get('ruleset_id', 'N/A')}`")
    lines.append(f"- policy_schema: {prov.get('policy_schema', 'N/A')}")
    lines.append(f"- generated_at: {decision.get('generated_at', '?')}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_trade_decision(
    execution_dir: Path,
    decision: Dict[str, Any],
) -> tuple:
    """Write TRADE_DECISION.json and .md to execution_dir.

    Returns (json_path, md_path).
    """
    execution_dir.mkdir(parents=True, exist_ok=True)

    json_path = execution_dir / "TRADE_DECISION.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(decision, f, indent=2, default=str)

    md_path = execution_dir / "TRADE_DECISION.md"
    md_content = render_trade_decision_md(decision)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return json_path, md_path


# ---------------------------------------------------------------------------
# Cap enforcement — apply caps to positions
# ---------------------------------------------------------------------------


def apply_caps_to_positions(
    positions: List[Dict[str, Any]],
    caps: List[Dict[str, Any]],
    account_usd: float,
) -> tuple:
    """Apply caps to positions in-memory, returning (capped_positions, summary).

    Cap types handled:
      - gap_risk_cap:   cap affected tickers' target_dollars, then reduce budget
      - min_trade_bump: returned in summary for caller to use as min_trade_usd

    Returns (capped_positions, caps_summary_dict).
    Positions are deep-copied; originals are not modified.
    """
    import copy

    capped = copy.deepcopy(positions)
    min_trade_usd_bump = 0

    # Snapshot before-state from originals
    orig_map = {p["ticker"]: p.get("target_dollars", 0) for p in positions}

    for cap in caps:
        cap_type = cap.get("type")

        if cap_type == "gap_risk_cap":
            name_cap_dollars = account_usd * cap.get("name_cap_pct", 100.0) / 100.0
            budget_reduction_pct = cap.get("budget_reduction_pct", 0)
            affected = set(cap.get("affected_tickers", []))

            # Cap individual names
            for p in capped:
                if p["ticker"] in affected:
                    p["target_dollars"] = min(p.get("target_dollars", 0), name_cap_dollars)

            # Reduce total budget
            if budget_reduction_pct > 0:
                scale = 1.0 - budget_reduction_pct / 100.0
                for p in capped:
                    p["target_dollars"] = round(p.get("target_dollars", 0) * scale, 2)

        elif cap_type == "global_name_cap":
            name_cap_pct = cap.get("name_cap_pct", 0.035)
            name_cap_dollars = account_usd * name_cap_pct
            _apply_global_name_cap_reflow(capped, name_cap_dollars)

        elif cap_type == "min_trade_bump":
            min_trade_usd_bump = max(min_trade_usd_bump, cap.get("min_trade_usd_bump", 0))

    # Update weight_pct to stay consistent with target_dollars
    for p in capped:
        if account_usd > 0:
            p["weight_pct"] = round(p.get("target_dollars", 0) / account_usd * 100, 4)

    # Sanity: no negative weights
    for p in capped:
        if p.get("target_dollars", 0) < 0:
            p["target_dollars"] = 0
            p["weight_pct"] = 0

    # Build per-ticker change list
    cap_map = {p["ticker"]: p for p in capped}
    ticker_changes = []
    for p in positions:
        ticker = p["ticker"]
        before = orig_map.get(ticker, 0)
        after = cap_map.get(ticker, {}).get("target_dollars", 0)
        delta = after - before
        if abs(delta) > 0.01:
            ticker_changes.append(
                {
                    "ticker": ticker,
                    "bucket": p.get("bucket", ""),
                    "before_usd": round(before, 2),
                    "after_usd": round(after, 2),
                    "delta_usd": round(delta, 2),
                    "reason": _classify_cap_reason(ticker, caps),
                }
            )

    # Sort by delta ascending (largest reductions first)
    ticker_changes.sort(key=lambda x: (x["delta_usd"], x["ticker"]))
    top_reductions = ticker_changes[:10]

    # Before/after summary
    before_total = sum(p.get("target_dollars", 0) for p in positions)
    after_total = sum(p.get("target_dollars", 0) for p in capped)

    def _gap_high_stats(pos_list):
        gh = [p for p in pos_list if p.get("gap_risk") == "HIGH"]
        weight = sum(p.get("target_dollars", 0) / account_usd * 100 for p in gh) if account_usd > 0 else 0
        return len(gh), round(weight, 2)

    gh_count_before, gh_weight_before = _gap_high_stats(positions)
    gh_count_after, gh_weight_after = _gap_high_stats(capped)

    def _largest_pct(pos_list):
        if not pos_list or account_usd <= 0:
            return 0
        return round(max(p.get("target_dollars", 0) for p in pos_list) / account_usd * 100, 2)

    # Extract global cap params for transparency
    global_cap_params = None
    for cap in caps:
        if cap.get("type") == "global_name_cap":
            global_cap_params = {
                "name_cap_pct": cap.get("name_cap_pct"),
                "base_cap_pct": cap.get("base_cap_pct"),
                "shock_applied": cap.get("shock_applied", False),
            }
            break

    summary = {
        "caps_applied": True,
        "caps_detail": caps,
        "min_trade_usd_bump": min_trade_usd_bump,
        "targets_before": {
            "total_usd": round(before_total, 2),
            "n_positions": len(positions),
            "largest_position_pct": _largest_pct(positions),
            "gap_risk_high_count": gh_count_before,
            "gap_risk_high_weight_pct": gh_weight_before,
        },
        "targets_after": {
            "total_usd": round(after_total, 2),
            "n_positions": len(capped),
            "largest_position_pct": _largest_pct(capped),
            "gap_risk_high_count": gh_count_after,
            "gap_risk_high_weight_pct": gh_weight_after,
        },
        "top_reductions": top_reductions,
    }

    if global_cap_params:
        summary["global_cap_params"] = global_cap_params

    return capped, summary


def _apply_global_name_cap_reflow(
    positions: List[Dict[str, Any]],
    name_cap_dollars: float,
    max_iterations: int = 10,
) -> None:
    """Cap every position at name_cap_dollars, reflowing overflow proportionally.

    Modifies positions in-place.  Iterates because reflow can push previously-
    uncapped names over the cap.  Total budget is conserved (sum of target_dollars
    is unchanged, up to floating-point rounding).
    """
    for _ in range(max_iterations):
        overflow = 0.0
        uncapped_total = 0.0

        for p in positions:
            td = p.get("target_dollars", 0)
            if td > name_cap_dollars:
                overflow += td - name_cap_dollars
                p["target_dollars"] = name_cap_dollars
            else:
                uncapped_total += td

        if overflow < 0.01:
            break

        if uncapped_total <= 0:
            break

        # Distribute overflow proportionally to positions still under the cap
        for p in positions:
            td = p.get("target_dollars", 0)
            if td < name_cap_dollars:
                share = td / uncapped_total
                p["target_dollars"] = round(td + overflow * share, 2)


def build_global_name_cap(
    policy: Dict[str, Any],
    *,
    xbi_weekly_ret: Optional[float] = None,
    xbi_dd_change_pp: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Build a global_name_cap dict from portfolio policy, or None if disabled.

    Args:
        policy: portfolio_policy.json contents
        xbi_weekly_ret: XBI 1-week return as decimal (e.g. -0.06 for -6%)
        xbi_dd_change_pp: XBI drawdown change in percentage points (e.g. -7.0)

    Returns cap dict suitable for apply_caps_to_positions, or None.
    """
    gnc = policy.get("global_name_cap", {})
    if not gnc.get("enabled", False):
        return None

    base_cap_pct = gnc.get("cap_pct", 0.035)
    cap_pct = base_cap_pct

    shock_applied = False
    shock_cfg = policy.get("global_cap_shock", {})
    if shock_cfg.get("enabled", False):
        floor_ret = shock_cfg.get("xbi_weekly_ret_floor", -0.05)
        floor_dd = shock_cfg.get("dd_change_floor_pp", -5.0)
        multiplier = shock_cfg.get("multiplier", 0.8)

        if (
            xbi_weekly_ret is not None
            and xbi_dd_change_pp is not None
            and xbi_weekly_ret <= floor_ret
            and xbi_dd_change_pp <= floor_dd
        ):
            cap_pct = base_cap_pct * multiplier
            shock_applied = True

    return {
        "type": "global_name_cap",
        "name_cap_pct": cap_pct,
        "base_cap_pct": base_cap_pct,
        "shock_applied": shock_applied,
        "triggered_by": "global_name_cap",
    }


def _classify_cap_reason(ticker: str, caps: List[Dict[str, Any]]) -> str:
    """Determine which cap(s) affected a ticker."""
    reasons = []
    for cap in caps:
        cap_type = cap.get("type", "")
        if cap_type == "gap_risk_cap":
            if ticker in cap.get("affected_tickers", []):
                reasons.append("gap_risk_cap")
            if cap.get("budget_reduction_pct", 0) > 0:
                reasons.append("budget_reduction")
        elif cap_type == "global_name_cap":
            reasons.append("global_name_cap")
        elif cap_type == "min_trade_bump":
            pass  # Doesn't affect position sizing
    return ", ".join(sorted(set(reasons))) if reasons else "budget_reduction"


# ---------------------------------------------------------------------------
# Top-level runner (from IC packet on disk)
# ---------------------------------------------------------------------------


def run_trade_decision(
    as_of_date: str,
    *,
    execution_root: Path = EXECUTION_ROOT,
    policy_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load IC packet, evaluate policy, write decision artifacts.

    Returns the decision dict.
    """
    _assert_not_production_default("execution_root", execution_root, EXECUTION_ROOT)

    execution_dir = execution_root / as_of_date
    ic_packet = load_ic_packet(execution_dir)
    policy = load_trade_decision_policy(policy_path)
    decision = build_trade_decision(ic_packet, policy)
    write_trade_decision(execution_dir, decision)
    return decision


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Trade Decision Engine — deterministic GO/NO-GO verdict")
    parser.add_argument("--as-of-date", type=str, required=True, help="Rebalance date (YYYY-MM-DD)")
    parser.add_argument("--execution-dir", type=str, help="Override execution directory path")
    parser.add_argument("--policy", type=str, help="Trade decision policy JSON path")
    args = parser.parse_args()

    policy_path = Path(args.policy) if args.policy else None

    if args.execution_dir:
        execution_dir = Path(args.execution_dir)
        ic_packet = load_ic_packet(execution_dir)
        policy = load_trade_decision_policy(policy_path)
        decision = build_trade_decision(ic_packet, policy)
        write_trade_decision(execution_dir, decision)
    else:
        decision = run_trade_decision(
            args.as_of_date,
            policy_path=policy_path,
        )

    verdict = decision.get("verdict", "UNKNOWN")
    print(f"Verdict: {verdict}")
    print(f"Checks: {decision['n_pass']} PASS, {decision['n_warn']} WARN, {decision['n_fail']} FAIL")

    if verdict == VERDICT_NO_TRADE:
        print("Blocking reasons:")
        for r in decision.get("blocking_reasons", []):
            print(f"  - {r}")
        sys.exit(2)
    elif verdict == VERDICT_TRADE_WITH_CAPS:
        print("Active caps:")
        for cap in decision.get("caps", []):
            print(f"  - [{cap['type']}] triggered by {cap['triggered_by']}")
        sys.exit(0)
    else:
        print("All clear — execute trade plan as-is")
        sys.exit(0)


if __name__ == "__main__":
    main()
