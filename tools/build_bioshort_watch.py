#!/usr/bin/env python3
"""Bioshort watch — read-only hedge monitor that diffs weekly bioshort outputs.

Reads the latest and prior hedge_report_*.json, compares key fields, and
surfaces operator-relevant changes. Does NOT modify scoring, ranking,
execution, or hedge report logic.

Output:
    artifacts/bioshort_watch/{date}_watch.json
    artifacts/bioshort_watch/{date}_watch.md

Usage:
    python tools/build_bioshort_watch.py
    python tools/build_bioshort_watch.py --as-of-date 2026-03-26
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("bioshort_watch")

SCHEMA_VERSION = "bioshort_watch.v1"

HEDGE_REPORT_DIR = REPO_ROOT / "output" / "hedge_report"
VERDICT_PATH = HEDGE_REPORT_DIR / "BIOSHORT_VERDICT.json"


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _find_reports(report_dir: Path) -> List[Path]:
    """Find hedge_report_*.json files sorted by date descending."""
    return sorted(report_dir.glob("hedge_report_*.json"), reverse=True)


def _safe_get(d: Dict, *keys, default=None):
    """Nested dict access with default."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def _pct_change(current: float, prior: float) -> Optional[float]:
    if prior and prior != 0:
        return round((current - prior) / abs(prior) * 100, 1)
    return None


def diff_verdict(current: Dict, prior: Optional[Dict]) -> Dict[str, Any]:
    """Compare verdict fields between current and prior."""
    if not prior:
        return {
            "verdict_changed": None,
            "reason": "no prior verdict for comparison",
        }

    changed = current.get("verdict") != prior.get("verdict")
    return {
        "verdict_changed": changed,
        "current_verdict": current.get("verdict"),
        "prior_verdict": prior.get("verdict"),
        "current_confidence": current.get("confidence"),
        "prior_confidence": prior.get("confidence"),
        "confidence_score_delta": round(
            (current.get("confidence_score", 0) or 0) - (prior.get("confidence_score", 0) or 0), 1
        ),
        "recommendation_changed": current.get("recommendation") != prior.get("recommendation"),
        "current_recommendation": current.get("recommendation"),
        "prior_recommendation": prior.get("recommendation"),
    }


def diff_vehicle(current: Dict, prior: Optional[Dict]) -> Dict[str, Any]:
    """Compare best hedge vehicle and beta stats."""
    if not prior:
        return {"vehicle_changed": None, "reason": "no prior report"}

    cur_vehicle = current.get("best_hedge_vehicle")
    pri_vehicle = prior.get("best_hedge_vehicle")

    cur_beta = _safe_get(current, "beta_stats", cur_vehicle, default={})
    pri_beta = _safe_get(prior, "beta_stats", pri_vehicle, default={})

    return {
        "vehicle_changed": cur_vehicle != pri_vehicle,
        "current_vehicle": cur_vehicle,
        "prior_vehicle": pri_vehicle,
        "current_r_squared": cur_beta.get("r_squared"),
        "prior_r_squared": pri_beta.get("r_squared"),
        "current_beta": cur_beta.get("beta"),
        "prior_beta": pri_beta.get("beta"),
        "r_squared_delta": round((cur_beta.get("r_squared") or 0) - (pri_beta.get("r_squared") or 0), 4),
    }


def diff_structure(current: Dict, prior: Optional[Dict]) -> Dict[str, Any]:
    """Compare recommended hedge structure and cost."""
    if not prior:
        return {"structure_changed": None, "reason": "no prior report"}

    cur_ic = current.get("ic_decision", {})
    pri_ic = prior.get("ic_decision", {})

    cur_cost = cur_ic.get("primary_cost_bps", 0) or 0
    pri_cost = pri_ic.get("primary_cost_bps", 0) or 0

    return {
        "structure_changed": cur_ic.get("primary_hedge") != pri_ic.get("primary_hedge"),
        "current_structure": cur_ic.get("primary_hedge"),
        "prior_structure": pri_ic.get("primary_hedge"),
        "carry_bps_current": cur_cost,
        "carry_bps_prior": pri_cost,
        "carry_bps_delta": round(cur_cost - pri_cost, 1),
        "carry_bps_changed": abs(cur_cost - pri_cost) > 10,
        "current_score": cur_ic.get("primary_score"),
        "prior_score": pri_ic.get("primary_score"),
    }


