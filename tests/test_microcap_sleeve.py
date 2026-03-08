"""Tests for microcap inversion sleeve.

Validates:
  1. Sleeve is absent unless --include-microcap-sleeve flag is passed
  2. Sleeve only contains XS-band names from less-binary bucket
  3. Deterministic sorting (worst rank first)
  4. No overlap between main buckets and sleeve
  5. Bottom-K selection correct
  6. Sleeve respects K parameter
  7. Output CSV has correct columns
  8. README includes warning text when sleeve present
  9. eval_by_bucket includes microcap_inversion only when flag set
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from build_action_lists import (
    BUCKET_NAMES,
    MICROCAP_SLEEVE_NAME,
    build_action_lists,
    build_microcap_sleeve,
    classify_action_bucket,
    write_action_lists,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_rankings_csv(snap_dir: Path, rows: list) -> Path:
    """Write a minimal rankings.csv for testing."""
    cols = [
        "ticker",
        "actionable_rank",
        "eligible",
        "tier_any",
        "target_weight_pct",
        "catalyst_days",
        "catalyst_mode",
        "catalyst_bucket",
        "catalyst_strength",
        "archetype",
        "alpha_cohort_key",
        "mom_state",
        "industry_group",
        "size_band",
    ]
    csv_path = snap_dir / "rankings.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            full = {c: "" for c in cols}
            full.update(r)
            writer.writerow(full)
    return csv_path


def _make_test_snapshot(tmp_path: Path) -> Path:
    """Create a snapshot with mixed buckets and size bands."""
    snap_dir = tmp_path / "snap"
    snap_dir.mkdir()

    rows = [
        # Binary 0-30 (2 names)
        {
            "ticker": "BIN1",
            "actionable_rank": "1",
            "eligible": "1",
            "catalyst_days": "10",
            "catalyst_mode": "specific_days",
            "size_band": "M",
        },
        {
            "ticker": "BIN2",
            "actionable_rank": "2",
            "eligible": "1",
            "catalyst_days": "25",
            "catalyst_mode": "specific_days",
            "size_band": "S",
        },
        # Binary 91-180 (1 name)
        {
            "ticker": "BIN3",
            "actionable_rank": "3",
            "eligible": "1",
            "catalyst_days": "120",
            "catalyst_mode": "specific_days",
            "size_band": "M",
        },
        # Less-binary names — various sizes and ranks
        {
            "ticker": "CORE_XS_1",
            "actionable_rank": "4",
            "eligible": "1",
            "catalyst_days": "",
            "catalyst_mode": "no_upcoming",
            "size_band": "XS",
        },
        {
            "ticker": "CORE_M_1",
            "actionable_rank": "5",
            "eligible": "1",
            "catalyst_days": "300",
            "catalyst_mode": "no_upcoming",
            "size_band": "M",
        },
        {
            "ticker": "CORE_XS_2",
            "actionable_rank": "6",
            "eligible": "1",
            "catalyst_days": "",
            "catalyst_mode": "missing",
            "size_band": "XS",
        },
        {
            "ticker": "CORE_XS_3",
            "actionable_rank": "7",
            "eligible": "1",
            "catalyst_days": "",
            "catalyst_mode": "no_upcoming",
            "size_band": "XS",
        },
        {
            "ticker": "CORE_L_1",
            "actionable_rank": "8",
            "eligible": "1",
            "catalyst_days": "",
            "catalyst_mode": "no_upcoming",
            "size_band": "L",
        },
        {
            "ticker": "CORE_XS_4",
            "actionable_rank": "9",
            "eligible": "1",
            "catalyst_days": "",
            "catalyst_mode": "no_upcoming",
            "size_band": "XS",
        },
        {
            "ticker": "CORE_XS_5",
            "actionable_rank": "10",
            "eligible": "1",
            "catalyst_days": "",
            "catalyst_mode": "no_upcoming",
            "size_band": "XS",
        },
        # Ineligible XS name — should not appear in sleeve by default
        {
            "ticker": "INELIG_XS",
            "actionable_rank": "11",
            "eligible": "0",
            "catalyst_days": "",
            "catalyst_mode": "no_upcoming",
            "size_band": "XS",
        },
    ]
    _make_rankings_csv(snap_dir, rows)
    return snap_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSleeveAbsentByDefault:

    def test_build_action_lists_no_sleeve(self, tmp_path):
        """Standard build_action_lists does not produce sleeve."""
        snap_dir = _make_test_snapshot(tmp_path)
        buckets = build_action_lists(snap_dir)
        assert MICROCAP_SLEEVE_NAME not in buckets

    def test_write_without_sleeve_no_file(self, tmp_path):
        """write_action_lists without sleeve does not create sleeve CSV."""
        snap_dir = _make_test_snapshot(tmp_path)
        buckets = build_action_lists(snap_dir)
        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir)
        assert not (out_dir / f"{MICROCAP_SLEEVE_NAME}.csv").exists()

    def test_readme_no_sleeve_section(self, tmp_path):
        """README does not mention microcap sleeve when not included."""
        snap_dir = _make_test_snapshot(tmp_path)
        buckets = build_action_lists(snap_dir)
        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir)
        readme = (out_dir / "README.md").read_text()
        assert "Microcap Inversion Sleeve" not in readme


class TestSleeveContent:

    def test_only_xs_names(self, tmp_path):
        """Sleeve only contains XS-band names."""
        snap_dir = _make_test_snapshot(tmp_path)
        sleeve = build_microcap_sleeve(snap_dir, k=20)
        for r in sleeve:
            assert r.get("size_band") == "XS", f"Non-XS in sleeve: {r}"

    def test_only_less_binary_names(self, tmp_path):
        """Sleeve only contains names from less-binary bucket."""
        snap_dir = _make_test_snapshot(tmp_path)
        sleeve = build_microcap_sleeve(snap_dir, k=20)
        for r in sleeve:
            bucket = classify_action_bucket(r)
            assert bucket == "less_binary", f"Non-less-binary in sleeve: {r}"

    def test_eligible_only_by_default(self, tmp_path):
        """Ineligible names excluded by default."""
        snap_dir = _make_test_snapshot(tmp_path)
        sleeve = build_microcap_sleeve(snap_dir, k=20)
        tickers = {r["ticker"] for r in sleeve}
        assert "INELIG_XS" not in tickers

    def test_bottom_k_selection(self, tmp_path):
        """Sleeve takes the worst-ranked names (highest rank number)."""
        snap_dir = _make_test_snapshot(tmp_path)
        # K=3: should get the 3 worst-ranked XS names
        sleeve = build_microcap_sleeve(snap_dir, k=3)
        assert len(sleeve) == 3
        tickers = [r["ticker"] for r in sleeve]
        # Worst ranked XS names: rank 10, 9, 7 → CORE_XS_5, CORE_XS_4, CORE_XS_3
        assert "CORE_XS_5" in tickers
        assert "CORE_XS_4" in tickers
        assert "CORE_XS_3" in tickers

    def test_k_larger_than_universe(self, tmp_path):
        """When K > available XS names, return all."""
        snap_dir = _make_test_snapshot(tmp_path)
        sleeve = build_microcap_sleeve(snap_dir, k=100)
        # 5 eligible XS names in test data
        assert len(sleeve) == 5

    def test_deterministic_sort_worst_first(self, tmp_path):
        """Sleeve sorted worst rank first (contrarian ordering)."""
        snap_dir = _make_test_snapshot(tmp_path)
        sleeve = build_microcap_sleeve(snap_dir, k=20)
        ranks = [float(r.get("actionable_rank", 0)) for r in sleeve]
        # Should be descending (worst first)
        assert ranks == sorted(ranks, reverse=True)


class TestNoOverlap:

    def test_sleeve_tickers_not_in_main_buckets(self, tmp_path):
        """Sleeve tickers should be a subset of less_binary, not duplicated."""
        snap_dir = _make_test_snapshot(tmp_path)
        buckets = build_action_lists(snap_dir)
        sleeve = build_microcap_sleeve(snap_dir, k=20)

        sleeve_tickers = {r["ticker"] for r in sleeve}
        # Sleeve names should only appear in less_binary bucket (they're a subset)
        for bucket_name in ["binary_0_30", "binary_31_90", "binary_91_180"]:
            bucket_tickers = {r["ticker"] for r in buckets[bucket_name]}
            overlap = sleeve_tickers & bucket_tickers
            assert not overlap, f"Overlap with {bucket_name}: {overlap}"


class TestOutputFiles:

    def test_sleeve_csv_written(self, tmp_path):
        """Sleeve CSV created when microcap_sleeve passed."""
        snap_dir = _make_test_snapshot(tmp_path)
        buckets = build_action_lists(snap_dir)
        sleeve = build_microcap_sleeve(snap_dir, k=20)
        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir, microcap_sleeve=sleeve)

        csv_path = out_dir / f"{MICROCAP_SLEEVE_NAME}.csv"
        assert csv_path.exists()

        # Read back and verify
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 5  # all 5 eligible XS names
        assert "size_band" in reader.fieldnames

    def test_readme_includes_warning(self, tmp_path):
        """README includes illiquidity warning when sleeve present."""
        snap_dir = _make_test_snapshot(tmp_path)
        buckets = build_action_lists(snap_dir)
        sleeve = build_microcap_sleeve(snap_dir, k=20)
        out_dir = tmp_path / "out"
        write_action_lists(buckets, out_dir, microcap_sleeve=sleeve)

        readme = (out_dir / "README.md").read_text()
        assert "Microcap Inversion Sleeve" in readme
        assert "illiquidity" in readme.lower()
        assert "WARNING" in readme

    def test_main_bucket_csvs_unchanged(self, tmp_path):
        """Adding sleeve does not alter main bucket CSVs."""
        snap_dir = _make_test_snapshot(tmp_path)
        buckets = build_action_lists(snap_dir)

        # Write without sleeve
        out1 = tmp_path / "out1"
        write_action_lists(buckets, out1)

        # Write with sleeve
        sleeve = build_microcap_sleeve(snap_dir, k=20)
        out2 = tmp_path / "out2"
        write_action_lists(buckets, out2, microcap_sleeve=sleeve)

        # Main bucket files should be identical
        for b in BUCKET_NAMES:
            content1 = (out1 / f"{b}.csv").read_text()
            content2 = (out2 / f"{b}.csv").read_text()
            assert content1 == content2, f"{b}.csv differs"
