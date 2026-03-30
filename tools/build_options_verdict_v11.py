#!/usr/bin/env python3
"""Options Monitor v1.1 — Daily artifact builder (Spec 040).

Reads today's rankings.csv (which already has ovf11_* fields computed by
run_screen.py), enriches with state transitions from prior day, and writes
the standalone v1.1 verdict artifact.

Output:
    artifacts/options_verdict/{date}_verdict_v11.json
    artifacts/options_verdict/{date}_verdict_v11.md

Wired into run_daily_production.py as a non-blocking post-screen step.

Usage:
    python tools/build_options_verdict_v11.py --as-of-date 2026-03-31
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("options_verdict_v11")

SCHEMA_VERSION = "options_verdict_v11.v1"


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def build_verdict_v11(
    as_of_date: str,
    *,
    snapshots_dir: Path = REPO_ROOT / "data" / "snapshots",
    artifacts_dir: Path = REPO_ROOT / "artifacts",
) -> Dict[str, Any]:
    """Build v1.1 verdict artifact from today's rankings.csv."""
    rankings_path = snapshots_dir / as_of_date / "rankings.csv"
    if not rankings_path.exists():
        return {"error": f"rankings.csv not found for {as_of_date}"}

    # Load rankings with v1.1 fields
    rows: List[Dict[str, str]] = []
    with open(rankings_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker"):
                rows.append(row)

    # Filter to tickers with v1.1 verdict != NONE
    active = []
    for row in rows:
        verdict = row.get("ovf11_monitor_verdict", "NONE")
        if verdict in ("HIGH", "WATCH"):
            active.append(row)

    # Load prior state for transitions
    out_dir = artifacts_dir / "options_verdict"
    out_dir.mkdir(parents=True, exist_ok=True)

    prior_dates = sorted(
        f.stem.replace("_verdict_v11", "")
        for f in out_dir.glob("*_verdict_v11.json")
        if f.stem.replace("_verdict_v11", "") < as_of_date
    )
    prior_tickers: Dict[str, Dict] = {}
    if prior_dates:
        prior_data = _load_json(out_dir / f"{prior_dates[-1]}_verdict_v11.json")
        if prior_data:
            for v in prior_data.get("verdicts", []):
                if v.get("state") != "RESOLVED" and v.get("ticker"):
                    prior_tickers[v["ticker"]] = v

    # Build verdicts with state transitions
    verdicts: List[Dict[str, Any]] = []

    for row in active:
        ticker = row["ticker"]
        was_active = ticker in prior_tickers
        state = "ONGOING" if was_active else "NEW"

        verdicts.append({
            "ticker": ticker,
            "tier": row.get("tier_dev", ""),
            "actionable_rank": row.get("actionable_rank", ""),
            "catalyst_days": row.get("catalyst_days", ""),
            "catalyst_family": row.get("catalyst_family", ""),
            "is_hard_catalyst": row.get("is_hard_catalyst", ""),
            "state": state,
            # v1.1 factor scores
            "om11_ep": row.get("ovf11_ep", ""),
            "om11_sr": row.get("ovf11_sr", ""),
            "om11_sk": row.get("ovf11_sk", ""),
            "om11_dv": row.get("ovf11_dv", ""),
            "om11_quality": row.get("ovf11_quality", ""),
            "om11_confidence": row.get("ovf11_confidence", ""),
            "om11_score_final": row.get("ovf11_score", ""),
            "om11_primary_factor": row.get("ovf11_primary_factor", ""),
            "om11_monitor_verdict": row.get("ovf11_monitor_verdict", ""),
            "om11_trade_bias": row.get("ovf11_trade_bias", ""),
            "om11_event_window_flag": row.get("ovf11_event_window_flag", ""),
            "om11_catalyst_class": row.get("ovf11_catalyst_class", ""),
        })

    # Add resolved tickers
    active_tickers = {r["ticker"] for r in active}
    for ticker, prev in prior_tickers.items():
        if ticker not in active_tickers:
            verdicts.append({
                "ticker": ticker,
                "state": "RESOLVED",
                "prior_verdict": prev.get("om11_monitor_verdict", ""),
                "prior_score": prev.get("om11_score_final", ""),
                "tier": prev.get("tier", ""),
            })

    # Sort: HIGH first, WATCH, RESOLVED
    sev_order = {"HIGH": 0, "WATCH": 1, "RESOLVED": 2, "": 3}
    verdicts.sort(key=lambda v: (
        sev_order.get(v.get("om11_monitor_verdict", v.get("state", "")), 9),
        v["ticker"],
    ))

    n_high = sum(1 for v in verdicts if v.get("om11_monitor_verdict") == "HIGH")
    n_watch = sum(1 for v in verdicts if v.get("om11_monitor_verdict") == "WATCH")
    n_resolved = sum(1 for v in verdicts if v.get("state") == "RESOLVED")
    n_new = sum(1 for v in verdicts if v.get("state") == "NEW")

    artifact = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_active": len(active),
        "n_high": n_high,
        "n_watch": n_watch,
        "n_resolved": n_resolved,
        "n_new": n_new,
        "n_universe": len(rows),
        "verdicts": verdicts,
    }

    # Write JSON
    json_path = out_dir / f"{as_of_date}_verdict_v11.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, sort_keys=True, default=str)
    logger.info("Wrote %s", json_path)

    # Write markdown
    md_path = out_dir / f"{as_of_date}_verdict_v11.md"
    md_path.write_text(_format_md(artifact), encoding="utf-8")
    logger.info("Wrote %s", md_path)

    return artifact


