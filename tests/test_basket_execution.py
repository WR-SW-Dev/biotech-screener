#!/usr/bin/env python3
"""Tests for basket assembly, CSRF, and execution idempotency (PR 3b).

This is the layer between "user clicks Execute" and the subprocess that places orders.
Three things must hold, and each has cost a real trading system money somewhere:

* the basket the user approved is the basket that executes (no re-read between review
  and click, no silent substitution if the snapshot rolls over mid-session)
* one click executes once (a double-submitted form must not double the position)
* a state-changing POST cannot be driven cross-origin
"""

import json

import pytest

from dashboard.basket import (
    BasketAlreadyExecuted,
    BasketMismatch,
    CSRFError,
    ExecutionLedger,
    build_basket,
    issue_csrf,
    verify_csrf,
)

SECRET = b"basket-test-secret"


def _rankings():
    """Three ranked names, descending final_score, as rankings.csv rows."""
    return {
        "COGT": {"ticker": "COGT", "actionable_rank": "1", "final_score": "0.65"},
        "DNTH": {"ticker": "DNTH", "actionable_rank": "2", "final_score": "0.64"},
        "NRIX": {"ticker": "NRIX", "actionable_rank": "3", "final_score": "0.63"},
    }


class TestBasketAssembly:
    def test_basket_is_ordered_by_actionable_rank(self):
        b = build_basket("2026-08-03", _rankings(), top_n=3, equity_usd="300")
        assert [p["ticker"] for p in b.positions] == ["COGT", "DNTH", "NRIX"]

    def test_top_n_truncates(self):
        b = build_basket("2026-08-03", _rankings(), top_n=2, equity_usd="300")
        assert [p["ticker"] for p in b.positions] == ["COGT", "DNTH"]

    def test_equal_weight_notional_split(self):
        b = build_basket("2026-08-03", _rankings(), top_n=3, equity_usd="300")
        assert all(p["notional_usd"] == "100.00" for p in b.positions)

    def test_basket_id_is_stable_for_same_inputs(self):
        a = build_basket("2026-08-03", _rankings(), top_n=3, equity_usd="300")
        b = build_basket("2026-08-03", _rankings(), top_n=3, equity_usd="300")
        assert a.basket_id == b.basket_id

    def test_basket_id_changes_with_membership(self):
        a = build_basket("2026-08-03", _rankings(), top_n=3, equity_usd="300")
        b = build_basket("2026-08-03", _rankings(), top_n=2, equity_usd="300")
        assert a.basket_id != b.basket_id

    def test_basket_id_changes_with_date(self):
        a = build_basket("2026-08-03", _rankings(), top_n=3, equity_usd="300")
        b = build_basket("2026-08-04", _rankings(), top_n=3, equity_usd="300")
        assert a.basket_id != b.basket_id

    def test_unranked_rows_are_excluded(self):
        r = _rankings()
        r["ZZZZ"] = {"ticker": "ZZZZ", "actionable_rank": "", "final_score": ""}
        b = build_basket("2026-08-03", r, top_n=10, equity_usd="300")
        assert "ZZZZ" not in [p["ticker"] for p in b.positions]

    def test_empty_rankings_yields_empty_basket(self):
        b = build_basket("2026-08-03", {}, top_n=30, equity_usd="300")
        assert b.positions == []


class TestApprovedBasketIsTheExecutedBasket:
    def test_mismatched_basket_id_is_refused(self):
        b = build_basket("2026-08-03", _rankings(), top_n=3, equity_usd="300")
        with pytest.raises(BasketMismatch):
            b.assert_matches("some-other-basket-id")

    def test_matching_basket_id_passes(self):
        b = build_basket("2026-08-03", _rankings(), top_n=3, equity_usd="300")
        b.assert_matches(b.basket_id)

    def test_snapshot_rollover_invalidates_the_approved_basket(self):
        """User reviews Monday's basket; Tuesday's snapshot lands before they click."""
        approved = build_basket("2026-08-03", _rankings(), top_n=3, equity_usd="300")
        now_current = build_basket("2026-08-04", _rankings(), top_n=3, equity_usd="300")
        with pytest.raises(BasketMismatch):
            now_current.assert_matches(approved.basket_id)


class TestCSRF:
    def test_round_trip(self):
        tok = issue_csrf("scott", secret=SECRET)
        verify_csrf(tok, "scott", secret=SECRET)

    def test_token_for_another_user_is_refused(self):
        tok = issue_csrf("darren", secret=SECRET)
        with pytest.raises(CSRFError):
            verify_csrf(tok, "scott", secret=SECRET)

    def test_tampered_token_refused(self):
        tok = issue_csrf("scott", secret=SECRET)
        with pytest.raises(CSRFError):
            verify_csrf(tok[:-4] + "0000", "scott", secret=SECRET)

    def test_missing_token_refused(self):
        for junk in ("", None, "garbage"):
            with pytest.raises(CSRFError):
                verify_csrf(junk, "scott", secret=SECRET)

    def test_token_from_other_secret_refused(self):
        tok = issue_csrf("scott", secret=b"attacker")
        with pytest.raises(CSRFError):
            verify_csrf(tok, "scott", secret=SECRET)


class TestIdempotency:
    def test_first_execution_is_allowed(self, tmp_path):
        led = ExecutionLedger(tmp_path / "exec.jsonl")
        led.assert_not_executed("scott", "basket-abc")

    def test_second_execution_of_same_basket_is_refused(self, tmp_path):
        led = ExecutionLedger(tmp_path / "exec.jsonl")
        led.record("scott", "basket-abc", {"placed": 3})
        with pytest.raises(BasketAlreadyExecuted):
            led.assert_not_executed("scott", "basket-abc")

    def test_ledger_is_per_tenant(self, tmp_path):
        """Scott executing his basket must not block Darren executing his."""
        led = ExecutionLedger(tmp_path / "exec.jsonl")
        led.record("scott", "basket-abc", {"placed": 3})
        led.assert_not_executed("darren", "basket-abc")

    def test_different_basket_same_tenant_allowed(self, tmp_path):
        led = ExecutionLedger(tmp_path / "exec.jsonl")
        led.record("scott", "basket-abc", {"placed": 3})
        led.assert_not_executed("scott", "basket-def")

    def test_record_survives_reopen(self, tmp_path):
        path = tmp_path / "exec.jsonl"
        ExecutionLedger(path).record("scott", "basket-abc", {"placed": 1})
        with pytest.raises(BasketAlreadyExecuted):
            ExecutionLedger(path).assert_not_executed("scott", "basket-abc")

    def test_ledger_entry_carries_no_credential(self, tmp_path):
        path = tmp_path / "exec.jsonl"
        ExecutionLedger(path).record("scott", "basket-abc", {"placed": 1, "bearer": "LEAK"})
        assert "LEAK" not in path.read_text(encoding="utf-8")

    def test_corrupt_ledger_line_does_not_open_the_gate(self, tmp_path):
        """A malformed line must not be read as 'nothing executed yet'."""
        path = tmp_path / "exec.jsonl"
        led = ExecutionLedger(path)
        led.record("scott", "basket-abc", {"placed": 1})
        with path.open("a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        with pytest.raises(BasketAlreadyExecuted):
            led.assert_not_executed("scott", "basket-abc")

    def test_recorded_payload_is_readable_back(self, tmp_path):
        path = tmp_path / "exec.jsonl"
        ExecutionLedger(path).record("scott", "basket-abc", {"placed": 2, "mode": "LIVE"})
        rec = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert rec["user_id"] == "scott"
        assert rec["basket_id"] == "basket-abc"
        assert rec["result"]["mode"] == "LIVE"