def diff_dte(current: Dict, prior: Optional[Dict]) -> Dict[str, Any]:
    """Compare best DTE selection."""
    cur_dte = _safe_get(current, "best_dte_summary", "best_overall", default={})
    pri_dte = _safe_get(prior, "best_dte_summary", "best_overall", default={}) if prior else {}

    if not cur_dte:
        return {"best_dte_changed": None, "reason": "no DTE data in current report"}

    return {
        "best_dte_changed": cur_dte.get("dte") != pri_dte.get("dte") if pri_dte else None,
        "current_dte": cur_dte.get("dte"),
        "current_expiry": cur_dte.get("expiry"),
        "current_dte_bucket": cur_dte.get("dte_bucket"),
        "current_ann_cost_bps": cur_dte.get("ann_cost_bps"),
        "prior_dte": pri_dte.get("dte"),
        "prior_expiry": pri_dte.get("expiry"),
        "prior_ann_cost_bps": pri_dte.get("ann_cost_bps"),
    }


def diff_greeks(current: Dict, prior: Optional[Dict]) -> Dict[str, Any]:
    """Compare hedge position Greeks."""
    cur_greeks = current.get("structure_greeks", {})
    pri_greeks = prior.get("structure_greeks", {}) if prior else {}

    if not cur_greeks:
        return {"greeks_available": False}

    # Find the primary structure's Greeks
    cur_ic = current.get("ic_decision", {})
    primary_key = cur_ic.get("primary_hedge", "")

    cur_g = None
    for key, val in cur_greeks.items():
        if primary_key and primary_key.lower() in key.lower():
            cur_g = val
            break
    if not cur_g:
        # Take first structure
        cur_g = next(iter(cur_greeks.values()), {})

    hpg = cur_g.get("hedge_position_greeks", {})

    # Prior primary
    pri_g = None
    if pri_greeks:
        pri_ic = prior.get("ic_decision", {}) if prior else {}
        pri_key = pri_ic.get("primary_hedge", "")
        for key, val in pri_greeks.items():
            if pri_key and pri_key.lower() in key.lower():
                pri_g = val
                break
        if not pri_g:
            pri_g = next(iter(pri_greeks.values()), {})

    pri_hpg = pri_g.get("hedge_position_greeks", {}) if pri_g else {}

    return {
        "greeks_available": True,
        "position_delta": hpg.get("position_delta"),
        "position_gamma": hpg.get("position_gamma"),
        "position_vega": hpg.get("position_vega"),
        "theta_per_day_dollars": hpg.get("theta_per_day_dollars"),
        "vega_pnl_per_1vol": hpg.get("vega_pnl_per_1vol_point_dollars"),
        "greeks_shifted": bool(pri_hpg)
        and (
            abs((hpg.get("position_delta", 0) or 0) - (pri_hpg.get("position_delta", 0) or 0)) > 50
            or abs((hpg.get("theta_per_day_dollars", 0) or 0) - (pri_hpg.get("theta_per_day_dollars", 0) or 0)) > 20
        ),
    }


