"""Tests for ETF-derived universe construction helpers."""

from add_etf_tickers_to_universe import _build_new_security, _extract_ticker_metadata


def test_extract_ticker_metadata_from_legacy_lists():
    holdings = {
        "xbi": ["AARD", "ABCL"],
        "ibb": ["ABCL"],
        "nbi": [],
    }

    metadata = _extract_ticker_metadata(holdings)

    assert metadata["AARD"] == {"sources": ["XBI"], "company_name": None}
    assert metadata["ABCL"] == {"sources": ["IBB", "XBI"], "company_name": None}


def test_extract_ticker_metadata_from_rich_rows():
    holdings = {
        "xbi": [{"ticker": "AARD", "company_name": "Aardvark Therapeutics, Inc."}],
        "ibb": [{"Symbol": "AARD", "Name": "Aardvark Therapeutics"}],
        "nbi": [{"symbol": "ABCL", "security_name": "AbCellera Biologics Inc."}],
    }

    metadata = _extract_ticker_metadata(holdings)

    assert metadata["AARD"] == {
        "sources": ["IBB", "XBI"],
        "company_name": "Aardvark Therapeutics, Inc.",
    }
    assert metadata["ABCL"] == {
        "sources": ["NBI"],
        "company_name": "AbCellera Biologics Inc.",
    }


def test_build_new_security_marks_uncovered_ticker_pending():
    entry = _build_new_security(
        "NEWC",
        {"sources": ["XBI"], "company_name": None},
        "2026-06-19",
    )

    assert entry["ticker"] == "NEWC"
    assert entry["name"] is None
    assert entry["status"] == "pending_data_collection"
    assert entry["added_from_etf"] is True
    assert entry["coverage_status"]["scientific_cartography"] == "pending"
    assert "added_from_et" not in entry


def test_build_new_security_preserves_company_name_when_available():
    entry = _build_new_security(
        "AARD",
        {"sources": ["IBB"], "company_name": "Aardvark Therapeutics, Inc."},
        "2026-06-19",
    )

    assert entry["name"] == "Aardvark Therapeutics, Inc."
    assert entry["company_name"] == "Aardvark Therapeutics, Inc."
    assert entry["market_data"]["company_name"] == "Aardvark Therapeutics, Inc."
