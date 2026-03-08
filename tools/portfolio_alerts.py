#!/usr/bin/env python3
"""Portfolio Alerts — check portfolio-level risk conditions, write alerts JSON, optionally fire webhook.

Alert types:
    NEW_GAP_RISK_HIGH   — New gap-risk HIGH not in prior snapshot
    HARD_GATE_FAIL      — run_manifest.json overall_status == FAIL
    CONCENTRATION_RISK  — Any name > max_name_pct weight
    LARGE_DRAWDOWN      — Period P&L < drawdown threshold
    HIGH_TURNOVER       — Turnover > turnover threshold

Usage:
    python3 tools/portfolio_alerts.py --as-of-date 2026-03-08
    python3 tools/portfolio_alerts.py --as-of-date 2026-03-08 --webhook-url https://hooks.slack.com/...
    python3 tools/portfolio_alerts.py --as-of-date 2026-03-08 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SHADOW_ROOT = PROJECT_ROOT / "artifacts" / "live_shadow"
SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "snapshots"

SCHEMA_VERSION = "portfolio_alerts.v1"

DEFAULT_THRESHOLDS = {
    "drawdown_pct": -3.0,
    "max_name_pct": 5.0,
    "turnover_pct": 30.0,
}

LEVEL_EMOJI = {
    "FAIL": ":red_circle:",
    "WARN": ":large_yellow_circle:",
    "OK": ":large_green_circle:",
}
LEVEL_COLOR = {
    "FAIL": "#d73a49",
    "WARN": "#e36209",
    "OK": "#22863a",
}


def _load_positions(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    with open(path) as f:
        return json.load(f)


def _find_prior_positions_path(as_of_date: str, positions_dir: Path) -> Optional[Path]:
    if not positions_dir.is_dir():
        return None
    candidates = [p for p in positions_dir.iterdir() if p.suffix == ".json" and p.stem < as_of_date]
    return max(candidates, key=lambda p: p.stem) if candidates else None


def check_gap_risk(
    positions_path: Path,
    positions_dir: Path,
) -> List[Dict[str, Any]]:
    """Check for NEW gap-risk HIGH positions vs prior snapshot."""
    alerts: List[Dict[str, Any]] = []
    doc = _load_positions(positions_path)
    current = doc.get("positions", [])
    as_of_date = doc.get("as_of_date", positions_path.stem)

    current_high = {p["ticker"] for p in current if p.get("gap_risk") == "HIGH"}
    if not current_high:
        return alerts

    prior_path = _find_prior_positions_path(as_of_date, positions_dir)
    prior_high: set[str] = set()
    if prior_path:
        prior_doc = _load_positions(prior_path)
        prior_high = {p["ticker"] for p in prior_doc.get("positions", []) if p.get("gap_risk") == "HIGH"}

    new_high = current_high - prior_high
    if new_high:
        alerts.append(
            {
                "type": "NEW_GAP_RISK_HIGH",
                "severity": "WARN",
                "detail": f"New gap-risk HIGH: {', '.join(sorted(new_high))}",
                "tickers": sorted(new_high),
            }
        )
    return alerts


def check_gate_fail(snap_dir: Path) -> List[Dict[str, Any]]:
    """Check for hard gate FAIL in run_manifest.json."""
    alerts: List[Dict[str, Any]] = []
    manifest_path = snap_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return alerts
    with open(manifest_path) as f:
        manifest = json.load(f)
    if manifest.get("overall_status") == "FAIL":
        fail_names = []
        for g in manifest.get("gates", []):
            if isinstance(g, dict) and g.get("status") == "FAIL":
                fail_names.append(g.get("name", "?"))
        alerts.append(
            {
                "type": "HARD_GATE_FAIL",
                "severity": "FAIL",
                "detail": f"Gate FAIL: {', '.join(fail_names) if fail_names else 'unknown'}",
                "tickers": [],
            }
        )
    return alerts


def check_concentration(
    positions_path: Path,
    max_name_pct: float = 5.0,
) -> List[Dict[str, Any]]:
    """Alert if any single position exceeds max_name_pct of total allocation."""
    alerts: List[Dict[str, Any]] = []
    doc = _load_positions(positions_path)
    positions = doc.get("positions", [])
    if not positions:
        return alerts

    total = sum(p.get("target_dollars", 0) for p in positions)
    if total <= 0:
        return alerts

    concentrated = []
    for p in positions:
        wt = p.get("target_dollars", 0) / total * 100
        if wt > max_name_pct:
            concentrated.append(p["ticker"])

    if concentrated:
        alerts.append(
            {
                "type": "CONCENTRATION_RISK",
                "severity": "WARN",
                "detail": f"{len(concentrated)} name(s) > {max_name_pct}% weight: {', '.join(sorted(concentrated))}",
                "tickers": sorted(concentrated),
            }
        )
    return alerts


def check_drawdown(
    perf_csv: Path,
    threshold_pct: float = -3.0,
) -> List[Dict[str, Any]]:
    """Alert if latest period P&L < threshold."""
    import csv

    alerts: List[Dict[str, Any]] = []
    if not perf_csv.is_file():
        return alerts

    with open(perf_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return alerts

    last = rows[-1]
    try:
        pnl_pct = float(last.get("pnl_pct", "0"))
    except (ValueError, TypeError):
        return alerts

    if pnl_pct < threshold_pct:
        alerts.append(
            {
                "type": "LARGE_DRAWDOWN",
                "severity": "WARN",
                "detail": f"Period P&L {pnl_pct:+.2f}% < {threshold_pct}% threshold",
                "tickers": [],
            }
        )
    return alerts


def check_turnover(
    perf_csv: Path,
    threshold_pct: float = 30.0,
) -> List[Dict[str, Any]]:
    """Alert if latest turnover exceeds threshold."""
    import csv

    alerts: List[Dict[str, Any]] = []
    if not perf_csv.is_file():
        return alerts

    with open(perf_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return alerts

    last = rows[-1]
    try:
        turnover = float(last.get("turnover", "0")) * 100
    except (ValueError, TypeError):
        return alerts

    if turnover > threshold_pct:
        alerts.append(
            {
                "type": "HIGH_TURNOVER",
                "severity": "WARN",
                "detail": f"Turnover {turnover:.1f}% > {threshold_pct}% threshold",
                "tickers": [],
            }
        )
    return alerts


def check_portfolio_alerts(
    as_of_date: str,
    *,
    shadow_root: Path = SHADOW_ROOT,
    snapshots_root: Path = SNAPSHOTS_ROOT,
    thresholds: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Run all alert checks. Returns list of alert dicts."""
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    positions_dir = shadow_root / "positions"
    positions_path = positions_dir / f"{as_of_date}.json"
    perf_csv = shadow_root / "performance.csv"
    snap_dir = snapshots_root / as_of_date

    alerts: List[Dict[str, Any]] = []

    if positions_path.is_file():
        alerts.extend(check_gap_risk(positions_path, positions_dir))
        alerts.extend(check_concentration(positions_path, t["max_name_pct"]))

    if snap_dir.is_dir():
        alerts.extend(check_gate_fail(snap_dir))

    alerts.extend(check_drawdown(perf_csv, t["drawdown_pct"]))
    alerts.extend(check_turnover(perf_csv, t["turnover_pct"]))

    return alerts


