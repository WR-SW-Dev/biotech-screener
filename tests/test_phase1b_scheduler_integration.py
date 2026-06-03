"""Phase 1b Integration: Scheduler health check invoked in operational path."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


def test_scheduler_health_check_invoked_in_main_path():
    """Verify scheduler_health_check() is called by run_agent_direct.main()."""
    from tools.run_agent_direct import main

    with patch("tools.run_agent_direct.scheduler_health_check") as mock_health:
        mock_health.return_value = ("OK", [])
        with patch("tools.run_agent_direct.auth_preflight_check", return_value=(True, None)):
            with patch("tools.run_agent_direct.load_registry_entry", return_value={"status": "active"}):
                with patch("tools.run_agent_direct.direct_run_block_reason", return_value=None):
                    with patch("tools.run_agent_direct.run_preflight", return_value=None):
                        with patch("tools.run_agent_direct.run_agent") as mock_agent:
                            mock_agent.return_value = {
                                "status": "success",
                                "response": "OK",
                                "usage": {"input_tokens": 100, "output_tokens": 50},
                            }
                            with patch("tools.run_agent_direct.maybe_write_memory"):
                                with patch("pathlib.Path.mkdir"):
                                    with patch("builtins.open", create=True):
                                        with patch.object(sys, "argv", ["prog", "--agent", "ops"]):
                                            main()

        mock_health.assert_called_once()
        assert mock_health.call_args[0][0] == "ops"


def test_scheduler_health_check_warns_nonblocking():
    """Verify scheduler health WARN is logged but doesn't block execution."""
    from tools.run_agent_direct import main

    with patch("tools.run_agent_direct.scheduler_health_check") as mock_health:
        mock_health.return_value = ("WARN", ["Gateway slow: last dispatch 3.5h ago"])
        with patch("tools.run_agent_direct.auth_preflight_check", return_value=(True, None)):
            with patch("tools.run_agent_direct.load_registry_entry", return_value={"status": "active"}):
                with patch("tools.run_agent_direct.direct_run_block_reason", return_value=None):
                    with patch("tools.run_agent_direct.run_preflight", return_value=None):
                        with patch("tools.run_agent_direct.run_agent") as mock_agent:
                            mock_agent.return_value = {
                                "status": "success",
                                "response": "test",
                                "usage": {"input_tokens": 100, "output_tokens": 50},
                            }
                            with patch("tools.run_agent_direct.maybe_write_memory"):
                                with patch("pathlib.Path.mkdir"):
                                    with patch("builtins.open", create=True):
                                        with patch.object(sys, "argv", ["prog", "--agent", "ops"]):
                                            result = main()

        assert result == 0
        mock_agent.assert_called_once()


def test_scheduler_health_check_alert_nonblocking():
    """Verify scheduler health ALERT is logged but doesn't block execution."""
    from tools.run_agent_direct import main

    with patch("tools.run_agent_direct.scheduler_health_check") as mock_health:
        mock_health.return_value = ("ALERT", ["WSL2 sleep detected: system uptime 0.25h"])
        with patch("tools.run_agent_direct.auth_preflight_check", return_value=(True, None)):
            with patch("tools.run_agent_direct.load_registry_entry", return_value={"status": "active"}):
                with patch("tools.run_agent_direct.direct_run_block_reason", return_value=None):
                    with patch("tools.run_agent_direct.run_preflight", return_value=None):
                        with patch("tools.run_agent_direct.run_agent") as mock_agent:
                            mock_agent.return_value = {
                                "status": "success",
                                "response": "test",
                                "usage": {"input_tokens": 100, "output_tokens": 50},
                            }
                            with patch("tools.run_agent_direct.maybe_write_memory"):
                                with patch("pathlib.Path.mkdir"):
                                    with patch("builtins.open", create=True):
                                        with patch.object(sys, "argv", ["prog", "--agent", "ops"]):
                                            result = main()

        assert result == 0
        mock_agent.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
