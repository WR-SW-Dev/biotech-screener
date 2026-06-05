#!/usr/bin/env python3
"""Firecrawl baseline analyzer — observe improvements over time.

Analyzes baseline metrics collected from firecrawl_baseline_collector.py
to identify performance trends and potential improvements.

Produces:
- Success rate tracking (% of executions that succeeded)
- Latency trends (execution time over time)
- Scrape efficiency (URLs found vs successfully scraped)
- Error pattern analysis (which errors are most common)
- Baseline stability (variance in metrics)

Usage:
    python3 tools/firecrawl_baseline_analyzer.py [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any, Dict, List

BASELINE_DIR = Path("artifacts/firecrawl_baseline")


def load_baselines(since: datetime | None = None) -> List[Dict[str, Any]]:
    """Load all baseline metrics files."""
    if not BASELINE_DIR.exists():
        return []

    baselines = []
    for baseline_file in sorted(BASELINE_DIR.glob("baseline_*.json")):
        try:
            data = json.loads(baseline_file.read_text())

            # Parse date from filename
            date_str = baseline_file.stem.replace("baseline_", "")
            try:
                date = datetime.fromisoformat(date_str)
                if since and date < since:
                    continue
            except ValueError:
                pass

            baselines.append(data)
        except Exception:
            pass

    return baselines


def analyze_baselines(baselines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze baseline metrics."""
    if not baselines:
        return {"status": "no_data", "message": "No baseline metrics found"}

    # Extract metrics
    latencies = [b.get("execution_latency_ms", 0) for b in baselines if b.get("success")]
    successes = [b.get("success", False) for b in baselines]
    scrape_rates = [b.get("scrape_success_rate", 0) for b in baselines if "scrape_success_rate" in b]
    urls_found = [b.get("search_results_found", 0) for b in baselines if "search_results_found" in b]
    urls_scraped = [b.get("urls_succeeded", 0) for b in baselines if "urls_succeeded" in b]

    analysis = {
        "total_runs": len(baselines),
        "successful_runs": sum(successes),
        "failed_runs": len(baselines) - sum(successes),
        "success_rate": sum(successes) / max(1, len(baselines)),
    }

    # Latency analysis
    if latencies:
        analysis["latency"] = {
            "min_ms": min(latencies),
            "max_ms": max(latencies),
            "mean_ms": mean(latencies),
            "median_ms": median(latencies),
            "stddev_ms": pstdev(latencies) if len(latencies) > 1 else 0,
            "count": len(latencies),
        }

    # Scrape efficiency
    if urls_found and urls_scraped:
        total_found = sum(urls_found)
        total_scraped = sum(urls_scraped)
        analysis["scrape_efficiency"] = {
            "total_urls_found": total_found,
            "total_urls_scraped": total_scraped,
            "overall_rate": total_scraped / max(1, total_found),
        }

    if scrape_rates:
        analysis["scrape_success_rate"] = {
            "mean": mean(scrape_rates),
            "median": median(scrape_rates),
            "min": min(scrape_rates),
            "max": max(scrape_rates),
        }

    # Error patterns
    all_errors = {}
    for b in baselines:
        errors = b.get("error_patterns", {})
        for error, count in errors.items():
            all_errors[error] = all_errors.get(error, 0) + count

    if all_errors:
        sorted_errors = sorted(all_errors.items(), key=lambda x: -x[1])
        analysis["top_errors"] = {error: count for error, count in sorted_errors[:5]}

    return analysis


def generate_report(analysis: Dict[str, Any]) -> str:
    """Generate human-readable report."""
    if analysis.get("status") == "no_data":
        return "No baseline data available. Run firecrawl_baseline_collector.py first.\n"

    lines = [
        "# Firecrawl Research Discovery — Baseline Analysis Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}Z",
        "",
        "## Execution Summary",
        "",
        f"- **Total Runs:** {analysis['total_runs']}",
        f"- **Successful:** {analysis['successful_runs']}",
        f"- **Failed:** {analysis['failed_runs']}",
        f"- **Success Rate:** {analysis['success_rate']*100:.1f}%",
        "",
    ]

    if "latency" in analysis:
        lat = analysis["latency"]
        lines.extend(
            [
                "## Execution Latency",
                "",
                f"- **Min:** {lat['min_ms']:.0f}ms",
                f"- **Max:** {lat['max_ms']:.0f}ms",
                f"- **Mean:** {lat['mean_ms']:.0f}ms",
                f"- **Median:** {lat['median_ms']:.0f}ms",
                f"- **Stddev:** {lat['stddev_ms']:.0f}ms",
                f"- **Samples:** {lat['count']}",
                "",
            ]
        )

    if "scrape_efficiency" in analysis:
        eff = analysis["scrape_efficiency"]
        lines.extend(
            [
                "## Scrape Efficiency",
                "",
                f"- **URLs Found:** {eff['total_urls_found']}",
                f"- **URLs Scraped:** {eff['total_urls_scraped']}",
                f"- **Efficiency Rate:** {eff['overall_rate']*100:.1f}%",
                "",
            ]
        )

    if "scrape_success_rate" in analysis:
        rate = analysis["scrape_success_rate"]
        lines.extend(
            [
                "## Per-Run Scrape Success Rate",
                "",
                f"- **Mean:** {rate['mean']*100:.1f}%",
                f"- **Median:** {rate['median']*100:.1f}%",
                f"- **Min:** {rate['min']*100:.1f}%",
                f"- **Max:** {rate['max']*100:.1f}%",
                "",
            ]
        )

    if "top_errors" in analysis and analysis["top_errors"]:
        lines.extend(
            [
                "## Top Errors",
                "",
            ]
        )
        for error, count in analysis["top_errors"].items():
            lines.append(f"- {error}: {count}x")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Baseline Metrics Interpretation",
            "",
            "**Success Rate:** Percentage of executions that completed without fatal errors.",
            "  - Target: ≥95% (occasional API/network hiccups acceptable)",
            "",
            "**Latency:** Time from start to finish of full execution.",
            "  - Current baseline (mean): Use as reference for improvement measurements",
            "  - Stddev: Indicates consistency (low stddev = reliable timing)",
            "",
            "**Scrape Efficiency:** Percentage of discovered URLs successfully scraped.",
            "  - Target: ≥80% (some URLs may be blocked, rate-limited, or malformed)",
            "",
            "## Next Steps (After Improvements)",
            "",
            "1. Collect baseline metrics for 5-10 runs (establishes stability)",
            "2. Identify improvement opportunity (e.g., timeout too short, rate limiting)",
            "3. Propose change (e.g., increase timeout, add retry logic, parallel scrape)",
            "4. Apply change and collect new metrics",
            "5. Compare: new metrics vs baseline using this report structure",
            "6. Verify: no regression in latency or error rates",
            "",
        ]
    )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Generate baseline analysis report."""
    parser = argparse.ArgumentParser(
        description="Analyze firecrawl baseline metrics",
    )
    parser.add_argument(
        "--since",
        help="Only include baselines since YYYY-MM-DD",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write report to file",
    )

    args = parser.parse_args(argv)

    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"Invalid date format: {args.since}")
            return 1

    baselines = load_baselines(since)
    analysis = analyze_baselines(baselines)
    report = generate_report(analysis)

    print(report)

    if args.write:
        output_file = BASELINE_DIR / "baseline_analysis_report.md"
        output_file.write_text(report)
        print(f"\nReport written to: {output_file}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
