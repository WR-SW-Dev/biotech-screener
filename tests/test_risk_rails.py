"""Tests for gap-risk and price-coverage risk rails in action list builder.

Validates:
  1. Binary 0-30 names with catalyst_days <= 7 get gap_risk=HIGH
  2. Binary 0-30 names with catalyst_days > 7 get gap_risk=MODERATE
  3. Non-binary_0_30 names get gap_risk=""
  4. Names with de_beta_xbi_60d_source present get price_coverage=OK
  5. Names with missing source get price_coverage=MISSING
  6. Risk rail columns appear in CSV output
  7. README includes Risk Rails section
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from build_action_lists import apply_risk_rails, build_action_lists, write_action_lists

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    ticker: str,
    rank: int,
    catalyst_days: str = "",
    catalyst_mode: str = "missing",
    eligible: str = "1",
    weight: str = "5.0",
    size_band: str = "M",
    de_beta_xbi_60d_source: str = "price_history",
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
        "de_beta_xbi_60d_source": de_beta_xbi_60d_source,
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
# A) Gap risk
# ---------------------------------------------------------------------------


class TestGapRisk:

    def test_imminent_catalyst_high_gap(self, tmp_path):
        """catalyst_days <= 7 in binary_0_30 → gap_risk=HIGH."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("VRTX", 1, "5", "specific_days")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)

        row = buckets["binary_0_30"][0]
        assert row["gap_risk"] == "HIGH"

    def test_boundary_7_days_is_high(self, tmp_path):
        """catalyst_days == 7 → gap_risk=HIGH."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, "7", "specific_days")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)
        assert buckets["binary_0_30"][0]["gap_risk"] == "HIGH"

    def test_8_days_is_moderate(self, tmp_path):
        """catalyst_days == 8 → gap_risk=MODERATE."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, "8", "specific_days")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)
        assert buckets["binary_0_30"][0]["gap_risk"] == "MODERATE"

    def test_binary_31_90_no_gap_risk(self, tmp_path):
        """Names outside binary_0_30 get empty gap_risk."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, "60", "specific_days")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)
        assert buckets["binary_31_90"][0]["gap_risk"] == ""

    def test_less_binary_no_gap_risk(self, tmp_path):
        """Less-binary names get empty gap_risk."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, "", "no_upcoming")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)
        assert buckets["less_binary"][0]["gap_risk"] == ""


# ---------------------------------------------------------------------------
# B) Price coverage
# ---------------------------------------------------------------------------


class TestPriceCoverage:

    def test_source_present_is_ok(self, tmp_path):
        """de_beta_xbi_60d_source="price_history" → price_coverage=OK."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, de_beta_xbi_60d_source="price_history")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)
        assert buckets["less_binary"][0]["price_coverage"] == "OK"

    def test_source_missing_is_missing(self, tmp_path):
        """Empty de_beta_xbi_60d_source → price_coverage=MISSING."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, de_beta_xbi_60d_source="")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)
        assert buckets["less_binary"][0]["price_coverage"] == "MISSING"


# ---------------------------------------------------------------------------
# C) CSV output
# ---------------------------------------------------------------------------


class TestRailCSVOutput:

    def test_rail_columns_in_csv(self, tmp_path):
        """CSVs include gap_risk and price_coverage when rails applied."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, "5", "specific_days")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)

        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir)

        with open(out_dir / "binary_0_30.csv") as f:
            reader = csv.DictReader(f)
            assert "gap_risk" in reader.fieldnames
            assert "price_coverage" in reader.fieldnames
            row = next(reader)
            assert row["gap_risk"] == "HIGH"

    def test_no_rail_columns_without_apply(self, tmp_path):
        """CSVs omit rail columns if apply_risk_rails not called."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, "5", "specific_days")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        # NOT calling apply_risk_rails

        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir)

        with open(out_dir / "binary_0_30.csv") as f:
            reader = csv.DictReader(f)
            assert "gap_risk" not in reader.fieldnames


# ---------------------------------------------------------------------------
# D) README
# ---------------------------------------------------------------------------


class TestRailREADME:

    def test_readme_has_risk_rails_section(self, tmp_path):
        """README includes Risk Rails section when rails applied."""
        snap_dir = tmp_path / "snap"
        rows = [
            _make_row("URGNT", 1, "3", "specific_days"),
            _make_row("NOPR", 2, de_beta_xbi_60d_source=""),
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)

        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir)

        readme = (out_dir / "README.md").read_text()
        assert "Risk Rails" in readme
        assert "Gap risk HIGH" in readme
        assert "URGNT" in readme
        assert "Price coverage MISSING" in readme
        assert "NOPR" in readme

    def test_readme_all_ok(self, tmp_path):
        """README shows 'all names OK' when no flags triggered."""
        snap_dir = tmp_path / "snap"
        rows = [_make_row("A", 1, "15", "specific_days")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)
        apply_risk_rails(buckets)

        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir)

        readme = (out_dir / "README.md").read_text()
        assert "Risk Rails" in readme
        assert "all names OK" in readme
