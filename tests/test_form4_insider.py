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
