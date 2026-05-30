"""Tests for intraday digest Firecrawl enrichment helpers."""

from __future__ import annotations

from tools.enrich_intraday_digest_with_research import extract_high_moves


def test_extract_high_moves_spec063_digest_format():
    digest = {
        "top_absolute_movers": [
            {
                "ticker": "MRNA",
                "severity": "HIGH",
                "stock_abs_move_pct": 12.5,
            },
            {
                "ticker": "LOW",
                "severity": "LOW",
                "stock_abs_move_pct": 2.0,
            },
        ],
        "top_relative_movers_vs_xbi": [
            {
                "ticker": "XBI",
                "severity": "HIGH",
                "rel_move_vs_xbi_pct": 8.0,
                "stock_abs_move_pct": 3.0,
            },
        ],
    }
    moves = extract_high_moves(digest)
    tickers = {m.ticker for m in moves}
    assert tickers == {"MRNA", "XBI"}
    mrna = next(m for m in moves if m.ticker == "MRNA")
    assert mrna.magnitude == 12.5
