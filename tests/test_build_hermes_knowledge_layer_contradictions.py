"""Contradiction-scan behavior for build_hermes_knowledge_layer (Spec 089)."""

from tools import build_hermes_knowledge_layer as bkl


def test_c3_unknown_cloud_env_when_crontab_unavailable():
    cron_info = {
        "available": False,
        "availability": "UNKNOWN_CLOUD_ENV",
        "active_jobs": [],
        "suppressed_jobs": [],
    }
    issues = bkl.detect_contradictions(
        git_info={"uncommitted": []},
        crontab_info=cron_info,
        agents={},
        artifacts={},
    )
    c3 = next(i for i in issues if i["id"] == "C3")
    assert c3["severity"] == "UNKNOWN_CLOUD_ENV"
    assert "crontab unavailable" in c3["description"]


def test_c3_hard_contradiction_when_crontab_available_but_line_missing():
    cron_info = {
        "available": True,
        "availability": "OPERATOR_HOST",
        "active_jobs": ["0 17 * * 1-5 cd /repo && python3 run_screen.py"],
        "suppressed_jobs": [],
    }
    issues = bkl.detect_contradictions(
        git_info={"uncommitted": []},
        crontab_info=cron_info,
        agents={},
        artifacts={},
    )
    c3 = next(i for i in issues if i["id"] == "C3")
    assert c3["severity"] == "HARD_CONTRADICTION"


def test_c3_ok_when_producer_cron_active():
    cron_info = {
        "available": True,
        "availability": "OPERATOR_HOST",
        "active_jobs": ["0 18 * * 5 cd /repo && python3 tools/biotech_hedge_report.py --portfolio-csv"],
        "suppressed_jobs": [],
    }
    issues = bkl.detect_contradictions(
        git_info={"uncommitted": []},
        crontab_info=cron_info,
        agents={},
        artifacts={},
    )
    c3 = next(i for i in issues if i["id"] == "C3")
    assert c3["severity"] == "OK"
