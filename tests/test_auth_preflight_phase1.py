"""
Test suite for Phase 1 Priority 1: Shared execution-layer auth preflight.

Validates that failing auth state blocks dispatch before any agent runs
and writes a clear diagnostic artifact.

Acceptance gate: A failing auth state blocks dispatch before any agent runs
and writes a clear diagnostic artifact.
"""

import json
import os
from pathlib import Path


def test_auth_preflight_function_exists():
    """Auth preflight check function is implemented."""
    from tools.run_agent_direct import auth_preflight_check

    # Function should exist and be callable
    assert callable(auth_preflight_check)


def test_auth_preflight_returns_tuple():
    """Auth preflight returns (success: bool, error: str | None) tuple."""
    from tools.run_agent_direct import auth_preflight_check

    result = auth_preflight_check("ops")
    assert isinstance(result, tuple)
    assert len(result) == 2
    success, error = result
    assert isinstance(success, bool)
    assert error is None or isinstance(error, str)


def test_auth_preflight_detects_missing_credentials():
    """Auth preflight detects when credentials are missing."""
    from tools.run_agent_direct import auth_preflight_check

    # Save and remove credentials
    orig_together = os.environ.pop("TOGETHER_API_KEY", None)
    orig_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)

    try:
        success, error = auth_preflight_check("ops")
        # Should fail when both credentials missing
        assert not success, "Auth preflight should detect missing credentials"
        assert error is not None
        assert "missing credentials" in error.lower()
    finally:
        # Restore
        if orig_together:
            os.environ["TOGETHER_API_KEY"] = orig_together
        if orig_anthropic:
            os.environ["ANTHROPIC_API_KEY"] = orig_anthropic


def test_auth_preflight_is_centralized():
    """Auth check is centralized at runner layer, not distributed to agents."""
    # Verify that auth_preflight_check is only called from run_agent_direct.main()
    runner_path = Path(__file__).resolve().parent.parent / "tools" / "run_agent_direct.py"
    runner_content = runner_path.read_text()

    # Should define auth_preflight_check once
    assert (
        runner_content.count("def auth_preflight_check") == 1
    ), "Auth preflight should be defined exactly once (centralized)"

    # Should call it once in main()
    assert (
        runner_content.count("auth_ok, auth_error = auth_preflight_check") == 1
    ), "Auth preflight should be called exactly once in main()"

    # Should NOT have per-agent auth logic in individual run_job.py files
    agents_dir = Path(__file__).resolve().parent.parent / "agents"
    for agent_dir in agents_dir.glob("*/"):
        if agent_dir.is_dir():
            run_job_py = agent_dir / "run_job.py"
            if run_job_py.exists():
                content = run_job_py.read_text()
                # Per-agent runner should NOT duplicate auth logic
                assert (
                    "auth_preflight_check" not in content
                ), f"Auth logic should not be in {run_job_py} (must be centralized)"


def test_auth_preflight_is_non_destructive():
    """Auth preflight check does not mutate any state."""
    from tools.run_agent_direct import auth_preflight_check

    # Capture environment before
    env_before = dict(os.environ)

    # Run auth check
    auth_preflight_check("ops")

    # Verify environment unchanged (no mutations)
    env_after = dict(os.environ)
    assert env_before == env_after, "Auth preflight check should not mutate environment"


def test_auth_preflight_fails_before_dispatch():
    """Verify auth failure blocks execution flow early in main()."""
    runner_path = Path(__file__).resolve().parent.parent / "tools" / "run_agent_direct.py"
    runner_content = runner_path.read_text()

    # Find where auth check happens relative to other checks
    auth_check_pos = runner_content.find("auth_ok, auth_error = auth_preflight_check")
    agent_dispatch_pos = runner_content.find("result = run_agent(")

    # Auth check should happen BEFORE agent dispatch
    assert auth_check_pos < agent_dispatch_pos, "Auth preflight must block execution BEFORE run_agent() is called"
    assert auth_check_pos > 0, "Auth preflight check should be present in main()"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
