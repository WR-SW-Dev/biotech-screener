#!/usr/bin/env python3
"""Regulatory calendar watch — monitor FDA events for universe tickers.

Consolidates FDA data from existing caches (adcom calendar, regulatory dates,
PDUFA manual, SEC 8-K FDA filings) into a single regulatory timeline.
Diffs against prior day to detect new/changed/resolved regulatory events.

Read-only — does not affect rankings, scoring, or execution.

Output:
    artifacts/regulatory_watch/{date}_watch.json
    artifacts/regulatory_watch/{date}_watch.md

Usage:
    python tools/build_regulatory_watch.py --as-of-date 2026-03-27
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("regulatory_watch")

SCHEMA_VERSION = "regulatory_watch.v1"

FDA_EVENT_TYPES = frozenset(
    {
        "FDA_PDUFA_DATE",
        "FDA_ADCOM",
        "FDA_CRL",
        "FDA_RTF",
        "FDA_APPROVAL",
        "FDA_SUBMISSION",
        "FDA_WARNING_LETTER",
        "FDA_DECISION",
        "FDA_DESIGNATION",
    }
)


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _sf(val: Any) -> float:
    import math

    if val is None or val == "":
        return math.nan
    try:
        return float(val)
    except (ValueError, TypeError):
        return math.nan


def load_regulatory_events(
    as_of_date: str,
    snapshots_dir: Path,
    cache_dir: Path,
    production_dir: Path,
) -> List[Dict[str, Any]]:
    """Consolidate all FDA regulatory events from multiple sources."""
    events = []

    # 1. Rankings.csv — regulatory_days and regulatory_event_type
    rankings_path = snapshots_dir / as_of_date / "rankings.csv"
    if rankings_path.exists():
        with open(rankings_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                reg_days = row.get("regulatory_days", "")
                reg_type = row.get("regulatory_event_type", "")
                if reg_days and reg_type:
                    events.append(
                        {
                            "ticker": row.get("ticker", ""),
                            "event_type": reg_type,
                            "days_to_event": int(_sf(reg_days)) if reg_days else None,
                            "confidence": row.get("regulatory_confidence", ""),
                            "source": "rankings",
                        }
                    )

    # 2. PDUFA manual calendar
    pdufa_path = production_dir / "pdufa_dates.json"
    pdufa_data = _load_json(pdufa_path)
    if pdufa_data:
        entries = pdufa_data if isinstance(pdufa_data, list) else pdufa_data.get("dates", [])
        for entry in entries:
            ticker = entry.get("ticker", "")
            event_date = entry.get("date", entry.get("pdufa_date", ""))
            if ticker and event_date and event_date >= as_of_date:
                events.append(
                    {
                        "ticker": ticker,
                        "event_type": "FDA_PDUFA_DATE",
                        "event_date": event_date,
                        "source": "pdufa_manual",
                        "drug": entry.get("drug", entry.get("name", "")),
                        "indication": entry.get("indication", ""),
                    }
                )

    # 3. FDA AdCom calendar cache
    adcom_candidates = (
        sorted(p for p in (cache_dir / "fda").glob("adcom_calendar_*.json")) if (cache_dir / "fda").exists() else []
    )
    if adcom_candidates:
        adcom_data = _load_json(adcom_candidates[-1])
        if adcom_data and isinstance(adcom_data, list):
            for entry in adcom_data:
                ticker = entry.get("ticker", "")
                if ticker:
                    events.append(
                        {
                            "ticker": ticker,
                            "event_type": "FDA_ADCOM",
                            "event_date": entry.get("date", entry.get("meeting_date", "")),
                            "source": "fda_adcom_cache",
                            "detail": entry.get("topic", entry.get("description", "")),
                        }
                    )

    # 4. SEC 8-K FDA events
    sec_candidates = (
        sorted(p for p in (cache_dir / "sec" / "8k_catalysts").glob("8k_catalysts_*.json"))
        if (cache_dir / "sec" / "8k_catalysts").exists()
        else []
    )
    if sec_candidates:
        sec_data = _load_json(sec_candidates[-1])
        if sec_data and isinstance(sec_data, list):
            for entry in sec_data:
                et = entry.get("event_type", "")
                if et in FDA_EVENT_TYPES:
                    events.append(
                        {
                            "ticker": entry.get("ticker", ""),
                            "event_type": et,
                            "event_date": entry.get("event_date", ""),
                            "source": "sec_8k",
                            "confidence": entry.get("confidence", ""),
                            "detail": entry.get("event_name", "")[:80],
                        }
                    )

    return events


def build_regulatory_watch(
    as_of_date: str,
    *,
    snapshots_dir: Path = REPO_ROOT / "data" / "snapshots",
    cache_dir: Path = REPO_ROOT / "cache",
    production_dir: Path = REPO_ROOT / "production_data",
    artifacts_dir: Path = REPO_ROOT / "artifacts",
) -> Dict[str, Any]:
    """Build regulatory calendar watch artifact."""
    events = load_regulatory_events(as_of_date, snapshots_dir, cache_dir, production_dir)

    # Deduplicate by ticker + event_type (keep highest-confidence source)
    seen = {}
    for e in events:
        key = (e["ticker"], e["event_type"])
        if key not in seen:
            seen[key] = e
        elif e.get("confidence") == "HIGH" and seen[key].get("confidence") != "HIGH":
            seen[key] = e

    deduped = sorted(seen.values(), key=lambda e: (e.get("days_to_event") or 999, e["ticker"]))

    # Load portfolio for relevance filtering
    portfolio_tickers: Set[str] = set()
    pos_data = _load_json(artifacts_dir / "live_shadow" / "positions" / f"{as_of_date}.json")
    if pos_data:
        portfolio_tickers = {p["ticker"] for p in pos_data.get("positions", []) if p.get("ticker")}

    # Split into near-term (<=90d) and portfolio-relevant
    near_term = [e for e in deduped if e.get("days_to_event") is not None and e["days_to_event"] <= 90]
    portfolio_events = [e for e in deduped if e["ticker"] in portfolio_tickers]

    # By type
    by_type = defaultdict(int)
    for e in deduped:
        by_type[e["event_type"]] += 1

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_events_total": len(deduped),
        "n_near_term_90d": len(near_term),
        "n_portfolio_events": len(portfolio_events),
        "by_type": dict(by_type),
        "near_term": near_term[:30],
        "portfolio_events": portfolio_events[:30],
    }

    out_dir = artifacts_dir / "regulatory_watch"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{as_of_date}_watch.json"
    md_path = out_dir / f"{as_of_date}_watch.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    md_path.write_text(format_watch_md(result), encoding="utf-8")
    logger.info("Wrote %s", md_path)

    result["_json_path"] = str(json_path)
    return result


def format_watch_md(d: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# Regulatory Watch — {d['as_of_date']}")
    lines.append("")
    lines.append(
        f"Total: {d['n_events_total']} | Near-term (<=90d): {d['n_near_term_90d']} | "
        f"Portfolio: {d['n_portfolio_events']}"
    )
    lines.append("")

    by_type = d.get("by_type", {})
    if by_type:
        lines.append("## By Type")
        lines.append("")
        for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"- {t}: {c}")
        lines.append("")

    near = d.get("near_term", [])
    if near:
        lines.append("## Near-Term (<=90d)")
        lines.append("")
        lines.append("| Ticker | Type | Days | Confidence | Source | Detail |")
        lines.append("|--------|------|------|------------|--------|--------|")
        for e in near:
            days = e.get("days_to_event", "?")
            detail = e.get("detail", e.get("drug", e.get("indication", "")))[:40]
            lines.append(
                f"| {e['ticker']} | {e['event_type']} | {days} | "
                f"{e.get('confidence', '')} | {e.get('source', '')} | {detail} |"
            )
        lines.append("")

    lines.append(f"*Generated: {d.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Regulatory calendar watch")
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    result = build_regulatory_watch(args.as_of_date)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)
    logger.info("Regulatory: %d events, %d near-term", result["n_events_total"], result["n_near_term_90d"])


if __name__ == "__main__":
    main()
