"""Tests for Town-Hermes bridge helpers (Spec 090 Phase B)."""

from __future__ import annotations

import pytest

from common.town_bridge_events import (
    notify_cron_missed,
    notify_cron_missed_from_runtime_health,
    notify_hard_contradictions,
)


@pytest.fixture(autouse=True)
def dry_run(monkeypatch):
    monkeypatch.setenv("OPERATOR_DELIVERY_DRY_RUN", "1")


def test_notify_hard_contradictions_noop_when_clear():
    assert notify_hard_contradictions([{"id": "C1", "severity": "OK", "description": "ok"}]) is True


def test_notify_hard_contradictions_sends_for_hard():
    contradictions = [
        {
            "id": "C1",
            "severity": "HARD_CONTRADICTION",
            "description": "bioshort cron active while suppressed",
        }
    ]
    assert notify_hard_contradictions(contradictions) is True


def test_notify_cron_missed_noop_when_nothing_missed():
    assert notify_cron_missed(as_of_date="2026-05-30", missed_critical_times=[]) is True


def test_notify_cron_missed_fail_for_critical():
    assert (
        notify_cron_missed(
            as_of_date="2026-05-30",
            missed_critical_times=["17:30"],
            runtime_severity="RED",
        )
        is True
    )


def test_notify_cron_missed_from_runtime_health():
    rh = {
        "missed_critical_job_times": ["17:30"],
        "missed_noncritical_job_times": [],
        "severity": "RED",
        "reasons": ["production-critical job(s) at ['17:30'] ET missed"],
    }
    assert notify_cron_missed_from_runtime_health("2026-05-30", rh) is True