def _format_md(d: Dict[str, Any]) -> str:
    lines = [f"# Options Monitor v1.1 — {d['as_of_date']}", ""]
    lines.append(
        f"**{d['n_active']} active** (H={d['n_high']} W={d['n_watch']}) | "
        f"{d['n_new']} new | {d['n_resolved']} resolved"
    )
    lines.append("")

    verdicts = d.get("verdicts", [])

    for sev in ("HIGH", "WATCH"):
        sev_v = [v for v in verdicts if v.get("om11_monitor_verdict") == sev]
        if not sev_v:
            continue
        lines.append(f"## {sev}")
        lines.append("")
        lines.append("| Ticker | Tier | Cat | State | EP | SR | SK | DV | Score | Trade | Primary |")
        lines.append("|--------|------|-----|-------|----|----|----|----|-------|-------|---------|")
        for v in sev_v:
            cat = v.get("catalyst_days", "-")
            ep = v.get("om11_ep", "-")[:5]
            sr = v.get("om11_sr", "-")[:5]
            sk = v.get("om11_sk", "-")[:5]
            dv = v.get("om11_dv", "-")[:5]
            score = v.get("om11_score_final", "-")[:5]
            trade = v.get("om11_trade_bias", "-")
            primary = v.get("om11_primary_factor", "-")
            lines.append(
                f"| {v['ticker']} | {v.get('tier', '?')} | {cat} | {v['state']} | "
                f"{ep} | {sr} | {sk} | {dv} | {score} | {trade} | {primary} |"
            )
        lines.append("")

    resolved = [v for v in verdicts if v.get("state") == "RESOLVED"]
    if resolved:
        lines.append(f"## RESOLVED ({len(resolved)})")
        lines.append("")
        lines.append(", ".join(v["ticker"] for v in resolved))
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Options Monitor v1.1 daily artifact builder")
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--snapshots-dir", type=Path, default=REPO_ROOT / "data" / "snapshots")
    parser.add_argument("--artifacts-dir", type=Path, default=REPO_ROOT / "artifacts")
    args = parser.parse_args()

    result = build_verdict_v11(
        args.as_of_date,
        snapshots_dir=args.snapshots_dir,
        artifacts_dir=args.artifacts_dir,
    )

    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)

    logger.info(
        "v1.1 Verdict: %d active (H=%d W=%d), %d new, %d resolved",
        result["n_active"], result["n_high"], result["n_watch"],
        result["n_new"], result["n_resolved"],
    )


if __name__ == "__main__":
    main()
