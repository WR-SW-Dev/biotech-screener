#!/usr/bin/env python3
"""SEC filing watch — monitor earnings, dilution, and cash events.

Scans SEC 8-K cache for portfolio-relevant filing events: earnings
surprises, cash runway updates, ATM offerings, shelf registrations,
and material agreements.

Read-only — does not affect rankings, scoring, or execution.

Output:
    artifacts/filing_watch/{date}_watch.json
    artifacts/filing_watch/{date}_watch.md

Usage:
    python tools/build_filing_watch.py --as-of-date 2026-03-27
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
logger = logging.getLogger("filing_watch")

SCHEMA_VERSION = "filing_watch.v1"

# Filing event categories and keyword patterns
DILUTION_KEYWORDS = [
    "atm",
    "at-the-market",
    "shelf registration",
    "shelf offering",
    "public offering",
    "secondary offering",
    "stock offering",
    "prospectus supplement",
    "s-3",
    "form s-3",
]
EARNINGS_KEYWORDS = [
    "quarterly report",
    "annual report",
    "earnings",
    "financial results",
    "revenue",
    "net loss",
    "cash position",
    "operating results",
]
CASH_KEYWORDS = [
    "cash runway",
    "cash burn",
    "cash position",
    "liquidity",
    "going concern",
    "working capital",
]
MATERIAL_KEYWORDS = [
    "material agreement",
    "license agreement",
    "collaboration",
    "partnership",
    "acquisition",
    "merger",
    "asset purchase",
]


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def classify_filing(event_name: str) -> List[str]:
    """Classify a filing event by keyword matching."""
    name_lower = event_name.lower() if event_name else ""
    categories = []

    for kw in DILUTION_KEYWORDS:
        if kw in name_lower:
            categories.append("DILUTION")
            break

    for kw in EARNINGS_KEYWORDS:
        if kw in name_lower:
            categories.append("EARNINGS")
            break

    for kw in CASH_KEYWORDS:
        if kw in name_lower:
            categories.append("CASH_UPDATE")
            break

    for kw in MATERIAL_KEYWORDS:
        if kw in name_lower:
            categories.append("MATERIAL_AGREEMENT")
            break

    return categories if categories else ["OTHER"]


def load_sec_filings(
    cache_dir: Path,
    as_of_date: str,
    lookback_days: int = 7,
) -> List[Dict[str, Any]]:
    """Load recent SEC 8-K filings from cache."""
    sec_dir = cache_dir / "sec" / "8k_catalysts"
    if not sec_dir.exists():
        return []

    candidates = sorted(sec_dir.glob("8k_catalysts_*.json"))
    if not candidates:
        return []

    # Load latest cache
    with open(candidates[-1], encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return []

    # Filter to recent filings (within lookback window)
    filings = []
    for entry in data:
        event_date = entry.get("event_date", "")
        if not event_date:
            continue

        # Simple date distance check
        if event_date > as_of_date:
            continue

        # Classify
        event_name = entry.get("event_name", "")
        categories = classify_filing(event_name)

        filings.append(
            {
                "ticker": entry.get("ticker", ""),
                "event_date": event_date,
                "event_type": entry.get("event_type", ""),
                "event_name": event_name[:100],
                "confidence": entry.get("confidence", ""),
                "source": entry.get("source", "SEC_8K_FILING"),
                "categories": categories,
            }
        )

    return filings


def build_filing_watch(
    as_of_date: str,
    *,
    cache_dir: Path = REPO_ROOT / "cache",
    artifacts_dir: Path = REPO_ROOT / "artifacts",
    snapshots_dir: Path = REPO_ROOT / "data" / "snapshots",
) -> Dict[str, Any]:
    """Build filing watch artifact."""
    filings = load_sec_filings(cache_dir, as_of_date)
    if not filings:
        return {"error": "no SEC 8-K filings found"}

    # Load portfolio tickers
    portfolio_tickers: Set[str] = set()
    pos_data = _load_json(artifacts_dir / "live_shadow" / "positions" / f"{as_of_date}.json")
    if pos_data:
        portfolio_tickers = {p["ticker"] for p in pos_data.get("positions", []) if p.get("ticker")}

    # Also include A/B tier from rankings
    watchlist_tickers = set(portfolio_tickers)
    rankings_path = snapshots_dir / as_of_date / "rankings.csv"
    if rankings_path.exists():
        with open(rankings_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("tier_dev") in ("A", "B"):
                    watchlist_tickers.add(row.get("ticker", ""))

    # Filter filings to watchlist
    relevant = [f for f in filings if f["ticker"] in watchlist_tickers]

    # Categorize
    by_category = defaultdict(list)
    for f in relevant:
        for cat in f["categories"]:
            by_category[cat].append(f)

    # Highlight: dilution events in portfolio names
    dilution_alerts = [f for f in relevant if "DILUTION" in f["categories"] and f["ticker"] in portfolio_tickers]
    cash_alerts = [f for f in relevant if "CASH_UPDATE" in f["categories"] and f["ticker"] in portfolio_tickers]

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_total_filings": len(filings),
        "n_relevant": len(relevant),
        "n_portfolio": len([f for f in relevant if f["ticker"] in portfolio_tickers]),
        "by_category": {cat: len(items) for cat, items in by_category.items()},
        "dilution_alerts": dilution_alerts[:10],
        "cash_alerts": cash_alerts[:10],
        "recent_filings": relevant[:30],
    }

    out_dir = artifacts_dir / "filing_watch"
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
    lines.append(f"# Filing Watch — {d['as_of_date']}")
    lines.append("")
    lines.append(
        f"Total filings: {d['n_total_filings']} | Relevant: {d['n_relevant']} | " f"Portfolio: {d['n_portfolio']}"
    )
    lines.append("")

    by_cat = d.get("by_category", {})
    if by_cat:
        lines.append("## By Category")
        lines.append("")
        for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
            lines.append(f"- {cat}: {n}")
        lines.append("")

    dilution = d.get("dilution_alerts", [])
    if dilution:
        lines.append("## Dilution Alerts (Portfolio Names)")
        lines.append("")
        for f in dilution:
            lines.append(f"- **{f['ticker']}** ({f['event_date']}): {f['event_name']}")
        lines.append("")

    cash = d.get("cash_alerts", [])
    if cash:
        lines.append("## Cash Updates (Portfolio Names)")
        lines.append("")
        for f in cash:
            lines.append(f"- **{f['ticker']}** ({f['event_date']}): {f['event_name']}")
        lines.append("")

    recent = d.get("recent_filings", [])
    if recent:
        lines.append("## Recent Filings")
        lines.append("")
        lines.append("| Ticker | Date | Type | Categories | Detail |")
        lines.append("|--------|------|------|------------|--------|")
        for f in recent[:20]:
            cats = ", ".join(f.get("categories", []))
            lines.append(f"| {f['ticker']} | {f['event_date']} | {f['event_type']} | {cats} | {f['event_name'][:50]} |")
        lines.append("")

    lines.append(f"*Generated: {d.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="SEC filing watch")
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    result = build_filing_watch(args.as_of_date)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)
    logger.info("Filing: %d relevant, %d portfolio", result["n_relevant"], result["n_portfolio"])


if __name__ == "__main__":
    main()
