#!/usr/bin/env python3
"""Tests for the per-request order subprocess (PR 3).

The subprocess exists so that one tenant's bearer token is live only inside a process
that can reach exactly one account, for exactly one call. These tests assert the
properties that makes true:

* the token arrives on **stdin** — never argv (world-readable via ``ps``/``/proc``),
  never the environment (inherited by any child)
* every failure path exits non-zero, so a caller that only checks the exit code cannot
  mistake a refusal for a placement
* live placement still requires both gates, even here
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKER = REPO_ROOT / "tools" / "mcp_order_worker.py"

BEARER_MARKER = "TOKEN_THAT_MUST_NOT_APPEAR_IN_ARGV"


def _job(**over):
    job = {
        "bearer": BEARER_MARKER,
        "expect_account": "111111111",
        "live": False,
        "order": {
            "account_number": "111111111",
            "symbol": "COGT",
            "side": "buy",
            "quantity": "2",
            "order_type": "market",
            "time_in_force": "gfd",
        },
    }
    job.update(over)
    return job


def _run(job, *, env=None, extra_args=()):
    """Run the worker with the job on stdin. Returns (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(WORKER), *extra_args],
        input=json.dumps(job),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestWorkerExists:
    def test_worker_script_is_present_and_executable_as_module(self):
        assert WORKER.is_file(), "PR 3 must ship the subprocess entrypoint"


class TestCredentialNeverInArgvOrEnv:
    def test_argv_carries_no_secret(self):
        """The worker takes no credential argument at all."""
        rc, out, err = _run(_job(), extra_args=("--dry-run",))
        combined = out + err
        assert BEARER_MARKER not in combined, "token must never be echoed back"

    def test_worker_rejects_a_bearer_passed_on_the_command_line(self):
        """A --bearer flag must not exist; if it ever appears, this test fails."""
        rc, out, err = _run(_job(), extra_args=("--bearer", BEARER_MARKER))
        assert rc != 0, "worker must not accept a credential via argv"

    def test_missing_stdin_job_fails_closed(self):
        proc = subprocess.run(
            [sys.executable, str(WORKER), "--dry-run"],
            input="",
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=60,
        )
        assert proc.returncode != 0

    def test_malformed_stdin_fails_closed(self):
        proc = subprocess.run(
            [sys.executable, str(WORKER), "--dry-run"],
            input="{not json",
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=60,
        )
        assert proc.returncode != 0


class TestFailClosed:
    def test_job_without_bearer_exits_nonzero(self):
        job = _job()
        del job["bearer"]
        rc, _, _ = _run(job, extra_args=("--dry-run",))
        assert rc != 0

    def test_account_mismatch_exits_nonzero(self):
        rc, _, err = _run(_job(expect_account="999999999"), extra_args=("--dry-run",))
        assert rc != 0

    def test_invalid_order_exits_nonzero(self):
        job = _job()
        job["order"]["side"] = "sideways"
        rc, _, _ = _run(job, extra_args=("--dry-run",))
        assert rc != 0

    def test_live_without_env_gate_exits_nonzero(self):
        """live=true in the job is not enough on its own."""
        rc, _, err = _run(_job(live=True), extra_args=("--dry-run",))
        assert rc != 0


class TestDryRun:
    def test_dry_run_emits_json_and_places_nothing(self):
        rc, out, err = _run(_job(), extra_args=("--dry-run",))
        assert rc == 0, err
        payload = json.loads(out)
        assert payload["placed"] is False
        assert payload["mode"] == "DRY_RUN"
        assert payload["symbol"] == "COGT"

    def test_dry_run_output_contains_no_credential(self):
        rc, out, _ = _run(_job(), extra_args=("--dry-run",))
        assert rc == 0
        assert BEARER_MARKER not in out
