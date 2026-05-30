#!/usr/bin/env python3
"""Research-only Firecrawl adapter for biotech news discovery and competitor intelligence.

Uses Firecrawl Python SDK v2 (`firecrawl-py` >= 4.28, `Firecrawl` client).

GOVERNANCE CONSTRAINTS (enforced):
  - RESEARCH_ONLY: True (no ranker/selector/scoring inputs)
  - NO_MODEL_FEATURES: True
  - NO_RANKER_INPUTS: True
  - NO_SELECTOR_INPUTS: True
  - SOURCE_URL_REQUIRED: True
  - FETCH_TIMESTAMP_REQUIRED: True

Usage:
    python tools/firecrawl_research_ingest.py \
        --query "biotech clinical trial results today" \
        --limit 20 \
        --out artifacts/research/firecrawl/$(date +%F)

Output structure:
    artifacts/research/firecrawl/YYYY-MM-DD/
      ├── search_results.json      (raw Firecrawl search output)
      ├── scraped_pages.md         (cleaned markdown content)
      ├── source_manifest.json     (URLs, timestamps, fetch status)
      └── analyst_summary.md       (high-level digest)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from firecrawl import Firecrawl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Governance constraints
RESEARCH_ONLY = True
NO_MODEL_FEATURES = True
NO_RANKER_INPUTS = True
NO_SELECTOR_INPUTS = True
SOURCE_URL_REQUIRED = True
FETCH_TIMESTAMP_REQUIRED = True

# Biotech news sources (optional domain hints for operators)
BIOTECH_NEWS_DOMAINS = [
    "fiercebiotech.com",
    "statnews.com",
    "biopharmadive.com",
    "biospace.com",
    "endpoints.news",
    "xconomy.com",
    "news.crunchbase.com",
    "prnewswire.com",
    "businesswire.com",
]


@dataclass
class SourceRecord:
    """Metadata for a single scraped source."""

    url: str
    title: Optional[str] = None
    summary: Optional[str] = None
    fetch_timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    fetch_status: str = "pending"  # pending, success, failed
    error_message: Optional[str] = None
    content_length: int = 0
    search_query: str = ""
    markdown: str = ""


@dataclass
class SearchResult:
    """Single search result from Firecrawl."""

    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    score: Optional[float] = None


def _iter_search_hits(search_data: Any) -> Iterable[Any]:
    """Yield hits from v2 SearchData (.web, .news, .images)."""
    if search_data is None:
        return
    for attr in ("web", "news", "images"):
        items = getattr(search_data, attr, None) or []
        yield from items


def _search_hit_to_result(item: Any) -> Optional[SearchResult]:
    """Normalize SearchResultWeb/Document/dict into SearchResult."""
    if item is None:
        return None

    url = getattr(item, "url", None)
    title = getattr(item, "title", None)
    description = getattr(item, "description", None)
    score = getattr(item, "score", None)

    metadata = getattr(item, "metadata", None)
    if metadata is not None:
        url = url or getattr(metadata, "url", None) or getattr(metadata, "source_url", None)
        title = title or getattr(metadata, "title", None)
        description = description or getattr(metadata, "description", None)

    if isinstance(item, dict):
        url = url or item.get("url")
        title = title or item.get("title")
        description = description or item.get("description")
        score = score if score is not None else item.get("score")
        meta = item.get("metadata") or {}
        if isinstance(meta, dict):
            url = url or meta.get("url") or meta.get("source_url")
            title = title or meta.get("title")
            description = description or meta.get("description")

    if not url:
        logger.warning("Search hit missing URL: %s", type(item))
        return None

    return SearchResult(
        url=str(url),
        title=title,
        description=description,
        score=score,
    )


def _document_from_scrape(doc: Any) -> tuple[Optional[str], Optional[str], str, Optional[str]]:
    """Extract title, description, markdown, error from v2 Document."""
    markdown = getattr(doc, "markdown", None) or ""
    if isinstance(doc, dict):
        markdown = doc.get("markdown", "") or ""

    metadata = getattr(doc, "metadata", None)
    if metadata is None and isinstance(doc, dict):
        metadata = doc.get("metadata")

    title = None
    description = None
    error = None
    if metadata is not None:
        title = getattr(metadata, "title", None)
        description = getattr(metadata, "description", None)
        error = getattr(metadata, "error", None)
        if isinstance(metadata, dict):
            title = title or metadata.get("title")
            description = description or metadata.get("description")
            error = error or metadata.get("error")

    warning = getattr(doc, "warning", None)
    if warning and not error and isinstance(warning, str):
        error = warning

    if not error and not markdown.strip():
        error = "Empty markdown response"

    return title, description, markdown, error


class FirecrawlResearchAdapter:
    """Research-only Firecrawl adapter for biotech intelligence gathering."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Firecrawl v2 client.

        Args:
            api_key: Firecrawl API key (defaults to FIRECRAWL_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        if not self.api_key:
            raise ValueError(
                "FIRECRAWL_API_KEY not set. "
                "Export env var or pass --api-key to CLI."
            )

        self.client = Firecrawl(api_key=self.api_key)
        self.sources: list[SourceRecord] = []
        self.search_results: list[dict] = []

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Search biotech news via Firecrawl v2.

        Args:
            query: Search query (e.g., "obesity drug phase 3 trial results")
            limit: Max results to fetch

        Returns:
            List of SearchResult objects with URL, title, description
        """
        logger.info("Searching: %r (limit=%s)", query, limit)

        try:
            response = self.client.search(query, limit=limit)
            results: list[SearchResult] = []
            seen_urls: set[str] = set()

            for item in _iter_search_hits(response):
                result = _search_hit_to_result(item)
                if result is None or result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                results.append(result)

            if not results:
                logger.warning(
                    "No results in search response (type=%s)",
                    type(response).__name__,
                )

            self.search_results = [asdict(r) for r in results]
            logger.info("Found %s results", len(results))
            return results

        except Exception as e:
            logger.error("Search failed: %s", e, exc_info=True)
            raise

    def scrape_urls(
        self, urls: list[str], timeout_sec: int = 30
    ) -> list[SourceRecord]:
        """Scrape and clean content from URLs via Firecrawl v2.

        Args:
            urls: List of URLs to scrape
            timeout_sec: Request timeout per URL (min 1 second, default 30)

        Returns:
            List of SourceRecord objects with fetch status and content
        """
        # Firecrawl API enforces minimum timeout of 1000ms
        timeout_ms = max(1000, timeout_sec * 1000)
        logger.info("Scraping %s URLs (timeout=%sms)", len(urls), timeout_ms)

        for url in urls:
            source = SourceRecord(url=url)
            logger.debug("Scraping: %s", url)

            try:
                doc = self.client.scrape(
                    url,
                    formats=["markdown"],
                    timeout=timeout_ms,
                )
                title, description, markdown, error = _document_from_scrape(doc)

                if error:
                    source.fetch_status = "failed"
                    source.error_message = error
                    logger.warning("Scrape failed for %s: %s", url, error)
                else:
                    source.fetch_status = "success"
                    source.title = title
                    source.summary = description
                    source.markdown = markdown
                    source.content_length = len(markdown)
                    logger.info(
                        "Scraped %s: %s bytes, title=%s",
                        url,
                        source.content_length,
                        source.title,
                    )

            except Exception as e:
                source.fetch_status = "failed"
                source.error_message = str(e)
                logger.error("Exception scraping %s: %s", url, e)

            if not source.fetch_timestamp:
                source.fetch_timestamp = datetime.now(UTC).isoformat()

            self.sources.append(source)

        return self.sources

    def write_artifacts(self, output_dir: str | Path) -> dict:
        """Write research artifacts to disk.

        Args:
            output_dir: Directory to write artifacts
                        (typically artifacts/research/firecrawl/YYYY-MM-DD/)

        Returns:
            Dict with paths of written files
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        artifacts = {}

        search_file = output_path / "search_results.json"
        with open(search_file, "w", encoding="utf-8") as f:
            json.dump(self.search_results, f, indent=2)
        artifacts["search_results"] = str(search_file)
        logger.info("Wrote search results: %s", search_file)

        manifest_file = output_path / "source_manifest.json"
        manifest = [asdict(s) for s in self.sources]
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        artifacts["source_manifest"] = str(manifest_file)
        logger.info("Wrote source manifest: %s", manifest_file)

        summary_file = output_path / "analyst_summary.md"
        summary = self._generate_summary()
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(summary)
        artifacts["analyst_summary"] = str(summary_file)
        logger.info("Wrote analyst summary: %s", summary_file)

        pages_file = output_path / "scraped_pages.md"
        with open(pages_file, "w", encoding="utf-8") as f:
            f.write(self._generate_scraped_pages_markdown())
        artifacts["scraped_pages"] = str(pages_file)
        logger.info("Wrote scraped pages: %s", pages_file)

        meta_file = output_path / "_metadata.json"
        meta = {
            "research_only": RESEARCH_ONLY,
            "no_model_features": NO_MODEL_FEATURES,
            "no_ranker_inputs": NO_RANKER_INPUTS,
            "no_selector_inputs": NO_SELECTOR_INPUTS,
            "source_url_required": SOURCE_URL_REQUIRED,
            "fetch_timestamp_required": FETCH_TIMESTAMP_REQUIRED,
            "firecrawl_sdk": "firecrawl-py>=4.28",
            "generated_at": datetime.now(UTC).isoformat(),
            "total_sources": len(self.sources),
            "successful_scrapes": sum(
                1 for s in self.sources if s.fetch_status == "success"
            ),
            "failed_scrapes": sum(
                1 for s in self.sources if s.fetch_status == "failed"
            ),
        }
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        artifacts["_metadata"] = str(meta_file)
        logger.info("Wrote governance metadata: %s", meta_file)

        return artifacts

    def _generate_summary(self) -> str:
        """Generate high-level analyst summary of scraped content."""
        summary_lines = [
            "# Research Ingest Summary\n",
            f"**Generated:** {datetime.now(UTC).isoformat()}\n",
            "**Governance:** Research-Only (No Alpha Inputs)\n",
            "## Fetch Status\n",
        ]

        successful = [s for s in self.sources if s.fetch_status == "success"]
        failed = [s for s in self.sources if s.fetch_status == "failed"]

        summary_lines.append(f"- **Successful:** {len(successful)}/{len(self.sources)}\n")
        summary_lines.append(f"- **Failed:** {len(failed)}/{len(self.sources)}\n")

        if successful:
            summary_lines.append("\n## Scraped Sources\n")
            for source in successful:
                summary_lines.append(
                    f"- [{source.title or 'Untitled'}]({source.url})\n"
                )
                if source.summary:
                    summary_lines.append(f"  > {source.summary}\n")

        if failed:
            summary_lines.append("\n## Failed Scrapes\n")
            for source in failed:
                summary_lines.append(
                    f"- {source.url}: {source.error_message or 'Unknown error'}\n"
                )

        return "".join(summary_lines)

    def _generate_scraped_pages_markdown(self) -> str:
        """Generate markdown document of all scraped pages."""
        lines = [
            "# Scraped Pages\n",
            f"Generated: {datetime.now(UTC).isoformat()}\n",
            "Status: Research-only — no features extracted, no scoring applied\n\n",
        ]

        for source in self.sources:
            if source.fetch_status != "success":
                lines.append(f"## ❌ {source.url}\n")
                lines.append(f"Error: {source.error_message}\n\n")
                continue

            lines.append(f"## ✓ {source.title or 'Untitled'}\n")
            lines.append(f"**URL:** {source.url}\n")
            lines.append(f"**Fetched:** {source.fetch_timestamp}\n\n")
            if source.markdown:
                lines.append(source.markdown)
                lines.append("\n\n")
            lines.append("---\n\n")

        return "".join(lines)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Research-only Firecrawl adapter for biotech news discovery",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Search query (e.g., 'biotech clinical trial results today')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max search results to fetch (default: 20)",
    )
    parser.add_argument(
        "--out",
        required=True,
        help=(
            "Output directory (typically: "
            "artifacts/research/firecrawl/$(date +%%F))"
        ),
    )
    parser.add_argument(
        "--api-key",
        help="Firecrawl API key (defaults to FIRECRAWL_API_KEY env var)",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Search only, don't scrape (debug mode)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Scrape timeout per URL in seconds (default: 30)",
    )

    args = parser.parse_args()

    try:
        adapter = FirecrawlResearchAdapter(api_key=args.api_key)

        results = adapter.search(args.query, limit=args.limit)
        urls = [r.url for r in results if r.url]

        if not args.skip_scrape and urls:
            adapter.scrape_urls(urls, timeout_sec=args.timeout)

        artifacts = adapter.write_artifacts(args.out)
        logger.info("Artifacts written to %s", args.out)
        logger.info("Files: %s", json.dumps(artifacts, indent=2))

        return 0

    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
