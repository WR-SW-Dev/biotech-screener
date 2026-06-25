#!/usr/bin/env python3
"""Enrich Intraday Mover Watch digest with research-only news context via Firecrawl.

GOVERNANCE: Research-only enrichment. No features extracted for ranker/selector.
No alpha derivation — digests remain read-only intelligence layers.

Usage:
    python tools/enrich_intraday_digest_with_research.py \
        --date 2026-05-27 \
        --digest-file artifacts/intraday_mover_watch/2026-05-27_digest.json

Output:
    artifacts/intraday_mover_watch/2026-05-27_digest_enriched.json
    (same structure + "firecrawl_news_context" array per HIGH-severity move)

Behavior:
    1. Load intraday digest (JSON)
    2. Find all HIGH-severity moves
    3. For each HIGH move, run targeted Firecrawl search on ticker+category keywords
    4. Append search results as enrichment (news URLs + titles)
    5. Write enriched digest (research-only output artifact)

Graceful degradation:
    - If FIRECRAWL_API_KEY not set: skip enrichment, return original digest
    - If search fails for a ticker: continue with other tickers
    - If Firecrawl timeout: continue with partially enriched digest
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.repo_env import load_repo_dotenv  # noqa: E402

load_repo_dotenv(REPO_ROOT)

from tools.firecrawl_research_ingest import FirecrawlResearchAdapter  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class HighMove:
    """HIGH-severity intraday move from digest."""

    ticker: str
    move_type: str  # INTRADAY_ABS_MOVE_UP_HIGH, INTRADAY_ABS_MOVE_DOWN_HIGH, etc.
    magnitude: float  # % move


def load_digest(digest_file: str | Path) -> dict:
    """Load intraday digest JSON."""
    with open(digest_file) as f:
        return json.load(f)


def extract_high_moves(digest: dict) -> list[HighMove]:
    """Extract HIGH-severity moves from digest.

    Supports both formats:
    1. New format: top_absolute_movers / top_relative_movers_vs_xbi with severity field
    2. Legacy format: alerts keyed by date with codes array
    """
    high_moves = []
    seen_tickers = set()

    # Try new format first (Spec 063)
    for move_list_key in ["top_absolute_movers", "top_relative_movers_vs_xbi"]:
        moves = digest.get(move_list_key, [])
        if not isinstance(moves, list):
            continue

        for move in moves:
            ticker = move.get("ticker", "").upper()
            severity = move.get("severity", "").upper()

            if not ticker or severity != "HIGH" or ticker in seen_tickers:
                continue

            seen_tickers.add(ticker)
            move_type = f"INTRADAY_{move_list_key.upper()}_HIGH"
            magnitude = float(
                move.get("stock_abs_move_pct") or move.get("rel_move_vs_xbi_pct") or move.get("move_pct") or 0.0
            )
            high_moves.append(HighMove(ticker=ticker, move_type=move_type, magnitude=magnitude))

    # Fall back to legacy format if available
    if not high_moves:
        alerts = digest.get("alerts", {})
        for date_key, ticker_alerts in alerts.items():
            if not isinstance(ticker_alerts, list):
                continue

            for alert in ticker_alerts:
                ticker = alert.get("ticker", "").upper()
                if not ticker or ticker in seen_tickers:
                    continue

                codes = alert.get("codes", [])
                for code in codes:
                    if "HIGH" in code and ("ABS_MOVE" in code or "REL_MOVE" in code):
                        seen_tickers.add(ticker)
                        move_type = code
                        magnitude = alert.get("magnitude", 0.0)
                        high_moves.append(HighMove(ticker=ticker, move_type=move_type, magnitude=magnitude))
                        break

    return high_moves


def search_news_for_ticker(
    adapter: FirecrawlResearchAdapter, ticker: str, move_type: str, limit: int = 5
) -> list[dict]:
    """Search Firecrawl for news on a specific ticker."""
    # Construct query based on move type
    if "UP" in move_type:
        query = f"{ticker} stock surge clinical trial positive results approval 2026"
    else:
        query = f"{ticker} stock decline setback trial failure news 2026"

    logger.info(f"Searching news for {ticker}: {query}")

    try:
        results = adapter.search(query, limit=limit)
        return [asdict(r) for r in results]
    except Exception as e:
        logger.warning(f"Search failed for {ticker}: {e}")
        return []


def enrich_digest(digest: dict, high_moves: list[HighMove], api_key: Optional[str] = None) -> dict:
    """Enrich digest with Firecrawl news context for HIGH-severity moves."""
    if not api_key:
        api_key = os.getenv("FIRECRAWL_API_KEY")

    if not api_key:
        logger.info("FIRECRAWL_API_KEY not set — returning original digest")
        return digest

    # Initialize adapter
    try:
        adapter = FirecrawlResearchAdapter(api_key=api_key)
    except Exception as e:
        logger.error(f"Failed to initialize Firecrawl: {e}")
        return digest

    # Enrich alerts with Firecrawl news context
    enriched_digest = digest.copy()
    firecrawl_context = {}

    for move in high_moves:
        ticker = move.ticker
        if ticker in firecrawl_context:
            continue  # Already searched this ticker

        news_results = search_news_for_ticker(adapter, ticker, move.move_type, limit=5)
        if news_results:
            firecrawl_context[ticker] = {
                "ticker": ticker,
                "move_type": move.move_type,
                "magnitude_pct": move.magnitude,
                "enriched_at": datetime.now(timezone.utc).isoformat(),
                "governance": "research_only",
                "news_sources": news_results,
            }
            logger.info(f"Enriched {ticker}: {len(news_results)} news sources found")

    # Add enrichment to digest under _firecrawl_context
    if firecrawl_context:
        enriched_digest["_firecrawl_context"] = {
            "enrichment_timestamp": datetime.now(timezone.utc).isoformat(),
            "governance": "research_only_no_alpha",
            "high_moves_enriched": firecrawl_context,
        }

    return enriched_digest


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Enrich intraday digest with research-only news context",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="As-of date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--digest-file",
        help="Path to digest JSON (default: artifacts/intraday_mover_watch/{date}_digest.json)",
    )
    parser.add_argument(
        "--out",
        help="Output path (default: artifacts/intraday_mover_watch/{date}_digest_enriched.json)",
    )
    parser.add_argument(
        "--api-key",
        help="Firecrawl API key (defaults to FIRECRAWL_API_KEY env var)",
    )

    args = parser.parse_args()

    # Resolve paths
    repo_root = Path(__file__).resolve().parent.parent
    digest_file = Path(args.digest_file or f"artifacts/intraday_mover_watch/{args.date}_digest.json")
    if not digest_file.is_absolute():
        digest_file = repo_root / digest_file

    out_file = Path(args.out or f"artifacts/intraday_mover_watch/{args.date}_digest_enriched.json")
    if not out_file.is_absolute():
        out_file = repo_root / out_file

    # Load digest
    if not digest_file.exists():
        logger.error(f"Digest file not found: {digest_file}")
        return 1

    try:
        digest = load_digest(digest_file)
    except Exception as e:
        logger.error(f"Failed to load digest: {e}")
        return 1

    # Extract HIGH moves
    high_moves = extract_high_moves(digest)
    logger.info(f"Found {len(high_moves)} HIGH-severity moves")

    if not high_moves:
        logger.info("No HIGH-severity moves to enrich")
        return 0

    # Enrich digest
    enriched = enrich_digest(digest, high_moves, api_key=args.api_key)

    # Write enriched digest
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(enriched, f, indent=2)

    logger.info(f"Enriched digest written → {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
