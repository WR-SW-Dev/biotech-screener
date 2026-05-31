"""
Town-Hermes bridge event helpers (Spec 090 Phase B).

Thin wrappers around common.operator_delivery.send_operator_event for
cron_missed and contradiction_detected. All sends respect OPERATOR_DELIVERY_DRY_RUN.
"""

from __future__ import annotations

import logging
from typing import Any

from common.operator_delivery import send_operator_event

logger = logging.getLogger(__name__)


def notify_hard_contradictions(contradictions: list[dict[str, Any]]) -> bool:
    """Emit contradiction_detected (WARN) when HARD_CONTRADICTION items exist."""
    hard = [c for c in contradictions if c.get("severity") == "HARD_CONTRADICTION"]
    if not hard:
        return True

    lines = [f"{c.get('id', '?')}: {c.get('description', '')}" for c in hard]
    summary = f"{len(hard)} hard contradiction(s). " + "; ".join(lines[:5])
    if len(lines) > 5:
        summary += f" (+{len(lines) - 5} more)"

    return send_operator_event(
        channel="town",
        severity="WARN",
        event_type="contradiction_detected",
        title=f"Knowledge layer: {len(hard)} hard contradiction(s)",
        summary=summary,
        artifact="artifacts/ops/contradiction_ledger/latest.md",
        next_operator_action="review",
        extra={"contradiction_ids": [c.get("id") for c in hard]},
    )


def notify_cron_missed(
    *,
    as_of_date: str,
    missed_critical_times: list[str],
    missed_noncritical_times: list[str] | None = None,
    runtime_severity: str = "RED",
    reasons: list[str] | None = None,
    artifact: str = "artifacts/ops_supervisor",
    recovery_triggered: bool = False,
    source: str = "ops_supervisor",
) -> bool:
    """
    Emit cron_missed when production-critical cron windows were missed.

    FAIL when missed_critical_times is non-empty or runtime_severity is RED.
    WARN when only non-critical times missed (ORANGE/YELLOW runtime).
    """
    missed_critical_times = missed_critical_times or []
    missed_noncritical_times = missed_noncritical_times or []
    reasons = reasons or []

    if not missed_critical_times and not missed_noncritical_times:
        return True

    if missed_critical_times or runtime_severity == "RED":
        severity = "FAIL"
    else:
        severity = "WARN"

    parts = []
    if missed_critical_times:
        parts.append(f"critical missed: {', '.join(missed_critical_times)} ET")
    if missed_noncritical_times:
        parts.append(f"non-critical missed: {', '.join(missed_noncritical_times)} ET")
    if recovery_triggered:
        parts.append("watchdog recovery was triggered")
    if reasons:
        parts.append(reasons[0])

    summary = f"{as_of_date} ({source}): " + "; ".join(parts)

    return send_operator_event(
        channel="town",
        severity=severity,
        event_type="cron_missed",
        title=f"Cron missed — {as_of_date}",
        summary=summary,
        artifact=artifact,
        next_operator_action="investigate",
        extra={
            "as_of_date": as_of_date,
            "missed_critical_job_times": missed_critical_times,
            "missed_noncritical_job_times": missed_noncritical_times,
            "runtime_severity": runtime_severity,
            "source": source,
            "recovery_triggered": recovery_triggered,
        },
    )


def notify_cron_missed_from_runtime_health(
    as_of_date: str,
    runtime_health: dict[str, Any],
    *,
    artifact: str | None = None,
) -> bool:
    """Bridge ops_supervisor runtime_health block to cron_missed."""
    missed_critical = runtime_health.get("missed_critical_job_times") or []
    missed_noncritical = runtime_health.get("missed_noncritical_job_times") or []
    rh_severity = runtime_health.get("severity", "GREEN")

    if not missed_critical and not missed_noncritical:
        return True
    if rh_severity == "GREEN" and not missed_critical:
        return True

    art = artifact or f"artifacts/ops_supervisor/{as_of_date}_supervisor.json"
    return notify_cron_missed(
        as_of_date=as_of_date,
        missed_critical_times=missed_critical,
        missed_noncritical_times=missed_noncritical,
        runtime_severity=rh_severity,
        reasons=runtime_health.get("reasons") or [],
        artifact=art,
        source="ops_supervisor",
    )
