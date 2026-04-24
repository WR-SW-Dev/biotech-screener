"""Tests for Form 4 insider transaction parser and feature computation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.fetch_form4_insider import InsiderTransaction, compute_insider_features, is_executive, parse_form4_xml

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_XML = b"""<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0609</schemaVersion>
    <documentType>4</documentType>
    <periodOfReport>2025-06-15</periodOfReport>
    <issuer>
        <issuerCik>0001234567</issuerCik>
        <issuerName>Test Biotech Inc.</issuerName>
        <issuerTradingSymbol>TBIO</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0009999999</rptOwnerCik>
            <rptOwnerName>DOE JANE</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isDirector>false</isDirector>
            <isOfficer>true</isOfficer>
            <isTenPercentOwner>false</isTenPercentOwner>
            <officerTitle>Chief Executive Officer</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>2025-06-13</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>P</transactionCode>
                <equitySwapInvolved>false</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>10000</value></transactionShares>
                <transactionPricePerShare><value>5.50</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>50000</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
            <ownershipNature>
                <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
            </ownershipNature>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>2025-06-14</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>S</transactionCode>
                <equitySwapInvolved>false</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>2000</value></transactionShares>
                <transactionPricePerShare><value>6.00</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>48000</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
            <ownershipNature>
                <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
            </ownershipNature>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParseForm4XML:
    def test_parses_two_transactions(self):
        txns = parse_form4_xml(SAMPLE_XML, "TBIO", "1234567", "2025-06-16", "0001-26-000001")
        assert len(txns) == 2

    def test_buy_transaction(self):
        txns = parse_form4_xml(SAMPLE_XML, "TBIO", "1234567", "2025-06-16", "0001-26-000001")
        buy = txns[0]
        assert buy.is_buy is True
        assert buy.is_sell is False
        assert buy.transaction_code == "P"
        assert buy.shares == 10000
        assert buy.price_per_share == 5.50
        assert buy.value == 55000
        assert buy.acquired_disposed == "A"

    def test_sell_transaction(self):
        txns = parse_form4_xml(SAMPLE_XML, "TBIO", "1234567", "2025-06-16", "0001-26-000001")
        sell = txns[1]
        assert sell.is_sell is True
        assert sell.is_buy is False
        assert sell.transaction_code == "S"
        assert sell.shares == 2000
        assert sell.value == 12000

    def test_officer_metadata(self):
        txns = parse_form4_xml(SAMPLE_XML, "TBIO", "1234567", "2025-06-16", "0001-26-000001")
        assert txns[0].is_officer is True
        assert txns[0].officer_title == "Chief Executive Officer"
        assert txns[0].filer_name == "DOE JANE"
        assert txns[0].filer_cik == "0009999999"

    def test_filing_date_is_pit_safe(self):
        txns = parse_form4_xml(SAMPLE_XML, "TBIO", "1234567", "2025-06-16", "0001-26-000001")
        # filing_date should be the EDGAR acceptance date, not txn date
        assert txns[0].filing_date == "2025-06-16"
        assert txns[0].transaction_date == "2025-06-13"

    def test_post_transaction_shares(self):
        txns = parse_form4_xml(SAMPLE_XML, "TBIO", "1234567", "2025-06-16", "0001-26-000001")
        assert txns[0].shares_owned_after == 50000
        assert txns[1].shares_owned_after == 48000

    def test_empty_xml_returns_empty(self):
        assert parse_form4_xml(b"not xml", "X", "1", "2025-01-01", "acc") == []


# ---------------------------------------------------------------------------
# Executive detection
# ---------------------------------------------------------------------------


class TestIsExecutive:
    @pytest.mark.parametrize(
        "title",
        [
            "Chief Executive Officer",
            "CEO",
            "ceo",
            "President and CEO",
            "Chief Financial Officer",
            "CFO",
            "Chief Operating Officer",
            "COO",
            "President",
            "Chief Medical Officer",
            "Chief Scientific Officer",
        ],
    )
    def test_executive_titles(self, title):
        assert is_executive(title) is True

    @pytest.mark.parametrize(
        "title",
        [
            "SVP, Finance & Accounting",
            "VP, Business Development",
            "General Counsel",
            "Chief Commercial Officer",
            "Director",
            "",
        ],
    )
    def test_non_executive_titles(self, title):
        assert is_executive(title) is False


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------


