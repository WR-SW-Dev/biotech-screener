"""Tests for scripts/research/ees_validation_filters.

Pins the load-bearing diagnostic decisions:
  - quarantine threshold (priced_move_pct >= 500.0)
  - Universe A membership (ees_v3_score non-null)
  - Universe B membership (next_catalyst_date within window)
  - independence of the three filters

These thresholds should not change without updating the validation harness
spec and the cohort-change quarantine memo.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.research.ees_validation_filters import (  # noqa: E402
    PMV_QUARANTINE_THRESHOLD,
    classify_rows,
    in_universe_a,
    in_universe_b,
    is_quarantined,
)


def test_quarantine_threshold_500():
    assert PMV_QUARANTINE_THRESHOLD == 500.0
    assert is_quarantined({"priced_move_pct": "499.99"}) is False
    assert is_quarantined({"priced_move_pct": "500.0"}) is True
    assert is_quarantined({"priced_move_pct": "2474.65"}) is True


def test_quarantine_handles_missing_pmv():
    assert is_quarantined({"priced_move_pct": ""}) is False
    assert is_quarantined({"priced_move_pct": "nan"}) is False
    assert is_quarantined({}) is False


def test_universe_a_requires_ees_v3_score():
    assert in_universe_a({"ees_v3_score": "1.5"}) is True
    assert in_universe_a({"ees_v3_score": "0.0"}) is True
    assert in_universe_a({"ees_v3_score": ""}) is False
    assert in_universe_a({"ees_v3_score": "nan"}) is False
    assert in_universe_a({}) is False


def test_universe_b_window_inclusive_both_ends():
    as_of = date(2026, 4, 30)
    # day 0 (same day)
    assert in_universe_b({"next_catalyst_date": "2026-04-30"}, as_of) is True
    # day +7 (boundary)
    assert in_universe_b({"next_catalyst_date": "2026-05-07"}, as_of) is True
    # day +8 (out)
    assert in_universe_b({"next_catalyst_date": "2026-05-08"}, as_of) is False
    # past catalyst (out — we want forward only)
    assert in_universe_b({"next_catalyst_date": "2026-04-29"}, as_of) is False


def test_universe_b_handles_missing_dates():
    as_of = date(2026, 4, 30)
    assert in_universe_b({"next_catalyst_date": ""}, as_of) is False
    assert in_universe_b({"next_catalyst_date": None}, as_of) is False
    assert in_universe_b({}, as_of) is False


def test_classify_rows_independence():
    """A row can be in both A and B; quarantine is independent of both."""
    as_of = date(2026, 4, 30)
    rows = [
        # A + B + clean
        {"ticker": "X1", "ees_v3_score": "1.5", "next_catalyst_date": "2026-05-02", "priced_move_pct": "30"},
        # A + B + quarantined
        {"ticker": "X2", "ees_v3_score": "1.5", "next_catalyst_date": "2026-05-02", "priced_move_pct": "800"},
        # A only (no near catalyst)
        {"ticker": "X3", "ees_v3_score": "0.5", "next_catalyst_date": "2026-06-15", "priced_move_pct": "20"},
        # neither A nor B
        {"ticker": "X4", "ees_v3_score": "", "next_catalyst_date": "", "priced_move_pct": ""},
    ]
    out = classify_rows(rows, as_of)

    def tickers(lst):
        return sorted(r["ticker"] for r in lst)

    assert tickers(out["universe_a"]) == ["X1", "X2", "X3"]
    assert tickers(out["universe_b"]) == ["X1", "X2"]
    assert tickers(out["quarantined"]) == ["X2"]
    assert tickers(out["all"]) == ["X1", "X2", "X3", "X4"]
