"""Tests for account-aware dollar sizing in action list builder.

Validates:
  1. Per-name band caps enforced (XS=2%, S=3%, M=5%, L=5%)
  2. Total dollars = sum of per-name target_dollars
  3. Residual cash = account - allocated
  4. Deterministic sorting unchanged by sizing
  5. Missing weight_pct → 0 fallback
  6. Missing size_band → fallback cap
  7. Custom band caps override defaults
  8. Sizing columns appear in CSV output
  9. README includes account summary section
  10. Zero-weight names get $0 allocation
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from build_action_lists import BAND_CAP_FALLBACK, apply_account_sizing, build_action_lists, write_action_lists

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACCOUNT_USD = 500_000.0


def _make_row(
    ticker: str,
    rank: int,
    catalyst_days: str = "",
    catalyst_mode: str = "missing",
    eligible: str = "1",
    weight: str = "5.0",
    size_band: str = "M",
) -> Dict[str, str]:
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": eligible,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "catalyst_bucket": "",
        "catalyst_strength": "",
        "target_weight_pct": weight,
        "tier_any": "A",
        "archetype": "drug_developer",
        "alpha_cohort_key": "",
        "mom_state": "tailwind",
        "industry_group": "",
        "size_band": size_band,
    }


def _write_rankings_csv(snap_dir: Path, rows: List[Dict[str, str]]) -> None:
    snap_dir.mkdir(parents=True, exist_ok=True)
    csv_path = snap_dir / "rankings.csv"
    if rows:
        fieldnames = list(rows[0].keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


# ---------------------------------------------------------------------------
# A) Cap enforcement
# ---------------------------------------------------------------------------


class TestCapEnforcement:

    def test_xs_capped_at_2pct(self, tmp_path):
        """XS name with 5% weight capped to 2%."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("TINY", 1, weight="5.0", size_band="XS")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_account_sizing(buckets, ACCOUNT_USD)

        row = buckets["less_binary"][0]
        assert float(row["weight_pct_raw"]) == 5.0
        assert float(row["weight_pct_capped"]) == 2.0
        assert float(row["target_dollars"]) == ACCOUNT_USD * 2.0 / 100

    def test_s_capped_at_3pct(self, tmp_path):
        """S name with 5% weight capped to 3%."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("SMOL", 1, weight="5.0", size_band="S")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_account_sizing(buckets, ACCOUNT_USD)

        row = buckets["less_binary"][0]
        assert float(row["weight_pct_capped"]) == 3.0

    def test_m_at_5pct_not_capped(self, tmp_path):
        """M name at exactly 5% — equals cap, not clamped."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("MID", 1, weight="5.0", size_band="M")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_account_sizing(buckets, ACCOUNT_USD)

        row = buckets["less_binary"][0]
        assert float(row["weight_pct_capped"]) == 5.0

    def test_l_below_cap_unchanged(self, tmp_path):
        """L name at 3% — below 5% cap, passed through."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("BIG", 1, weight="3.0", size_band="L")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_account_sizing(buckets, ACCOUNT_USD)

        row = buckets["less_binary"][0]
        assert float(row["weight_pct_capped"]) == 3.0
        assert float(row["weight_pct_raw"]) == 3.0


# ---------------------------------------------------------------------------
# B) Dollar totals
# ---------------------------------------------------------------------------


class TestDollarTotals:

    def test_total_allocated_sums_correctly(self, tmp_path):
        """Total allocated = sum of all target_dollars."""
        snap_dir = tmp_path / "snap"
        rows = [
            _make_row("A", 1, "15", "specific_days", weight="5.0", size_band="M"),
            _make_row("B", 2, weight="3.0", size_band="S"),
            _make_row("C", 3, weight="8.0", size_band="XS"),
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        summary = apply_account_sizing(buckets, ACCOUNT_USD)

        # A: M, min(5,5)=5% → $25000
        # B: S, min(3,3)=3% → $15000
        # C: XS, min(8,2)=2% → $10000
        expected = 25000 + 15000 + 10000
        assert abs(summary["total_allocated"] - expected) < 0.01

    def test_residual_cash(self, tmp_path):
        """Residual = account - allocated."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, weight="5.0", size_band="M")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        summary = apply_account_sizing(buckets, ACCOUNT_USD)

        assert abs(summary["residual_cash"] - (ACCOUNT_USD - 25000)) < 0.01

    def test_per_bucket_totals(self, tmp_path):
        """Per-bucket allocation matches sum of names in that bucket."""
        snap_dir = tmp_path / "snap"
        rows = [
            _make_row("A", 1, "15", "specific_days", weight="5.0", size_band="M"),
            _make_row("B", 2, "15", "specific_days", weight="4.0", size_band="M"),
            _make_row("C", 3, weight="3.0", size_band="S"),
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        summary = apply_account_sizing(buckets, ACCOUNT_USD)

        # A + B in binary_0_30: $25000 + $20000 = $45000
        assert abs(summary["per_bucket"]["binary_0_30"] - 45000) < 0.01
        # C in less_binary: $15000
        assert abs(summary["per_bucket"]["less_binary"] - 15000) < 0.01

    def test_per_band_totals(self, tmp_path):
        """Per-band allocation sums correctly."""
        snap_dir = tmp_path / "snap"
        rows = [
            _make_row("A", 1, "15", "specific_days", weight="5.0", size_band="M"),
            _make_row("B", 2, weight="3.0", size_band="M"),
            _make_row("C", 3, weight="8.0", size_band="XS"),
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        summary = apply_account_sizing(buckets, ACCOUNT_USD)

        # M: A(5%) + B(3%) = $25000 + $15000 = $40000
        assert abs(summary["per_band"]["M"] - 40000) < 0.01
        # XS: C capped at 2% = $10000
        assert abs(summary["per_band"]["XS"] - 10000) < 0.01


# ---------------------------------------------------------------------------
# C) Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_missing_weight_defaults_to_zero(self, tmp_path):
        """Row with empty target_weight_pct → $0."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, weight="", size_band="M")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_account_sizing(buckets, ACCOUNT_USD)

        row = buckets["less_binary"][0]
        assert float(row["weight_pct_raw"]) == 0.0
        assert float(row["target_dollars"]) == 0.0

    def test_missing_size_band_uses_fallback_cap(self, tmp_path):
        """Row with empty size_band gets BAND_CAP_FALLBACK."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, weight="10.0", size_band="")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_account_sizing(buckets, ACCOUNT_USD)

        row = buckets["less_binary"][0]
        assert float(row["weight_pct_capped"]) == BAND_CAP_FALLBACK

    def test_zero_weight_name_gets_zero_dollars(self, tmp_path):
        """Explicit 0% weight → $0."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, weight="0.0", size_band="M")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_account_sizing(buckets, ACCOUNT_USD)

        row = buckets["less_binary"][0]
        assert float(row["target_dollars"]) == 0.0

    def test_custom_band_caps(self, tmp_path):
        """Custom caps override defaults."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, weight="5.0", size_band="XS")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        custom_caps = {"XS": 4.0, "S": 4.0, "M": 6.0, "L": 6.0}
        apply_account_sizing(buckets, ACCOUNT_USD, band_caps=custom_caps)

        row = buckets["less_binary"][0]
        # XS with custom cap 4% → min(5, 4) = 4%
        assert float(row["weight_pct_capped"]) == 4.0


# ---------------------------------------------------------------------------
# D) Sorting unchanged
# ---------------------------------------------------------------------------


class TestSortingUnchanged:

    def test_sizing_preserves_sort_order(self, tmp_path):
        """Sizing does not change sort order within buckets."""
        snap_dir = tmp_path / "snap"
        rows = [
            _make_row("C", 3, weight="8.0", size_band="XS"),
            _make_row("A", 1, weight="2.0", size_band="M"),
            _make_row("B", 2, weight="5.0", size_band="S"),
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        # Record order before sizing
        before = [r["ticker"] for r in buckets["less_binary"]]

        apply_account_sizing(buckets, ACCOUNT_USD)

        after = [r["ticker"] for r in buckets["less_binary"]]
        assert before == after


# ---------------------------------------------------------------------------
# E) CSV output
# ---------------------------------------------------------------------------


class TestCSVOutput:

    def test_sizing_columns_in_csv(self, tmp_path):
        """CSVs include sizing columns when sizing_summary provided."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, "15", "specific_days", weight="5.0", size_band="M")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        summary = apply_account_sizing(buckets, ACCOUNT_USD)

        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir, sizing_summary=summary)

        with open(out_dir / "binary_0_30.csv") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            assert "weight_pct_raw" in fields
            assert "weight_pct_capped" in fields
            assert "target_dollars" in fields
            row = next(reader)
            assert float(row["target_dollars"]) == 25000.0

    def test_no_sizing_columns_without_flag(self, tmp_path):
        """CSVs omit sizing columns when sizing_summary is None."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, "15", "specific_days", weight="5.0", size_band="M")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir)

        with open(out_dir / "binary_0_30.csv") as f:
            reader = csv.DictReader(f)
            assert "weight_pct_raw" not in reader.fieldnames
            assert "target_dollars" not in reader.fieldnames


# ---------------------------------------------------------------------------
# F) README account summary
# ---------------------------------------------------------------------------


class TestREADMEAccountSummary:

    def test_readme_has_account_section(self, tmp_path):
        """README includes Account Sizing section."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, weight="5.0", size_band="M")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        summary = apply_account_sizing(buckets, ACCOUNT_USD)

        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir, sizing_summary=summary)

        readme = (out_dir / "README.md").read_text()
        assert "Account Sizing" in readme
        assert "$500,000" in readme
        assert "Residual cash" in readme
        assert "Band Caps" in readme
        assert "Per-Bucket Allocation" in readme
        assert "Per-Band Allocation" in readme

    def test_readme_no_account_section_by_default(self, tmp_path):
        """README omits Account Sizing when sizing_summary is None."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, weight="5.0", size_band="M")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir)

        readme = (out_dir / "README.md").read_text()
        assert "Account Sizing" not in readme
