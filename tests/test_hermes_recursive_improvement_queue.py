"""Tests for Hermes recursive self-improvement queue."""

from __future__ import annotations

import json
from pathlib import Path


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")


def test_build_queue_flags_unreliable_skill(tmp_path: Path):
    from tools.hermes_recursive_improvement_queue import build_queue

    logs_dir = tmp_path / "logs"
    executions = []
    for i in range(5):
        executions.append(
            {
                "execution_id": f"exec{i}",
                "skill_name": "screener_ops",
                "metrics": {"latency_ms": 1000, "cost_usd": 0.001},
                "outcome": {"success": i >= 2, "error": "tool failed" if i < 2 else None},
            }
        )
    _write_jsonl(logs_dir / "execution_log_prod_2026-06.jsonl", executions)

    queue = build_queue(environment="prod", month="2026-06", as_of_date="2026-06-20", logs_dir=logs_dir)

    assert queue["generated_at"] == "2026-06-20T00:00:00Z"
    assert queue["governance"]["automation_approval"] is False
    assert queue["governance"]["production_deployment_approved"] is False
    assert queue["summary"]["high_priority_count"] == 1
    assert any(entry["classification"] == "INVESTIGATE_FAILURES" for entry in queue["queue"])


def test_build_queue_promotes_only_as_human_review_candidate(tmp_path: Path):
    from tools.hermes_recursive_improvement_queue import build_queue

    logs_dir = tmp_path / "logs"
    executions = [
        {
            "execution_id": f"exec{i}",
            "skill_name": "codegraph",
            "metrics": {"latency_ms": 900, "cost_usd": 0.001},
            "outcome": {"success": True, "error": None},
        }
        for i in range(5)
    ]
    feedback = [
        {"execution_id": "exec0", "verdict": "helpful"},
        {"execution_id": "exec1", "verdict": "helpful"},
        {"execution_id": "exec2", "verdict": "helpful"},
    ]
    _write_jsonl(logs_dir / "execution_log_prod_2026-06.jsonl", executions)
    _write_jsonl(logs_dir / "feedback_log_prod_2026-06.jsonl", feedback)

    queue = build_queue(environment="prod", month="2026-06", as_of_date="2026-06-20", logs_dir=logs_dir)
    promotion = [entry for entry in queue["queue"] if entry["classification"] == "PROMOTION_CANDIDATE"]

    assert len(promotion) == 1
    assert promotion[0]["requires_human_review"] is True
    assert promotion[0]["automation_approval"] is False
    assert promotion[0]["allowed_action"] == "operator_review_only"


def test_write_queue_artifacts(tmp_path: Path):
    from tools.hermes_recursive_improvement_queue import build_queue, write_queue_artifacts

    logs_dir = tmp_path / "logs"
    output_dir = tmp_path / "out"
    _write_jsonl(
        logs_dir / "execution_log_test_2026-06.jsonl",
        [
            {
                "execution_id": "exec0",
                "skill_name": "memory_steward",
                "metrics": {"latency_ms": 7500, "cost_usd": 0.02},
                "outcome": {"success": True, "error": None},
            }
        ],
    )

    queue = build_queue(environment="test", month="2026-06", as_of_date="2026-06-20", logs_dir=logs_dir)
    paths = write_queue_artifacts(queue, output_dir)

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["artifact_type"] == (
        "hermes_recursive_self_improvement_queue"
    )
    assert "Automation approval: False" in paths["markdown"].read_text(encoding="utf-8")