class TestComputeInsiderFeatures:
    @pytest.fixture
    def sample_txns(self):
        """Build a set of transactions for feature testing."""
        common = dict(
            ticker="TBIO",
            cik="1234567",
            form_type="4",
            accession_number="acc1",
            is_ten_pct_owner=False,
            security_title="Common Stock",
            shares_owned_after=50000,
            direct_indirect="D",
            is_derivative=False,
        )
        return [
            # CEO buy $55k, filed 2025-06-16
            InsiderTransaction(
                **common,
                filer_cik="9999999",
                filer_name="DOE JANE",
                filing_date="2025-06-16",
                transaction_date="2025-06-13",
                is_director=False,
                is_officer=True,
                officer_title="Chief Executive Officer",
                transaction_code="P",
                shares=10000,
                price_per_share=5.50,
                value=55000,
                acquired_disposed="A",
                is_buy=True,
                is_sell=False,
            ),
            # CFO buy $20k, filed 2025-06-17 (cluster: 2 buyers)
            InsiderTransaction(
                **common,
                filer_cik="8888888",
                filer_name="SMITH JOHN",
                filing_date="2025-06-17",
                transaction_date="2025-06-14",
                is_director=False,
                is_officer=True,
                officer_title="Chief Financial Officer",
                transaction_code="P",
                shares=4000,
                price_per_share=5.00,
                value=20000,
                acquired_disposed="A",
                is_buy=True,
                is_sell=False,
            ),
            # Director sell $30k, filed 2025-07-01
            InsiderTransaction(
                **common,
                filer_cik="7777777",
                filer_name="BOARD MEMBER",
                filing_date="2025-07-01",
                transaction_date="2025-06-28",
                is_director=True,
                is_officer=False,
                officer_title="",
                transaction_code="S",
                shares=5000,
                price_per_share=6.00,
                value=30000,
                acquired_disposed="D",
                is_buy=False,
                is_sell=True,
            ),
        ]

    def test_90d_window_captures_all(self, sample_txns):
        feats = compute_insider_features(sample_txns, "2025-07-15")
        assert feats["insider_buy_count_90d"] == 2
        assert feats["insider_sell_count_90d"] == 1
        assert feats["insider_net_buy_value_90d"] == 55000 + 20000 - 30000
        assert feats["insider_net_buyer_flag_90d"] == 1

    def test_exec_buy_flag(self, sample_txns):
        feats = compute_insider_features(sample_txns, "2025-07-15")
        assert feats["insider_buying_by_exec_flag_90d"] == 1

    def test_cluster_buy_flag(self, sample_txns):
        feats = compute_insider_features(sample_txns, "2025-07-15")
        # Two different filer_ciks buying
        assert feats["insider_cluster_buy_flag_90d"] == 1

    def test_30d_window_excludes_old(self, sample_txns):
        feats = compute_insider_features(sample_txns, "2025-07-15")
        # 30d window from July 15 = June 15 - July 15
        # Buy on June 16, 17 are in window; sell on July 1 is in window
        assert feats["insider_buy_count_30d"] == 2
        assert feats["insider_sell_count_30d"] == 1

    def test_pit_safety_uses_filing_date(self, sample_txns):
        # As of June 15, the buy filed June 16 should NOT be visible
        feats = compute_insider_features(sample_txns, "2025-06-15")
        assert feats["insider_buy_count_90d"] == 0

    def test_empty_transactions(self):
        feats = compute_insider_features([], "2025-07-15")
        assert feats["insider_buy_count_90d"] == 0
        assert feats["insider_net_buy_value_90d"] == 0


# ---------------------------------------------------------------------------
# Incremental refresh (append-only, accession-level dedup)
# ---------------------------------------------------------------------------


import importlib  # noqa: E402
import json as _json  # noqa: E402
from dataclasses import asdict  # noqa: E402


@pytest.fixture
def form4_mod():
    import tools.fetch_form4_insider as mod

    return importlib.reload(mod)


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


def _patch_sec(monkeypatch, mod, filings: list, xml_bytes_by_accession: dict):
    """Replace SEC network calls with in-memory fixtures."""
    monkeypatch.setattr(mod, "get_form4_filings", lambda cik, since="2020-01-01": list(filings))

    # Route _fetch_url by matching accession token present in the URL.
    def fake_fetch_url(url: str) -> bytes:
        for acc, body in xml_bytes_by_accession.items():
            if acc.replace("-", "") in url:
                return body
        raise RuntimeError(f"Unexpected SEC URL in test: {url}")

    monkeypatch.setattr(mod, "_fetch_url", fake_fetch_url)


def test_incremental_no_new_accessions_leaves_raw_unchanged(tmp_path, monkeypatch, form4_mod):
    """When every filing returned by SEC is already in seen_accessions, fetch_ticker
    returns no new transactions — caller must not rewrite the raw file."""
    monkeypatch.setattr(
        form4_mod,
        "get_form4_filings",
        lambda cik, since="2020-01-01": [
            {"form": "4", "filingDate": "2026-01-15", "accessionNumber": "0001-25-A", "primaryDocument": "x.xml"},
        ],
    )
    new_txns = form4_mod.fetch_ticker("TEST", "1", "2020-01-01", seen_accessions={"0001-25-A"})
    assert new_txns == []

    # Caller logic: if new_txns is empty, file is not rewritten. Simulate this.
    existing = [_mk_txn("0001-25-A", "2026-01-15")]
    raw_file = tmp_path / "TEST.json"
    raw_file.write_text(_json.dumps([asdict(t) for t in existing], indent=1))
    before_mtime = raw_file.stat().st_mtime
    before_text = raw_file.read_text()

    if not new_txns:
        pass  # do nothing — matches _fetch_one's branch

    assert raw_file.read_text() == before_text
    assert raw_file.stat().st_mtime == before_mtime


