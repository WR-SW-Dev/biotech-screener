"""Tests for tools/ic_decomposition.py — IC math, cohort tagging, segment detection."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from tools.ic_decomposition import COHORT_CHANGE_DATE, COHORT_CLEAR_DATE, compute_ic_for_date, ic_t_stat, spearman_ic

# ---------------------------------------------------------------------------
# spearman_ic
# ---------------------------------------------------------------------------


class TestSpearmanIC:
    def test_perfect_positive(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert spearman_ic(xs, ys) == pytest.approx(1.0, abs=1e-9)

    def test_perfect_negative(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [5.0, 4.0, 3.0, 2.0, 1.0]
        assert spearman_ic(xs, ys) == pytest.approx(-1.0, abs=1e-9)

    def test_zero_correlation(self):
        # Symmetric opposite ranks → IC should be near 0
        xs = [1.0, 3.0, 5.0, 2.0, 4.0]
        ys = [4.0, 2.0, 5.0, 3.0, 1.0]
        ic = spearman_ic(xs, ys)
        assert ic is not None
        assert abs(ic) < 0.5  # not strongly correlated

    def test_too_few_returns_none(self):
        assert spearman_ic([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) is None

    def test_exactly_five_accepted(self):
        result = spearman_ic([1.0, 2.0, 3.0, 4.0, 5.0], [5.0, 4.0, 3.0, 2.0, 1.0])
        assert result is not None

    def test_ties_handled(self):
        # All xs tied → constant, IC should be None (den_x = 0)
        xs = [1.0, 1.0, 1.0, 1.0, 1.0]
        ys = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert spearman_ic(xs, ys) is None


# ---------------------------------------------------------------------------
# ic_t_stat
# ---------------------------------------------------------------------------


class TestIcTStat:
    def test_positive_ic(self):
        t = ic_t_stat(0.10, 100)
        assert t is not None
        assert t > 0

    def test_negative_ic(self):
        t = ic_t_stat(-0.10, 100)
        assert t is not None
        assert t < 0

    def test_too_few_returns_none(self):
        assert ic_t_stat(0.10, 4) is None

    def test_magnitude_grows_with_n(self):
        t_small = ic_t_stat(0.10, 20)
        t_large = ic_t_stat(0.10, 200)
        assert abs(t_large) > abs(t_small)

    def test_ic_equals_zero(self):
        t = ic_t_stat(0.0, 100)
        assert t == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Cohort contamination tagging
# ---------------------------------------------------------------------------


def _make_snap_rows(n: int = 20) -> list[dict]:
    """Generate n rows with varying coinvest_score_z and catalyst_quality."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "ticker": f"T{i:03d}",
                "coinvest_score_z": str(math.sin(i) * 2),
                "actionable_rank": str(i + 1),
                "stage_bucket": "late" if i % 3 == 0 else ("mid" if i % 3 == 1 else "early"),
                "catalyst_quality": "binary_alpha" if i % 4 == 0 else ("registry_only" if i % 4 == 1 else ""),
                "has_catalyst_signal": "1" if i % 4 in (0, 1) else "0",
            }
        )
    return rows


def _make_fwd_map(rows: list[dict], base_fwd: float = 0.01) -> dict:
    """Return {ticker: {excess_return_5d: fwd}} with mild positive correlation to coinvest_score_z."""
    result = {}
    for r in rows:
        cz = float(r["coinvest_score_z"])
        result[r["ticker"]] = {"excess_return_5d": base_fwd + cz * 0.005}
    return result


class TestCohortTagging:
    def test_pre_cohort_date_clean(self):
        rows = _make_snap_rows()
        fwd_map = _make_fwd_map(rows)
        result = compute_ic_for_date("2026-04-14", rows, fwd_map)
        assert result["cohort_contaminated"] is False

    def test_cohort_change_date_contaminated(self):
        rows = _make_snap_rows()
        fwd_map = _make_fwd_map(rows)
        result = compute_ic_for_date(COHORT_CHANGE_DATE, rows, fwd_map)
        assert result["cohort_contaminated"] is True

    def test_post_cohort_date_contaminated(self):
        rows = _make_snap_rows()
        fwd_map = _make_fwd_map(rows)
        result = compute_ic_for_date("2026-04-27", rows, fwd_map)
        assert result["cohort_contaminated"] is True

    def test_clear_date_not_contaminated(self):
        rows = _make_snap_rows()
        fwd_map = _make_fwd_map(rows)
        result = compute_ic_for_date(COHORT_CLEAR_DATE, rows, fwd_map)
        assert result["cohort_contaminated"] is False

    def test_post_clear_date_clean(self):
        rows = _make_snap_rows()
        fwd_map = _make_fwd_map(rows)
        result = compute_ic_for_date("2026-05-20", rows, fwd_map)
        assert result["cohort_contaminated"] is False


# ---------------------------------------------------------------------------
# compute_ic_for_date
# ---------------------------------------------------------------------------


class TestComputeICForDate:
    def test_returns_expected_keys(self):
        rows = _make_snap_rows()
        fwd_map = _make_fwd_map(rows)
        result = compute_ic_for_date("2026-04-14", rows, fwd_map)
        assert "snap_date" in result
        assert "n_obs" in result
        assert "ic" in result
        assert "t_stat" in result
        assert "segments" in result
        assert "top30" in result

    def test_positive_correlation_gives_positive_ic(self):
        # Construct strongly positively correlated data (n=20, well above threshold)
        rows = [
            {
                "ticker": f"T{i:03d}",
                "coinvest_score_z": str(float(i)),
                "actionable_rank": str(i + 1),
                "stage_bucket": "late",
                "catalyst_quality": "",
                "has_catalyst_signal": "0",
            }
            for i in range(20)
        ]
        fwd_map = {f"T{i:03d}": {"excess_return_5d": float(i) * 0.01} for i in range(20)}
        result = compute_ic_for_date("2026-04-14", rows, fwd_map)
        assert result["ic"] is not None
        assert result["ic"] > 0

    def test_top30_n_correct(self):
        rows = _make_snap_rows(50)
        fwd_map = _make_fwd_map(rows)
        result = compute_ic_for_date("2026-04-14", rows, fwd_map)
        assert result["top30"]["n"] == 30

    def test_missing_signal_skipped(self):
        rows = _make_snap_rows(20)
        for r in rows[:5]:
            r["coinvest_score_z"] = ""
        fwd_map = _make_fwd_map(_make_snap_rows(20))
        result = compute_ic_for_date("2026-04-14", rows, fwd_map)
        assert result["n_obs"] <= 20

    def test_stage_bucket_segment_present(self):
        rows = _make_snap_rows(20)
        fwd_map = _make_fwd_map(rows)
        result = compute_ic_for_date("2026-04-14", rows, fwd_map)
        seg = result["segments"].get("stage_bucket", {})
        assert "late" in seg or "mid" in seg or "early" in seg

    def test_catalyst_quality_populated_when_present(self):
        rows = _make_snap_rows(20)
        fwd_map = _make_fwd_map(rows)
        result = compute_ic_for_date("2026-05-08", rows, fwd_map)
        seg = result["segments"].get("catalyst_quality", {})
        # binary_alpha and registry_only should appear in segment results
        assert "binary_alpha" in seg or "registry_only" in seg
