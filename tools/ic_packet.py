#!/usr/bin/env python3
"""IC-Ready Weekly Packet — single consolidated artifact for the rebalance date.

Composes outputs from existing modules (no duplicated logic):
  - tools/pre_trade_check.py          → gate outcomes
  - tools/live_shadow_portfolio.py     → performance, model_vs_realized, execution quality
  - tools/build_attribution_packet.py  → alpha attribution

Outputs:
    artifacts/live_shadow/execution/{YYYY-MM-DD}/IC_PACKET.json
    artifacts/live_shadow/execution/{YYYY-MM-DD}/IC_PACKET.md
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import BUCKET_DISPLAY, BUCKET_NAMES, render_model_vs_realized_md

SCHEMA_VERSION = "ic_packet.v1"


# ---------------------------------------------------------------------------
# Production-path guards
# ---------------------------------------------------------------------------


def _in_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _assert_not_production_default(name: str, value: Path, production_default: Path) -> None:
    if _in_pytest() and value == production_default:
        raise AssertionError(f"Tests must pass `{name}` explicitly — got production default {production_default}")


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def _compute_policy_hash(policy_path: Optional[Path]) -> str:
    """SHA-256 of portfolio_policy.json content (first 16 hex chars)."""
    if policy_path is None or not policy_path.is_file():
        return "N/A"
    content = policy_path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:16]


def _read_git_sha() -> str:
    """Best-effort git SHA from .git/HEAD."""
    try:
        head = PROJECT_ROOT / ".git" / "HEAD"
        if not head.is_file():
            return "N/A"
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            ref_path = PROJECT_ROOT / ".git" / ref[5:]
            if ref_path.is_file():
                return ref_path.read_text().strip()[:12]
        return ref[:12]
    except Exception:
        return "N/A"


def build_provenance(
    as_of_date: str,
    metadata: Dict[str, Any],
    policy_path: Optional[Path],
    execution_status: str,
) -> Dict[str, Any]:
    """Build provenance section."""
    return {
        "as_of_date": as_of_date,
        "ruleset_id": metadata.get("ruleset_id", "N/A"),
        "engine_version": metadata.get("engine_version", "N/A"),
        "git_sha": _read_git_sha(),
        "policy_hash": _compute_policy_hash(policy_path),
        "execution_status": execution_status,
    }


# ---------------------------------------------------------------------------
# Gate outcomes (reuses pre_trade_check results)
# ---------------------------------------------------------------------------


def build_gates(pre_trade: Dict[str, Any]) -> Dict[str, Any]:
    """Extract gate outcomes from execution packet's pre_trade section."""
    checks = pre_trade.get("checks", [])
    blocking = [c for c in checks if c.get("status") == "FAIL"]
    return {
        "overall": pre_trade.get("overall", "N/A"),
        "can_trade": pre_trade.get("can_trade", False),
        "checks": checks,
        "blocking_reasons": [c["detail"] for c in blocking],
    }


# ---------------------------------------------------------------------------
# Portfolio summary (reuses positions_data summary)
# ---------------------------------------------------------------------------


