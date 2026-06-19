"""Tests for ETF universe expansion construction."""

import json

import expand_universe_to_etfs as expand


def test_expand_universe_adds_pending_entries(tmp_path, monkeypatch):
    universe_path = tmp_path / "universe.json"
    output_path = tmp_path / "expanded.json"
    universe_path.write_text(json.dumps([{"ticker": "OLD", "status": "active"}]))

    monkeypatch.setattr(expand, "get_xbi_constituents", lambda: {"OLD", "NEWC"})
    monkeypatch.setattr(expand, "get_ibb_constituents", lambda: {"NEWC"})
    monkeypatch.setattr(expand, "get_nbi_constituents", lambda: set())

    result = expand.expand_universe(
        universe_path,
        output_path,
        include_xbi=True,
        include_ibb=True,
        include_nbi=False,
    )

    assert result["added_tickers"] == ["NEWC"]

    expanded = json.loads(output_path.read_text())
    new_entry = next(entry for entry in expanded if entry["ticker"] == "NEWC")
    assert new_entry["status"] == "pending_data_collection"
    assert new_entry["added_from_etf"] is True
    assert new_entry["etf_sources"] == ["XBI", "IBB"]
    assert new_entry["coverage_status"]["scientific_cartography"] == "pending"
    assert "added_from_et" not in new_entry
