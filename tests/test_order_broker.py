#!/usr/bin/env python3
"""Tests for the per-request order subprocess broker (PR 3).

These run the *real* subprocess rather than a mock, because the properties under test
are properties of process spawning: what lands in the child's environment, what happens
on a non-zero exit, and whether a timeout is reported as ambiguous rather than failed.
"""

import json

import pytest

from common.order_broker import BrokerResult, OrderBrokerError, OrderTimeout, _child_env, place_order_for_tenant

ORDER = {
    "account_number": "111111111",
    "symbol": "COGT",
    "side": "buy",
    "quantity": "2",
    "order_type": "market",
    "time_in_force": "gfd",
}


class TestChildEnvironmentIsScrubbed:
    def test_credstore_key_is_not_inherited(self, monkeypatch):
        """A compromised worker must not be able to read other tenants' credentials."""
        monkeypatch.setenv("BIOTECH_CREDSTORE_KEY", "super-secret-master-key")
        env = _child_env(live=False)
        assert "BIOTECH_CREDSTORE_KEY" not in env

    def test_session_secret_is_not_inherited(self, monkeypatch):
        monkeypatch.setenv("BIOTECH_SESSION_SECRET", "session-signing-secret")
        assert "BIOTECH_SESSION_SECRET" not in _child_env(live=False)

    def test_live_gate_not_forwarded_for_review_only(self, monkeypatch):
        monkeypatch.setenv("BIOTECH_LIVE_TRADING", "1")
        assert "BIOTECH_LIVE_TRADING" not in _child_env(live=False)

    def test_live_gate_forwarded_only_when_both_agree(self, monkeypatch):
        monkeypatch.setenv("BIOTECH_LIVE_TRADING", "1")
        assert _child_env(live=True).get("BIOTECH_LIVE_TRADING") == "1"

    def test_live_gate_absent_in_parent_is_not_invented(self, monkeypatch):
        monkeypatch.delenv("BIOTECH_LIVE_TRADING", raising=False)
        assert "BIOTECH_LIVE_TRADING" not in _child_env(live=True)


class TestDryRunRoundTrip:
    def test_dry_run_returns_a_result_and_places_nothing(self):
        res = place_order_for_tenant(
            user_id="scott",
            bearer="tok-scott",
            account_number="111111111",
            order=ORDER,
            dry_run=True,
        )
        assert isinstance(res, BrokerResult)
        assert res.ok is True
        assert res.placed is False
        assert res.mode == "DRY_RUN"

    def test_missing_bearer_refused_before_spawn(self):
        with pytest.raises(OrderBrokerError):
            place_order_for_tenant(user_id="scott", bearer="", account_number="111111111", order=ORDER, dry_run=True)


class TestFailClosed:
    def test_account_mismatch_surfaces_as_error(self):
        with pytest.raises(OrderBrokerError):
            place_order_for_tenant(
                user_id="scott",
                bearer="tok",
                account_number="999999999",  # order says 111111111
                order=ORDER,
                dry_run=True,
            )

    def test_invalid_order_surfaces_as_error(self):
        bad = dict(ORDER, side="sideways")
        with pytest.raises(OrderBrokerError):
            place_order_for_tenant(user_id="scott", bearer="tok", account_number="111111111", order=bad, dry_run=True)

    def test_error_message_does_not_echo_the_token(self):
        bad = dict(ORDER, side="sideways")
        try:
            place_order_for_tenant(
                user_id="scott",
                bearer="LEAKY_TOKEN_MARKER",
                account_number="111111111",
                order=bad,
                dry_run=True,
            )
        except OrderBrokerError as exc:
            assert "LEAKY_TOKEN_MARKER" not in str(exc)
        else:
            pytest.fail("expected refusal")

    def test_timeout_is_reported_as_ambiguous(self, tmp_path):
        """A timeout must not be reported as a clean failure — the order may have landed."""
        slow = tmp_path / "slow_worker.py"
        slow.write_text("import time, sys\nsys.stdin.read()\ntime.sleep(30)\n", encoding="utf-8")
        with pytest.raises(OrderTimeout) as err:
            place_order_for_tenant(
                user_id="scott",
                bearer="tok",
                account_number="111111111",
                order=ORDER,
                dry_run=True,
                timeout=1.0,
                worker=slow,
            )
        assert "may or may not" in str(err.value).lower()

    def test_nonzero_exit_becomes_broker_error(self, tmp_path):
        boom = tmp_path / "boom.py"
        boom.write_text("import sys\nsys.stdin.read()\nsys.exit(7)\n", encoding="utf-8")
        with pytest.raises(OrderBrokerError):
            place_order_for_tenant(
                user_id="scott",
                bearer="tok",
                account_number="111111111",
                order=ORDER,
                dry_run=True,
                worker=boom,
            )

    def test_undecodable_output_becomes_broker_error(self, tmp_path):
        junk = tmp_path / "junk.py"
        junk.write_text("import sys\nsys.stdin.read()\nprint('not json')\n", encoding="utf-8")
        with pytest.raises(OrderBrokerError):
            place_order_for_tenant(
                user_id="scott",
                bearer="tok",
                account_number="111111111",
                order=ORDER,
                dry_run=True,
                worker=junk,
            )


class TestCredentialTransport:
    def test_token_reaches_the_child_on_stdin_only(self, tmp_path):
        """Echo the child's argv and env back, and assert the token is in neither."""
        spy = tmp_path / "spy.py"
        spy.write_text(
            "import json, os, sys\n"
            "job = json.loads(sys.stdin.read())\n"
            "print(json.dumps({\n"
            "    'ok': True, 'mode': 'DRY_RUN', 'placed': False, 'order_id': None,\n"
            "    'argv': sys.argv, 'env_values': list(os.environ.values()),\n"
            "    'saw_token': job.get('bearer'),\n"
            "}))\n",
            encoding="utf-8",
        )
        marker = "TOKEN_ONLY_VIA_STDIN"
        res = place_order_for_tenant(
            user_id="scott",
            bearer=marker,
            account_number="111111111",
            order=ORDER,
            dry_run=True,
            worker=spy,
        )
        assert res.payload["saw_token"] == marker, "child must actually receive it on stdin"
        assert marker not in json.dumps(res.payload["argv"])
        assert marker not in json.dumps(res.payload["env_values"])