def diff_source(current: Dict, prior: Optional[Dict]) -> Dict[str, Any]:
    """Compare options data source (market vs proxy)."""
    cur_src = current.get("options_source_used", "unknown")
    pri_src = prior.get("options_source_used", "unknown") if prior else "unknown"

    # Check surface sources per ETF
    cur_surface = current.get("surface", {})
    sources = {}
    for etf in ("XBI", "IBB"):
        s = cur_surface.get(etf, {})
        sources[etf] = s.get("data_source", "unknown")

    degraded = any("proxy" in s.lower() or "realized" in s.lower() for s in sources.values())

    return {
        "source_changed": cur_src != pri_src,
        "current_source": cur_src,
        "prior_source": pri_src,
        "source_degraded_to_proxy": degraded,
        "per_etf_sources": sources,
        "source_selection_reason": current.get("source_selection_reason"),
    }


def diff_coverage(current: Dict, prior: Optional[Dict]) -> Dict[str, Any]:
    """Compare backtest coverage and efficacy."""
    cur_bt = current.get("backtest", {})
    pri_bt = prior.get("backtest", {}) if prior else {}

    cur_eff = current.get("shadow_efficacy", {})

    return {
        "historical_months": cur_bt.get("historical_months"),
        "total_months": cur_bt.get("total_months"),
        "backtest_pricing": cur_bt.get("backtest_pricing"),
        "bs_fallback_months": cur_bt.get("bs_fallback_months"),
        "coverage_quality_changed": (
            cur_bt.get("backtest_pricing") != pri_bt.get("backtest_pricing") if pri_bt else None
        ),
        "worst_month_hedged": cur_bt.get("worst_month_hedged"),
        "max_drawdown_hedged": cur_bt.get("max_drawdown_hedged"),
        "efficacy_agrees": cur_eff.get("agree"),
        "efficacy_status": cur_eff.get("status"),
    }


def compute_alert_level(diffs: Dict[str, Dict]) -> str:
    """Determine overall alert level from diffs."""
    verdict = diffs.get("verdict", {})
    structure = diffs.get("structure", {})
    source = diffs.get("source", {})

    if verdict.get("verdict_changed"):
        return "HIGH"
    if structure.get("structure_changed") or source.get("source_degraded_to_proxy"):
        return "MEDIUM"
    if structure.get("carry_bps_changed") or diffs.get("greeks", {}).get("greeks_shifted"):
        return "LOW"
    return "NONE"


