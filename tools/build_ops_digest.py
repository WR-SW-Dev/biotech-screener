#!/usr/bin/env python3
"""Post-run operations digest — single-screen actionable summary.

Reads today's snapshot + shadow portfolio artifacts, diffs against the
prior snapshot, and produces a concise digest highlighting only items
that need human attention.

Designed as the core skill for an ops agent: run after production,
summarize new issues, refuse to modify active rulesets.

Output:
    artifacts/ops_digest/{date}_digest.json   — structured digest
    artifacts/ops_digest/{date}_digest.md     — human-readable summary

Usage:
    python tools/build_ops_digest.py --as-of-date 2026-03-23
    python tools/build_ops_digest.py  # auto-detect latest snapshot

Programmatic:
    from tools.build_ops_digest import build_ops_digest
    digest = build_ops_digest("2026-03-23")
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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("ops_digest")

SCHEMA_VERSION = "ops_digest.v1"
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
SHADOW_DIR = REPO_ROOT / "artifacts" / "live_shadow"
READINESS_DIR = REPO_ROOT / "artifacts" / "readiness"
OUT_DIR = REPO_ROOT / "artifacts" / "ops_digest"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _find_prior_snapshot(snapshots_dir: Path, current_date: str) -> Optional[str]:
    """Find the most recent snapshot before current_date."""
    candidates = []
    for d in snapshots_dir.iterdir():
        name = d.name
        if d.is_dir() and len(name) == 10 and name < current_date and "__" not in name:
            try:
                # Validate date format
                datetime.strptime(name, "%Y-%m-%d")
                candidates.append(name)
            except ValueError:
                continue
    return max(candidates) if candidates else None


def _find_latest_snapshot(snapshots_dir: Path) -> Optional[str]:
    """Find the most recent snapshot."""
    candidates = []
    for d in snapshots_dir.iterdir():
        name = d.name
        if d.is_dir() and len(name) == 10 and "__" not in name:
            try:
                datetime.strptime(name, "%Y-%m-%d")
                candidates.append(name)
            except ValueError:
                continue
    return max(candidates) if candidates else None


def _severity(status: str) -> int:
    return {"FAIL": 3, "WARN": 2, "INFO": 1, "PASS": 0}.get(status, 0)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_health_section(snap_dir: Path) -> Dict[str, Any]:
    """Phase-2 health + collection health + exposure checks."""
    phase2 = _load_json(snap_dir / "phase2_health.json") or {}
    collection = _load_json(snap_dir / "data_collection_health.json") or {}
    exposure = _load_json(snap_dir / "health_exposure_metrics.json") or {}

    # Collect all non-PASS items
    alerts: List[Dict[str, str]] = []

    # Phase2 health
    p2_status = phase2.get("status", "?")
    if p2_status != "OK":
        for reason in phase2.get("reasons", []):
            alerts.append({"source": "phase2_health", "level": "WARN", "detail": reason})

    # Collection health flags
    for flag in collection.get("flags", []):
        level = "WARN"
        if "FAIL" in flag.upper():
            level = "FAIL"
        elif "measured on" in flag.lower():
            level = "INFO"
        alerts.append({"source": "collection_health", "level": level, "detail": flag})

    # Exposure checks
    for name, check in (exposure.get("checks") or {}).items():
        if check.get("status", "PASS") != "PASS":
            alerts.append(
                {
                    "source": "exposure",
                    "level": check["status"],
                    "detail": f"{name}: {check.get('value', '?')} (threshold: {check.get('warn_threshold', '?')})",
                }
            )

    return {
        "phase2_status": p2_status,
        "collection_status": collection.get("status", "?"),
        "exposure_alerts": len([a for a in alerts if a["level"] in ("WARN", "FAIL")]),
        "alerts": sorted(alerts, key=lambda a: -_severity(a["level"])),
    }


def _build_coverage_section(snap_dir: Path) -> Dict[str, Any]:
    """Coverage quality snapshot."""
    cq = _load_json(snap_dir / "coverage_quality.json") or {}
    elig = _load_json(snap_dir / "eligibility_summary.json") or {}

    cat_cov = cq.get("catalyst_coverage", {})
    comp_cov = cq.get("component_coverage", {})
    reg_sec = cq.get("regulatory_secondary", {})

    return {
        "n_total": elig.get("n_total", 0),
        "n_eligible": elig.get("n_eligible", 0),
        "n_ineligible": elig.get("n_ineligible", 0),
        "catalyst_pct": cat_cov.get("specific_days_pct", 0),
        "sponsor_pct": comp_cov.get("sponsor_pct", 0),
        "options_pct": comp_cov.get("options_pct", 0),
        "regulatory_secondary_pct": reg_sec.get("coverage_pct", 0),
    }


def _build_delta_section(snap_dir: Path, prior_date: Optional[str]) -> Dict[str, Any]:
    """Turnover and tier changes vs prior."""
    delta = _load_json(snap_dir / "phase2_run_delta_details.json")
    if not delta:
        return {"available": False, "prior_date": prior_date}

    pt = delta.get("portfolio_turnover", {})
    return {
        "available": True,
        "prior_date": delta.get("prior", {}).get("date", prior_date),
        "entrants": pt.get("entrants", []),
        "exits": pt.get("exits", []),
        "name_turnover_pct": pt.get("name_turnover_pct", 0),
        "weight_l1_delta": pt.get("weight_l1_delta", 0),
        "tier_current": delta.get("tier_distribution", {}).get("current", {}),
        "tier_prior": delta.get("tier_distribution", {}).get("prior", {}),
        "top_catalysts": delta.get("top_catalysts", []),
    }


def _build_performance_section() -> Dict[str, Any]:
    """Shadow portfolio performance summary."""
    metrics = _load_json(SHADOW_DIR / "portfolio_metrics.json")
    if not metrics:
        return {"available": False}

    return {
        "available": True,
        "n_periods": metrics.get("n_periods", 0),
        "cumulative_return_pct": metrics.get("cumulative_return_pct", 0),
        "cumulative_excess_pct": metrics.get("cumulative_excess_pct", 0),
        "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
        "sharpe_ratio": metrics.get("sharpe_ratio", 0),
        "win_rate": metrics.get("win_rate", 0),
        "total_pnl_usd": metrics.get("total_pnl_usd", 0),
        "best_period": metrics.get("best_period", {}),
        "worst_period": metrics.get("worst_period", {}),
        "sleeve_attribution": metrics.get("sleeve_attribution", {}),
    }


def _build_readiness_section(as_of_date: str) -> Dict[str, Any]:
    """Latest readiness scorecard."""
    sc = _load_json(READINESS_DIR / f"scorecard_{as_of_date}.json")
    if not sc:
        # Try to find the latest scorecard
        candidates = sorted(READINESS_DIR.glob("scorecard_*.json"))
        if candidates:
            sc = _load_json(candidates[-1])
    if not sc:
        return {"available": False}

    checks_summary = {}
    warn_checks = []
    fail_checks = []
    for check in sc.get("checks", []):
        name = check.get("name", "?")
        status = check.get("status", "?")
        checks_summary[name] = status
        if status == "WARN":
            warn_checks.append(f"{name}: {check.get('detail', check.get('value', ''))}")
        elif status == "FAIL":
            fail_checks.append(f"{name}: {check.get('detail', check.get('value', ''))}")

    return {
        "available": True,
        "verdict": sc.get("verdict", "?"),
        "checks": checks_summary,
        "warn_checks": warn_checks,
        "fail_checks": fail_checks,
        "n_perf_rows": sc.get("context", {}).get("n_performance_rows", 0),
    }


def _build_nearest_catalysts(snap_dir: Path, n: int = 10) -> List[Dict[str, Any]]:
    """Extract nearest catalysts from delta details."""
    delta = _load_json(snap_dir / "phase2_run_delta_details.json")
    if not delta:
        return []
    tc = delta.get("top_catalysts", {})
    if isinstance(tc, dict):
        tc = tc.get("current", [])
    return tc[:n]


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_ops_digest(
    as_of_date: str,
    *,
    snapshots_dir: Path = SNAPSHOT_DIR,
    shadow_dir: Path = SHADOW_DIR,
    readiness_dir: Path = READINESS_DIR,
) -> Dict[str, Any]:
    """Build the unified operations digest.

    Returns structured dict with all sections.
    """
    snap_dir = snapshots_dir / as_of_date
    if not snap_dir.exists():
        return {"error": f"No snapshot for {as_of_date}"}

    prior_date = _find_prior_snapshot(snapshots_dir, as_of_date)

    health = _build_health_section(snap_dir)
    coverage = _build_coverage_section(snap_dir)
    delta = _build_delta_section(snap_dir, prior_date)
    performance = _build_performance_section()
    readiness = _build_readiness_section(as_of_date)
    catalysts = _build_nearest_catalysts(snap_dir)

    # Compute overall attention level
    n_fails = len([a for a in health["alerts"] if a["level"] == "FAIL"])
    n_warns = len([a for a in health["alerts"] if a["level"] == "WARN"])
    readiness_verdict = readiness.get("verdict", "?") if readiness.get("available") else "?"

    if n_fails > 0 or readiness_verdict == "HOLD":
        attention = "ACTION_REQUIRED"
    elif n_warns > 0 or readiness_verdict == "REVIEW":
        attention = "REVIEW"
    else:
        attention = "CLEAR"

    # Collect action items
    action_items: List[str] = []
    for alert in health["alerts"]:
        if alert["level"] in ("FAIL", "WARN"):
            action_items.append(f"[{alert['source']}] {alert['detail']}")
    for item in readiness.get("fail_checks", []):
        action_items.append(f"[readiness FAIL] {item}")
    for item in readiness.get("warn_checks", []):
        action_items.append(f"[readiness WARN] {item}")

    # Load ruleset info from phase2_health (has the ID) + metadata
    p2_metrics = (health.get("_raw_phase2") or {}).get("metrics", {})
    if not p2_metrics:
        p2_raw = _load_json(snap_dir / "phase2_health.json") or {}
        p2_metrics = p2_raw.get("metrics", {})
    ruleset_id = p2_metrics.get("ruleset_id", "?")
    meta = _load_json(snap_dir / "metadata.json") or {}
    ruleset_version = meta.get("decision_engine_version", meta.get("engine_version", "?"))

    return {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "prior_date": prior_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attention": attention,
        "action_items": action_items,
        "ruleset": {"id": ruleset_id, "version": ruleset_version},
        "health": health,
        "coverage": coverage,
        "delta": delta,
        "performance": performance,
        "readiness": readiness,
        "nearest_catalysts": catalysts,
    }


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def format_digest_md(d: Dict[str, Any]) -> str:
    """Render the digest as a concise markdown briefing."""
    lines: List[str] = []

    attention = d.get("attention", "?")
    icon = {"CLEAR": "CLEAR", "REVIEW": "REVIEW", "ACTION_REQUIRED": "ACTION REQUIRED"}
    lines.append(f"# Ops Digest — {d['as_of_date']}")
    lines.append("")
    lines.append(f"**Status: {icon.get(attention, attention)}**  ")
    lines.append(f"Ruleset: `{d['ruleset']['id']}` ({d['ruleset']['version']})  ")
    lines.append(f"Prior: {d.get('prior_date', 'none')}  ")
    lines.append(f"Generated: {d.get('generated_at', '')}")
    lines.append("")

    # Action items
    action_items = d.get("action_items", [])
    if action_items:
        lines.append("## Action Items")
        lines.append("")
        for item in action_items:
            lines.append(f"- {item}")
        lines.append("")
    else:
        lines.append("## No action items")
        lines.append("")

    # Health
    h = d.get("health", {})
    lines.append("## Health")
    lines.append("")
    lines.append("| Gate | Status |")
    lines.append("|------|--------|")
    lines.append(f"| Phase-2 | {h.get('phase2_status', '?')} |")
    lines.append(f"| Collection | {h.get('collection_status', '?')} |")
    lines.append(f"| Exposure alerts | {h.get('exposure_alerts', 0)} |")
    lines.append("")

    # Coverage
    c = d.get("coverage", {})
    lines.append("## Coverage")
    lines.append("")
    lines.append(
        f"| Metric | Value |\n|--------|-------|\n"
        f"| Universe | {c.get('n_eligible', 0)}/{c.get('n_total', 0)} eligible |\n"
        f"| Catalyst | {c.get('catalyst_pct', 0):.1f}% |\n"
        f"| Sponsor | {c.get('sponsor_pct', 0):.1f}% |\n"
        f"| Options | {c.get('options_pct', 0):.1f}% |\n"
        f"| Regulatory (secondary) | {c.get('regulatory_secondary_pct', 0):.1f}% |"
    )
    lines.append("")

    # Delta
    delta = d.get("delta", {})
    if delta.get("available"):
        lines.append("## Delta vs Prior")
        lines.append("")
        entrants = delta.get("entrants", [])
        exits = delta.get("exits", [])
        if entrants or exits:
            lines.append(f"- Entrants ({len(entrants)}): {', '.join(entrants) if entrants else 'none'}")
            lines.append(f"- Exits ({len(exits)}): {', '.join(exits) if exits else 'none'}")
            lines.append(f"- Turnover: {delta.get('name_turnover_pct', 0):.1f}%")
        else:
            lines.append("No portfolio changes.")
        lines.append("")

    # Performance
    perf = d.get("performance", {})
    if perf.get("available"):
        lines.append("## Shadow Performance")
        lines.append("")
        lines.append(
            f"| Metric | Value |\n|--------|-------|\n"
            f"| Cumulative | {perf.get('cumulative_return_pct', 0):+.2f}% |\n"
            f"| Excess vs XBI | {perf.get('cumulative_excess_pct', 0):+.2f}% |\n"
            f"| Max DD | {perf.get('max_drawdown_pct', 0):.2f}% |\n"
            f"| Sharpe | {perf.get('sharpe_ratio', 0):.3f} |\n"
            f"| Win rate | {perf.get('win_rate', 0):.0%} |\n"
            f"| PnL | ${perf.get('total_pnl_usd', 0):,.0f} |\n"
            f"| Periods | {perf.get('n_periods', 0)} |"
        )
        lines.append("")

        sleeve = perf.get("sleeve_attribution", {})
        if sleeve:
            lines.append("Sleeve attribution:")
            for bucket, pnl in sleeve.items():
                lines.append(f"  {bucket}: ${pnl:+,.0f}")
            lines.append("")

    # Readiness
    rd = d.get("readiness", {})
    if rd.get("available"):
        lines.append("## Readiness")
        lines.append("")
        lines.append(f"**Verdict: {rd.get('verdict', '?')}** ({rd.get('n_perf_rows', 0)} perf rows)")
        lines.append("")
        checks = rd.get("checks", {})
        if checks:
            lines.append("| Check | Status |")
            lines.append("|-------|--------|")
            for name, status in checks.items():
                lines.append(f"| {name} | {status} |")
            lines.append("")

    # Nearest catalysts
    cats = d.get("nearest_catalysts", [])
    if cats:
        lines.append("## Nearest Catalysts")
        lines.append("")
        lines.append("| Ticker | Days | Tier |")
        lines.append("|--------|------|------|")
        for cat in cats[:10]:
            t = cat.get("ticker", "?")
            days = cat.get("catalyst_days", cat.get("days", "?"))
            tier = cat.get("tier_dev", cat.get("tier", "?"))
            lines.append(f"| {t} | {days} | {tier} |")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_ops_digest(
    digest: Dict[str, Any],
    out_dir: Path = OUT_DIR,
) -> Dict[str, str]:
    """Write JSON + MD digest files. Returns paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    as_of = digest["as_of_date"]

    json_path = out_dir / f"{as_of}_digest.json"
    md_path = out_dir / f"{as_of}_digest.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(digest, f, indent=2, default=str)

    md_content = format_digest_md(digest)
    md_path.write_text(md_content, encoding="utf-8")

    return {"json_path": str(json_path), "md_path": str(md_path)}


