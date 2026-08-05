#!/usr/bin/env python3
"""Tests for releasing a basket claim after a provably clean all-failure run.

Smoke-test finding: a basket where every order was refused before placement (wrong
bearer token, say) could never be retried. The ledger treated that identically to an
ambiguous crash, so the first attempt permanently burned the basket for that snapshot
date — the first thing a tester hits if their token is wrong.

The release is deliberately narrow. A claim may be dropped only when it is *provable*
that nothing reached the broker:

* nothing was placed, and
* no failure was ambiguous — no timeout, and no failure during the placement call itself

A failure during ``review`` means the order was never submitted. A failure during
``place`` might have landed. Those must not be conflated, which is why they raise
different types.
"""

import pytest

from common.mcp_exec import MCPError, OrderRequest, PlacementAmbiguous, execute_order
from dashboard.basket import BasketAlreadyExecuted, ExecutionLedger


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code = payload, status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeTransport:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def post(self, url, *, json=None, headers=None, timeout=None):
        self.requests.append(json)
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _ok(payload):
    return _FakeResponse(
        {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "{}"}], "isError": False}}
    )


def _tool_err(msg):
    return _FakeResponse(
        {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": msg}], "isError": True}}
    )


@pytest.fixture()
def order():
    return OrderRequest(
        account_number="111111111",
        symbol="COGT",
        side="buy",
        quantity="1",
        order_type="market",
        time_in_force="gfd",
    )


class TestFailurePhaseIsDistinguishable:
    def test_review_failure_raises_plain_mcp_error(self, order):
        """Nothing was submitted — safe to retry."""
        t = _FakeTransport([_tool_err("401 unauthorized")])
        with pytest.raises(MCPError) as err:
            execute_order(order, bearer="bad", transport=t, live=False, expect_account="111111111")
        assert not isinstance(err.value, PlacementAmbiguous)

    def test_placement_failure_raises_placement_ambiguous(self, order, monkeypatch):
        """Review passed, place failed — the order may or may not have landed."""
        monkeypatch.setenv("BIOTECH_LIVE_TRADING", "1")
        t = _FakeTransport([_ok({}), _tool_err("gateway timeout")])
        with pytest.raises(PlacementAmbiguous):
            execute_order(order, bearer="tok", transport=t, live=True, expect_account="111111111")

    def test_placement_ambiguous_is_an_mcp_error(self):
        """Existing except MCPError handlers must keep catching it."""
        assert issubclass(PlacementAmbiguous, MCPError)


class TestLedgerRelease:
    def test_release_allows_a_retry(self, tmp_path):
        led = ExecutionLedger(tmp_path / "e.db")
        led.reserve("scott", "b1")
        led.release("scott", "b1", reason="all orders refused before placement")
        led.reserve("scott", "b1")  # must not raise

    def test_release_is_refused_once_the_claim_is_completed(self, tmp_path):
        """A recorded outcome means the loop ran; releasing it would permit a double."""
        led = ExecutionLedger(tmp_path / "e.db")
        led.reserve("scott", "b1")
        led.record("scott", "b1", {"placed": 3})
        with pytest.raises(BasketAlreadyExecuted):
            led.release("scott", "b1", reason="nope")
        with pytest.raises(BasketAlreadyExecuted):
            led.reserve("scott", "b1")

    def test_release_of_an_unknown_claim_is_a_noop(self, tmp_path):
        ExecutionLedger(tmp_path / "e.db").release("scott", "never-claimed", reason="x")

    def test_release_only_affects_the_named_tenant(self, tmp_path):
        led = ExecutionLedger(tmp_path / "e.db")
        led.reserve("scott", "b1")
        led.reserve("darren", "b1")
        led.release("scott", "b1", reason="x")
        led.reserve("scott", "b1")
        with pytest.raises(BasketAlreadyExecuted):
            led.reserve("darren", "b1")


class TestReleaseDecision:
    """is_safe_to_release() is the whole safety argument, so it is tested directly."""

    def test_clean_all_failure_is_releasable(self):
        assert ExecutionLedger.is_safe_to_release(placed=0, failures=[{"ambiguous": False}] * 3) is True

    def test_any_placement_blocks_release(self):
        assert ExecutionLedger.is_safe_to_release(placed=1, failures=[{"ambiguous": False}]) is False

    def test_a_single_ambiguous_failure_blocks_release(self):
        fails = [{"ambiguous": False}, {"ambiguous": True}, {"ambiguous": False}]
        assert ExecutionLedger.is_safe_to_release(placed=0, failures=fails) is False

    def test_no_failures_and_nothing_placed_is_not_releasable(self):
        """An empty basket completed successfully — it is not a failed run."""
        assert ExecutionLedger.is_safe_to_release(placed=0, failures=[]) is False

    def test_missing_ambiguous_key_is_treated_as_ambiguous(self):
        """Fail closed: an unclassified failure must not unlock a retry."""
        assert ExecutionLedger.is_safe_to_release(placed=0, failures=[{"error": "?"}]) is False
