"""Trading-isolation tests (design §5) — the safety-critical boundary.

These assert the repo-side guard refuses to construct or submit an order against an
account the acting tenant does not own, and that a process cannot rebind to a second
account mid-life (the race-condition case).

Scope caveat, restated because it matters: orders are actually placed by MCP tool calls
outside this repo, so these tests prove the guard refuses — not that a cross-account order
is impossible. That property comes from one OS user per tenant with one Robinhood MCP
server each.
"""

from __future__ import annotations

import json

import pytest

from common.tenancy import UserContext
from common.trading_guard import (
    AccountIsolationError,
    ProcessAccountRebindError,
    UnprovenAccountError,
    assert_account_owned,
    bind_process_account,
    bound_account,
    reset_for_testing,
    verify_blotter_account,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Fresh latch and a throwaway audit log for every test."""
    monkeypatch.setenv("BIOTECH_TRADING_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    reset_for_testing()
    yield
    reset_for_testing()


def _ctx(user_id="alice", account="111111111"):
    return UserContext(user_id, account, "srv-" + user_id, None)  # type: ignore[arg-type]


def _audit_records(tmp_path):
    path = tmp_path / "audit.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------------------
# ownership
# ---------------------------------------------------------------------------------------


def test_owned_account_is_allowed():
    ctx = _ctx()
    assert_account_owned(ctx, "111111111")
    assert bound_account() == "111111111"


def test_other_tenants_account_is_refused():
    """The headline property: alice cannot trade bob's account."""
    alice = _ctx("alice", "111111111")
    with pytest.raises(AccountIsolationError) as exc:
        assert_account_owned(alice, "222222222")
    assert "222222222" in str(exc.value)
    assert "111111111" in str(exc.value)


@pytest.mark.parametrize("bad", ["", None, "11111111", "1111111119", " 111111111", "111111111 "])
def test_near_miss_account_numbers_are_refused(bad):
    """No trimming, no prefix tolerance — an account number matches exactly or not at all."""
    ctx = _ctx("alice", "111111111")
    with pytest.raises((AccountIsolationError, UnprovenAccountError)):
        assert_account_owned(ctx, bad)  # type: ignore[arg-type]


def test_context_without_account_cannot_prove_ownership():
    """The legacy tenant has no account number; it must not be able to trade."""
    ctx = _ctx("_legacy", "")
    with pytest.raises(UnprovenAccountError):
        assert_account_owned(ctx, "111111111")


def test_refusal_leaves_process_unbound():
    """A refused attempt must not latch the process to the rejected account."""
    with pytest.raises(AccountIsolationError):
        assert_account_owned(_ctx("alice", "111111111"), "222222222")
    assert bound_account() is None


# ---------------------------------------------------------------------------------------
# process monogamy (race-condition defense)
# ---------------------------------------------------------------------------------------


def test_process_cannot_rebind_to_a_second_account():
    alice = _ctx("alice", "111111111")
    bob = _ctx("bob", "222222222")
    bind_process_account(alice)
    with pytest.raises(ProcessAccountRebindError):
        bind_process_account(bob)
    assert bound_account() == "111111111"


def test_rebinding_same_account_is_idempotent():
    ctx = _ctx()
    bind_process_account(ctx)
    bind_process_account(ctx)
    assert bound_account() == "111111111"


def test_second_tenant_order_refused_after_first_order_in_same_process():
    """Simulates a worker that resolved a second context after already trading."""
    assert_account_owned(_ctx("alice", "111111111"), "111111111")
    with pytest.raises((ProcessAccountRebindError, AccountIsolationError)):
        assert_account_owned(_ctx("bob", "222222222"), "222222222")


def test_same_account_claimed_by_different_user_id_is_refused():
    """Defends the case where a registry edit reassigns an account mid-process."""
    bind_process_account(_ctx("alice", "111111111"))
    with pytest.raises(ProcessAccountRebindError):
        bind_process_account(_ctx("mallory", "111111111"))


# ---------------------------------------------------------------------------------------
# blotter re-verification (TOCTOU)
# ---------------------------------------------------------------------------------------


def test_blotter_for_owned_account_verifies():
    ctx = _ctx()
    blotter = {"metadata": {"account_number": "111111111"}}
    assert verify_blotter_account(ctx, blotter) == "111111111"


def test_blotter_for_another_account_is_refused():
    ctx = _ctx("alice", "111111111")
    blotter = {"metadata": {"account_number": "222222222"}}
    with pytest.raises(AccountIsolationError):
        verify_blotter_account(ctx, blotter)


@pytest.mark.parametrize(
    "meta",
    [{}, {"metadata": {}}, {"metadata": {"account_number": ""}}, {"metadata": None}],
)
def test_blotter_without_account_is_refused(meta):
    """Unverifiable target account means refuse, not assume."""
    with pytest.raises(AccountIsolationError):
        verify_blotter_account(_ctx(), meta if "metadata" in meta else {"metadata": {}})


# ---------------------------------------------------------------------------------------
# audit trail
# ---------------------------------------------------------------------------------------


def test_allowed_attempt_is_audited(tmp_path):
    assert_account_owned(_ctx(), "111111111")
    events = [r["event"] for r in _audit_records(tmp_path)]
    assert "allowed" in events


def test_refused_attempt_is_audited(tmp_path):
    """A refusal that leaves no trace is a refusal nobody can investigate."""
    with pytest.raises(AccountIsolationError):
        assert_account_owned(_ctx("alice", "111111111"), "222222222")
    records = _audit_records(tmp_path)
    assert any(r["event"] == "refused_mismatch" for r in records)
    refused = [r for r in records if r["event"] == "refused_mismatch"][0]
    assert refused["user_id"] == "alice"
    assert refused["account_number"] == "222222222"


def test_audit_failure_does_not_mask_refusal(monkeypatch):
    """If the audit log is unwritable the guard must still refuse."""
    monkeypatch.setenv("BIOTECH_TRADING_AUDIT_LOG", "/proc/definitely-not-writable/audit.jsonl")
    with pytest.raises(AccountIsolationError):
        assert_account_owned(_ctx("alice", "111111111"), "222222222")