def build_bioshort_watch(
    *,
    as_of_date: Optional[str] = None,
    report_dir: Path = HEDGE_REPORT_DIR,
    output_dir: Path = REPO_ROOT / "artifacts" / "bioshort_watch",
) -> Dict[str, Any]:
    """Build bioshort watch artifact by diffing latest vs prior hedge reports."""

    reports = _find_reports(report_dir)
    if not reports:
        return {"error": "no hedge reports found"}

    current = _load_json(reports[0])
    if not current:
        return {"error": f"could not load {reports[0]}"}

    current_date = current.get("as_of_date", "unknown")

    # Find prior report
    prior = None
    prior_date = None
    for rp in reports[1:]:
        p = _load_json(rp)
        if p and p.get("as_of_date") != current_date:
            prior = p
            prior_date = p.get("as_of_date")
            break

    # Load verdict
    verdict_data = _load_json(VERDICT_PATH) or {}

    logger.info("Current report: %s, Prior: %s", current_date, prior_date or "none")

    # Build prior verdict from ic_decision (different field names than BIOSHORT_VERDICT.json)
    prior_verdict_compat = None
    if prior:
        pic = prior.get("ic_decision", {})
        if pic:
            prior_verdict_compat = {
                "verdict": pic.get("policy_action"),
                "confidence": pic.get("confidence"),
                "confidence_score": pic.get("confidence_score"),
                "recommendation": pic.get("primary_hedge"),
            }

    # Build diffs
    diffs = {
        "verdict": diff_verdict(verdict_data, prior_verdict_compat),
        "vehicle": diff_vehicle(current, prior),
        "structure": diff_structure(current, prior),
        "dte": diff_dte(current, prior),
        "greeks": diff_greeks(current, prior),
        "source": diff_source(current, prior),
        "coverage": diff_coverage(current, prior),
    }

    alert_level = compute_alert_level(diffs)

    # Build alert summary
    alerts = []
    if diffs["verdict"].get("verdict_changed"):
        alerts.append(f"VERDICT CHANGED: {diffs['verdict']['prior_verdict']} → {diffs['verdict']['current_verdict']}")
    if diffs["vehicle"].get("vehicle_changed"):
        alerts.append(f"VEHICLE CHANGED: {diffs['vehicle']['prior_vehicle']} → {diffs['vehicle']['current_vehicle']}")
    if diffs["structure"].get("structure_changed"):
        alerts.append(
            f"STRUCTURE CHANGED: {diffs['structure']['prior_structure']} → {diffs['structure']['current_structure']}"
        )
    if diffs["structure"].get("carry_bps_changed"):
        alerts.append(
            f"CARRY MOVED: {diffs['structure']['carry_bps_prior']} → {diffs['structure']['carry_bps_current']} bps"
        )
    if diffs["dte"].get("best_dte_changed"):
        alerts.append(f"DTE CHANGED: {diffs['dte']['prior_dte']} → {diffs['dte']['current_dte']}d")
    if diffs["greeks"].get("greeks_shifted"):
        alerts.append("GREEKS SHIFTED: position delta or theta moved materially")
    if diffs["source"].get("source_degraded_to_proxy"):
        alerts.append(f"SOURCE DEGRADED: using {diffs['source']['current_source']} (proxy/realized vol)")
    if diffs["coverage"].get("coverage_quality_changed"):
        alerts.append(f"BACKTEST PRICING CHANGED: {diffs['coverage']['backtest_pricing']}")

    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_date": current_date,
        "prior_date": prior_date,
        "alert_level": alert_level,
        "n_alerts": len(alerts),
        "alerts": alerts,
        "diffs": diffs,
    }

    # Write outputs
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = as_of_date or current_date

    json_path = output_dir / f"{date_str}_watch.json"
    md_path = output_dir / f"{date_str}_watch.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    md_path.write_text(format_watch_md(result), encoding="utf-8")
    logger.info("Wrote %s", md_path)

    return result


