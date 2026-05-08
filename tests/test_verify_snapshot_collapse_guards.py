"""Tests for _check_column_content collapse guards in verify_snapshot_integrity."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools.verify_snapshot_integrity import CATALYST_QUALITY_MIN_COVERAGE_PCT, COINVEST_SD_FLOOR, _check_column_content


def _write_rankings(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "rankings.csv"
    if not rows:
        p.write_text("")
        return p
    fieldnames = list(rows[0].keys())
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return p


def _make_row(ticker: str, cz: float, has_signal: str, quality: str) -> dict:
    return {
        "ticker": ticker,
        "coinvest_score_z": str(cz),
        "has_catalyst_signal": has_signal,
        "catalyst_quality": quality,
    }


class TestCoinvestCollapse:
    def _healthy_rows(self, n: int = 20) -> list[dict]:
        import math

        return [_make_row(f"T{i:03d}", math.sin(i) * 2, "0", "") for i in range(n)]

    def test_healthy_sd_passes(self, tmp_path):
        rows = self._healthy_rows()
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        cz = next(r for r in results if r.name == "coinvest_score_z_collapse")
        assert cz.severity == "PASS"

    def test_flat_sd_fails(self, tmp_path):
        # All coinvest_score_z = 0.0 → SD = 0
        rows = [_make_row(f"T{i:03d}", 0.0, "0", "") for i in range(20)]
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        cz = next(r for r in results if r.name == "coinvest_score_z_collapse")
        assert cz.severity == "FAIL"
        assert "flat" in cz.detail.lower() or str(COINVEST_SD_FLOOR) in cz.detail

    def test_near_threshold_fails(self, tmp_path):
        # SD just at floor — first row +0.05, rest 0.0 → tiny variance
        rows = [_make_row("T000", 0.05, "0", "")] + [_make_row(f"T{i:03d}", 0.0, "0", "") for i in range(1, 20)]
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        cz = next(r for r in results if r.name == "coinvest_score_z_collapse")
        # sd ≈ 0.011 which is ≤ 0.10
        assert cz.severity == "FAIL"

    def test_too_few_rows_fails(self, tmp_path):
        rows = [_make_row(f"T{i}", 1.0, "0", "") for i in range(5)]
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        # too few rows overall → first guard fires
        assert any(r.severity == "FAIL" for r in results)

    def test_missing_column_fails(self, tmp_path):
        # Write rows without coinvest_score_z
        rows = [{"ticker": f"T{i}", "has_catalyst_signal": "0", "catalyst_quality": ""} for i in range(20)]
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        cz = next(r for r in results if r.name == "coinvest_score_z_collapse")
        assert cz.severity == "FAIL"


class TestCatalystQualityCollapse:
    def _base_rows(self, n: int = 20) -> list[dict]:
        import math

        return [_make_row(f"T{i:03d}", math.sin(i) * 2, "0", "") for i in range(n)]

    def test_all_classified_passes(self, tmp_path):
        rows = self._base_rows()
        # Add 10 rows with signal, all classified
        for i in range(10):
            rows.append(_make_row(f"S{i:03d}", float(i) * 0.1, "1", "binary_alpha"))
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        cq = next(r for r in results if r.name == "catalyst_quality_collapse")
        assert cq.severity == "PASS"
        assert cq.extra["n_classified"] == 10

    def test_no_signal_rows_warns(self, tmp_path):
        rows = self._base_rows()
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        cq = next(r for r in results if r.name == "catalyst_quality_collapse")
        assert cq.severity == "WARN"

    def test_zero_classified_fails(self, tmp_path):
        rows = self._base_rows()
        # 10 with signal but all blank quality
        for i in range(10):
            rows.append(_make_row(f"S{i:03d}", float(i) * 0.1, "1", ""))
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        cq = next(r for r in results if r.name == "catalyst_quality_collapse")
        assert cq.severity == "FAIL"

    def test_partial_collapse_fails(self, tmp_path):
        rows = self._base_rows()
        # 10 with signal, only 5 classified → 50% < 90% threshold
        for i in range(5):
            rows.append(_make_row(f"S{i:03d}", float(i) * 0.1, "1", "registry_only"))
        for i in range(5, 10):
            rows.append(_make_row(f"S{i:03d}", float(i) * 0.1, "1", ""))
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        cq = next(r for r in results if r.name == "catalyst_quality_collapse")
        assert cq.severity == "FAIL"
        assert cq.extra["pct"] == pytest.approx(50.0)

    def test_high_coverage_passes(self, tmp_path):
        rows = self._base_rows()
        # 10 with signal, 9/10 classified → 90% exactly at threshold (pass)
        for i in range(9):
            rows.append(_make_row(f"S{i:03d}", float(i) * 0.1, "1", "registry_only"))
        rows.append(_make_row("S009", 0.9, "1", ""))
        p = _write_rankings(tmp_path, rows)
        results = _check_column_content(p)
        cq = next(r for r in results if r.name == "catalyst_quality_collapse")
        # 90.0% == CATALYST_QUALITY_MIN_COVERAGE_PCT, pct < threshold means fail
        # 9/10 = 90.0, which is NOT < 90.0, so should PASS
        assert cq.severity == "PASS"