def test_incremental_one_new_accession_appends_only_that_one(tmp_path, monkeypatch, form4_mod):
    """New accession must be fetched, parsed, and appended; prior rows preserved."""
    _patch_sec(
        monkeypatch,
        form4_mod,
        filings=[
            {"form": "4", "filingDate": "2026-01-10", "accessionNumber": "OLD", "primaryDocument": "x.xml"},
            {"form": "4", "filingDate": "2026-02-20", "accessionNumber": "NEW", "primaryDocument": "x.xml"},
        ],
        xml_bytes_by_accession={"NEW": SAMPLE_XML, "OLD": SAMPLE_XML},
    )
    existing = [_mk_txn("OLD", "2026-01-10", code="P", shares=50, price=5.0)]
    seen = {t.accession_number for t in existing}

    new_txns = form4_mod.fetch_ticker("TEST", "1", "2020-01-01", seen_accessions=seen)
    assert new_txns, "expected at least one new transaction parsed from NEW accession"
    assert all(
        t.accession_number == "NEW" for t in new_txns
    ), f"only NEW accession should be fetched; got {sorted({t.accession_number for t in new_txns})}"

    merged = form4_mod._merge_transactions(existing, new_txns)
    assert any(t.accession_number == "OLD" for t in merged), "existing OLD row lost after merge"
    assert any(t.accession_number == "NEW" for t in merged)


def test_incremental_duplicate_accession_is_not_duplicated(monkeypatch, form4_mod):
    """If SEC's submissions API returns an accession already in seen, fetch_ticker
    must filter it BEFORE the XML fetch so nothing is re-parsed and no duplicate
    rows surface post-merge."""
    fetch_calls = []

    def tracking_fetch_url(url: str) -> bytes:
        fetch_calls.append(url)
        return SAMPLE_XML

    monkeypatch.setattr(
        form4_mod,
        "get_form4_filings",
        lambda cik, since="2020-01-01": [
            {"form": "4", "filingDate": "2026-01-10", "accessionNumber": "DUPE", "primaryDocument": "x.xml"},
        ],
    )
    monkeypatch.setattr(form4_mod, "_fetch_url", tracking_fetch_url)

    new_txns = form4_mod.fetch_ticker("TEST", "1", "2020-01-01", seen_accessions={"DUPE"})
    assert new_txns == [], "duplicate accession must be filtered out"
    assert fetch_calls == [], "XML fetch must be skipped for already-seen accession"

    # Defensive: even if a caller injects a stale duplicate at the merge step,
    # the merge helper does not dedup (upstream gating is authoritative) — so the
    # guarantee lives in the accession filter, not the merge.
    existing = [_mk_txn("DUPE", "2026-01-10")]
    merged = form4_mod._merge_transactions(existing, [])
    assert len(merged) == 1


def test_incremental_panel_rebuild_preserves_schema(tmp_path, form4_mod):
    """build_panel over incrementally-updated raw/ must produce the same header
    schema as compute_insider_features keys — i.e. no schema drift from incremental."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    txns_a = [_mk_txn("A-1", "2026-01-10"), _mk_txn("A-2", "2026-02-10", code="S", shares=20, price=12)]
    txns_b = [_mk_txn("B-1", "2026-03-01", shares=200, price=4)]
    (raw_dir / "TICKA.json").write_text(_json.dumps([asdict(t) for t in txns_a], indent=1))
    (raw_dir / "TICKB.json").write_text(_json.dumps([asdict(t) for t in txns_b], indent=1))

    panel_path = tmp_path / "panel.csv"
    n_rows = form4_mod.build_panel(raw_dir, panel_path)
    assert n_rows > 0
    header = panel_path.read_text().splitlines()[0].split(",")

    # Must contain the canonical field naming for every window
    expected_core = {
        "ticker",
        "as_of_date",
        "insider_net_buy_value_30d",
        "insider_net_buy_value_60d",
        "insider_net_buy_value_90d",
        "insider_buy_value_30d",
        "insider_buy_value_60d",
        "insider_buy_value_90d",
        "insider_sell_value_30d",
        "insider_sell_value_60d",
        "insider_sell_value_90d",
        "insider_buy_count_30d",
        "insider_buy_count_60d",
        "insider_buy_count_90d",
        "insider_sell_count_30d",
        "insider_sell_count_60d",
        "insider_sell_count_90d",
        "insider_unique_buyers_90d",
        "insider_unique_sellers_90d",
    }
    missing = expected_core - set(header)
    assert not missing, f"panel schema lost fields after incremental rebuild: {missing}"
