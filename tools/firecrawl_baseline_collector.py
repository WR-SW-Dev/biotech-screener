#!/usr/bin/env python3
"""Firecrawl baseline metrics collector — observe-only instrumentation.

Wraps firecrawl_research_ingest.py to capture execution metrics without modifying behavior.
Logs to skills_logger_v2 and generates baseline metrics for future comparison.

Metrics collected:
- Query, limit, timeout configuration
- Number of search results found
- Number of URLs successfully scraped
- Scrape success rate (successful / total URLs)
- Execution latency (total, search phase, scrape phase)
- Error patterns (API errors, timeouts, network failures)
- Output artifact sizes (search results, markdown, manifest)

Baseline usage:
    python3 tools/firecrawl_baseline_collector.py \
        --query "biotech news" \
        --limit 20 \
        --out artifacts/research/firecrawl/2026-06-05
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Import skills logger
sys.path.insert(0, str(Path(__file__).parent))
try:
    from skills_logger_v2 import SkillExecutionLoggerV2

    SKILLS_LOGGER = SkillExecutionLoggerV2()
except Exception:
    SKILLS_LOGGER = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO_ROOT / "artifacts" / "firecrawl_baseline"
BASELINE_DIR.mkdir(parents=True, exist_ok=True)


def collect_baseline_metrics(output_dir: Path) -> Dict[str, Any]:
    """Collect baseline metrics from firecrawl artifacts."""
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return {}

    metrics = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
    }

    # Search results
    search_file = output_dir / "search_results.json"
    if search_file.exists():
        try:
            search_data = json.loads(search_file.read_text())
            metrics["search_results_found"] = len(search_data.get("urls", []))
            metrics["search_results_file_size"] = search_file.stat().st_size
        except Exception as e:
            logger.warning("Failed to read search results: %s", e)
            metrics["search_results_found"] = 0

    # Source manifest (scrape results)
    manifest_file = output_dir / "source_manifest.json"
    if manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text())
            sources = manifest.get("sources", [])
            metrics["urls_attempted"] = len(sources)
            metrics["urls_succeeded"] = sum(1 for s in sources if s.get("fetch_status") == "success")
            metrics["urls_failed"] = sum(1 for s in sources if s.get("fetch_status") == "failed")
            metrics["scrape_success_rate"] = (
                metrics["urls_succeeded"] / max(1, metrics["urls_attempted"]) if metrics["urls_attempted"] > 0 else 0
            )

            # Error patterns
            errors = {}
            for source in sources:
                if source.get("fetch_status") == "failed":
                    error_msg = source.get("error_message", "unknown")
                    errors[error_msg] = errors.get(error_msg, 0) + 1
            if errors:
                metrics["error_patterns"] = errors

            metrics["manifest_file_size"] = manifest_file.stat().st_size
        except Exception as e:
            logger.warning("Failed to read manifest: %s", e)

    # Scraped content
    content_file = output_dir / "scraped_pages.md"
    if content_file.exists():
        try:
            metrics["content_file_size"] = content_file.stat().st_size
            metrics["content_line_count"] = len(content_file.read_text().split("\n"))
        except Exception as e:
            logger.warning("Failed to read content: %s", e)

    return metrics


def run_firecrawl_ingest(
    query: str,
    limit: int,
    out: str,
    api_key: Optional[str] = None,
    skip_scrape: bool = False,
    timeout: int = 30,
) -> tuple[int, float]:
    """Run firecrawl_research_ingest.py and return exit code + latency."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "firecrawl_research_ingest.py"),
        "--query",
        query,
        "--limit",
        str(limit),
        "--out",
        out,
        "--timeout",
        str(timeout),
    ]

    if skip_scrape:
        cmd.append("--skip-scrape")

    if api_key:
        cmd.extend(["--api-key", api_key])

    start_time = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        elapsed_ms = (time.time() - start_time) * 1000
        return result.returncode, elapsed_ms
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error("Firecrawl execution timed out after 600s")
        return 1, elapsed_ms
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error("Firecrawl execution failed: %s", e)
        return 1, elapsed_ms


def main(argv: list[str] | None = None) -> int:
    """Instrument firecrawl execution and collect baseline metrics."""
    parser = argparse.ArgumentParser(
        description="Firecrawl baseline metrics collector (observe-only instrumentation)",
    )
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--limit", type=int, default=20, help="Max search results")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--api-key", help="Firecrawl API key (defaults to env var)")
    parser.add_argument("--skip-scrape", action="store_true", help="Search only")
    parser.add_argument("--timeout", type=int, default=30, help="Scrape timeout (seconds)")

    args = parser.parse_args(argv)
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting firecrawl instrumentation: query=%s, limit=%d, out=%s",
        args.query,
        args.limit,
        args.out,
    )

    time.time()

    # Run firecrawl
    exit_code, elapsed_ms = run_firecrawl_ingest(
        query=args.query,
        limit=args.limit,
        out=args.out,
        api_key=args.api_key,
        skip_scrape=args.skip_scrape,
        timeout=args.timeout,
    )

    # Collect baseline metrics
    baseline_metrics = collect_baseline_metrics(output_dir)
    baseline_metrics["execution_latency_ms"] = elapsed_ms
    baseline_metrics["exit_code"] = exit_code
    baseline_metrics["success"] = exit_code == 0

    # Save baseline to file
    baseline_file = BASELINE_DIR / f"baseline_{output_dir.name}.json"
    try:
        baseline_file.write_text(json.dumps(baseline_metrics, indent=2))
        logger.info("Baseline metrics saved to %s", baseline_file)
    except Exception as e:
        logger.warning("Failed to save baseline metrics: %s", e)

    # Log to skills logger (non-blocking)
    if SKILLS_LOGGER:
        try:
            SKILLS_LOGGER.log_execution(
                skill_name="firecrawl-research-discovery",
                task_context=f"Biotech news discovery: {args.query[:100]}",
                inputs={
                    "query": args.query,
                    "limit": args.limit,
                    "skip_scrape": args.skip_scrape,
                    "timeout": args.timeout,
                },
                outputs={
                    "search_results_found": baseline_metrics.get("search_results_found", 0),
                    "urls_attempted": baseline_metrics.get("urls_attempted", 0),
                    "urls_succeeded": baseline_metrics.get("urls_succeeded", 0),
                    "scrape_success_rate": baseline_metrics.get("scrape_success_rate", 0),
                    "exit_code": exit_code,
                },
                latency_ms=elapsed_ms,
                success=(exit_code == 0),
                error=None if exit_code == 0 else f"exit_code_{exit_code}",
            )
            logger.info("Execution logged to skills logger")
        except Exception as e:
            logger.warning("Failed to log to skills logger: %s", e)

    # Report
    logger.info(
        "Firecrawl baseline complete: %d results found, %d scraped, %.1fs elapsed",
        baseline_metrics.get("search_results_found", 0),
        baseline_metrics.get("urls_succeeded", 0),
        elapsed_ms / 1000,
    )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
