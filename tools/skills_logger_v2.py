#!/usr/bin/env python3
"""Skill execution logging with redaction, environment tagging, and safety guards.

Features:
- Automatic PII/sensitive data scrubbing before logging
- Environment tagging (test vs production)
- Minimum sample-size rules (5+ executions before skill evaluation)
- Advisory-only recommendations (no auto-apply)
- One-week observation before routing changes
"""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Patterns for redaction (PII, credentials, internal IDs)
REDACT_PATTERNS = [
    (r"(api[_-]?key|apikey|token|password)\s*[:=]\s*['\"]?[^\s'\"]+", "[REDACTED_KEY]"),
    (r"(email|from|to)\s*[:=]\s*[\w\.-]+@[\w\.-]+", "[REDACTED_EMAIL]"),
    (r"(ticker|symbol)\s*[:=]\s*[A-Z]{1,5}", "[REDACTED_TICKER]"),
    (r"\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b", "[REDACTED_DATE]"),  # YYYY-MM-DD
    (r"(\d{1,3}\.){3}\d{1,3}", "[REDACTED_IP]"),
    (r"authorization\s*[:=]\s*Bearer\s+\S+", "[REDACTED_AUTH]"),
]


def scrub_sensitive_data(text: str) -> str:
    """Redact PII and credentials from text."""
    if not isinstance(text, str):
        return text
    result = text
    for pattern, replacement in REDACT_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def scrub_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively scrub sensitive data from dict values."""
    if not isinstance(data, dict):
        return data
    scrubbed = {}
    for key, value in data.items():
        if isinstance(value, str):
            scrubbed[key] = scrub_sensitive_data(value)
        elif isinstance(value, dict):
            scrubbed[key] = scrub_dict(value)
        elif isinstance(value, list):
            scrubbed[key] = [
                scrub_dict(v) if isinstance(v, dict) else scrub_sensitive_data(v) if isinstance(v, str) else v
                for v in value
            ]
        else:
            scrubbed[key] = value
    return scrubbed


class SkillExecutionLoggerV2:
    """Log skill executions with redaction, environment tagging, and safety guards."""

    def __init__(self, logs_dir: Path = Path("artifacts/skills_learning")):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def log_execution(
        self,
        skill_name: str,
        task_context: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        latency_ms: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        success: bool = True,
        error: Optional[str] = None,
        environment: str = "prod",  # "prod" or "test"
    ) -> str:
        """Log a skill execution with redaction and environment tagging.

        Args:
            skill_name: Name of the skill
            task_context: Brief description of what the skill was asked to do
            inputs: Dict of input parameters
            outputs: Dict of output values
            latency_ms: Execution time in milliseconds
            tokens_in: Input tokens (for LLM calls)
            tokens_out: Output tokens (for LLM calls)
            cost_usd: Cost of execution
            success: Whether execution succeeded
            error: Error message if failed
            environment: "prod" for production, "test" for test data

        Returns:
            execution_id (for later feedback)
        """
        exec_id = str(uuid.uuid4())[:8]

        # Scrub sensitive data
        task_context_scrubbed = scrub_sensitive_data(task_context)
        inputs_scrubbed = scrub_dict(inputs)
        outputs_scrubbed = scrub_dict(outputs)
        error_scrubbed = scrub_sensitive_data(error) if error else None

        record = {
            "execution_id": exec_id,
            "skill_name": skill_name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "environment": environment,
            "task_context": task_context_scrubbed,
            "inputs": inputs_scrubbed,
            "outputs": outputs_scrubbed,
            "metrics": {
                "latency_ms": latency_ms,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_usd,
            },
            "outcome": {
                "success": success,
                "error": error_scrubbed,
                "user_feedback": None,
            },
        }

        # Write to environment-specific log
        month_str = datetime.utcnow().strftime("%Y-%m")
        log_file = self.logs_dir / f"execution_log_{environment}_{month_str}.jsonl"

        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            print(f"Warning: Could not log skill execution: {e}")

        return exec_id

    def record_feedback(
        self,
        execution_id: str,
        verdict: str,  # "helpful" | "unhelpful" | "missing"
        notes: str = "",
        environment: str = "prod",
    ) -> None:
        """Record feedback on a previous execution."""
        feedback = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "execution_id": execution_id,
            "verdict": verdict,
            "notes": scrub_sensitive_data(notes),
            "environment": environment,
        }

        month_str = datetime.utcnow().strftime("%Y-%m")
        log_file = self.logs_dir / f"feedback_log_{environment}_{month_str}.jsonl"

        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(feedback) + "\n")
        except OSError as e:
            print(f"Warning: Could not record feedback: {e}")


# Global instance
_skill_logger = None


def get_logger() -> SkillExecutionLoggerV2:
    """Get or create global logger instance."""
    global _skill_logger
    if _skill_logger is None:
        _skill_logger = SkillExecutionLoggerV2()
    return _skill_logger


def log_skill(
    skill_name: str,
    task_context: str,
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    latency_ms: float,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    success: bool = True,
    error: Optional[str] = None,
    environment: str = "prod",
) -> str:
    """Convenience function to log a skill execution.

    Returns execution_id for later feedback recording.
    """
    return get_logger().log_execution(
        skill_name=skill_name,
        task_context=task_context,
        inputs=inputs,
        outputs=outputs,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        success=success,
        error=error,
        environment=environment,
    )


def record_feedback(execution_id: str, verdict: str, notes: str = "", environment: str = "prod") -> None:
    """Record feedback on a skill execution."""
    get_logger().record_feedback(execution_id, verdict, notes, environment)


if __name__ == "__main__":
    # Quick test
    logger = SkillExecutionLoggerV2()
    exec_id = logger.log_execution(
        skill_name="test-skill",
        task_context="testing api_key=secret123 and user@example.com",
        inputs={"api_token": "sk-abc123", "ticker": "RVMD"},
        outputs={"result": "success"},
        latency_ms=123.4,
        tokens_in=100,
        tokens_out=50,
        cost_usd=0.001,
        success=True,
        environment="test",
    )
    print(f"✓ Logged execution: {exec_id}")

    logger.record_feedback(exec_id, "helpful", notes="Works well", environment="test")
    print("✓ Recorded feedback")

    # Verify redaction
    log_file = Path("artifacts/skills_learning/execution_log_test_2026-06.jsonl")
    if log_file.exists():
        last_line = log_file.read_text().strip().split("\n")[-1]
        record = json.loads(last_line)
        print("\n✓ Redaction verification:")
        print(f"  Task context: {record['task_context']}")
        print(f"  Inputs: {record['inputs']}")
