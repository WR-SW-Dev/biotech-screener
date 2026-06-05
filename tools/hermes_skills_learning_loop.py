#!/usr/bin/env python3
"""Hermes skills learning loop: aggregate logs, compute efficacy, generate reports.

Runs monthly to analyze skill performance, feedback, and learning opportunities.
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file."""
    if not path.exists():
        return []
    records = []
    for line in path.read_text().strip().split("\n"):
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def generate_monthly_report(month_str: str = None) -> Path:
    """Aggregate logs and generate monthly skills learning report.

    Args:
        month_str: YYYY-MM format (default: current month)

    Returns:
        Path to generated report
    """
    if not month_str:
        month_str = datetime.utcnow().strftime("%Y-%m")

    logs_dir = Path("artifacts/skills_learning")
    logs_dir.mkdir(parents=True, exist_ok=True)

    exec_log = logs_dir / f"execution_log_{month_str}.jsonl"
    feedback_log = logs_dir / f"feedback_log_{month_str}.jsonl"

    # Load logs
    executions = load_jsonl(exec_log)
    feedback = load_jsonl(feedback_log)

    # Aggregate by skill
    skill_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "executions": 0,
            "successes": 0,
            "failures": 0,
            "total_latency": 0.0,
            "total_cost": 0.0,
            "total_tokens": 0,
            "feedback": [],
            "errors": [],
        }
    )

    for exec_record in executions:
        skill = exec_record.get("skill_name", "unknown")
        stats = skill_stats[skill]

        stats["executions"] += 1
        if exec_record.get("outcome", {}).get("success"):
            stats["successes"] += 1
        else:
            stats["failures"] += 1
            error = exec_record.get("outcome", {}).get("error")
            if error:
                stats["errors"].append(error)

        metrics = exec_record.get("metrics", {})
        stats["total_latency"] += metrics.get("latency_ms", 0)
        stats["total_cost"] += metrics.get("cost_usd", 0)
        stats["total_tokens"] += metrics.get("tokens_in", 0) + metrics.get("tokens_out", 0)

    for fb in feedback:
        skill = fb.get("skill_name", "unknown")
        if skill in skill_stats:
            skill_stats[skill]["feedback"].append(fb)

    # Generate report
    report_lines = [
        f"# Monthly Skills Learning Report — {month_str}",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "## Summary",
        "",
        f"- Total executions: {len(executions)}",
        f"- Total feedback records: {len(feedback)}",
        f"- Skills monitored: {len(skill_stats)}",
        f"- Skills with feedback: {sum(1 for s in skill_stats.values() if s['feedback'])}",
        "",
        "## Skills by Efficacy (Success Rate)",
        "",
    ]

    # Sort by success rate
    sorted_skills = sorted(
        skill_stats.items(),
        key=lambda x: x[1]["successes"] / max(1, x[1]["executions"]),
        reverse=True,
    )

    for skill_name, stats in sorted_skills:
        execs = stats["executions"]
        success_rate = 100 * stats["successes"] / max(1, execs)
        avg_latency = stats["total_latency"] / max(1, execs)
        avg_cost = stats["total_cost"] / max(1, execs)
        avg_tokens = stats["total_tokens"] / max(1, execs)

        report_lines.append(f"### {skill_name}")
        report_lines.append(f"- **Executions:** {execs}")
        report_lines.append(f"- **Success rate:** {success_rate:.1f}%")
        report_lines.append(f"- **Avg latency:** {avg_latency:.0f}ms (p50)")
        report_lines.append(f"- **Avg cost:** ${avg_cost:.4f}")
        report_lines.append(f"- **Avg tokens:** {avg_tokens:.0f}")
        report_lines.append("")

        if stats["feedback"]:
            helpful = sum(1 for f in stats["feedback"] if f.get("verdict") == "helpful")
            unhelpful = sum(1 for f in stats["feedback"] if f.get("verdict") == "unhelpful")
            missing = sum(1 for f in stats["feedback"] if f.get("verdict") == "missing")
            report_lines.append("**Feedback:**")
            report_lines.append(f"- Helpful: {helpful}")
            report_lines.append(f"- Unhelpful: {unhelpful}")
            report_lines.append(f"- Missing features: {missing}")

            if unhelpful > 0 or missing > 0:
                report_lines.append("")
                report_lines.append("**Notes:**")
                for fb in stats["feedback"]:
                    if fb.get("notes"):
                        report_lines.append(f"- {fb['notes']}")

        report_lines.append("")

    # Add learning insights
    report_lines.extend(
        [
            "## Learning Insights",
            "",
        ]
    )

    # Find most used skills
    most_used = sorted(skill_stats.items(), key=lambda x: x[1]["executions"], reverse=True)[:5]
    if most_used:
        report_lines.append("### Most Used Skills")
        for skill, stats in most_used:
            report_lines.append(f"- **{skill}:** {stats['executions']} executions")
        report_lines.append("")

    # Find most expensive skills
    most_expensive = sorted(skill_stats.items(), key=lambda x: x[1]["total_cost"], reverse=True)[:5]
    if most_expensive:
        report_lines.append("### Most Expensive Skills")
        for skill, stats in most_expensive:
            avg_cost = stats["total_cost"] / max(1, stats["executions"])
            report_lines.append(f"- **{skill}:** ${stats['total_cost']:.2f} total (${avg_cost:.4f} avg)")
        report_lines.append("")

    # Find slowest skills
    slowest = sorted(skill_stats.items(), key=lambda x: x[1]["total_latency"], reverse=True)[:5]
    if slowest:
        report_lines.append("### Slowest Skills")
        for skill, stats in slowest:
            avg_latency = stats["total_latency"] / max(1, stats["executions"])
            report_lines.append(f"- **{skill}:** {avg_latency:.0f}ms avg latency")
        report_lines.append("")

    report_lines.append("## Recommendations for Next Month")
    report_lines.append("")
    report_lines.append("1. Review feedback for unhelpful/missing-feature skills")
    report_lines.append("2. Optimize top-5 slowest skills for latency")
    report_lines.append("3. Consider parallelizing independent skills")
    report_lines.append("4. Profile high-cost skills for optimization")
    report_lines.append("")

    # Write report
    report_text = "\n".join(report_lines)
    report_path = logs_dir / f"monthly_report_{month_str}.md"
    report_path.write_text(report_text)

    return report_path


if __name__ == "__main__":
    import sys

    month = sys.argv[1] if len(sys.argv) > 1 else None
    report_path = generate_monthly_report(month)
    print(f"✓ Report generated: {report_path}")
