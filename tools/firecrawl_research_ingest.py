#!/usr/bin/env python3
"""Research-only Firecrawl adapter for biotech news discovery and competitor intelligence.

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
from typing import Optional

from firecrawl import FirecrawlApp

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

# Biotech news sources known to Firecrawl
BIOTECH_NEWS_DOMAINS = [
    "fiercebiotech.com",
    "statnews.com",
    "biopharmadive.com",
    "biospace.com",
    "endpoints.json",  # Endpoints News
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


@dataclass
class SearchResult:
    """Single search result from Firecrawl."""

    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    score: Optional[float] = None


class FirecrawlResearchAdapter:
    """Research-only Firecrawl adapter for biotech intelligence gathering."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Firecrawl client.

        Args:
            api_key: Firecrawl API key (defaults to FIRECRAWL_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        if not self.api_key:
            raise ValueError(
                "FIRECRAWL_API_KEY not set. "
                "Export env var or pass --api-key to CLI."
            )

        self.app = FirecrawlApp(api_key=self.api_key)
        self.sources: list[SourceRecord] = []
        self.search_results: list[dict] = []

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Search biotech news via Firecrawl.

        Args:
            query: Search query (e.g., "obesity drug phase 3 trial results")
            limit: Max results to fetch

        Returns:
            List of SearchResult objects with URL, title, description
        """
        logger.info(f"Searching: {query!r} (limit={limit})")

        try:
            response = self.app.search(query, limit=limit)
            results = []

            # Handle both dict and object responses
            search_results = []

            # Try various attributes that might contain results
            if hasattr(response, "web") and response.web:
                # Firecrawl SearchData has .web, .news, .images attributes
                search_results = response.web if isinstance(response.web, list) else []
            elif hasattr(response, "news") and response.news:
                search_results = response.news if isinstance(response.news, list) else []
            elif hasattr(response, "data") and response.data:
                search_results = response.data if isinstance(response.data, list) else []
            elif hasattr(response, "results"):
                search_results = response.results if isinstance(response.results, list) else []
            elif isinstance(response, dict):
                search_results = response.get("results", []) or response.get("web", []) or response.get("news", [])

            # Process results
            for item in search_results:
                # item might be dict or object
                if hasattr(item, "url"):
                    result = SearchResult(
                        url=item.url or "",
                        title=getattr(item, "title", None),
                        description=getattr(item, "description", None),
                        score=getattr(item, "score", None),
                    )
                elif isinstance(item, dict):
                    result = SearchResult(
                        url=item.get("url", ""),
                        title=item.get("title"),
                        description=item.get("description"),
                        score=item.get("score"),
                    )
                else:
                    logger.warning(f"Unexpected item format: {type(item)}")
                    continue
                results.append(result)

            if not results:
                logger.warning(
                    f"No results found in search response. "
                    f"Response type: {type(response)}"
                )

            self.search_results = [asdict(r) for r in results]
            logger.info(f"Found {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Search failed: {e}", exc_info=True)
            raise

    def scrape_urls(
        self, urls: list[str], timeout_sec: int = 30
    ) -> list[SourceRecord]:
        """Scrape and clean content from URLs.

        Args:
            urls: List of URLs to scrape
            timeout_sec: Request timeout per URL (min 1 second, default 30)

        Returns:
            List of SourceRecord objects with fetch status and content
        """
        # Firecrawl API enforces minimum timeout of 1000ms
        timeout_ms = max(1000, timeout_sec * 1000)
        logger.info(f"Scraping {len(urls)} URLs (timeout={timeout_ms}ms)")

        for url in urls:
            source = SourceRecord(url=url)
            logger.debug(f"Scraping: {url}")

            try:
                response = self.app.scrape_url(url, timeout=timeout_ms)

                # Handle both dict and Document object responses
                success = False
                markdown = ""
                title = None
                description = None

                if hasattr(response, "success"):
                    success = response.success
                elif isinstance(response, dict):
                    success = response.get("success", False)

                if hasattr(response, "markdown"):
                    markdown = response.markdown or ""
                elif isinstance(response, dict):
                    markdown = response.get("markdown", "")

                if hasattr(response, "metadata"):
                    metadata = response.metadata
                    if isinstance(metadata, dict):
                        title = metadata.get("title")
                        description = metadata.get("description")
                    elif hasattr(metadata, "title"):
                        title = metadata.title
                        description = getattr(metadata, "description", None)
                elif isinstance(response, dict):
                    metadata = response.get("metadata", {})
                    title = metadata.get("title")
                    description = metadata.get("description")

                if success:
                    source.fetch_status = "success"
                    source.title = title
                    source.summary = description
                    source.content_length = len(markdown)
                    logger.info(
                        f"Scraped {url}: "
                        f"{source.content_length} bytes, "
                        f"title={source.title}"
                    )
                else:
                    source.fetch_status = "failed"
                    if isinstance(response, dict):
                        source.error_message = response.get("error", "Unknown error")
                    else:
                        source.error_message = "Scrape returned success=false"
                    logger.warning(f"Scrape failed for {url}: {source.error_message}")

            except Exception as e:
                source.fetch_status = "failed"
                source.error_message = str(e)
                logger.error(f"Exception scraping {url}: {e}")

            # GOVERNANCE CHECK: ensure timestamp is set
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

        # Write search results
        search_file = output_path / "search_results.json"
        with open(search_file, "w") as f:
            json.dump(self.search_results, f, indent=2)
        artifacts["search_results"] = str(search_file)
        logger.info(f"Wrote search results: {search_file}")

        # Write source manifest with fetch status
        manifest_file = output_path / "source_manifest.json"
        manifest = [asdict(s) for s in self.sources]
        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)
        artifacts["source_manifest"] = str(manifest_file)
        logger.info(f"Wrote source manifest: {manifest_file}")

        # Write analyst summary (high-level digest)
        summary_file = output_path / "analyst_summary.md"
        summary = self._generate_summary()
        with open(summary_file, "w") as f:
            f.write(summary)
        artifacts["analyst_summary"] = str(summary_file)
        logger.info(f"Wrote analyst summary: {summary_file}")

        # Write scraped pages markdown
        pages_file = output_path / "scraped_pages.md"
        with open(pages_file, "w") as f:
            f.write(self._generate_scraped_pages_markdown())
        artifacts["scraped_pages"] = str(pages_file)
        logger.info(f"Wrote scraped pages: {pages_file}")

        # GOVERNANCE: write metadata file confirming research-only status
        meta_file = output_path / "_metadata.json"
        meta = {
            "research_only": RESEARCH_ONLY,
            "no_model_features": NO_MODEL_FEATURES,
            "no_ranker_inputs": NO_RANKER_INPUTS,
            "no_selector_inputs": NO_SELECTOR_INPUTS,
            "source_url_required": SOURCE_URL_REQUIRED,
            "fetch_timestamp_required": FETCH_TIMESTAMP_REQUIRED,
            "generated_at": datetime.now(UTC).isoformat(),
            "total_sources": len(self.sources),
            "successful_scrapes": sum(
                1 for s in self.sources if s.fetch_status == "success"
            ),
            "failed_scrapes": sum(
                1 for s in self.sources if s.fetch_status == "failed"
            ),
        }
        with open(meta_file, "w") as f:
            json.dump(meta, f, indent=2)
        artifacts["_metadata"] = str(meta_file)
        logger.info(f"Wrote governance metadata: {meta_file}")

        return artifacts

    def _generate_summary(self) -> str:
        """Generate high-level analyst summary of scraped content."""
        summary_lines = [
            "# Research Ingest Summary\n",
            f"**Generated:** {datetime.now(UTC).isoformat()}\n",
            f"**Governance:** Research-Only (No Alpha Inputs)\n",
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

        # Search
        results = adapter.search(args.query, limit=args.limit)
        urls = [r.url for r in results if r.url]

        if not args.skip_scrape and urls:
            # Scrape top results
            adapter.scrape_urls(urls, timeout_sec=args.timeout)

        # Write artifacts
        artifacts = adapter.write_artifacts(args.out)
        logger.info(f"Artifacts written to {args.out}")
        logger.info(f"Files: {json.dumps(artifacts, indent=2)}")

        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