# ---------------------------------------------------------------------------
# Programmatic entry point (for daily pipeline)
# ---------------------------------------------------------------------------


def run_ops_digest(as_of_date: str) -> Dict[str, Any]:
    """Build and write the ops digest. Returns digest + paths."""
    digest = build_ops_digest(as_of_date)
    if "error" in digest:
        return digest
    paths = write_ops_digest(digest)
    digest["_paths"] = paths
    return digest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Build post-run operations digest")
    parser.add_argument(
        "--as-of-date",
        default=None,
        help="Snapshot date (YYYY-MM-DD). Default: latest snapshot.",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=SNAPSHOT_DIR,
    )
    parser.add_argument("--stdout", action="store_true", help="Print markdown to stdout")
    args = parser.parse_args()

    as_of = args.as_of_date or _find_latest_snapshot(args.snapshot_dir)
    if not as_of:
        print("No snapshots found.", file=sys.stderr)
        sys.exit(1)

    digest = build_ops_digest(as_of, snapshots_dir=args.snapshot_dir)
    if "error" in digest:
        print(f"Error: {digest['error']}", file=sys.stderr)
        sys.exit(1)

    paths = write_ops_digest(digest)
    print(f"Digest: {paths['md_path']}")

    if args.stdout:
        print()
        print(format_digest_md(digest))


if __name__ == "__main__":
    main()