def write_alerts_json(
    alerts: List[Dict[str, Any]],
    as_of_date: str,
    out_path: Path,
) -> Path:
    """Write alerts JSON sidecar."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "alert_count": len(alerts),
        "alerts": alerts,
    }
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=2)
    return out_path


def fire_webhook_if_needed(
    alerts: List[Dict[str, Any]],
    as_of_date: str,
    webhook_url: str,
    *,
    dry_run: bool = False,
) -> None:
    """POST alert summary to webhook if any FAIL or WARN alerts."""
    if not alerts:
        return

    max_severity = "WARN"
    for a in alerts:
        if a.get("severity") == "FAIL":
            max_severity = "FAIL"
            break

    emoji = LEVEL_EMOJI.get(max_severity, ":white_circle:")
    color = LEVEL_COLOR.get(max_severity, "#888888")

    title = f"{emoji} Portfolio Alert {max_severity} — {as_of_date}"
    details = "\n".join(f"[{a['severity']}] {a['type']}: {a['detail']}" for a in alerts)

    payload = {
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": f"{len(alerts)} alert(s)",
                "fields": [{"title": "Details", "value": details, "short": False}],
                "footer": "biotech-screener-portfolio",
                "ts": int(datetime.now(timezone.utc).timestamp()),
            }
        ]
    }

    if dry_run:
        print("[portfolio_alerts] DRY RUN — would POST:")
        print(json.dumps(payload, indent=2))
        return

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                body = resp.read().decode("utf-8")
                print(f"[portfolio_alerts] Webhook returned HTTP {resp.status}: {body}", file=sys.stderr)
        print(f"[portfolio_alerts] Webhook posted: {max_severity} ({len(alerts)} alerts)")
    except Exception as exc:
        print(f"[portfolio_alerts] WARNING: webhook POST failed: {exc}", file=sys.stderr)


def run_portfolio_alerts(
    as_of_date: str,
    *,
    shadow_root: Path = SHADOW_ROOT,
    snapshots_root: Path = SNAPSHOTS_ROOT,
    thresholds: Optional[Dict[str, float]] = None,
    webhook_url: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Main entry: run checks, write JSON, optionally POST webhook."""
    alerts = check_portfolio_alerts(
        as_of_date,
        shadow_root=shadow_root,
        snapshots_root=snapshots_root,
        thresholds=thresholds,
    )

    alerts_dir = shadow_root / "alerts"
    alert_path = write_alerts_json(alerts, as_of_date, alerts_dir / f"{as_of_date}.json")

    if webhook_url and alerts:
        fire_webhook_if_needed(alerts, as_of_date, webhook_url, dry_run=dry_run)

    return {
        "alert_count": len(alerts),
        "alert_path": str(alert_path),
        "alerts": alerts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Portfolio risk alerts")
    parser.add_argument("--as-of-date", required=True, help="Check date (YYYY-MM-DD)")
    parser.add_argument("--webhook-url", type=str, help="Slack webhook URL")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without POSTing")
    args = parser.parse_args()

    result = run_portfolio_alerts(
        args.as_of_date,
        webhook_url=args.webhook_url,
        dry_run=args.dry_run,
    )

    n = result["alert_count"]
    if n > 0:
        print(f"Portfolio alerts: {n} alert(s)")
        for a in result["alerts"]:
            print(f"  [{a['severity']}] {a['type']}: {a['detail']}")
    else:
        print("Portfolio alerts: none")
    print(f"Output: {result['alert_path']}")


if __name__ == "__main__":
    main()
