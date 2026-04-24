"""Tests for common.insider_enrichment — Pass B wiring into rankings.csv.

Covers the six contract points called out in the Pass B spec:
  1. row count unchanged after enrichment
  2. ticker order unchanged
  3. missing raw file → blank/NA (empty string)
  4. present raw file with no qualifying activity → 0.0 (not blank)
  5. present raw file with qualifying activity → expected net value
  6. no other columns are touched by enrichment (side-effect-free on other keys)
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from common.insider_enrichment import (  # noqa: E402
    INSIDER_FIELD,
    compute_insider_net_buy_value_90d,
    enrich_rows_with_insider_net_buy_value,
)
from tools.fetch_form4_insider import InsiderTransaction  # noqa: E402


def _mk_txn(
    accession: str, filing_date: str, code: str = "P", shares: float = 100, price: float = 10.0
) -> InsiderTransaction:
    return InsiderTransaction(
        ticker="TEST",
        cik="1",
        filer_cik="99",
        filer_name="Doe Jane",
        filing_date=filing_date,
        transaction_date=filing_date,
        form_type="4",
        accession_number=accession,
        is_director=False,
        is_officer=True,
        officer_title="CEO",
        is_ten_pct_owner=False,
        security_title="Common Stock",
        transaction_code=code,
        shares=shares,
        price_per_share=price,
        value=shares * price,
        acquired_disposed="A" if code == "P" else "D",
        shares_owned_after=shares,
        direct_indirect="D",
        is_buy=(code == "P"),
        is_sell=(code == "S"),
        is_derivative=False,
    )


def _write_raw(raw_dir: Path, ticker: str, txns):
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{ticker}.json").write_text(json.dumps([asdict(t) for t in txns], indent=1))


# ---------------------------------------------------------------------------
# 1) row count unchanged
# ---------------------------------------------------------------------------


def test_row_count_unchanged_after_enrichment(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    rows = [
        {"ticker": "TKA", "actionable_rank": 1},
        {"ticker": "TKB", "actionable_rank": 2},
        {"ticker": "TKC", "actionable_rank": 3},
    ]
    n_before = len(rows)
    enrich_rows_with_insider_net_buy_value(rows, "2026-04-24", raw_dir)
    assert len(rows) == n_before


# ---------------------------------------------------------------------------
# 2) ticker order unchanged
# ---------------------------------------------------------------------------


def test_ticker_order_unchanged_after_enrichment(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    # Mix of tickers with and without raw files — order must not change
    _write_raw(raw_dir, "TKB", [_mk_txn("A-1", "2026-04-10", code="P", shares=50, price=2.0)])
    rows = [
        {"ticker": "TKA", "actionable_rank": 1},
        {"ticker": "TKB", "actionable_rank": 2},
        {"ticker": "TKC", "actionable_rank": 3},
    ]
    enrich_rows_with_insider_net_buy_value(rows, "2026-04-24", raw_dir)
    assert [r["ticker"] for r in rows] == ["TKA", "TKB", "TKC"]


# ---------------------------------------------------------------------------
# 3) missing raw file → blank/NA
# ---------------------------------------------------------------------------


def test_missing_raw_file_yields_blank_not_zero(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    rows = [{"ticker": "NOFILE", "actionable_rank": 1}]
    enrich_rows_with_insider_net_buy_value(rows, "2026-04-24", raw_dir)
    assert rows[0][INSIDER_FIELD] == "", f"missing raw file must be blank, got {rows[0][INSIDER_FIELD]!r}"
    assert rows[0][INSIDER_FIELD] != 0
    assert rows[0][INSIDER_FIELD] != 0.0


# ---------------------------------------------------------------------------
# 4) present raw file with no qualifying activity → 0.0
# ---------------------------------------------------------------------------


def test_raw_file_present_no_qualifying_activity_yields_zero(tmp_path):
    raw_dir = tmp_path / "raw"
    # Transaction exists but falls OUTSIDE the 90d window — counts as "no qualifying activity"
    old_txn = _mk_txn("OLD-1", "2025-01-01", code="P", shares=100, price=5.0)
    _write_raw(raw_dir, "OLDER", [old_txn])
    rows = [{"ticker": "OLDER", "actionable_rank": 1}]
    enrich_rows_with_insider_net_buy_value(rows, "2026-04-24", raw_dir)
    assert rows[0][INSIDER_FIELD] == 0.0
    assert isinstance(rows[0][INSIDER_FIELD], float)

    # Also: file exists but only has derivative transactions (excluded from P/S aggregation)
    deriv = _mk_txn("DRV-1", "2026-04-10", code="M", shares=100, price=5.0)
    deriv.is_derivative = True
    _write_raw(raw_dir, "DRVONLY", [deriv])
    rows = [{"ticker": "DRVONLY", "actionable_rank": 1}]
    enrich_rows_with_insider_net_buy_value(rows, "2026-04-24", raw_dir)
    assert rows[0][INSIDER_FIELD] == 0.0


# ---------------------------------------------------------------------------
# 5) present raw file with qualifying activity → expected net value
# ---------------------------------------------------------------------------


def test_qualifying_activity_yields_expected_net_value(tmp_path):
    raw_dir = tmp_path / "raw"
    # Inside 90d window: two buys (P/A) and one sell (S/D); expected net = buys - sells
    buy1 = _mk_txn("B-1", "2026-04-01", code="P", shares=1000, price=10.0)  # +$10,000
    buy2 = _mk_txn("B-2", "2026-04-05", code="P", shares=500, price=12.0)  # +$6,000
    sell = _mk_txn("S-1", "2026-04-10", code="S", shares=200, price=15.0)  # -$3,000
    _write_raw(raw_dir, "ACTV", [buy1, buy2, sell])

    expected = 1000 * 10.0 + 500 * 12.0 - 200 * 15.0  # = 13,000
    assert compute_insider_net_buy_value_90d(raw_dir, "ACTV", "2026-04-24") == pytest.approx(expected)

    rows = [{"ticker": "ACTV", "actionable_rank": 1}]
    enrich_rows_with_insider_net_buy_value(rows, "2026-04-24", raw_dir)
    assert rows[0][INSIDER_FIELD] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 6) no other columns change (enrichment is single-field write)
# ---------------------------------------------------------------------------


def test_no_other_columns_change(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_raw(raw_dir, "TKA", [_mk_txn("A-1", "2026-04-10", code="P", shares=50, price=2.0)])

    before = {
        "ticker": "TKA",
        "actionable_rank": 1,
        "tier_dev": "A4",
        "ees_v3_score": 0.42,
        "financial_score": 0.78,
        "short_interest_pct": 3.1,
        "priced_move_pct": 15.0,
    }
    # Snapshot keys+values BEFORE enrichment
    snapshot = {k: v for k, v in before.items()}
    rows = [before]
    enrich_rows_with_insider_net_buy_value(rows, "2026-04-24", raw_dir)

    # New field is added
    assert INSIDER_FIELD in rows[0]
    # Every pre-existing key keeps its exact value
    for k, v in snapshot.items():
        assert rows[0][k] == v, f"enrichment mutated field {k!r}: {rows[0][k]!r} != {v!r}"
    # Only the insider field was added; no other keys appeared
    new_keys = set(rows[0].keys()) - set(snapshot.keys())
    assert new_keys == {INSIDER_FIELD}, f"unexpected new keys: {new_keys - {INSIDER_FIELD}}"


# ---------------------------------------------------------------------------
# Additional safety: row missing ticker key is blank (defensive)
# ---------------------------------------------------------------------------


def test_row_without_ticker_is_blank(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    rows = [{"actionable_rank": 1}]  # no ticker key
    enrich_rows_with_insider_net_buy_value(rows, "2026-04-24", raw_dir)
    assert rows[0][INSIDER_FIELD] == ""