def build_positions_summary(
    positions: List[Dict[str, Any]],
    policy: Dict[str, Any],
    perf: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build portfolio summary section from positions + policy."""
    account_usd = policy.get("account_usd", 500_000)
    total_dollars = sum(p.get("target_dollars", 0) for p in positions)
    n_positions = len(positions)

    # Bucket allocation
    bucket_alloc = {}
    for b in BUCKET_NAMES:
        b_pos = [p for p in positions if p.get("bucket") == b]
        b_dollars = sum(p.get("target_dollars", 0) for p in b_pos)
        bucket_alloc[b] = {
            "count": len(b_pos),
            "dollars": round(b_dollars, 2),
            "pct": round(b_dollars / account_usd * 100, 2) if account_usd > 0 else 0,
        }

    # Family allocation
    family_alloc: Dict[str, Dict[str, Any]] = {}
    for p in positions:
        fam = p.get("effective_family", p.get("catalyst_family", "OTHER"))
        if fam not in family_alloc:
            family_alloc[fam] = {"count": 0, "dollars": 0.0}
        family_alloc[fam]["count"] += 1
        family_alloc[fam]["dollars"] += p.get("target_dollars", 0)
    for fam in family_alloc:
        d = family_alloc[fam]["dollars"]
        family_alloc[fam]["pct"] = round(d / account_usd * 100, 2) if account_usd > 0 else 0
        family_alloc[fam]["dollars"] = round(d, 2)

    # Turnover estimate from performance
    turnover_pct = None
    if perf:
        turnover_pct = perf.get("name_turnover_pct")

    return {
        "n_positions": n_positions,
        "gross_exposure_usd": round(total_dollars, 2),
        "cash_usd": round(max(0, account_usd - total_dollars), 2),
        "turnover_estimate_pct": turnover_pct,
        "by_bucket": bucket_alloc,
        "by_family": family_alloc,
    }


# ---------------------------------------------------------------------------
# Alpha attribution (reuses perf sleeve_attribution)
# ---------------------------------------------------------------------------


def build_alpha_attribution(perf: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract alpha attribution from compute_performance() result."""
    if not perf:
        return {"available": False}

    sleeve = perf.get("sleeve_attribution", {})
    xbi_pct = perf.get("excess_vs_xbi_pct")
    total_pnl = perf.get("total_pnl", 0)
    pnl_pct = perf.get("pnl_pct", 0)

    by_bucket = {}
    for b in BUCKET_NAMES:
        s = sleeve.get(b, {})
        by_bucket[b] = {
            "pnl_usd": s.get("pnl", 0),
            "return_pct": s.get("return_pct", 0),
            "excess_vs_xbi_pct": s.get("excess_pct"),
        }

    return {
        "available": True,
        "total_pnl_usd": total_pnl,
        "total_pnl_pct": pnl_pct,
        "excess_vs_xbi_pct": xbi_pct,
        "by_bucket": by_bucket,
    }


# ---------------------------------------------------------------------------
# Contributors (top 5 positive / negative)
# ---------------------------------------------------------------------------


def build_contributors(perf: Optional[Dict[str, Any]], n: int = 5) -> Dict[str, Any]:
    """Extract top/bottom N contributors from performance result."""
    if not perf:
        return {"available": False}

    contribs = perf.get("contributors", [])
    if not contribs:
        return {"available": False, "n_total": 0}

    # Already sorted by pnl desc in compute_performance
    sorted_c = sorted(contribs, key=lambda c: (-c.get("pnl", 0), c.get("ticker", "")))
    top = sorted_c[:n]
    bottom = list(reversed(sorted_c[-n:])) if len(sorted_c) > n else []
    # Remove overlap
    top_tickers = {c["ticker"] for c in top}
    bottom = [c for c in bottom if c["ticker"] not in top_tickers]

    def _fmt(c: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ticker": c.get("ticker", ""),
            "bucket": c.get("bucket", ""),
            "family": c.get("effective_family", c.get("family", "")),
            "pnl_usd": round(c.get("pnl", 0), 2),
            "return_pct": round(c.get("return_pct", 0), 4),
            "dollars": round(c.get("dollars", 0), 2),
        }

    return {
        "available": True,
        "n_total": len(contribs),
        "top": [_fmt(c) for c in top],
        "bottom": [_fmt(c) for c in bottom],
    }


# ---------------------------------------------------------------------------
# Execution quality (reuse existing metrics)
# ---------------------------------------------------------------------------


def build_execution_quality(perf: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract execution quality from performance result."""
    if not perf:
        return {"available": False}

    eq = perf.get("execution_quality")
    if not eq:
        return {"available": False}

    return {
        "available": True,
        "fill_coverage_pct": eq.get("fill_coverage_pct"),
        "avg_slippage_bps": eq.get("mean_slippage_bps"),
        "median_slippage_bps": eq.get("median_slippage_bps"),
        "worst_slippage": eq.get("worst_slippage", [])[:5],
        "by_bucket": eq.get("by_bucket"),
        "by_family": eq.get("by_family"),
    }


# ---------------------------------------------------------------------------
# Risk flags
# ---------------------------------------------------------------------------


def build_risk_flags(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Identify risk flags from current positions."""
    gap_high = []
    missing_price = []
    resolved_regulatory = []

    for p in positions:
        ticker = p.get("ticker", "")
        if p.get("gap_risk") == "HIGH":
            gap_high.append(
                {
                    "ticker": ticker,
                    "bucket": p.get("bucket", ""),
                    "catalyst_days": p.get("catalyst_days"),
                    "weight_pct": round(p.get("weight_pct", 0), 2),
                }
            )
        if p.get("price_coverage") == "MISSING":
            missing_price.append(ticker)
        reg_days = p.get("regulatory_days")
        if reg_days is not None and reg_days != "":
            try:
                if float(reg_days) <= 0:
                    resolved_regulatory.append(ticker)
            except (ValueError, TypeError):
                pass

    return {
        "gap_risk_high": gap_high,
        "missing_price_coverage": missing_price,
        "resolved_regulatory": resolved_regulatory,
    }


# ---------------------------------------------------------------------------
# File index
# ---------------------------------------------------------------------------


def build_file_index(execution_dir: Path) -> List[str]:
    """List files written in the execution directory."""
    if not execution_dir.is_dir():
        return []
    return sorted(f.name for f in execution_dir.iterdir() if f.is_file())


# ---------------------------------------------------------------------------
# Packet builder
# ---------------------------------------------------------------------------


def build_ic_packet(
    as_of_date: str,
    execution_packet: Dict[str, Any],
    positions: List[Dict[str, Any]],
    policy: Dict[str, Any],
    metadata: Dict[str, Any],
    perf: Optional[Dict[str, Any]],
    execution_dir: Path,
    *,
    policy_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build the complete IC packet from existing computation results.

    Args:
        as_of_date: Rebalance date.
        execution_packet: Result from run_execution_pipeline().
        positions: Current position list.
        policy: Portfolio policy dict.
        metadata: Snapshot metadata.
        perf: Performance dict from compute_performance() (None if no prior).
        execution_dir: Path to execution/{date}/ directory.
        policy_path: Path to policy JSON (for hash computation).
    """
    status = execution_packet.get("status", "UNKNOWN")

    packet = {
        "schema": SCHEMA_VERSION,
        "provenance": build_provenance(as_of_date, metadata, policy_path, status),
        "status": status,
        "gates": build_gates(execution_packet.get("pre_trade", {})),
        "positions_summary": build_positions_summary(positions, policy, perf),
        "model_vs_realized": (perf or {}).get("model_vs_realized"),
        "alpha_attribution": build_alpha_attribution(perf),
        "contributors": build_contributors(perf),
        "execution_quality": build_execution_quality(perf),
        "risk_flags": build_risk_flags(positions),
        "files_written": build_file_index(execution_dir),
    }

    return packet


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def render_ic_packet_md(packet: Dict[str, Any]) -> str:
    """Render IC_PACKET.md from packet dict."""
    lines: List[str] = []
    prov = packet.get("provenance", {})
    status = packet.get("status", "UNKNOWN")

    # 1. Header / Provenance
    lines.append(f"# IC Packet — {prov.get('as_of_date', '?')}")
    lines.append("")
    lines.append("## Provenance")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| as_of_date | {prov.get('as_of_date', 'N/A')} |")
    lines.append(f"| ruleset_id | `{prov.get('ruleset_id', 'N/A')}` |")
    lines.append(f"| engine_version | {prov.get('engine_version', 'N/A')} |")
    lines.append(f"| git_sha | `{prov.get('git_sha', 'N/A')}` |")
    lines.append(f"| policy_hash | `{prov.get('policy_hash', 'N/A')}` |")
    lines.append(f"| execution_status | **{status}** |")
    lines.append("")

    # 2. Gate Outcomes
    gates = packet.get("gates", {})
    lines.append(f"## Gate Outcomes: {gates.get('overall', 'N/A')}")
    lines.append("")
    checks = gates.get("checks", [])
    if checks:
        lines.append("| Check | Status | Detail |")
        lines.append("|-------|--------|--------|")
        for c in checks:
            lines.append(f"| {c.get('name', '?')} | **{c.get('status', '?')}** | {c.get('detail', '')} |")
        lines.append("")

    blocking = gates.get("blocking_reasons", [])
    if blocking:
        lines.append("**Blocking reasons:**")
        for r in blocking:
            lines.append(f"- {r}")
        lines.append("")

    # 3. Portfolio Summary
    ps = packet.get("positions_summary", {})
    lines.append("## Portfolio Summary")
    lines.append("")
    lines.append(f"- **Positions**: {ps.get('n_positions', 0)}")
    lines.append(f"- **Gross exposure**: ${ps.get('gross_exposure_usd', 0):,.0f}")
    lines.append(f"- **Cash**: ${ps.get('cash_usd', 0):,.0f}")
    turn = ps.get("turnover_estimate_pct")
    if turn is not None:
        lines.append(f"- **Turnover**: {turn:.1f}%")
    lines.append("")

    # Bucket table
    by_bucket = ps.get("by_bucket", {})
    if by_bucket:
        lines.append("| Bucket | Names | $ | % |")
        lines.append("|--------|-------|---|---|")
        for b in BUCKET_NAMES:
            bd = by_bucket.get(b, {})
            lines.append(
                f"| {BUCKET_DISPLAY.get(b, b)}"
                f" | {bd.get('count', 0)}"
                f" | ${bd.get('dollars', 0):,.0f}"
                f" | {bd.get('pct', 0):.1f}% |"
            )
        lines.append("")

    # Family table
    by_family = ps.get("by_family", {})
    if by_family:
        lines.append("| Family | Names | $ | % |")
        lines.append("|--------|-------|---|---|")
        for fam in sorted(by_family.keys()):
            fd = by_family[fam]
            lines.append(
                f"| {fam}" f" | {fd.get('count', 0)}" f" | ${fd.get('dollars', 0):,.0f}" f" | {fd.get('pct', 0):.1f}% |"
            )
        lines.append("")

    # 4. Model vs Realized
    lines.append("## Performance: Model vs Realized")
    lines.append("")
    mvr = packet.get("model_vs_realized")
    mvr_lines = render_model_vs_realized_md(mvr)
    if mvr_lines:
        lines.extend(mvr_lines)
    else:
        lines.append("*N/A — no fill data available*")
    lines.append("")

    # 5. Alpha Attribution
    aa = packet.get("alpha_attribution", {})
    lines.append("## Alpha Attribution")
    lines.append("")
    if not aa.get("available"):
        lines.append("*N/A — no performance data*")
    else:
        lines.append(f"- **Total P&L**: ${aa.get('total_pnl_usd', 0):,.2f} ({aa.get('total_pnl_pct', 0):+.4f}%)")
        xbi = aa.get("excess_vs_xbi_pct")
        if xbi is not None:
            lines.append(f"- **XBI excess**: {xbi:+.4f}%")
        lines.append("")

        aa_bucket = aa.get("by_bucket", {})
        if aa_bucket:
            lines.append("| Bucket | P&L $ | Return % | XBI Excess |")
            lines.append("|--------|-------|----------|------------|")
            for b in BUCKET_NAMES:
                bd = aa_bucket.get(b, {})
                exc = bd.get("excess_vs_xbi_pct")
                exc_str = f"{exc:+.4f}%" if exc is not None else "N/A"
                lines.append(
                    f"| {BUCKET_DISPLAY.get(b, b)}"
                    f" | ${bd.get('pnl_usd', 0):,.2f}"
                    f" | {bd.get('return_pct', 0):+.4f}%"
                    f" | {exc_str} |"
                )
            lines.append("")

    # 6. What Drove the Week
    cc = packet.get("contributors", {})
    lines.append("## What Drove the Week")
    lines.append("")
    if not cc.get("available"):
        lines.append("*N/A — no performance data*")
    else:
        lines.append(f"*{cc.get('n_total', 0)} positions total*")
        lines.append("")

        def _contrib_table(items: List[Dict], label: str) -> None:
            if not items:
                return
            lines.append(f"### {label}")
            lines.append("")
            lines.append("| Ticker | Bucket | Family | P&L $ | Return % |")
            lines.append("|--------|--------|--------|-------|----------|")
            for e in items:
                lines.append(
                    f"| {e['ticker']}"
                    f" | {BUCKET_DISPLAY.get(e.get('bucket', ''), e.get('bucket', ''))}"
                    f" | {e.get('family', '')}"
                    f" | ${e['pnl_usd']:,.2f}"
                    f" | {e['return_pct']:+.2f}% |"
                )
            lines.append("")

        _contrib_table(cc.get("top", []), "Top 5 Positive")
        _contrib_table(cc.get("bottom", []), "Top 5 Negative")

    # 7. Execution Quality
    eq = packet.get("execution_quality", {})
    lines.append("## Execution Quality")
    lines.append("")
    if not eq.get("available"):
        lines.append("*N/A — no fill data*")
    else:
        lines.append(f"- **Fill coverage**: {eq.get('fill_coverage_pct', 0):.0f}%")
        avg_slip = eq.get("avg_slippage_bps")
        if avg_slip is not None:
            lines.append(f"- **Avg slippage**: {avg_slip:.1f}bps")
        med_slip = eq.get("median_slippage_bps")
        if med_slip is not None:
            lines.append(f"- **Median slippage**: {med_slip:.1f}bps")

        worst = eq.get("worst_slippage", [])
        if worst:
            lines.append("")
            lines.append("**Worst 5 slippage lines:**")
            lines.append("")
            lines.append("| Ticker | Slippage bps |")
            lines.append("|--------|-------------|")
            for w in worst[:5]:
                if isinstance(w, dict):
                    lines.append(f"| {w.get('ticker', '?')} | {w.get('slippage_bps', 0):.1f} |")
                else:
                    lines.append(f"| {w} | — |")
            lines.append("")

    lines.append("")

    # 8. Risk Flags
    rf = packet.get("risk_flags", {})
    lines.append("## Risk Flags")
    lines.append("")
    gap_high = rf.get("gap_risk_high", [])
    if gap_high:
        lines.append(f"**Gap-risk HIGH** ({len(gap_high)} names, <= 7d):")
        lines.append("")
        lines.append("| Ticker | Bucket | Days | Weight % |")
        lines.append("|--------|--------|------|----------|")
        for g in gap_high:
            lines.append(
                f"| {g['ticker']}"
                f" | {BUCKET_DISPLAY.get(g.get('bucket', ''), g.get('bucket', ''))}"
                f" | {g.get('catalyst_days', 'N/A')}"
                f" | {g.get('weight_pct', 0):.2f}% |"
            )
        lines.append("")
    else:
        lines.append("- No gap-risk HIGH positions")

    resolved = rf.get("resolved_regulatory", [])
    if resolved:
        lines.append(f"- **Resolved regulatory** (demoted): {', '.join(resolved)}")

    missing = rf.get("missing_price_coverage", [])
    if missing:
        lines.append(f"- **Missing price coverage**: {', '.join(missing)}")

    if not gap_high and not resolved and not missing:
        lines.append("- No active risk flags")
    lines.append("")

    # 9. File index
    files = packet.get("files_written", [])
    lines.append("## Files")
    lines.append("")
    if files:
        for f in files:
            lines.append(f"- `{f}`")
    else:
        lines.append("- (none)")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_ic_packet(
    execution_dir: Path,
    packet: Dict[str, Any],
) -> tuple:
    """Write IC_PACKET.json and IC_PACKET.md to execution_dir.

    Returns (json_path, md_path).
    """
    execution_dir.mkdir(parents=True, exist_ok=True)

    json_path = execution_dir / "IC_PACKET.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, default=str)

    md_path = execution_dir / "IC_PACKET.md"
    md_content = render_ic_packet_md(packet)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return json_path, md_path