def format_watch_md(d: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# Bioshort Watch — {d['current_date']}")
    lines.append("")
    lines.append(f"**Alert level: {d['alert_level']}** | Prior: {d['prior_date'] or 'none'}")
    lines.append("")

    alerts = d.get("alerts", [])
    if alerts:
        lines.append("## Alerts")
        lines.append("")
        for a in alerts:
            lines.append(f"- {a}")
        lines.append("")
    else:
        lines.append("No material changes since prior report.")
        lines.append("")

    diffs = d.get("diffs", {})

    # Verdict
    v = diffs.get("verdict", {})
    lines.append("## Verdict")
    lines.append("")
    lines.append("| Field | Current | Prior |")
    lines.append("|-------|---------|-------|")
    lines.append(f"| Verdict | {v.get('current_verdict', '—')} | {v.get('prior_verdict', '—')} |")
    lines.append(f"| Confidence | {v.get('current_confidence', '—')} | {v.get('prior_confidence', '—')} |")
    lines.append(f"| Recommendation | {v.get('current_recommendation', '—')} | {v.get('prior_recommendation', '—')} |")
    lines.append("")

    # Structure & cost
    s = diffs.get("structure", {})
    lines.append("## Structure & Cost")
    lines.append("")
    lines.append("| Field | Current | Prior | Delta |")
    lines.append("|-------|---------|-------|-------|")
    lines.append(
        f"| Structure | {s.get('current_structure', '—')} | {s.get('prior_structure', '—')} | {'CHANGED' if s.get('structure_changed') else 'same'} |"
    )
    lines.append(
        f"| Carry (bps) | {s.get('carry_bps_current', '—')} | {s.get('carry_bps_prior', '—')} | {s.get('carry_bps_delta', '—')} |"
    )
    lines.append(f"| Score | {s.get('current_score', '—')} | {s.get('prior_score', '—')} | |")
    lines.append("")

    # Vehicle
    vh = diffs.get("vehicle", {})
    lines.append("## Vehicle")
    lines.append("")
    lines.append("| Field | Current | Prior |")
    lines.append("|-------|---------|-------|")
    lines.append(f"| Vehicle | {vh.get('current_vehicle', '—')} | {vh.get('prior_vehicle', '—')} |")
    lines.append(f"| R-squared | {vh.get('current_r_squared', '—')} | {vh.get('prior_r_squared', '—')} |")
    lines.append(f"| Beta | {vh.get('current_beta', '—')} | {vh.get('prior_beta', '—')} |")
    lines.append("")

    # DTE
    dt = diffs.get("dte", {})
    if dt.get("current_dte") is not None:
        lines.append("## Best DTE")
        lines.append("")
        lines.append("| Field | Current | Prior |")
        lines.append("|-------|---------|-------|")
        lines.append(f"| DTE | {dt.get('current_dte', '—')} | {dt.get('prior_dte', '—')} |")
        lines.append(f"| Expiry | {dt.get('current_expiry', '—')} | {dt.get('prior_expiry', '—')} |")
        lines.append(f"| Bucket | {dt.get('current_dte_bucket', '—')} | |")
        lines.append(
            f"| Ann cost (bps) | {dt.get('current_ann_cost_bps', '—')} | {dt.get('prior_ann_cost_bps', '—')} |"
        )
        lines.append("")

    # Greeks
    g = diffs.get("greeks", {})
    if g.get("greeks_available"):
        lines.append("## Position Greeks")
        lines.append("")
        lines.append("| Greek | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| Delta | {g.get('position_delta', '—')} |")
        lines.append(f"| Gamma | {g.get('position_gamma', '—')} |")
        lines.append(f"| Vega | {g.get('position_vega', '—')} |")
        lines.append(f"| Theta/day ($) | {g.get('theta_per_day_dollars', '—')} |")
        lines.append(f"| Vega P&L/1vol ($) | {g.get('vega_pnl_per_1vol', '—')} |")
        if g.get("greeks_shifted"):
            lines.append("| **SHIFTED** | delta or theta moved materially |")
        lines.append("")

    # Source
    src = diffs.get("source", {})
    lines.append("## Data Source")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Source | {src.get('current_source', '—')} |")
    lines.append(f"| Prior source | {src.get('prior_source', '—')} |")
    lines.append(f"| Degraded to proxy | {'YES' if src.get('source_degraded_to_proxy') else 'no'} |")
    for etf, s in src.get("per_etf_sources", {}).items():
        lines.append(f"| {etf} source | {s} |")
    lines.append("")

    # Coverage
    cov = diffs.get("coverage", {})
    lines.append("## Backtest Coverage")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Historical months | {cov.get('historical_months', '—')} / {cov.get('total_months', '—')} |")
    lines.append(f"| Pricing | {cov.get('backtest_pricing', '—')} |")
    lines.append(f"| BS fallback months | {cov.get('bs_fallback_months', '—')} |")
    lines.append(f"| Worst month (hedged) | {cov.get('worst_month_hedged', '—')} |")
    lines.append(f"| Max DD (hedged) | {cov.get('max_drawdown_hedged', '—')} |")
    lines.append(f"| Efficacy agrees | {cov.get('efficacy_agrees', '—')} |")
    lines.append("")

    lines.append(f"*Generated: {d.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Bioshort watch — hedge monitor")
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--report-dir", type=Path, default=HEDGE_REPORT_DIR)
    args = parser.parse_args()

    result = build_bioshort_watch(as_of_date=args.as_of_date, report_dir=args.report_dir)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)
    logger.info("Alert level: %s, %d alerts", result["alert_level"], result["n_alerts"])


if __name__ == "__main__":
    main()
