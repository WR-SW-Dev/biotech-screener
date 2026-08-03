#!/usr/bin/env python3
"""Tests for the headless MCP order client (PR 3).

This is the first code in the repository that can place a real brokerage order, so the
tests are weighted towards what must *not* happen:

* nothing is placed unless live mode is explicitly and unambiguously enabled
* any error, timeout, or malformed response fails closed rather than retrying or guessing
* the bearer token never reaches argv or the environment

``tools/robinhood_execute_trades_v2_mcp.py`` remains the stub simulator; this module is
the real path it always said it was not.
"""

import json

import pytest

from common.mcp_exec import LiveTradingDisabled, MCPClient, MCPError, OrderRequest, OrderResult, execute_order


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class _FakeTransport:
    """Records requests and replays scripted responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def post(self, url, *, json=None, headers=None, timeout=None):
        self.requests.append({"url": url, "json": json, "headers": headers or {}, "timeout": timeout})
        if not self.responses:
            raise AssertionError("unexpected extra request: " + str(json))
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _ok(result):
    return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": result})


def _tool_ok(payload):
    return _ok({"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False})


@pytest.fixture()
def order():
    return OrderRequest(
        account_number="111111111",
        symbol="COGT",
        side="buy",
        quantity="3",
        order_type="market",
        time_in_force="gfd",
    )


class TestMCPClientTransport:
    def test_bearer_token_is_sent_as_authorization_header(self, order):
        t = _FakeTransport([_tool_ok({"id": "ord-1"})])
        MCPClient("https://example/mcp", bearer="tok-abc", transport=t).call_tool("review_equity_order", {})
        assert t.requests[0]["headers"]["Authorization"] == "Bearer tok-abc"

    def test_jsonrpc_envelope_is_well_formed(self):
        t = _FakeTransport([_tool_ok({"ok": True})])
        MCPClient("https://example/mcp", bearer="x", transport=t).call_tool("review_equity_order", {"a": 1})
        body = t.requests[0]["json"]
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "review_equity_order"
        assert body["params"]["arguments"] == {"a": 1}

    def test_jsonrpc_error_raises(self):
        t = _FakeTransport([_FakeResponse({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "nope"}})])
        with pytest.raises(MCPError, match="nope"):
            MCPClient("https://example/mcp", bearer="x", transport=t).call_tool("review_equity_order", {})

    def test_tool_level_iserror_raises(self):
        payload = {"content": [{"type": "text", "text": "insufficient buying power"}], "isError": True}
        t = _FakeTransport([_ok(payload)])
        with pytest.raises(MCPError, match="insufficient buying power"):
            MCPClient("https://example/mcp", bearer="x", transport=t).call_tool("place_equity_order", {})

    def test_http_error_status_raises(self):
        t = _FakeTransport([_FakeResponse({"detail": "unauthorized"}, status_code=401)])
        with pytest.raises(MCPError, match="401"):
            MCPClient("https://example/mcp", bearer="x", transport=t).call_tool("review_equity_order", {})

    def test_transport_exception_propagates_as_mcp_error(self):
        t = _FakeTransport([RuntimeError("connection reset")])
        with pytest.raises(MCPError):
            MCPClient("https://example/mcp", bearer="x", transport=t).call_tool("review_equity_order", {})


class TestFailClosedByDefault:
    """Nothing is placed unless live is explicitly on."""

    def test_default_is_review_only_and_places_nothing(self, order):
        t = _FakeTransport([_tool_ok({"status": "ok", "estimated_cost": "42.00"})])
        res = execute_order(order, bearer="tok", transport=t, live=False)
        assert isinstance(res, OrderResult)
        assert res.placed is False
        assert res.mode == "REVIEW_ONLY"
        called = [r["json"]["params"]["name"] for r in t.requests]
        assert called == ["review_equity_order"], "review must not be followed by a placement"

    def test_live_true_but_env_flag_absent_refuses(self, order, monkeypatch):
        monkeypatch.delenv("BIOTECH_LIVE_TRADING", raising=False)
        t = _FakeTransport([_tool_ok({"status": "ok"})])
        with pytest.raises(LiveTradingDisabled):
            execute_order(order, bearer="tok", transport=t, live=True)
        assert t.requests == [], "must refuse before any network call"

    def test_env_flag_alone_does_not_enable_live(self, order, monkeypatch):
        """Both the flag and the explicit argument are required — neither alone."""
        monkeypatch.setenv("BIOTECH_LIVE_TRADING", "1")
        t = _FakeTransport([_tool_ok({"status": "ok"})])
        res = execute_order(order, bearer="tok", transport=t, live=False)
        assert res.placed is False

    def test_live_with_both_gates_places(self, order, monkeypatch):
        monkeypatch.setenv("BIOTECH_LIVE_TRADING", "1")
        t = _FakeTransport([_tool_ok({"status": "ok"}), _tool_ok({"id": "ord-99", "state": "queued"})])
        res = execute_order(order, bearer="tok", transport=t, live=True)
        assert res.placed is True
        assert res.mode == "LIVE"
        assert res.order_id == "ord-99"
        assert [r["json"]["params"]["name"] for r in t.requests] == [
            "review_equity_order",
            "place_equity_order",
        ]

    def test_failed_review_blocks_placement(self, order, monkeypatch):
        monkeypatch.setenv("BIOTECH_LIVE_TRADING", "1")
        bad = {"content": [{"type": "text", "text": "rejected: market closed"}], "isError": True}
        t = _FakeTransport([_ok(bad)])
        with pytest.raises(MCPError):
            execute_order(order, bearer="tok", transport=t, live=True)
        assert len(t.requests) == 1, "must not place after a failed review"


class TestOrderValidation:
    def test_account_mismatch_is_refused(self, order, monkeypatch):
        monkeypatch.setenv("BIOTECH_LIVE_TRADING", "1")
        t = _FakeTransport([])
        with pytest.raises(Exception):
            execute_order(order, bearer="tok", transport=t, live=True, expect_account="999999999")
        assert t.requests == []

    def test_unknown_side_rejected(self):
        with pytest.raises(ValueError):
            OrderRequest(
                account_number="1",
                symbol="COGT",
                side="yolo",
                quantity="1",
                order_type="market",
                time_in_force="gfd",
            )

    def test_nonpositive_quantity_rejected(self):
        for q in ("0", "-1"):
            with pytest.raises(ValueError):
                OrderRequest(
                    account_number="1",
                    symbol="COGT",
                    side="buy",
                    quantity=q,
                    order_type="market",
                    time_in_force="gfd",
                )

    def test_empty_symbol_rejected(self):
        with pytest.raises(ValueError):
            OrderRequest(
                account_number="1",
                symbol="",
                side="buy",
                quantity="1",
                order_type="market",
                time_in_force="gfd",
            )


class TestSecretHandling:
    def test_repr_does_not_leak_bearer(self):
        c = MCPClient("https://example/mcp", bearer="SUPER_SECRET_TOKEN")
        assert "SUPER_SECRET_TOKEN" not in repr(c)

    def test_result_does_not_carry_the_token(self, order):
        t = _FakeTransport([_tool_ok({"status": "ok"})])
        res = execute_order(order, bearer="SUPER_SECRET_TOKEN", transport=t, live=False)
        assert "SUPER_SECRET_TOKEN" not in json.dumps(res.as_dict())
