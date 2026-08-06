#!/usr/bin/env python3
"""Tests for binding a brokerage account number to a tenant.

The gap this closes: create_tenant/ensure_tenant leave account_number empty, and until
now nothing ever filled it for a self-service user. execute_order() raises
UnprovenAccountError on an empty expected account, so such a tenant could never place or
even review an order — and would not find out until the click that was meant to trade.

The account number is fetched from the broker, never accepted as input, because it is the
value trading_guard compares an order against to prove ownership. A typed value would
make that check verify a claim against itself.
"""

import pytest

from common.credstore import (
    AccountAlreadyClaimed,
    CredentialNotFound,
    CredentialStore,
    CredentialStoreError,
    TenantExists,
    generate_key,
)
from common.mcp_exec import AccountDiscoveryError, MCPError, MultipleAccountsFound, fetch_account_number


@pytest.fixture()
def store(tmp_path):
    return CredentialStore(tmp_path / "cred.db", key=generate_key())


# --------------------------------------------------------------------------------------
# Store primitives
# --------------------------------------------------------------------------------------


class TestCreateTenant:
    def test_creates_an_empty_tenant(self, store):
        store.create_tenant("scott")
        creds = store.get("scott")
        assert creds.account_number == ""
        assert creds.robinhood_bearer == ""

    def test_refuses_a_duplicate_rather_than_ignoring_it(self, store):
        """ensure_tenant() would no-op here; signup needs the refusal."""
        store.create_tenant("scott")
        with pytest.raises(TenantExists):
            store.create_tenant("scott")

    def test_refusal_leaves_the_existing_password_intact(self, store):
        store.create_tenant("scott")
        store.set_password("scott", "original")
        with pytest.raises(TenantExists):
            store.create_tenant("scott")
        assert store.verify_password("scott", "original") is True

    def test_invalid_user_id_is_refused(self, store):
        with pytest.raises(Exception):
            store.create_tenant("../escape")


class TestFindAccountOwner:
    def test_returns_none_when_unclaimed(self, store):
        store.create_tenant("scott")
        assert store.find_account_owner("111111111") is None

    def test_finds_the_claiming_tenant(self, store):
        store.create_tenant("scott")
        store.set_account_number("scott", "111111111")
        assert store.find_account_owner("111111111") == "scott"

    def test_excluding_skips_the_named_tenant(self, store):
        store.create_tenant("scott")
        store.set_account_number("scott", "111111111")
        assert store.find_account_owner("111111111", excluding="scott") is None

    def test_empty_account_number_is_never_owned(self, store):
        """Every fresh tenant has account_number == '' — that must not read as a clash."""
        store.create_tenant("scott")
        store.create_tenant("darren")
        assert store.find_account_owner("") is None


class TestSetAccountNumber:
    def test_stores_the_number(self, store):
        store.create_tenant("scott")
        store.set_account_number("scott", "111111111")
        assert store.get("scott").account_number == "111111111"

    def test_two_tenants_cannot_share_an_account(self, store):
        """A shared account number makes the trading guard's ownership check meaningless."""
        store.create_tenant("scott")
        store.create_tenant("darren")
        store.set_account_number("scott", "111111111")
        with pytest.raises(AccountAlreadyClaimed):
            store.set_account_number("darren", "111111111")

    def test_refusal_leaves_the_loser_unbound(self, store):
        store.create_tenant("scott")
        store.create_tenant("darren")
        store.set_account_number("scott", "111111111")
        with pytest.raises(AccountAlreadyClaimed):
            store.set_account_number("darren", "111111111")
        assert store.get("darren").account_number == ""

    def test_rebinding_the_same_account_to_the_same_tenant_is_fine(self, store):
        """Reconnecting Robinhood must not trip the uniqueness check against oneself."""
        store.create_tenant("scott")
        store.set_account_number("scott", "111111111")
        store.set_account_number("scott", "111111111")
        assert store.get("scott").account_number == "111111111"

    def test_empty_account_number_is_refused(self, store):
        store.create_tenant("scott")
        with pytest.raises(CredentialStoreError):
            store.set_account_number("scott", "")

    def test_unknown_tenant_is_refused(self, store):
        with pytest.raises(CredentialNotFound):
            store.set_account_number("nobody", "111111111")

    def test_preserves_the_bearer_token(self, store):
        store.create_tenant("scott")
        store.set_robinhood_tokens("scott", access_token="tok", refresh_token="r", expires_at=1.0)
        store.set_account_number("scott", "111111111")
        assert store.get("scott").robinhood_bearer == "tok"


# --------------------------------------------------------------------------------------
# Broker-side discovery
# --------------------------------------------------------------------------------------


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeTransport:
    """Records the call and replays a canned MCP envelope. Never touches the network."""

    def __init__(self, tool_payload, *, status_code=200):
        self.tool_payload = tool_payload
        self.status_code = status_code
        self.calls = []

    def post(self, url, *, json=None, headers=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "json": json, "headers": headers})
        resp = _FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": __import__("json").dumps(self.tool_payload)}]},
            }
        )
        resp.status_code = self.status_code
        return resp


class TestFetchAccountNumber:
    def test_returns_the_single_account(self, store):
        t = _FakeTransport({"data": {"accounts": [{"account_number": "802349084", "type": "cash"}]}})
        assert fetch_account_number(bearer="tok", transport=t) == "802349084"

    def test_calls_get_accounts_with_the_tenants_bearer(self, store):
        t = _FakeTransport({"accounts": [{"account_number": "1"}]})
        fetch_account_number(bearer="tenant-token", transport=t)
        assert t.calls[0]["json"]["params"]["name"] == "get_accounts"
        assert t.calls[0]["headers"]["Authorization"] == "Bearer tenant-token"

    def test_finds_the_field_at_any_depth(self, store):
        """The envelope shape is not a contract we control, so the walk is deliberate."""
        t = _FakeTransport({"results": [{"detail": {"account_number": "999"}}]})
        assert fetch_account_number(bearer="tok", transport=t) == "999"

    def test_duplicate_mentions_of_one_account_are_not_ambiguous(self, store):
        t = _FakeTransport({"account_number": "5", "data": {"account_number": "5"}})
        assert fetch_account_number(bearer="tok", transport=t) == "5"

    def test_multiple_accounts_are_refused_not_guessed(self, store):
        t = _FakeTransport({"accounts": [{"account_number": "1"}, {"account_number": "2"}]})
        with pytest.raises(MultipleAccountsFound) as exc:
            fetch_account_number(bearer="tok", transport=t)
        assert exc.value.accounts == ["1", "2"]

    def test_missing_account_number_is_an_error(self, store):
        t = _FakeTransport({"accounts": []})
        with pytest.raises(AccountDiscoveryError):
            fetch_account_number(bearer="tok", transport=t)

    def test_blank_account_number_is_not_accepted(self, store):
        t = _FakeTransport({"accounts": [{"account_number": "   "}]})
        with pytest.raises(AccountDiscoveryError):
            fetch_account_number(bearer="tok", transport=t)

    def test_transport_failure_surfaces_as_mcp_error(self, store):
        t = _FakeTransport({"accounts": [{"account_number": "1"}]}, status_code=500)
        with pytest.raises(MCPError):
            fetch_account_number(bearer="tok", transport=t)

    def test_refuses_to_build_an_unauthenticated_client(self, store):
        with pytest.raises(MCPError):
            fetch_account_number(bearer="", transport=_FakeTransport({}))
